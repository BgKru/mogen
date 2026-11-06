"""Repository for generation results (05_database_specification.md Section 11)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update

from app.db.models import GenerationResult
from app.repositories.base import BaseRepository


class ResultRepository(BaseRepository[GenerationResult]):
    """Database access for generated asset metadata.

    Current-result replacement is coordinated by a service transaction using
    ``clear_current`` and ``create`` (Section 11.4); the partial unique index
    is the final safeguard.
    """

    model = GenerationResult

    def create(
        self,
        *,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        format: str,
        mime_type: str,
        storage_key: str,
        file_size_bytes: int,
        sha256: str,
        metadata: dict[str, Any] | None = None,
        is_current: bool = False,
    ) -> GenerationResult:
        """Insert result metadata for an already stored and validated asset."""
        return self.add(
            GenerationResult(
                project_id=project_id,
                task_id=task_id,
                format=format,
                mime_type=mime_type,
                storage_key=storage_key,
                file_size_bytes=file_size_bytes,
                sha256=sha256,
                result_metadata=metadata if metadata is not None else {},
                is_current=is_current,
            )
        )

    def get_current_for_project(self, project_id: uuid.UUID) -> GenerationResult | None:
        """Return the project's current result, if one exists."""
        statement = select(GenerationResult).where(
            GenerationResult.project_id == project_id,
            GenerationResult.is_current.is_(True),
        )
        return self.session.scalar(statement)

    def get_for_task(self, task_id: uuid.UUID) -> GenerationResult | None:
        """Return the result produced by a task, if any."""
        return self.session.scalar(
            select(GenerationResult).where(GenerationResult.task_id == task_id)
        )

    def list_for_project(
        self, project_id: uuid.UUID, *, current_only: bool = False
    ) -> Sequence[GenerationResult]:
        """Return a project's results, newest first."""
        statement = select(GenerationResult).where(GenerationResult.project_id == project_id)
        if current_only:
            statement = statement.where(GenerationResult.is_current.is_(True))
        statement = statement.order_by(
            GenerationResult.created_at.desc(), GenerationResult.id.desc()
        )
        return self.session.scalars(statement).all()

    def current_by_project_ids(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, GenerationResult]:
        """Return the current result of each project in one query, for listings."""
        if not project_ids:
            return {}
        statement = select(GenerationResult).where(
            GenerationResult.project_id.in_(project_ids),
            GenerationResult.is_current.is_(True),
        )
        return {result.project_id: result for result in self.session.scalars(statement).all()}

    def clear_current(self, project_id: uuid.UUID) -> int:
        """Unset the current flag for a project's result; return rows changed."""
        result = self.session.execute(
            update(GenerationResult)
            .where(
                GenerationResult.project_id == project_id,
                GenerationResult.is_current.is_(True),
            )
            .values(is_current=False)
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        return result.rowcount or 0
