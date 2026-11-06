"""Generation start and status API against PostgreSQL.

Traceability: BE-AC-13 (persistent tasks scheduled through the outbox),
BE-AC-15 (accurate status), BE-AC-16 (duplicate protection), DB-AC-16
(transaction consistency), DB-AC-20 (durable outbox), DB-AC-21 (project-scoped
idempotency), DB-AC-22 (composite ownership), API-AC-09..12 (202/200,
idempotency, 409 conflicts, persisted status), TEST-AC-06/07/08/18, roadmap
4.5-4.7 and 4.9.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import (
    GenerationResult,
    GenerationTask,
    GenerationTaskImage,
    OutboxMessage,
    Project,
)
from app.repositories import OutboxRepository
from app.services.generation_service import GenerationService

pytestmark = [pytest.mark.integration]

PROJECTS_URL = "/api/v1/projects"
SHA256_SAMPLE = "0123456789abcdef" * 4


def _csrf(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _create_project(client, *, project_type: str = "OBJECT", name: str = "Project") -> dict:
    response = client.post(
        PROJECTS_URL,
        json={"name": name, "type": project_type},
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


def _generate(client, project_id: str, key: str):
    return client.post(
        f"{PROJECTS_URL}/{project_id}/generate",
        json={},
        headers={**_csrf(client), "Idempotency-Key": key},
    )


def _status(client, project_id: str):
    return client.get(f"{PROJECTS_URL}/{project_id}/status")


def _task_count(session: Session, project_id: uuid.UUID) -> int:
    session.expire_all()
    return (
        session.scalar(
            select(func.count())
            .select_from(GenerationTask)
            .where(GenerationTask.project_id == project_id)
        )
        or 0
    )


def _task_events(session: Session, task_id: uuid.UUID) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_type == "GenerationTask",
                OutboxMessage.aggregate_id == task_id,
            )
        ).all()
    )


def _finish_task(session: Session, task_id: uuid.UUID, status: str = "FAILED") -> None:
    """Move a task and its project to a terminal state without touching results."""
    task = session.get(GenerationTask, task_id)
    assert task is not None
    task.status = status
    task.finished_at = datetime.now(UTC)
    project = session.get(Project, task.project_id)
    assert project is not None
    project.status = status
    session.commit()


# --- successful creation --------------------------------------------------


def test_object_generation_is_accepted_and_persisted(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client, project_type="OBJECT")
    image = _upload_image(registered_client, project["id"])

    response = _generate(registered_client, project["id"], "object-key-1")

    assert response.status_code == 202, response.text
    body = response.json()["task"]
    task_id = uuid.UUID(body["id"])
    project_id = uuid.UUID(project["id"])
    assert body["project_id"] == project["id"]
    assert body["task_type"] == "OBJECT"
    assert body["status"] == "PENDING"
    assert body["stage"] is None
    assert body["progress_percent"] is None
    assert body["status_message"] == "Generation task accepted"
    assert body["created_at"] is not None
    assert body["started_at"] is None
    assert body["finished_at"] is None
    assert "storage_key" not in response.text

    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    assert task.project_id == project_id
    assert task.status == "PENDING"
    assert task.celery_task_id == str(task_id)
    assert task.idempotency_key == "object-key-1"
    assert len(task.request_fingerprint) == 64
    assert task.parameters == {"algorithm": "TripoSR", "output_format": "GLB"}
    assert task.queued_at is not None

    snapshot = inspection_session.scalars(
        select(GenerationTaskImage).where(GenerationTaskImage.task_id == task_id)
    ).all()
    assert [(row.image_id, row.position) for row in snapshot] == [(uuid.UUID(image["id"]), 0)]

    reloaded_project = inspection_session.get(Project, project_id)
    assert reloaded_project is not None
    assert reloaded_project.status == "PENDING"

    events = _task_events(inspection_session, task_id)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "generation.requested"
    assert event.aggregate_id == task_id
    assert event.schema_version == 1
    assert event.status == "PENDING"
    assert event.payload["event_id"] == str(event.id)
    assert event.payload["task_id"] == str(task_id)
    assert event.payload["project_id"] == project["id"]
    assert event.payload["task_type"] == "OBJECT"


def test_scene_generation_snapshots_every_image_in_order(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client, project_type="SCENE")
    images = [_upload_image(registered_client, project["id"]) for _ in range(3)]

    response = _generate(registered_client, project["id"], "scene-key-1")

    assert response.status_code == 202, response.text
    task_id = uuid.UUID(response.json()["task"]["id"])
    assert response.json()["task"]["task_type"] == "SCENE"
    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    assert task.parameters == {"algorithm": "COLMAP_OPENMVS", "output_format": "GLB"}
    snapshot = inspection_session.scalars(
        select(GenerationTaskImage)
        .where(GenerationTaskImage.task_id == task_id)
        .order_by(GenerationTaskImage.position)
    ).all()
    assert [(row.image_id, row.position) for row in snapshot] == [
        (uuid.UUID(image["id"]), position) for position, image in enumerate(images)
    ]


# --- authorization and request validation --------------------------------


def test_generation_requires_authentication(api_client, registered_client) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])

    response = api_client.post(
        f"{PROJECTS_URL}/{project['id']}/generate",
        json={},
        headers={"Idempotency-Key": "anonymous"},
    )

    assert response.status_code == 401


def test_generation_requires_csrf(registered_client) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])

    response = registered_client.post(
        f"{PROJECTS_URL}/{project['id']}/generate",
        json={},
        headers={"Idempotency-Key": "no-csrf"},
    )

    assert response.status_code == 403


def test_a_missing_idempotency_key_is_rejected(registered_client) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])

    response = registered_client.post(
        f"{PROJECTS_URL}/{project['id']}/generate",
        json={},
        headers=_csrf(registered_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_blank_idempotency_key_is_rejected(registered_client) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])

    response = registered_client.post(
        f"{PROJECTS_URL}/{project['id']}/generate",
        json={},
        headers={**_csrf(registered_client), "Idempotency-Key": ""},
    )

    assert response.status_code == 422


def test_another_users_project_is_not_disclosed(
    register_client, inspection_session: Session
) -> None:
    owner = register_client(email="owner@example.com")
    other = register_client(email="other@example.com")
    project = _create_project(owner)
    _upload_image(owner, project["id"])

    response = _generate(other, project["id"], "foreign-key")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 0


def test_an_unknown_project_is_not_found(registered_client) -> None:
    response = _generate(registered_client, str(uuid.uuid4()), "unknown-project")

    assert response.status_code == 404


# --- input and state rules ------------------------------------------------


def test_an_object_project_without_an_image_is_rejected(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client, project_type="OBJECT")

    response = _generate(registered_client, project["id"], "object-empty")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GENERATION_INPUT_MISSING"
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 0


def test_a_scene_project_below_the_minimum_is_rejected(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client, project_type="SCENE")
    _upload_image(registered_client, project["id"])
    _upload_image(registered_client, project["id"])

    response = _generate(registered_client, project["id"], "scene-too-few")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GENERATION_INPUT_MISSING"
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 0


def test_an_uploading_project_rejects_generation(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    row = inspection_session.get(Project, uuid.UUID(project["id"]))
    assert row is not None
    row.status = "UPLOADING"
    inspection_session.commit()

    response = _generate(registered_client, project["id"], "uploading")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"


# --- idempotency and duplicate protection ---------------------------------


def test_a_repeated_key_returns_the_existing_task(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])

    first = _generate(registered_client, project["id"], "repeat-key")
    second = _generate(registered_client, project["id"], "repeat-key")

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 1
    assert len(_task_events(inspection_session, uuid.UUID(first.json()["task"]["id"]))) == 1


def test_a_reused_key_with_different_inputs_is_rejected(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client, project_type="SCENE")
    for _ in range(3):
        _upload_image(registered_client, project["id"])
    first = _generate(registered_client, project["id"], "reused-key")
    assert first.status_code == 202

    _finish_task(inspection_session, uuid.UUID(first.json()["task"]["id"]), "FAILED")
    _upload_image(registered_client, project["id"])

    response = _generate(registered_client, project["id"], "reused-key")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 1


def test_a_second_key_while_a_task_is_active_is_rejected(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    assert _generate(registered_client, project["id"], "first-key").status_code == 202

    response = _generate(registered_client, project["id"], "second-key")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GENERATION_ALREADY_RUNNING"
    assert _task_count(inspection_session, uuid.UUID(project["id"])) == 1


def test_idempotency_keys_are_scoped_to_a_project(registered_client) -> None:
    first = _create_project(registered_client, name="First")
    second = _create_project(registered_client, name="Second")
    _upload_image(registered_client, first["id"])
    _upload_image(registered_client, second["id"])

    first_response = _generate(registered_client, first["id"], "shared-key")
    second_response = _generate(registered_client, second["id"], "shared-key")

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["task"]["id"] != second_response.json()["task"]["id"]


# --- status ---------------------------------------------------------------


def test_status_before_generation_has_no_task(registered_client) -> None:
    project = _create_project(registered_client)

    response = _status(registered_client, project["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["project_status"] == "CREATED"
    assert body["latest_task"] is None
    assert body["result_available"] is False


def test_status_returns_persisted_task_information(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    task_id = uuid.UUID(
        _generate(registered_client, project["id"], "status-key").json()["task"]["id"]
    )

    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    task.status = "PROCESSING"
    task.stage = "MODEL_GENERATION"
    task.progress_percent = 42
    task.status_message = "Generating 3D geometry"
    task.started_at = datetime.now(UTC)
    row = inspection_session.get(Project, uuid.UUID(project["id"]))
    assert row is not None
    row.status = "PROCESSING"
    inspection_session.commit()

    response = _status(registered_client, project["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["project_status"] == "PROCESSING"
    assert body["latest_task"]["status"] == "PROCESSING"
    assert body["latest_task"]["stage"] == "MODEL_GENERATION"
    assert body["latest_task"]["progress_percent"] == 42
    assert body["latest_task"]["status_message"] == "Generating 3D geometry"
    assert body["result_available"] is False


def test_status_reports_the_failure_fields(registered_client, inspection_session: Session) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    task_id = uuid.UUID(
        _generate(registered_client, project["id"], "fail-key").json()["task"]["id"]
    )
    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    task.status = "FAILED"
    task.error_code = "WORKER_UNAVAILABLE"
    task.error_message = "The worker stopped before the task completed."
    task.finished_at = datetime.now(UTC)
    row = inspection_session.get(Project, uuid.UUID(project["id"]))
    assert row is not None
    row.status = "FAILED"
    inspection_session.commit()

    body = _status(registered_client, project["id"]).json()

    assert body["project_status"] == "FAILED"
    assert body["latest_task"]["error_code"] == "WORKER_UNAVAILABLE"
    assert body["latest_task"]["error_message"] is not None
    assert body["latest_task"]["finished_at"] is not None


def test_status_is_ownership_scoped(register_client) -> None:
    owner = register_client(email="status-owner@example.com")
    other = register_client(email="status-other@example.com")
    project = _create_project(owner)

    assert _status(other, project["id"]).status_code == 404
    assert _status(other, str(uuid.uuid4())).status_code == 404


# --- result preservation and retry ----------------------------------------


def _add_current_result(session: Session, project_id: uuid.UUID) -> uuid.UUID:
    """Create a completed task with a current result for a project."""
    task = GenerationTask(
        project_id=project_id,
        task_type="OBJECT",
        status="COMPLETED",
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="a" * 64,
        parameters={"algorithm": "TripoSR", "output_format": "GLB"},
        finished_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session.add(task)
    session.flush()
    result = GenerationResult(
        project_id=project_id,
        task_id=task.id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project_id}/results/{uuid.uuid4()}.glb",
        file_size_bytes=2048,
        sha256=SHA256_SAMPLE,
        result_metadata={"vertices_count": 100},
        is_current=True,
    )
    session.add(result)
    session.commit()
    return result.id


def test_a_current_result_stays_available_while_a_new_task_runs(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    project_id = uuid.UUID(project["id"])
    result_id = _add_current_result(inspection_session, project_id)

    assert _generate(registered_client, project["id"], "preserve-key").status_code == 202

    body = _status(registered_client, project["id"]).json()
    assert body["result_available"] is True
    assert body["project_status"] == "PENDING"
    result = inspection_session.get(GenerationResult, result_id)
    assert result is not None
    inspection_session.refresh(result)
    assert result.is_current is True


def test_retry_after_failure_creates_a_new_task(
    registered_client, inspection_session: Session
) -> None:
    project = _create_project(registered_client)
    _upload_image(registered_client, project["id"])
    project_id = uuid.UUID(project["id"])
    first_task_id = uuid.UUID(
        _generate(registered_client, project["id"], "attempt-one").json()["task"]["id"]
    )
    _finish_task(inspection_session, first_task_id, "FAILED")

    retry = _generate(registered_client, project["id"], "attempt-two")

    assert retry.status_code == 202, retry.text
    assert uuid.UUID(retry.json()["task"]["id"]) != first_task_id
    assert _task_count(inspection_session, project_id) == 2
    assert inspection_session.get(GenerationTask, first_task_id).status == "FAILED"
    assert inspection_session.get(Project, project_id).status == "PENDING"
    # A failed attempt keeps its record and its outbox history.
    assert len(_task_events(inspection_session, first_task_id)) == 1


# --- transaction boundary -------------------------------------------------


def test_task_creation_rolls_back_when_the_outbox_insert_fails(
    db_session: Session, make_user, make_project, make_image, monkeypatch
) -> None:
    owner = make_user()
    project = make_project(owner)
    make_image(project)
    db_session.commit()
    service = GenerationService(db_session, Settings(app_env="test", log_level="WARNING"))

    def _fail(self, **_kwargs):
        raise RuntimeError("outbox insert failed")

    monkeypatch.setattr(OutboxRepository, "create", _fail)

    with pytest.raises(RuntimeError):
        service.start_generation(
            user_id=owner.id, project_id=project.id, idempotency_key="rollback-key"
        )

    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(GenerationTask)) == 0
    assert db_session.scalar(select(func.count()).select_from(OutboxMessage)) == 0
    assert db_session.get(Project, project.id).status == "CREATED"


def test_the_openapi_document_lists_the_generation_routes(api_client) -> None:
    schema = api_client.get("/openapi.json").json()

    assert "/api/v1/projects/{project_id}/generate" in schema["paths"]
    assert "/api/v1/projects/{project_id}/status" in schema["paths"]


def test_the_concurrent_conflict_fallback_uses_the_database_constraint(
    db_session: Session, make_user, make_project, make_task
) -> None:
    """The persistence-level fallback returns or rejects the right request."""
    owner = make_user()
    project = make_project(owner)
    task = make_task(
        project,
        idempotency_key="fallback-key",
        request_fingerprint="a" * 64,
    )
    db_session.commit()
    service = GenerationService(db_session, Settings(app_env="test", log_level="WARNING"))

    existing = service._resolve_concurrent_conflict(project.id, "fallback-key", "a" * 64)
    assert existing is not None
    assert existing.task.id == task.id
    assert existing.created is False

    with pytest.raises(AppError) as reused:
        service._resolve_concurrent_conflict(project.id, "fallback-key", "b" * 64)
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"

    with pytest.raises(AppError) as running:
        service._resolve_concurrent_conflict(project.id, "another-key", "a" * 64)
    assert running.value.code == "GENERATION_ALREADY_RUNNING"

    empty_project = make_project(owner)
    db_session.commit()
    assert service._resolve_concurrent_conflict(empty_project.id, "new-key", "a" * 64) is None
