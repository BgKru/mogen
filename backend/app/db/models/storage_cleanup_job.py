"""ORM model for ``storage_cleanup_jobs`` (05_database_specification.md Section 12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import CleanupStatus, CleanupTargetType, sql_values

if TYPE_CHECKING:
    from app.db.models.project import Project


class StorageCleanupJob(Base):
    """A durable request to delete a stored file or directory.

    Filesystem and database operations cannot commit atomically, so cleanup is
    tracked here and retried independently (Section 12).
    """

    __tablename__ = "storage_cleanup_jobs"
    __table_args__ = (
        CheckConstraint(f"target_type IN ({sql_values(CleanupTargetType)})", name="target_type"),
        CheckConstraint(f"status IN ({sql_values(CleanupStatus)})", name="status"),
        Index("ix_storage_cleanup_jobs_project_id", "project_id"),
        Index("ix_storage_cleanup_jobs_status_created_at", "status", "created_at"),
        # Only one in-flight cleanup per storage target is useful; completed
        # and failed jobs remain as history (Section 12.5).
        Index(
            "uq_storage_cleanup_jobs_active_storage_key",
            "storage_key",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'PROCESSING')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Cleanup history must survive project removal, so this reference is
    # optional and set to NULL when the project row is deleted (Section 12.4).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    target_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project | None] = relationship(back_populates="cleanup_jobs")
