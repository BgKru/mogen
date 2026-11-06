"""ORM model for ``generation_task_images`` (05_database_specification.md Section 10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.generation_task import GenerationTask
    from app.db.models.project_image import ProjectImage


class GenerationTaskImage(Base):
    """Immutable snapshot of the source images used by one generation task.

    Both foreign keys are composite and include ``project_id``, so PostgreSQL
    itself rejects a row whose task and image come from different projects
    (Section 10.3).
    """

    __tablename__ = "generation_task_images"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["generation_tasks.id", "generation_tasks.project_id"],
            name="fk_generation_task_images_task_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["image_id", "project_id"],
            ["project_images.id", "project_images.project_id"],
            name="fk_generation_task_images_image_project",
            ondelete="RESTRICT",
        ),
        Index("ix_generation_task_images_image_project", "image_id", "project_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    image_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    # Duplicated from the referenced rows so the composite foreign keys can
    # enforce same-project ownership.
    project_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    task: Mapped[GenerationTask] = relationship(
        back_populates="task_images",
        primaryjoin="GenerationTask.id == GenerationTaskImage.task_id",
        foreign_keys="GenerationTaskImage.task_id",
    )
    image: Mapped[ProjectImage] = relationship(
        back_populates="task_images",
        primaryjoin="ProjectImage.id == GenerationTaskImage.image_id",
        foreign_keys="GenerationTaskImage.image_id",
    )
