"""Outbox message to Celery message translation (data_flow.md Sections 6.6, 7.1).

Traceability: BE-AC-14 (object and scene tasks reach their queues),
DB-AC-20 (durable dispatch), INF-AC-10 (queue separation), roadmap 4.4.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models import OutboxMessage
from app.services.outbox_events import CLEANUP_AGGREGATE, GENERATION_AGGREGATE
from app.services.outbox_service import PermanentDispatchError
from app.tasks.celery_app import (
    CLEANUP_QUEUE,
    CLEANUP_TASK_NAME,
    OBJECT_GENERATION_QUEUE,
    OBJECT_GENERATION_TASK,
    SCENE_RECONSTRUCTION_QUEUE,
    SCENE_RECONSTRUCTION_TASK,
)
from app.tasks.outbox_publisher import CeleryPublisher, resolve_dispatch_target

pytestmark = pytest.mark.unit

TASK_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440002")
PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
JOB_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440003")


def _message(
    *,
    event_type: str = "generation.requested",
    task_type: str | None = "OBJECT",
    schema_version: int = 1,
    task_id: str | None = str(TASK_ID),
    project_id: str | None = str(PROJECT_ID),
    cleanup_job_id: str | None = None,
    aggregate_type: str = GENERATION_AGGREGATE,
    aggregate_id: uuid.UUID = TASK_ID,
) -> OutboxMessage:
    payload: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": schema_version,
    }
    if task_type is not None:
        payload["task_type"] = task_type
    if task_id is not None:
        payload["task_id"] = task_id
    if project_id is not None:
        payload["project_id"] = project_id
    if cleanup_job_id is not None:
        payload["cleanup_job_id"] = cleanup_job_id
        payload["target_type"] = "FILE"
        payload["storage_key"] = "projects/00000000-0000-0000-0000-000000000000/source/x.jpg"
    return OutboxMessage(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        schema_version=schema_version,
    )


def test_an_object_generation_event_targets_the_object_queue() -> None:
    target = resolve_dispatch_target(_message(task_type="OBJECT"))

    assert target.task_name == OBJECT_GENERATION_TASK
    assert target.queue == OBJECT_GENERATION_QUEUE
    assert target.task_id == str(TASK_ID)
    assert target.args == (str(TASK_ID),)
    assert target.kwargs == {"project_id": str(PROJECT_ID), "task_type": "OBJECT"}


def test_a_scene_generation_event_targets_the_scene_queue() -> None:
    target = resolve_dispatch_target(_message(task_type="SCENE"))

    assert target.task_name == SCENE_RECONSTRUCTION_TASK
    assert target.queue == SCENE_RECONSTRUCTION_QUEUE
    assert target.kwargs["task_type"] == "SCENE"


def test_a_cleanup_event_targets_the_cleanup_queue() -> None:
    message = _message(
        event_type="cleanup.requested",
        task_type=None,
        task_id=None,
        project_id=None,
        cleanup_job_id=str(JOB_ID),
        aggregate_type=CLEANUP_AGGREGATE,
        aggregate_id=JOB_ID,
    )

    target = resolve_dispatch_target(message)

    assert target.task_name == CLEANUP_TASK_NAME
    assert target.queue == CLEANUP_QUEUE
    assert target.task_id == str(JOB_ID)
    assert target.args == (str(JOB_ID),)
    assert target.kwargs == {}


def test_an_unsupported_schema_version_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(schema_version=2))


def test_an_unknown_event_type_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(event_type="project.archived"))


def test_an_unknown_task_type_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(task_type="VIDEO"))


def test_a_missing_task_id_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(task_id=None))


def test_a_malformed_task_id_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(task_id="not-a-uuid"))


def test_a_missing_project_id_is_permanent() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(project_id=None))


def _cleanup_message(**overrides) -> OutboxMessage:
    return _message(
        event_type="cleanup.requested",
        task_type=None,
        task_id=None,
        project_id=None,
        cleanup_job_id=str(JOB_ID),
        aggregate_type=CLEANUP_AGGREGATE,
        aggregate_id=JOB_ID,
        **overrides,
    )


def test_a_cleanup_event_without_a_job_id_is_permanent() -> None:
    message = _cleanup_message()
    message.payload = {**message.payload, "cleanup_job_id": None}

    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(message)


def test_a_cleanup_event_with_an_unknown_target_type_is_permanent() -> None:
    message = _cleanup_message()
    message.payload = {**message.payload, "target_type": "WHOLE_DISK"}

    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(message)


def test_a_cleanup_event_without_a_storage_key_is_permanent() -> None:
    message = _cleanup_message()
    message.payload = {**message.payload, "storage_key": None}

    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(message)


class _RecordingApp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def send_task(self, name: str, **kwargs: object) -> None:
        self.calls.append((name, kwargs))


def test_the_publisher_sends_the_task_without_celery_side_retries() -> None:
    app = _RecordingApp()
    publisher = CeleryPublisher(app)  # type: ignore[arg-type]

    publisher.publish(_message())

    name, kwargs = app.calls[0]
    assert name == OBJECT_GENERATION_TASK
    assert kwargs["queue"] == OBJECT_GENERATION_QUEUE
    assert kwargs["task_id"] == str(TASK_ID)
    assert kwargs["retry"] is False
    assert kwargs["args"] == [str(TASK_ID)]
