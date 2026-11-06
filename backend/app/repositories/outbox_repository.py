"""Repository for outbox messages (05_database_specification.md Section 13).

An outbox row is inserted in the same transaction as the state change it
announces, so the caller must not commit between the two (Section 16.4).
Claiming, publishing and retry policy belong to the Outbox Dispatcher; this
repository only reads and writes rows and never commits.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.db.models import OutboxMessage
from app.db.models.enums import OutboxStatus
from app.repositories.base import BaseRepository


class OutboxRepository(BaseRepository[OutboxMessage]):
    """Database access for transactional outbox events."""

    model = OutboxMessage

    def create(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict[str, Any],
        schema_version: int = 1,
        available_at: datetime | None = None,
        message_id: uuid.UUID | None = None,
    ) -> OutboxMessage:
        """Insert a pending outbox message.

        ``message_id`` lets the caller use one identifier as both the row key
        and the ``event_id`` carried in the payload.
        """
        message = OutboxMessage(
            id=message_id or uuid.uuid4(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            schema_version=schema_version,
        )
        if available_at is not None:
            message.available_at = available_at
        return self.add(message)

    def list_pending(self, *, now: datetime, limit: int) -> Sequence[OutboxMessage]:
        """Return dispatchable messages in claim order.

        Only PENDING rows whose ``available_at`` has been reached are returned;
        the query matches the ``ix_outbox_pending`` partial index.
        """
        statement = (
            select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PENDING.value,
                OutboxMessage.available_at <= now,
            )
            .order_by(OutboxMessage.available_at, OutboxMessage.created_at)
            .limit(limit)
        )
        return self.session.scalars(statement).all()

    def claim_pending(
        self, *, now: datetime, limit: int, locked_by: str
    ) -> Sequence[OutboxMessage]:
        """Claim due messages and move them to PROCESSING.

        ``FOR UPDATE ... SKIP LOCKED`` lets concurrent dispatchers claim
        different rows without waiting on each other (Section 13.4). The row
        lock is held until the caller commits the claiming transaction; the
        dispatcher must commit before the network call to Redis, so the lock is
        never held across publishing.
        """
        statement = (
            select(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PENDING.value,
                OutboxMessage.available_at <= now,
            )
            .order_by(OutboxMessage.available_at, OutboxMessage.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = list(self.session.scalars(statement).all())
        for message in messages:
            message.status = OutboxStatus.PROCESSING.value
            message.locked_at = now
            message.locked_by = locked_by
            message.attempts += 1
        self.session.flush()
        return messages

    def release_expired_locks(self, *, now: datetime, timeout_seconds: int) -> int:
        """Return abandoned PROCESSING messages to PENDING.

        A dispatcher that terminates after claiming but before publishing
        leaves a row in PROCESSING. Once its lock is older than the configured
        timeout the row becomes claimable again; ``attempts`` and
        ``last_error`` are kept for diagnostics (Section 13.4).
        """
        threshold = now - timedelta(seconds=timeout_seconds)
        statement = (
            update(OutboxMessage)
            .where(
                OutboxMessage.status == OutboxStatus.PROCESSING.value,
                OutboxMessage.locked_at.is_not(None),
                OutboxMessage.locked_at <= threshold,
            )
            .values(
                status=OutboxStatus.PENDING.value,
                locked_at=None,
                locked_by=None,
            )
            .execution_options(synchronize_session=False)
        )
        released = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return released

    def mark_published(self, message_id: uuid.UUID, *, published_at: datetime) -> bool:
        """Move a claimed message to PUBLISHED, in its own transaction."""
        statement = (
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message_id,
                OutboxMessage.status == OutboxStatus.PROCESSING.value,
            )
            .values(
                status=OutboxStatus.PUBLISHED.value,
                published_at=published_at,
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        updated = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return updated > 0

    def mark_retry(self, message_id: uuid.UUID, *, available_at: datetime, last_error: str) -> bool:
        """Return a claimed message to PENDING after a transient failure."""
        statement = (
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message_id,
                OutboxMessage.status == OutboxStatus.PROCESSING.value,
            )
            .values(
                status=OutboxStatus.PENDING.value,
                available_at=available_at,
                last_error=last_error,
                locked_at=None,
                locked_by=None,
            )
            .execution_options(synchronize_session=False)
        )
        updated = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return updated > 0

    def mark_failed(self, message_id: uuid.UUID, *, last_error: str) -> bool:
        """Stop automatic publication after a permanent failure or exhausted retries."""
        statement = (
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message_id,
                OutboxMessage.status == OutboxStatus.PROCESSING.value,
            )
            .values(
                status=OutboxStatus.FAILED.value,
                last_error=last_error,
                locked_at=None,
                locked_by=None,
            )
            .execution_options(synchronize_session=False)
        )
        updated = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return updated > 0

    def has_dispatchable_or_published(self, aggregate_type: str, aggregate_id: uuid.UUID) -> bool:
        """Return whether an aggregate still has a PENDING or PUBLISHED event.

        A task that remains PENDING with no such event was never dispatched;
        stale-task recovery uses this check (05 Section 13.6).
        """
        statement = (
            select(OutboxMessage.id)
            .where(
                OutboxMessage.aggregate_type == aggregate_type,
                OutboxMessage.aggregate_id == aggregate_id,
                OutboxMessage.status.in_(
                    (OutboxStatus.PENDING.value, OutboxStatus.PUBLISHED.value)
                ),
            )
            .limit(1)
        )
        return self.session.scalar(statement) is not None

    def list_by_aggregate(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> Sequence[OutboxMessage]:
        """Return the event history of one aggregate, oldest first."""
        statement = (
            select(OutboxMessage)
            .where(
                OutboxMessage.aggregate_type == aggregate_type,
                OutboxMessage.aggregate_id == aggregate_id,
            )
            .order_by(OutboxMessage.created_at, OutboxMessage.id)
        )
        return self.session.scalars(statement).all()
