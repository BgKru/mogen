"""Repository for project images (05_database_specification.md Section 8)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.db.models import ProjectImage
from app.repositories.base import BaseRepository


class ImageRepository(BaseRepository[ProjectImage]):
    """Database access for uploaded image metadata.

    Files live in storage; rows hold references and verified properties
    (Section 8). Image count policy is a service rule (Section 8.4).
    """

    model = ProjectImage

    def create(
        self,
        *,
        project_id: uuid.UUID,
        original_filename: str,
        storage_key: str,
        mime_type: str,
        file_size_bytes: int,
        sha256: str,
        width: int,
        height: int,
        position: int,
        image_id: uuid.UUID | None = None,
    ) -> ProjectImage:
        """Insert image metadata for an already stored file.

        ``image_id`` can be supplied when the storage key is derived from it,
        so the key can be written before the row exists.
        """
        return self.add(
            ProjectImage(
                id=image_id or uuid.uuid4(),
                project_id=project_id,
                original_filename=original_filename,
                storage_key=storage_key,
                mime_type=mime_type,
                file_size_bytes=file_size_bytes,
                sha256=sha256,
                width=width,
                height=height,
                position=position,
            )
        )

    def get_for_project(self, image_id: uuid.UUID, project_id: uuid.UUID) -> ProjectImage | None:
        """Return an image only when it belongs to ``project_id``.

        Scoping the lookup by project means a valid identifier from another
        project is reported as absent instead of being exposed
        (api_contracts.md Section 11).
        """
        statement = select(ProjectImage).where(
            ProjectImage.id == image_id,
            ProjectImage.project_id == project_id,
        )
        return self.session.scalar(statement)

    def list_for_project(self, project_id: uuid.UUID) -> Sequence[ProjectImage]:
        """Return a project's images in their stored order."""
        statement = (
            select(ProjectImage)
            .where(ProjectImage.project_id == project_id)
            .order_by(ProjectImage.position, ProjectImage.id)
        )
        return self.session.scalars(statement).all()

    def count_for_project(self, project_id: uuid.UUID) -> int:
        """Return how many images belong to a project."""
        return (
            self.session.scalar(
                select(func.count())
                .select_from(ProjectImage)
                .where(ProjectImage.project_id == project_id)
            )
            or 0
        )

    def count_by_project_ids(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Return per-project image counts in one query, for project listings."""
        if not project_ids:
            return {}
        statement = (
            select(ProjectImage.project_id, func.count())
            .where(ProjectImage.project_id.in_(project_ids))
            .group_by(ProjectImage.project_id)
        )
        return {project_id: total for project_id, total in self.session.execute(statement).all()}

    def next_position(self, project_id: uuid.UUID) -> int:
        """Return the next free zero-based position for a project's images."""
        statement = select(func.coalesce(func.max(ProjectImage.position) + 1, 0)).where(
            ProjectImage.project_id == project_id
        )
        return self.session.scalar(statement) or 0
