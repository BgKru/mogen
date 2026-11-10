"""Database test fixtures.

Integration tests run against the Compose PostgreSQL service using dedicated
test databases, because the API test container has no Docker socket and
therefore cannot use Testcontainers (see docs/HANDOFF.md Section 9). Schema
tests migrate a scratch database with the real Alembic CLI instead of calling
``Base.metadata.create_all``, so the migrations themselves are verified.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import (  # noqa: F401  # registers every table on Base.metadata
    GenerationResult,
    GenerationTask,
    GenerationTaskImage,
    OutboxMessage,
    Project,
    ProjectImage,
    StorageCleanupJob,
    User,
    UserSession,
)
from app.db.models.enums import ProjectStatus, ProjectType, TaskType
from app.main import create_app
from app.repositories import (
    CleanupJobRepository,
    ImageRepository,
    OutboxRepository,
    ProjectRepository,
    ResultRepository,
    SessionRepository,
    TaskRepository,
    UserRepository,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:change_me@db:5432/app"
SHA256_SAMPLE = "0123456789abcdef" * 4

# Shared API test settings. Authentication cookies need an allowed Origin for
# browser-initiated registration, and the CSRF secret must be deterministic.
API_ALLOWED_ORIGIN = "http://localhost:5173"
API_TEST_PASSWORD = "SecurePassword123"
REGISTER_URL = "/api/v1/auth/register"
API_TEST_SETTINGS: dict[str, Any] = {
    "app_env": "test",
    "log_level": "WARNING",
    "redis_url": "redis://localhost:6379/0",
    # Never fall back to the production /data volume: a test client that does
    # not override get_storage must not leave uploaded files in the shared
    # application storage (Phase 8 finding).
    "storage_root": "/tmp/mogen-test-storage",
    "cors_origins": API_ALLOWED_ORIGIN,
    "csrf_secret": "integration-csrf-secret-0123456789abcdef",
    "session_cookie_secure": False,
    "session_ttl_hours": 24,
    "password_min_length": 8,
    "password_max_length": 128,
    "max_page_size": 100,
}


def _application_url() -> URL:
    return make_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def _with_database(url: URL, database: str) -> str:
    return url.set(database=database).render_as_string(hide_password=False)


def _connection_parameters(url: URL, database: str) -> dict[str, Any]:
    return {
        "host": url.host or "db",
        "port": url.port or 5432,
        "user": url.username,
        "password": url.password,
        "dbname": database,
    }


def _recreate_database(url: URL, name: str) -> None:
    """Drop and recreate a test database on the Compose server."""
    with psycopg.connect(autocommit=True, **_connection_parameters(url, "postgres")) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(url: URL, name: str) -> None:
    with psycopg.connect(autocommit=True, **_connection_parameters(url, "postgres")) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _run_alembic(command: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    """Run the real Alembic CLI against a specific database."""
    environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_must_succeed(
    command: list[str], database_url: str
) -> subprocess.CompletedProcess[str]:
    result = _run_alembic(command, database_url)
    assert result.returncode == 0, (
        f"alembic {' '.join(command)} failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _truncate_all(engine: Engine) -> None:
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """A migrated scratch database for entity and constraint tests."""
    application_url = _application_url()
    database_name = "mogen_test"
    _recreate_database(application_url, database_name)
    database_url = _with_database(application_url, database_name)
    try:
        _alembic_must_succeed(["upgrade", "head"], database_url)
        yield database_url
    finally:
        _drop_database(application_url, database_name)


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose work is discarded after every test."""
    _truncate_all(migrated_engine)
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def clean_database(migrated_engine: Engine) -> Iterator[Engine]:
    """Truncate all tables for tests that talk to the API instead of a session."""
    _truncate_all(migrated_engine)
    yield migrated_engine


@pytest.fixture
def session_factory(migrated_engine: Engine) -> sessionmaker[Session]:
    """A factory for services that own their transaction, such as workers.

    Unlike ``db_session`` an instance of this factory commits explicitly, so
    dispatcher and recovery tests can observe committed state from a second
    connection.
    """
    return sessionmaker(bind=migrated_engine, expire_on_commit=False, class_=Session)


@pytest.fixture
def inspection_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session for assertions after API calls; it never truncates."""
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def api_client_factory(
    test_database_url: str, clean_database: Engine
) -> Iterator[Callable[..., TestClient]]:
    """Build API clients against the scratch database.

    Settings can be overridden per client so a test can, for example, lower
    ``max_page_size``. Every client shares the one truncated database.
    """
    with ExitStack() as stack:

        def _factory(**overrides: Any) -> TestClient:
            values: dict[str, Any] = {
                **API_TEST_SETTINGS,
                "database_url": test_database_url,
            }
            values.update(overrides)
            return stack.enter_context(TestClient(create_app(Settings(**values))))

        yield _factory


@pytest.fixture
def api_client(api_client_factory: Callable[..., TestClient]) -> TestClient:
    """An unauthenticated API client."""
    return api_client_factory()


@pytest.fixture
def register_client(
    api_client_factory: Callable[..., TestClient],
) -> Callable[..., TestClient]:
    """Return a factory that registers a user and yields that user's client.

    Each registered client has its own cookie jar, so one test can exercise
    two users without juggling headers.
    """

    def _register(
        *,
        email: str | None = None,
        password: str = API_TEST_PASSWORD,
        **overrides: Any,
    ) -> TestClient:
        client = api_client_factory(**overrides)
        response = client.post(
            REGISTER_URL,
            json={"email": email or f"user-{uuid.uuid4().hex}@example.com", "password": password},
        )
        assert response.status_code == 201, response.text
        return client

    return _register


@pytest.fixture
def registered_client(register_client: Callable[..., TestClient]) -> TestClient:
    """A client holding the session cookies of a freshly registered user."""
    return register_client(email="user@example.com")


@pytest.fixture
def alembic() -> Callable[[list[str], str], subprocess.CompletedProcess[str]]:
    """Expose the Alembic runner to tests that need the raw result."""
    return _run_alembic


@pytest.fixture(scope="session")
def migration_database_url() -> Iterator[str]:
    """A separate scratch database for schema and migration tests."""
    application_url = _application_url()
    database_name = "mogen_test_migration"
    _recreate_database(application_url, database_name)
    database_url = _with_database(application_url, database_name)
    try:
        yield database_url
    finally:
        _drop_database(application_url, database_name)


@pytest.fixture
def migration_alembic() -> Callable[[list[str], str], subprocess.CompletedProcess[str]]:
    """Alembic runner whose failures are assertions, not silent skips."""
    return _alembic_must_succeed


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    def _make_user(**overrides: Any) -> User:
        values: dict[str, Any] = {
            "email": f"user-{uuid.uuid4().hex}@example.com",
            "password_hash": "argon2id-placeholder-hash",
        }
        values.update(overrides)
        user = User(**values)
        db_session.add(user)
        db_session.flush()
        return user

    return _make_user


def _utc_after(**offset: int) -> datetime:
    return datetime.now(UTC) + timedelta(**offset)


@pytest.fixture
def make_session(db_session: Session) -> Callable[..., UserSession]:
    def _make_session(user: User, **overrides: Any) -> UserSession:
        values: dict[str, Any] = {
            "token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "expires_at": _utc_after(days=1),
        }
        values.update(overrides)
        session = UserSession(user_id=user.id, **values)
        db_session.add(session)
        db_session.flush()
        return session

    return _make_session


@pytest.fixture
def make_project(db_session: Session) -> Callable[..., Project]:
    def _make_project(owner: User, **overrides: Any) -> Project:
        values: dict[str, Any] = {
            "name": "Test project",
            "type": ProjectType.OBJECT.value,
            "status": ProjectStatus.CREATED.value,
        }
        values.update(overrides)
        project = Project(user_id=owner.id, **values)
        db_session.add(project)
        db_session.flush()
        return project

    return _make_project


@pytest.fixture
def make_image(db_session: Session) -> Callable[..., ProjectImage]:
    def _make_image(project: Project, **overrides: Any) -> ProjectImage:
        values: dict[str, Any] = {
            "original_filename": "photo.jpg",
            "storage_key": f"projects/{project.id}/source/{uuid.uuid4().hex}.jpg",
            "mime_type": "image/jpeg",
            "file_size_bytes": 1024,
            "sha256": SHA256_SAMPLE,
            "width": 640,
            "height": 480,
            "position": 0,
        }
        values.update(overrides)
        image = ProjectImage(project_id=project.id, **values)
        db_session.add(image)
        db_session.flush()
        return image

    return _make_image


@pytest.fixture
def make_task(db_session: Session) -> Callable[..., GenerationTask]:
    def _make_task(project: Project, **overrides: Any) -> GenerationTask:
        values: dict[str, Any] = {
            "task_type": TaskType.OBJECT.value,
            "status": "PENDING",
            "idempotency_key": uuid.uuid4().hex,
            "request_fingerprint": uuid.uuid4().hex + uuid.uuid4().hex,
            "parameters": {"algorithm": "TripoSR", "output_format": "GLB"},
        }
        values.update(overrides)
        task = GenerationTask(project_id=project.id, **values)
        db_session.add(task)
        db_session.flush()
        return task

    return _make_task


@pytest.fixture
def make_task_image(db_session: Session) -> Callable[..., GenerationTaskImage]:
    def _make_task_image(
        task: GenerationTask, image: ProjectImage, **overrides: Any
    ) -> GenerationTaskImage:
        values: dict[str, Any] = {"position": 0}
        values.update(overrides)
        task_image = GenerationTaskImage(
            task_id=task.id, image_id=image.id, project_id=task.project_id, **values
        )
        db_session.add(task_image)
        db_session.flush()
        return task_image

    return _make_task_image


@pytest.fixture
def make_result(db_session: Session) -> Callable[..., GenerationResult]:
    def _make_result(project: Project, task: GenerationTask, **overrides: Any) -> GenerationResult:
        values: dict[str, Any] = {
            "format": "GLB",
            "mime_type": "model/gltf-binary",
            "storage_key": f"projects/{project.id}/results/{uuid.uuid4().hex}.glb",
            "file_size_bytes": 2048,
            "sha256": SHA256_SAMPLE,
            "result_metadata": {"vertices_count": 100},
            "is_current": False,
        }
        values.update(overrides)
        result = GenerationResult(project_id=project.id, task_id=task.id, **values)
        db_session.add(result)
        db_session.flush()
        return result

    return _make_result


@pytest.fixture
def make_cleanup_job(db_session: Session) -> Callable[..., StorageCleanupJob]:
    def _make_cleanup_job(project: Project | None, **overrides: Any) -> StorageCleanupJob:
        values: dict[str, Any] = {
            "storage_key": f"projects/{uuid.uuid4().hex}/",
            "target_type": "DIRECTORY",
            "status": "PENDING",
        }
        values.update(overrides)
        job = StorageCleanupJob(project_id=project.id if project is not None else None, **values)
        db_session.add(job)
        db_session.flush()
        return job

    return _make_cleanup_job


@pytest.fixture
def make_outbox_message(db_session: Session) -> Callable[..., OutboxMessage]:
    def _make_outbox_message(task: GenerationTask, **overrides: Any) -> OutboxMessage:
        values: dict[str, Any] = {
            "event_type": "generation.requested",
            "aggregate_type": "GenerationTask",
            "aggregate_id": task.id,
            "payload": {
                "event_id": str(uuid.uuid4()),
                "event_type": "generation.requested",
                "schema_version": 1,
                "task_id": str(task.id),
                "project_id": str(task.project_id),
                "task_type": task.task_type,
            },
        }
        values.update(overrides)
        message = OutboxMessage(**values)
        db_session.add(message)
        db_session.flush()
        return message

    return _make_outbox_message


# --- repositories bound to the test session -------------------------------


@pytest.fixture
def user_repository(db_session: Session) -> UserRepository:
    return UserRepository(db_session)


@pytest.fixture
def session_repository(db_session: Session) -> SessionRepository:
    return SessionRepository(db_session)


@pytest.fixture
def project_repository(db_session: Session) -> ProjectRepository:
    return ProjectRepository(db_session)


@pytest.fixture
def image_repository(db_session: Session) -> ImageRepository:
    return ImageRepository(db_session)


@pytest.fixture
def task_repository(db_session: Session) -> TaskRepository:
    return TaskRepository(db_session)


@pytest.fixture
def result_repository(db_session: Session) -> ResultRepository:
    return ResultRepository(db_session)


@pytest.fixture
def cleanup_job_repository(db_session: Session) -> CleanupJobRepository:
    return CleanupJobRepository(db_session)


@pytest.fixture
def outbox_repository(db_session: Session) -> OutboxRepository:
    return OutboxRepository(db_session)
