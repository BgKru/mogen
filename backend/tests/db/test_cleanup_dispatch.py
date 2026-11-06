"""Cleanup jobs are dispatched through the outbox and executed by the worker.

Traceability: DB-AC-15 (cleanup scheduling and completion), DB-AC-20 (durable
outbox), BE-AC-13 (background scheduling), INF-AC-10 (file_cleanup queue),
TEST-AC-09, roadmap 4.4, 4.8 and 4.9.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import OutboxMessage, StorageCleanupJob
from app.services.outbox_service import dispatch_pending
from app.storage import LocalStorage
from app.tasks.cleanup_tasks import run_cleanup
from app.tasks.outbox_publisher import resolve_dispatch_target

pytestmark = [pytest.mark.integration]

PROJECTS_URL = "/api/v1/projects"


def _csrf(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token
    return {"X-CSRF-Token": token}


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(90, 40, 10)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _create_project(client) -> dict:
    response = client.post(
        PROJECTS_URL,
        json={"name": "Cleanup project", "type": "OBJECT"},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_image(client, project_id: str) -> dict:
    response = client.post(
        f"{PROJECTS_URL}/{project_id}/images",
        files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _delete_image(client, project_id: str, image_id: str):
    return client.delete(
        f"{PROJECTS_URL}/{project_id}/images/{image_id}",
        headers=_csrf(client),
    )


@pytest.fixture
def cleanup_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(tmp_path / "storage"),
        cleanup_batch_size=6,
        cleanup_max_attempts=3,
        outbox_batch_size=10,
        outbox_max_attempts=3,
    )


class _TargetPublisher:
    def __init__(self) -> None:
        self.targets = []

    def publish(self, message: OutboxMessage) -> None:
        self.targets.append(resolve_dispatch_target(message))


def _cleanup_events(session: Session, job_id: uuid.UUID) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_type == "StorageCleanupJob",
                OutboxMessage.aggregate_id == job_id,
            )
        ).all()
    )


def test_image_deletion_records_a_cleanup_event(
    api_client_factory, inspection_session: Session, tmp_path: Path
) -> None:
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    assert registration.status_code == 201, registration.text
    project = _create_project(client)
    image = _upload_image(client, project["id"])

    assert _delete_image(client, project["id"], image["id"]).status_code == 204

    job = inspection_session.scalars(select(StorageCleanupJob)).one()
    events = _cleanup_events(inspection_session, job.id)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "cleanup.requested"
    assert event.schema_version == 1
    assert event.status == "PENDING"
    assert event.payload["event_id"] == str(event.id)
    assert event.payload["cleanup_job_id"] == str(job.id)
    assert event.payload["project_id"] == project["id"]
    assert event.payload["target_type"] == "FILE"
    assert event.payload["storage_key"] == job.storage_key


def test_project_deletion_records_a_cleanup_event(
    api_client_factory, inspection_session: Session, tmp_path: Path
) -> None:
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    project = _create_project(client)

    response = client.delete(f"{PROJECTS_URL}/{project['id']}", headers=_csrf(client))
    assert response.status_code == 202

    job = inspection_session.scalars(select(StorageCleanupJob)).one()
    events = _cleanup_events(inspection_session, job.id)
    assert len(events) == 1
    assert events[0].payload["target_type"] == "DIRECTORY"
    assert events[0].payload["storage_key"] == f"projects/{project['id']}/"


def test_the_dispatcher_routes_the_cleanup_event_to_the_cleanup_queue(
    api_client_factory,
    inspection_session: Session,
    session_factory: sessionmaker[Session],
    cleanup_settings: Settings,
    tmp_path: Path,
) -> None:
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    project = _create_project(client)
    image = _upload_image(client, project["id"])
    _delete_image(client, project["id"], image["id"])
    job = inspection_session.scalars(select(StorageCleanupJob)).one()

    publisher = _TargetPublisher()
    summary = dispatch_pending(
        inspection_session,
        settings=cleanup_settings,
        publisher=publisher,
        dispatcher_id="cleanup-test",
    )

    assert summary.published == 1
    assert len(publisher.targets) == 1
    target = publisher.targets[0]
    assert target.task_name == "cleanup_storage_task"
    assert target.queue == "file_cleanup"
    assert target.args == (str(job.id),)
    event = _cleanup_events(inspection_session, job.id)[0]
    assert event.status == "PUBLISHED"


def test_a_dispatched_cleanup_job_is_processed_by_the_worker(
    api_client_factory,
    inspection_session: Session,
    session_factory: sessionmaker[Session],
    cleanup_settings: Settings,
    tmp_path: Path,
) -> None:
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    project = _create_project(client)
    image = _upload_image(client, project["id"])
    _delete_image(client, project["id"], image["id"])
    job = inspection_session.scalars(select(StorageCleanupJob)).one()
    storage_key = job.storage_key
    storage = LocalStorage(tmp_path / "storage")
    assert storage.exists(storage_key) is True

    summary = run_cleanup(
        settings=cleanup_settings,
        session_factory=session_factory,
        storage=storage,
        job_id=job.id,
    )

    assert summary.completed == 1
    assert storage.exists(storage_key) is False
    inspection_session.expire_all()
    reloaded = inspection_session.get(StorageCleanupJob, job.id)
    assert reloaded is not None
    assert reloaded.status == "COMPLETED"
    assert reloaded.attempts == 1


def test_a_cleanup_event_failure_rolls_back_the_image_deletion(
    api_client_factory, inspection_session: Session, monkeypatch, tmp_path: Path
) -> None:
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    project = _create_project(client)
    image = _upload_image(client, project["id"])

    def _fail(_outbox, _job):
        raise RuntimeError("outbox insert failed")

    monkeypatch.setattr("app.services.image_service.create_cleanup_event", _fail)

    with pytest.raises(RuntimeError):
        _delete_image(client, project["id"], image["id"])

    assert inspection_session.scalar(select(func.count()).select_from(StorageCleanupJob)) == 0
    content = client.get(f"{PROJECTS_URL}/{project['id']}/images/{image['id']}/content")
    assert content.status_code == 200


def test_the_beat_scan_still_processes_an_undispatched_cleanup_job(
    api_client_factory,
    inspection_session: Session,
    session_factory: sessionmaker[Session],
    cleanup_settings: Settings,
    tmp_path: Path,
) -> None:
    """A job whose event was never dispatched remains recoverable by the poll."""
    client = api_client_factory(storage_root=str(tmp_path / "storage"))
    client.post(
        "/api/v1/auth/register",
        json={"email": f"cleanup-{uuid.uuid4().hex}@example.com", "password": "SecurePassword123"},
    )
    project = _create_project(client)
    image = _upload_image(client, project["id"])
    _delete_image(client, project["id"], image["id"])
    job = inspection_session.scalars(select(StorageCleanupJob)).one()
    storage = LocalStorage(tmp_path / "storage")

    summary = run_cleanup(
        settings=cleanup_settings, session_factory=session_factory, storage=storage
    )

    assert summary.completed == 1
    inspection_session.expire_all()
    assert inspection_session.get(StorageCleanupJob, job.id).status == "COMPLETED"
