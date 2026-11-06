"""Repository for projects (05_database_specification.md Section 7)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select

from app.db.models import Project
from app.db.models.enums import ProjectStatus
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Database access for projects.

    Every ordinary query excludes soft-deleted projects (Section 7.6).
    Ownership is data, not policy: ``get_active_for_user`` returns ``None`` for
    a project owned by someone else and the service decides the response.
    """

    model = Project

    def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        project_type: str,
        status: str = ProjectStatus.CREATED.value,
    ) -> Project:
        """Insert a project owned by ``user_id``."""
        return self.add(Project(user_id=user_id, name=name, type=project_type, status=status))

    def get_active(self, project_id: uuid.UUID) -> Project | None:
        """Return a project that has not been soft-deleted."""
        return self.session.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )

    def get_active_for_user(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project | None:
        """Return an active project only when it belongs to ``user_id``."""
        statement = select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.deleted_at.is_(None),
        )
        return self.session.scalar(statement)

    def get_active_for_update(self, project_id: uuid.UUID) -> Project | None:
        """Lock an active project row for the duration of the transaction.

        Used when creating a generation task, so concurrent requests cannot
        both observe a free project (Section 16.4).
        """
        statement = (
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
        )
        return self.session.scalar(statement)

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int = 0,
        project_type: str | None = None,
        status: str | None = None,
        newest_first: bool = True,
    ) -> Sequence[Project]:
        """Return one page of a user's active projects, newest first by default."""
        statement = self._filtered_statement(user_id, project_type=project_type, status=status)
        order_column = Project.created_at.desc() if newest_first else Project.created_at.asc()
        id_column = Project.id.desc() if newest_first else Project.id.asc()
        statement = statement.order_by(order_column, id_column).limit(limit).offset(offset)
        return self.session.scalars(statement).all()

    def count_for_user(
        self,
        user_id: uuid.UUID,
        *,
        project_type: str | None = None,
        status: str | None = None,
    ) -> int:
        """Count a user's active projects, optionally filtered."""
        statement = self._filtered_statement(user_id, project_type=project_type, status=status)
        return self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0

    def mark_deleted(self, project: Project, deleted_at: datetime) -> None:
        """Soft-delete a project; it immediately disappears from active queries."""
        project.deleted_at = deleted_at
        self.session.flush()

    def set_status(self, project: Project, status: str) -> None:
        """Set the project status and refresh ``updated_at``."""
        project.status = status
        self.session.flush()

    def _filtered_statement(
        self,
        user_id: uuid.UUID,
        *,
        project_type: str | None,
        status: str | None,
    ) -> Select[tuple[Project]]:
        statement = select(Project).where(Project.user_id == user_id, Project.deleted_at.is_(None))
        if project_type is not None:
            statement = statement.where(Project.type == project_type)
        if status is not None:
            statement = statement.where(Project.status == status)
        return statement
