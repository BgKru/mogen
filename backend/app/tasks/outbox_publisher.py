"""Translate outbox events into Celery messages.

The event type, together with the task type it carries, selects the target
queue (data_flow.md Section 7.1). The Celery task ID equals
``GenerationTask.id`` so a repeated delivery correlates to one logical task
(Section 7.2); a cleanup message uses its cleanup job identifier in the same
spirit.

Payload validation happens before the broker is touched. An unsupported
``schema_version``, an unlisted event type, a missing identifier or an unknown
task type is a permanent failure and must not be retried
(05_database_specification.md Section 13.6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from celery import Celery

from app.db.models import OutboxMessage
from app.db.models.enums import CleanupTargetType, OutboxEventType, TaskType
from app.services.outbox_events import OUTBOX_SCHEMA_VERSION
from app.services.outbox_service import PermanentDispatchError
from app.services.scene_methods import GAUSSIAN_SPLAT, persisted_representation
from app.tasks.celery_app import (
    CLEANUP_QUEUE,
    CLEANUP_TASK_NAME,
    OBJECT_GENERATION_QUEUE,
    OBJECT_GENERATION_TASK,
    SCENE_RECONSTRUCTION_QUEUE,
    SCENE_RECONSTRUCTION_TASK,
    SCENE_SPLAT_QUEUE,
)


@dataclass(frozen=True, slots=True)
class DispatchTarget:
    """The Celery call an outbox message maps to."""

    task_name: str
    queue: str
    task_id: str
    args: tuple[str, ...]
    kwargs: dict[str, str]


def _identifier(payload: dict[str, object], field: str, event_type: str) -> str:
    """Read a UUID field, rejecting a missing or malformed value."""
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise PermanentDispatchError(f"{event_type} payload has no {field}")
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise PermanentDispatchError(f"{event_type} payload has an invalid {field}") from exc
    return value


def resolve_dispatch_target(
    message: OutboxMessage, *, splat_queue: str = SCENE_SPLAT_QUEUE
) -> DispatchTarget:
    """Map one outbox message onto its queue and Celery task.

    A scene task is routed by its persisted representation. A message written
    before increment 15 (or by an object task) has no representation and keeps
    the released ``scene_reconstruction`` queue.
    """
    if message.schema_version != OUTBOX_SCHEMA_VERSION:
        raise PermanentDispatchError(f"unsupported outbox schema_version {message.schema_version}")
    payload = message.payload or {}

    if message.event_type == OutboxEventType.GENERATION_REQUESTED.value:
        task_id = _identifier(payload, "task_id", message.event_type)
        project_id = _identifier(payload, "project_id", message.event_type)
        task_type = payload.get("task_type")
        if task_type == TaskType.OBJECT.value:
            task_name, queue = OBJECT_GENERATION_TASK, OBJECT_GENERATION_QUEUE
        elif task_type == TaskType.SCENE.value:
            raw_representation = payload.get("representation")
            try:
                representation = persisted_representation(
                    {"representation": raw_representation}
                    if raw_representation is not None
                    else None
                )
            except ValueError as exc:
                raise PermanentDispatchError(str(exc)) from exc
            task_name = SCENE_RECONSTRUCTION_TASK
            queue = (
                splat_queue
                if representation.value == GAUSSIAN_SPLAT
                else SCENE_RECONSTRUCTION_QUEUE
            )
        else:
            raise PermanentDispatchError(
                f"generation.requested payload has an unknown task_type {task_type!r}"
            )
        return DispatchTarget(
            task_name=task_name,
            queue=queue,
            task_id=task_id,
            args=(task_id,),
            kwargs={"project_id": project_id, "task_type": str(task_type)},
        )

    if message.event_type == OutboxEventType.CLEANUP_REQUESTED.value:
        cleanup_job_id = _identifier(payload, "cleanup_job_id", message.event_type)
        target_type = payload.get("target_type")
        if target_type not in (
            CleanupTargetType.FILE.value,
            CleanupTargetType.DIRECTORY.value,
        ):
            raise PermanentDispatchError(
                f"cleanup.requested payload has an unknown target_type {target_type!r}"
            )
        storage_key = payload.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key:
            raise PermanentDispatchError("cleanup.requested payload has no storage_key")
        return DispatchTarget(
            task_name=CLEANUP_TASK_NAME,
            queue=CLEANUP_QUEUE,
            task_id=cleanup_job_id,
            args=(cleanup_job_id,),
            kwargs={},
        )

    raise PermanentDispatchError(f"unhandled outbox event_type {message.event_type!r}")


class CeleryPublisher:
    """Publish outbox messages to the configured Celery broker."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def publish(self, message: OutboxMessage) -> None:
        """Send one Celery task, without Celery's own retry policy.

        The dispatcher owns retries through the outbox row, so ``retry=False``
        keeps a failure visible to it instead of being retried invisibly.
        """
        configured = getattr(getattr(self._app, "conf", None), "mogen_scene_splat_queue", None)
        splat_queue = configured or SCENE_SPLAT_QUEUE
        target = resolve_dispatch_target(message, splat_queue=splat_queue)
        self._app.send_task(
            target.task_name,
            args=list(target.args),
            kwargs=target.kwargs,
            queue=target.queue,
            task_id=target.task_id,
            retry=False,
        )
