"""ORM model for the ``projects`` table (05_database_specification.md Section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import ProjectStatus, ProjectType, sql_values

if TYPE_CHECKING:
    from app.db.models.generation_result import GenerationResult
    from app.db.models.generation_task import GenerationTask
    from app.db.models.project_image import ProjectImage
    from app.db.models.storage_cleanup_job import StorageCleanupJob
    from app.db.models.user import User

# Maximum project name length, as defined by the ``projects.name`` column
# (Section 7.1). Services validate against it; schemas only guard input size.
PROJECT_NAME_MAX_LENGTH = 150


class Project(Base):
    """A user-owned generation project.

    Soft deletion is expressed by ``deleted_at``; ordinary queries must filter
    rows where it is not null (Section 7.6).
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"type IN ({sql_values(ProjectType)})", name="type"),
        CheckConstraint(f"status IN ({sql_values(ProjectStatus)})", name="status"),
        CheckConstraint("btrim(name) <> ''", name="name_not_empty"),
        # (user_id, created_at DESC) already serves lookups by user_id alone,
        # so no separate single-column index is created (Section 17).
        Index("ix_projects_user_created_at", "user_id", desc("created_at")),
        Index("ix_projects_user_status", "user_id", "status"),
        Index("ix_projects_type", "type"),
        Index("ix_projects_deleted_at", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH))
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="projects")
    images: Mapped[list[ProjectImage]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tasks: Mapped[list[GenerationTask]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    results: Mapped[list[GenerationResult]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        primaryjoin="Project.id == GenerationResult.project_id",
        foreign_keys="GenerationResult.project_id",
    )
    # Cleanup history must survive project removal for auditability, so the
    # database sets project_id to NULL instead of cascading (Section 12.4).
    cleanup_jobs: Mapped[list[StorageCleanupJob]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
