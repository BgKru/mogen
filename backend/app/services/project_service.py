"""Project business logic (04_backend_specification.md Section 9).

The service owns validation, ownership checks and transaction boundaries.
Repositories only read and write rows; project deletion is one transaction so
the project, its tasks and its cleanup job change state together
(05_database_specification.md Section 12.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import GenerationResult, GenerationTask, Project
from app.db.models.enums import CleanupTargetType, ProjectStatus, ProjectType
from app.db.models.project import PROJECT_NAME_MAX_LENGTH
from app.repositories import (
    CleanupJobRepository,
    ImageRepository,
    OutboxRepository,
    ProjectRepository,
    ResultRepository,
    TaskRepository,
)
from app.services.outbox_events import create_cleanup_event


def normalize_project_name(name: str, *, max_length: int = PROJECT_NAME_MAX_LENGTH) -> str:
    """Trim a project name and enforce the documented length rule.

    Trimming happens before the length check so that surrounding whitespace
    never produces an empty or over-long stored value (Section 7.4).
    """
    normalized = name.strip()
    if not normalized:
        raise AppError(
            422,
            "PROJECT_NAME_INVALID",
            "The project name is invalid.",
            details=[
                {
                    "field": "name",
                    "code": "STRING_TOO_SHORT",
                    "message": "Project name must not be empty.",
                }
            ],
        )
    if len(normalized) > max_length:
        raise AppError(
            422,
            "PROJECT_NAME_INVALID",
            "The project name is invalid.",
            details=[
                {
                    "field": "name",
                    "code": "STRING_TOO_LONG",
                    "message": f"Project name must be at most {max_length} characters.",
                }
            ],
        )
    return normalized


def clamp_page_limit(requested: int, maximum: int) -> int:
    """Cap a requested page size at the configured maximum (api_contracts 7.2)."""
    return max(1, min(requested, maximum))


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project plus the summaries shown in a project response.

    ``result_available`` follows the current result only and is deliberately
    independent of the project status (api_contracts.md Section 5.10).
    """

    project: Project
    source_image_count: int
    current_result: GenerationResult | None
    latest_task: GenerationTask | None

    @property
    def result_available(self) -> bool:
        return self.current_result is not None


@dataclass(frozen=True, slots=True)
class ProjectPage:
    """One page of a user's projects plus the unpaginated total."""

    items: list[ProjectView]
    total_count: int
    limit: int
    offset: int


def _project_not_found() -> AppError:
    """Ownership failures are reported as 404, never 403 (api_contracts 11)."""
    return AppError(404, "PROJECT_NOT_FOUND", "Project not found.")


class ProjectService:
    """Create, list, read and delete projects owned by one user."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._projects = ProjectRepository(session)
        self._images = ImageRepository(session)
        self._tasks = TaskRepository(session)
        self._results = ResultRepository(session)
        self._cleanup_jobs = CleanupJobRepository(session)
        self._outbox = OutboxRepository(session)

    def create_project(
        self, *, user_id: uuid.UUID, name: str, project_type: ProjectType
    ) -> ProjectView:
        """Create a project owned by ``user_id`` without starting generation."""
        project = self._projects.create(
            user_id=user_id,
            name=normalize_project_name(name),
            project_type=project_type.value,
        )
        self._db.commit()
        return ProjectView(
            project=project,
            source_image_count=0,
            current_result=None,
            latest_task=None,
        )

    def list_projects(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int = 0,
        project_type: ProjectType | None = None,
        status: ProjectStatus | None = None,
        newest_first: bool = True,
    ) -> ProjectPage:
        """Return one page of the caller's active projects.

        Per-project image counts, current results and latest tasks are fetched
        in bulk, so the page costs a fixed number of queries instead of three
        per project (09_testing.md Section 7.3; 04 Section 9.2).
        """
        effective_limit = clamp_page_limit(limit, self._settings.max_page_size)
        type_filter = project_type.value if project_type is not None else None
        status_filter = status.value if status is not None else None

        projects = self._projects.list_for_user(
            user_id,
            limit=effective_limit,
            offset=offset,
            project_type=type_filter,
            status=status_filter,
            newest_first=newest_first,
        )
        total_count = self._projects.count_for_user(
            user_id, project_type=type_filter, status=status_filter
        )

        project_ids = [project.id for project in projects]
        image_counts = self._images.count_by_project_ids(project_ids)
        current_results = self._results.current_by_project_ids(project_ids)
        latest_tasks = self._tasks.latest_by_project_ids(project_ids)
        items = [
            ProjectView(
                project=project,
                source_image_count=image_counts.get(project.id, 0),
                current_result=current_results.get(project.id),
                latest_task=latest_tasks.get(project.id),
            )
            for project in projects
        ]
        return ProjectPage(
            items=items,
            total_count=total_count,
            limit=effective_limit,
            offset=offset,
        )

    def get_project(self, *, user_id: uuid.UUID, project_id: uuid.UUID) -> ProjectView:
        """Return one active project owned by the caller."""
        project = self._projects.get_active_for_user(project_id, user_id)
        if project is None:
            raise _project_not_found()

        latest_tasks = self._tasks.list_for_project(project_id, limit=1)
        return ProjectView(
            project=project,
            source_image_count=self._images.count_for_project(project_id),
            current_result=self._results.get_current_for_project(project_id),
            latest_task=latest_tasks[0] if latest_tasks else None,
        )

    def delete_project(self, *, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Soft-delete a project and schedule its files for asynchronous cleanup.

        One transaction performs the logical deletion, cancels queued tasks,
        asks running tasks to stop cooperatively and records the cleanup job
        (05_database_specification.md Section 12.4; api_contracts 7.4). The row
        lock serialises concurrent deletions of the same project.
        """
        project = self._projects.get_active_for_update(project_id)
        if project is None or project.user_id != user_id:
            raise _project_not_found()

        now = datetime.now(UTC)
        self._projects.mark_deleted(project, now)
        self._tasks.cancel_pending_for_project(project_id, finished_at=now)
        self._tasks.request_cancellation_for_processing(project_id, requested_at=now)

        storage_key = f"projects/{project_id}/"
        if self._cleanup_jobs.get_active_for_target(storage_key) is None:
            job = self._cleanup_jobs.create(
                project_id=project_id,
                storage_key=storage_key,
                target_type=CleanupTargetType.DIRECTORY.value,
            )
            # The cleanup job and its dispatch event commit together, so a
            # committed deletion can never lose its queue message
            # (05 Section 13).
            create_cleanup_event(self._outbox, job)
        self._db.commit()
