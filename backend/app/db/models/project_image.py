"""ORM model for ``project_images`` (05_database_specification.md Section 8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import ImageMimeType, sql_values

if TYPE_CHECKING:
    from app.db.models.generation_task_image import GenerationTaskImage
    from app.db.models.project import Project


class ProjectImage(Base):
    """Metadata for one photograph uploaded to a project.

    The file itself lives in storage; this row holds only its reference and
    verified properties (Section 8).
    """

    __tablename__ = "project_images"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint("width > 0", name="width_positive"),
        CheckConstraint("height > 0", name="height_positive"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("sha256 ~* '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint(f"mime_type IN ({sql_values(ImageMimeType)})", name="mime_type"),
        # Composite ownership target: lets generation_task_images prove that an
        # image and a task belong to the same project (Section 10.3).
        UniqueConstraint("id", "project_id", name="uq_project_images_id_project_id"),
        Index("ix_project_images_project_position", "project_id", "position"),
        Index("ix_project_images_project_sha256", "project_id", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    project: Mapped[Project] = relationship(back_populates="images")
    # Restricted by the database while a generation task still references the
    # image, so no ORM cascade here (Section 10.3).
    task_images: Mapped[list[GenerationTaskImage]] = relationship(
        back_populates="image",
        passive_deletes=True,
        primaryjoin="ProjectImage.id == GenerationTaskImage.image_id",
        foreign_keys="GenerationTaskImage.image_id",
    )
