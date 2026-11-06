"""Payload builders for the closed outbox event enumeration.

``data_flow.md`` Section 6.6 and ``05_database_specification.md`` Section 13.7
define the exact payload contracts. Building them in one place keeps the
dispatcher, the API services and the tests from inventing slightly different
field names.

A payload contains identifiers and small routing metadata only: never image
bytes, credentials or filesystem paths (Section 13.5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import GenerationTask, OutboxMessage, StorageCleanupJob
from app.db.models.enums import OutboxEventType
from app.repositories import OutboxRepository

GENERATION_AGGREGATE = "GenerationTask"
CLEANUP_AGGREGATE = "StorageCleanupJob"
OUTBOX_SCHEMA_VERSION = 1


def _timestamp(value: datetime | None) -> str:
    """Return an ISO-8601 UTC timestamp for a JSON payload."""
    return (value or datetime.now(UTC)).isoformat()


def generation_requested_payload(*, event_id: uuid.UUID, task: GenerationTask) -> dict[str, object]:
    """Build the ``generation.requested`` payload (Section 13.7)."""
    return {
        "event_id": str(event_id),
        "event_type": OutboxEventType.GENERATION_REQUESTED.value,
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "task_id": str(task.id),
        "project_id": str(task.project_id),
        "task_type": task.task_type,
        "created_at": _timestamp(task.created_at),
    }


def cleanup_requested_payload(*, event_id: uuid.UUID, job: StorageCleanupJob) -> dict[str, object]:
    """Build the ``cleanup.requested`` payload (Section 13.7)."""
    return {
        "event_id": str(event_id),
        "event_type": OutboxEventType.CLEANUP_REQUESTED.value,
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "cleanup_job_id": str(job.id),
        "project_id": str(job.project_id) if job.project_id is not None else None,
        "target_type": job.target_type,
        "storage_key": job.storage_key,
        "created_at": _timestamp(job.created_at),
    }


def create_generation_event(outbox: OutboxRepository, task: GenerationTask) -> OutboxMessage:
    """Insert the dispatch event for a new generation task.

    The caller must be inside the task-creation transaction: the event and the
    state change it announces commit together or not at all (Section 16.4).
    """
    event_id = uuid.uuid4()
    return outbox.create(
        message_id=event_id,
        event_type=OutboxEventType.GENERATION_REQUESTED.value,
        aggregate_type=GENERATION_AGGREGATE,
        aggregate_id=task.id,
        payload=generation_requested_payload(event_id=event_id, task=task),
        schema_version=OUTBOX_SCHEMA_VERSION,
    )


def create_cleanup_event(outbox: OutboxRepository, job: StorageCleanupJob) -> OutboxMessage:
    """Insert the dispatch event for a new cleanup job, in the caller's transaction."""
    event_id = uuid.uuid4()
    return outbox.create(
        message_id=event_id,
        event_type=OutboxEventType.CLEANUP_REQUESTED.value,
        aggregate_type=CLEANUP_AGGREGATE,
        aggregate_id=job.id,
        payload=cleanup_requested_payload(event_id=event_id, job=job),
        schema_version=OUTBOX_SCHEMA_VERSION,
    )
