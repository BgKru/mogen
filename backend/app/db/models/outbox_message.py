"""ORM model for ``outbox_messages`` (05_database_specification.md Section 13).

The Transactional Outbox pattern requires an outbox row to be committed in the
same transaction as the state change it announces, so a committed generation
request cannot lose its dispatch event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import OutboxEventType, OutboxStatus, sql_values


class OutboxMessage(Base):
    """A durable event awaiting publication to the message broker.

    ``OutboxMessage`` is not part of the project ownership graph: it references
    an aggregate by type and identifier and deliberately has no foreign key
    (Section 13).
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(f"event_type IN ({sql_values(OutboxEventType)})", name="event_type"),
        CheckConstraint(f"status IN ({sql_values(OutboxStatus)})", name="status"),
        # Dispatcher claim query; published history is excluded (Section 13.3).
        Index(
            "ix_outbox_pending",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(20), default=OutboxStatus.PENDING.value)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
