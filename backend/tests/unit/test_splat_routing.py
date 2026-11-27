"""Deterministic routing for the two scene representations (increment 15).

Traceability: I15-AC-09 and the addendum's Sections 4.2 and 7: mesh tasks go to
the released ``scene_reconstruction`` queue, splat tasks to the dedicated neural
queue, and the choice comes from the persisted payload rather than the current
environment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from celery import Celery

from app.db.models import GenerationTask, OutboxMessage
from app.services.outbox_events import (
    OUTBOX_SCHEMA_VERSION,
    generation_requested_payload,
)
from app.services.outbox_service import PermanentDispatchError
from app.tasks.celery_app import SCENE_RECONSTRUCTION_QUEUE, SCENE_SPLAT_QUEUE
from app.tasks.outbox_publisher import CeleryPublisher, resolve_dispatch_target


def _task(*, task_type: str = "SCENE", parameters: dict[str, str] | None = None) -> GenerationTask:
    return GenerationTask(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        task_type=task_type,
        parameters=parameters or {},
        created_at=datetime.now(UTC),
    )


def _message(payload: dict[str, object]) -> OutboxMessage:
    return OutboxMessage(
        id=uuid.uuid4(),
        event_type="generation.requested",
        aggregate_type="GenerationTask",
        aggregate_id=uuid.uuid4(),
        payload=payload,
        schema_version=OUTBOX_SCHEMA_VERSION,
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "event_type": "generation.requested",
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "task_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "task_type": "SCENE",
    }
    payload.update(overrides)
    return payload


def test_payload_persists_the_scene_representation() -> None:
    mesh = generation_requested_payload(event_id=uuid.uuid4(), task=_task())
    splat = generation_requested_payload(
        event_id=uuid.uuid4(),
        task=_task(
            parameters={
                "algorithm": "COLMAP_SPLATFACTO",
                "output_format": "PLY",
                "representation": "GAUSSIAN_SPLAT",
                "method": "NERFSTUDIO_SPLATFACTO",
            }
        ),
    )
    assert mesh["representation"] == "MESH"
    assert splat["representation"] == "GAUSSIAN_SPLAT"


def test_object_payload_has_no_representation() -> None:
    payload = generation_requested_payload(
        event_id=uuid.uuid4(),
        task=_task(task_type="OBJECT", parameters={"algorithm": "TripoSR"}),
    )
    assert "representation" not in payload


def test_mesh_tasks_route_to_the_released_scene_queue() -> None:
    target = resolve_dispatch_target(_message(_payload(representation="MESH")))
    assert target.queue == SCENE_RECONSTRUCTION_QUEUE
    assert target.task_name == "reconstruct_scene_task"


def test_legacy_payload_without_a_representation_routes_to_mesh() -> None:
    target = resolve_dispatch_target(_message(_payload()))
    assert target.queue == SCENE_RECONSTRUCTION_QUEUE


def test_splat_tasks_route_to_the_dedicated_neural_queue() -> None:
    target = resolve_dispatch_target(_message(_payload(representation="GAUSSIAN_SPLAT")))
    assert target.queue == SCENE_SPLAT_QUEUE
    assert target.task_name == "reconstruct_scene_task"


def test_the_splat_queue_is_configurable() -> None:
    target = resolve_dispatch_target(
        _message(_payload(representation="GAUSSIAN_SPLAT")), splat_queue="custom_splat"
    )
    assert target.queue == "custom_splat"


def test_an_unknown_task_type_is_a_permanent_failure() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(_payload(task_type="NEURAL")))


def test_an_unknown_representation_is_a_permanent_failure() -> None:
    with pytest.raises(PermanentDispatchError):
        resolve_dispatch_target(_message(_payload(representation="NERF")))


def test_publisher_uses_the_configured_splat_queue() -> None:
    app = Celery("routing-test")
    app.conf.update(mogen_scene_splat_queue="configured_splat")
    published: list[dict[str, object]] = []

    def _capture(*args: object, **kwargs: object) -> None:
        published.append({"args": args, "kwargs": kwargs})

    app.send_task = _capture  # type: ignore[method-assign]
    publisher = CeleryPublisher(app)
    publisher.publish(_message(_payload(representation="GAUSSIAN_SPLAT")))

    assert len(published) == 1
    kwargs = published[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["queue"] == "configured_splat"


def test_publisher_falls_back_to_the_documented_splat_queue() -> None:
    app = Celery("routing-test")
    published: list[dict[str, object]] = []

    def _capture(*args: object, **kwargs: object) -> None:
        published.append({"args": args, "kwargs": kwargs})

    app.send_task = _capture  # type: ignore[method-assign]
    CeleryPublisher(app).publish(_message(_payload(representation="GAUSSIAN_SPLAT")))

    kwargs = published[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["queue"] == SCENE_SPLAT_QUEUE
