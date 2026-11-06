"""ORM model for ``generation_results`` (05_database_specification.md Section 11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import ResultFormat, sql_values

if TYPE_CHECKING:
    from app.db.models.generation_task import GenerationTask
    from app.db.models.project import Project


class GenerationResult(Base):
    """Metadata for one generated 3D asset.

    Assets are stored outside PostgreSQL; this row references the stored file.
    Historical results are retained, but at most one row per project may be
    current (Section 11.4).
    """

    __tablename__ = "generation_results"
    __table_args__ = (
        CheckConstraint(f"format IN ({sql_values(ResultFormat)})", name="format"),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint("sha256 ~* '^[0-9a-f]{64}$'", name="sha256_format"),
        UniqueConstraint("task_id", name="uq_generation_results_task_id"),
        # The composite foreign key relies on UNIQUE (id, project_id) in
        # generation_tasks and prevents attaching a result to another
        # project's task (Section 11.3).
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["generation_tasks.id", "generation_tasks.project_id"],
            name="fk_generation_results_task_project",
            ondelete="CASCADE",
        ),
        Index("ix_generation_results_project_id", "project_id"),
        Index(
            "uq_generation_results_current_project",
            "project_id",
            unique=True,
            postgresql_where=text("is_current = TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    format: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    # Attribute renamed because ``metadata`` is reserved by DeclarativeBase.
    result_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    project: Mapped[Project] = relationship(
        back_populates="results",
        primaryjoin="Project.id == GenerationResult.project_id",
        foreign_keys="GenerationResult.project_id",
    )
    task: Mapped[GenerationTask] = relationship(
        back_populates="result",
        primaryjoin="GenerationTask.id == GenerationResult.task_id",
        foreign_keys="GenerationResult.task_id",
    )
