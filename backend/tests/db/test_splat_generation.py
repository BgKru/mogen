"""Scene representation selection through the public generation API.

Traceability: increment 15 Sections 4.2 and 7; I15-AC-02, I15-AC-03, I15-AC-09,
I15-AC-11. The work is limited to task creation, the persisted parameters and
the outbox message: no ML runs in this test.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationTask, OutboxMessage
from app.tasks.celery_app import SCENE_RECONSTRUCTION_QUEUE, SCENE_SPLAT_QUEUE
from app.tasks.outbox_publisher import resolve_dispatch_target

pytestmark = [pytest.mark.integration]

PROJECTS_URL = "/api/v1/projects"


def _csrf(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _create_scene_project(client, *, name: str = "Splat project") -> dict:
    response = client.post(
        PROJECTS_URL,
        json={"name": name, "type": "SCENE"},
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


def _generate(client, project_id: str):
    response = client.post(
        f"{PROJECTS_URL}/{project_id}/generate",
        json={},
        headers={**_csrf(client), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["task"]["id"])


def _events(session: Session, task_id: uuid.UUID) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        session.scalars(select(OutboxMessage).where(OutboxMessage.aggregate_id == task_id)).all()
    )


def _splat_client(register_client):
    return register_client(
        scene_representation="gaussian_splat",
        scene_splat_enabled=True,
        scene_output_format="PLY",
    )


def test_a_splat_project_persists_the_representation_and_routes_to_the_neural_queue(
    register_client, inspection_session: Session
) -> None:
    client = _splat_client(register_client)
    project = _create_scene_project(client)
    for _ in range(3):
        _upload_image(client, project["id"])

    task_id = _generate(client, project["id"])

    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    assert task.parameters["representation"] == "GAUSSIAN_SPLAT"
    assert task.parameters["method"] == "NERFSTUDIO_SPLATFACTO"
    assert task.parameters["algorithm"] == "COLMAP_SPLATFACTO"
    assert task.parameters["output_format"] == "PLY"

    events = _events(inspection_session, task_id)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["representation"] == "GAUSSIAN_SPLAT"
    target = resolve_dispatch_target(events[0])
    assert target.queue == SCENE_SPLAT_QUEUE
    assert target.task_name == "reconstruct_scene_task"


def test_a_mesh_project_keeps_the_released_queue_and_parameters(
    registered_client, inspection_session: Session
) -> None:
    project = _create_scene_project(registered_client, name="Mesh project")
    for _ in range(3):
        _upload_image(registered_client, project["id"])

    task_id = _generate(registered_client, project["id"])

    task = inspection_session.get(GenerationTask, task_id)
    assert task is not None
    assert task.parameters["representation"] == "MESH"
    assert task.parameters["output_format"] == "GLB"
    events = _events(inspection_session, task_id)
    assert events and events[0].payload["representation"] == "MESH"
    assert resolve_dispatch_target(events[0]).queue == SCENE_RECONSTRUCTION_QUEUE


def test_splat_generation_requires_the_capability_gate_at_startup() -> None:
    """The deployment cannot silently select splat without the neural image."""
    from app.core.config import Settings

    with pytest.raises(ValueError, match="scene_splat_enabled"):
        Settings(
            app_env="test",
            scene_representation="gaussian_splat",
            scene_output_format="PLY",
        )
