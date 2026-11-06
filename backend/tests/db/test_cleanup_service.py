"""Cleanup worker behaviour against PostgreSQL and real file storage.

Traceability: DB-AC-15 (schedule, track and retry cleanup), DB-AC-16 (job
persistence), 08_infrastructure.md Sections 3.7 and 7.2; 05_database_
specification.md Sections 12.2-12.5; data_flow.md Sections 14.5-14.6;
09_testing.md Sections 8.4, 8.5, 16.4 and 16.7; TEST-AC-09.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import Project, StorageCleanupJob, User
from app.services.cleanup_service import CleanupService
from app.storage import LocalStorage
from app.tasks.cleanup_tasks import run_cleanup

pytestmark = [pytest.mark.integration]

PROJECTS_URL = "/api/v1/projects"
IMAGES_URL = "/api/v1/projects/{project_id}/images"


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def storage(storage_root: Path) -> LocalStorage:
    return LocalStorage(storage_root)


@pytest.fixture
def cleanup_settings(storage_root: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(storage_root),
        cleanup_batch_size=6,
        cleanup_max_attempts=3,
        cleanup_poll_interval_seconds=1,
    )


@pytest.fixture
def session_factory(migrated_engine) -> sessionmaker[Session]:
    return sessionmaker(bind=migrated_engine, expire_on_commit=False, class_=Session)


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _reload(session: Session, job_id: uuid.UUID) -> StorageCleanupJob:
    session.expire_all()
    job = session.get(StorageCleanupJob, job_id)
    assert job is not None
    return job


# --- processing a job (05 Section 12.3) -----------------------------------


def test_process_pending_deletes_a_file_and_completes_the_job(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"stored image", key)
    job = make_cleanup_job(project, storage_key=key, target_type="FILE")
    db_session.commit()

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending()

    assert (summary.attempted, summary.completed, summary.failed) == (1, 1, 0)
    assert storage.exists(key) is False
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "COMPLETED"
    assert reloaded.attempts == 1
    assert reloaded.completed_at is not None
    assert reloaded.last_error is None


def test_process_pending_removes_a_directory_tree(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    storage.save(b"source", f"projects/{project.id}/source/{uuid.uuid4()}.jpg")
    storage.save(b"working", f"projects/{project.id}/working/object/{uuid.uuid4()}/mesh.bin")
    job = make_cleanup_job(project, storage_key=f"projects/{project.id}/", target_type="DIRECTORY")
    db_session.commit()

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending()

    assert summary.completed == 1
    assert storage.exists(f"projects/{project.id}/") is False
    assert _reload(db_session, job.id).status == "COMPLETED"


def test_an_absent_target_counts_as_success(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    job = make_cleanup_job(
        project,
        storage_key=f"projects/{project.id}/source/{uuid.uuid4()}.jpg",
        target_type="FILE",
    )
    db_session.commit()

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending()

    assert summary.completed == 1
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "COMPLETED"
    assert reloaded.last_error is None


# --- failures and retries (05 Section 12.4, data_flow 14.5) ---------------


def test_failed_delete_is_retried_and_then_marked_failed(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    job = make_cleanup_job(
        project, storage_key=f"projects/{project.id}/source/{uuid.uuid4()}.jpg", target_type="FILE"
    )
    db_session.commit()
    service = CleanupService(db_session, cleanup_settings, storage)

    def failing_delete(self: LocalStorage, key: str) -> None:
        raise AppError(503, "STORAGE_UNAVAILABLE", "The storage backend is unavailable.")

    monkeypatch.setattr(LocalStorage, "delete", failing_delete)

    first = service.process_pending()
    reloaded = _reload(db_session, job.id)
    assert first.retried == 1
    assert reloaded.status == "PENDING"
    assert reloaded.attempts == 1
    assert reloaded.last_error == "The storage backend is unavailable."
    assert reloaded.completed_at is None

    second = service.process_pending()
    assert second.retried == 1
    assert _reload(db_session, job.id).attempts == 2

    third = service.process_pending()
    assert third.failed == 1
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "FAILED"
    assert reloaded.attempts == 3
    assert reloaded.last_error is not None

    # FAILED is terminal: the next cycle does not attempt it again.
    assert service.process_pending().attempted == 0
    assert _reload(db_session, job.id).attempts == 3


def test_max_attempts_one_fails_immediately(
    db_session: Session,
    storage_root: Path,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    job = make_cleanup_job(
        project, storage_key=f"projects/{project.id}/source/{uuid.uuid4()}.jpg", target_type="FILE"
    )
    db_session.commit()
    settings = Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(storage_root),
        cleanup_max_attempts=1,
    )

    def failing_delete(self: LocalStorage, key: str) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(LocalStorage, "delete", failing_delete)

    summary = CleanupService(db_session, settings, storage).process_pending()

    assert summary.failed == 1
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "FAILED"
    assert reloaded.attempts == 1
    assert "disk unavailable" in (reloaded.last_error or "")


# --- duplicate delivery and targeted dispatch -----------------------------


def test_repeated_delivery_of_a_completed_job_is_a_noop(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"payload", key)
    job = make_cleanup_job(project, storage_key=key, target_type="FILE")
    db_session.commit()
    service = CleanupService(db_session, cleanup_settings, storage)

    service.process_pending()
    outcome = service.process_job(job.id)

    assert outcome is None
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "COMPLETED"
    assert reloaded.attempts == 1


def test_process_job_targets_one_job(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    first_key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    second_key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"first", first_key)
    storage.save(b"second", second_key)
    first = make_cleanup_job(project, storage_key=first_key, target_type="FILE")
    second = make_cleanup_job(project, storage_key=second_key, target_type="FILE")
    db_session.commit()
    service = CleanupService(db_session, cleanup_settings, storage)

    outcome = service.process_job(second.id)

    assert outcome is not None and outcome.completed
    assert storage.exists(second_key) is False
    assert storage.exists(first_key) is True
    assert _reload(db_session, first.id).status == "PENDING"


def test_process_job_ignores_an_unknown_identifier(
    db_session: Session, cleanup_settings: Settings, storage: LocalStorage
) -> None:
    assert CleanupService(db_session, cleanup_settings, storage).process_job(uuid.uuid4()) is None


# --- active-task coordination (08 Section 3.7, data_flow 14.4) ------------


def test_directory_job_waits_for_an_active_generation_task(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    task_repository,
    make_user,
    make_project,
    make_cleanup_job,
    make_task,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    storage.save(b"source", f"projects/{project.id}/source/{uuid.uuid4()}.jpg")
    job = make_cleanup_job(project, storage_key=f"projects/{project.id}/", target_type="DIRECTORY")
    task = make_task(project, status="PROCESSING")
    db_session.commit()
    service = CleanupService(db_session, cleanup_settings, storage)

    deferred = service.process_pending()

    assert deferred.deferred == 1
    assert deferred.attempted == 0
    assert storage.exists(f"projects/{project.id}/") is True
    reloaded = _reload(db_session, job.id)
    assert reloaded.status == "PENDING"
    assert reloaded.attempts == 0

    task_repository.set_status(task, "CANCELLED", finished_at=datetime.now(UTC))
    db_session.commit()

    completed = service.process_pending()

    assert completed.completed == 1
    assert storage.exists(f"projects/{project.id}/") is False
    assert _reload(db_session, job.id).status == "COMPLETED"


def test_file_job_is_not_deferred_by_a_generation_task(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
    make_task,
) -> None:
    """File jobs address objects whose image row is already deleted.

    Image deletion is refused while a task is active, so a queued file job can
    never point at a file the task still needs.
    """
    owner: User = make_user()
    project: Project = make_project(owner)
    key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"payload", key)
    job = make_cleanup_job(project, storage_key=key, target_type="FILE")
    make_task(project, status="PROCESSING")
    db_session.commit()

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending()

    assert summary.completed == 1
    assert storage.exists(key) is False
    assert _reload(db_session, job.id).status == "COMPLETED"


def test_a_deferred_job_does_not_starve_the_batch(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
    make_task,
) -> None:
    owner: User = make_user()
    blocked_project = make_project(owner, name="Blocked")
    free_project = make_project(owner, name="Free")
    storage.save(b"source", f"projects/{blocked_project.id}/source/{uuid.uuid4()}.jpg")
    blocked = make_cleanup_job(
        blocked_project,
        storage_key=f"projects/{blocked_project.id}/",
        target_type="DIRECTORY",
        created_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    free_key = f"projects/{free_project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"payload", free_key)
    free = make_cleanup_job(free_project, storage_key=free_key, target_type="FILE")
    make_task(blocked_project, status="PROCESSING")
    db_session.commit()

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending(limit=1)

    assert summary.completed == 1
    assert summary.deferred == 1
    assert storage.exists(free_key) is False
    assert _reload(db_session, free.id).status == "COMPLETED"
    assert _reload(db_session, blocked.id).status == "PENDING"


def test_batch_limit_is_respected(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    jobs = []
    for _ in range(3):
        key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
        storage.save(b"payload", key)
        jobs.append(make_cleanup_job(project, storage_key=key, target_type="FILE"))
    db_session.commit()
    service = CleanupService(db_session, cleanup_settings, storage)

    first = service.process_pending(limit=2)

    assert first.completed == 2
    statuses = [_reload(db_session, job.id).status for job in jobs]
    assert statuses.count("COMPLETED") == 2
    assert statuses.count("PENDING") == 1

    assert service.process_pending(limit=2).completed == 1


# --- worker entrypoint ----------------------------------------------------


def test_run_cleanup_processes_pending_jobs_with_new_sessions(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    session_factory,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"payload", key)
    job = make_cleanup_job(project, storage_key=key, target_type="FILE")
    db_session.commit()

    summary = run_cleanup(
        settings=cleanup_settings,
        session_factory=session_factory,
        storage=storage,
        limit=10,
    )

    assert summary.completed == 1
    assert storage.exists(key) is False
    assert _reload(db_session, job.id).status == "COMPLETED"


def test_run_cleanup_can_target_one_job(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    session_factory,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    owner: User = make_user()
    project: Project = make_project(owner)
    first_key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    second_key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"first", first_key)
    storage.save(b"second", second_key)
    first = make_cleanup_job(project, storage_key=first_key, target_type="FILE")
    second = make_cleanup_job(project, storage_key=second_key, target_type="FILE")
    db_session.commit()

    summary = run_cleanup(
        settings=cleanup_settings,
        session_factory=session_factory,
        storage=storage,
        job_id=second.id,
    )

    assert summary.completed == 1
    assert storage.exists(second_key) is False
    assert storage.exists(first_key) is True
    assert _reload(db_session, first.id).status == "PENDING"


def test_the_celery_task_runs_a_cleanup_cycle(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
    make_user,
    make_project,
    make_cleanup_job,
) -> None:
    from app.tasks import cleanup_tasks

    owner: User = make_user()
    project: Project = make_project(owner)
    key = f"projects/{project.id}/source/{uuid.uuid4()}.jpg"
    storage.save(b"payload", key)
    job = make_cleanup_job(project, storage_key=key, target_type="FILE")
    db_session.commit()
    monkeypatch.setattr(cleanup_tasks, "get_settings", lambda: cleanup_settings)
    monkeypatch.setattr(cleanup_tasks, "_runtime_for", lambda settings: (session_factory, storage))

    result = cleanup_tasks.cleanup_storage_task.apply(args=[]).get()

    assert result["completed"] == 1
    assert result["attempted"] == 1
    assert storage.exists(key) is False
    assert _reload(db_session, job.id).status == "COMPLETED"


def test_the_worker_runtime_builds_a_working_session_and_storage(
    tmp_path: Path,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import text

    from app.tasks import cleanup_tasks

    settings = Settings(
        app_env="test",
        database_url=test_database_url,
        storage_root=str(tmp_path / "worker-storage"),
    )
    monkeypatch.setattr(cleanup_tasks, "_runtime", None)

    factory, storage = cleanup_tasks._runtime_for(settings)
    try:
        assert isinstance(storage, LocalStorage)
        with factory() as session:
            assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        factory.kw["bind"].dispose()


# --- end to end with the API ----------------------------------------------


def test_deleted_image_file_is_removed_by_the_worker(
    db_session: Session,
    cleanup_settings: Settings,
    storage: LocalStorage,
    storage_root: Path,
    register_client,
) -> None:
    client = register_client(
        email=f"cleanup-{uuid.uuid4().hex}@example.com", storage_root=str(storage_root)
    )
    project = client.post(
        PROJECTS_URL, json={"name": "Cleanup", "type": "OBJECT"}, headers=_csrf(client)
    ).json()
    image = client.post(
        IMAGES_URL.format(project_id=project["id"]),
        files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=_csrf(client),
    ).json()
    key = f"projects/{project['id']}/source/{image['id']}.jpg"
    assert storage_root.joinpath(*key.split("/")).is_file()

    deleted = client.delete(
        IMAGES_URL.format(project_id=project["id"]) + f"/{image['id']}",
        headers=_csrf(client),
    )
    assert deleted.status_code == 204

    summary = CleanupService(db_session, cleanup_settings, storage).process_pending()

    assert summary.completed == 1
    assert storage_root.joinpath(*key.split("/")).exists() is False
    assert db_session.get(Project, uuid.UUID(project["id"])) is not None
