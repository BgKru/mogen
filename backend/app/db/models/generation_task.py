"""ORM model for ``generation_tasks`` (05_database_specification.md Section 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import TaskStatus, TaskType, sql_values

if TYPE_CHECKING:
    from app.db.models.generation_result import GenerationResult
    from app.db.models.generation_task_image import GenerationTaskImage
    from app.db.models.project import Project


class GenerationTask(Base):
    """One generation attempt for a project.

    ``attempt_count`` counts internal worker recovery attempts; it never
    creates a new row. A manual user retry creates a new task (Section 9.3).
    """

    __tablename__ = "generation_tasks"
    __table_args__ = (
        CheckConstraint(f"task_type IN ({sql_values(TaskType)})", name="task_type"),
        CheckConstraint(f"status IN ({sql_values(TaskStatus)})", name="status"),
        CheckConstraint(
            "progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100",
            name="progress_percent_range",
        ),
        # Composite ownership target for generation_task_images and
        # generation_results (Sections 10.3 and 11.3).
        UniqueConstraint("id", "project_id", name="uq_generation_tasks_id_project_id"),
        # Project-scoped idempotency, exactly as specified in Section 9.10.
        Index(
            "uq_generation_task_idempotency",
            "project_id",
            "idempotency_key",
            unique=True,
        ),
        # The composite (project_id, created_at DESC) index also serves
        # lookups by project_id alone (Section 17).
        Index("ix_generation_tasks_project_created_at", "project_id", desc("created_at")),
        Index("ix_generation_tasks_status_created_at", "status", "created_at"),
        Index("ix_generation_tasks_status_lease_expires_at", "status", "lease_expires_at"),
        Index("ix_generation_tasks_worker_id", "worker_id"),
        # Persistence-level safeguard against concurrent generation for one
        # project (Section 9.10).
        Index(
            "uq_generation_task_active_project",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'PROCESSING')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    task_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str | None] = mapped_column(String(50))
    progress_percent: Mapped[int | None] = mapped_column(SmallInteger)
    status_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="tasks")
    task_images: Mapped[list[GenerationTaskImage]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin="GenerationTask.id == GenerationTaskImage.task_id",
        foreign_keys="GenerationTaskImage.task_id",
        order_by="GenerationTaskImage.position",
    )
    result: Mapped[GenerationResult | None] = relationship(
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin="GenerationTask.id == GenerationResult.task_id",
        foreign_keys="GenerationResult.task_id",
    )
