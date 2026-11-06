"""Worker-side lifecycle of a generation task.

The service owns the atomic claim, the heartbeat and the terminal transitions.
Database access stays in the repository; this layer decides what a transition
means for the project (05_database_specification.md Section 9.11).

A worker may only claim a task through the conditional ``PENDING`` to
``PROCESSING`` transition, so a duplicate Celery delivery can never start a
second processing instance while a lease is valid (data_flow.md Section 7.4).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import GenerationTask, Project
from app.db.models.enums import ProjectStatus, TaskStatus
from app.repositories import ProjectRepository, TaskRepository

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TaskClaim:
    """Outcome of one claim attempt."""

    claimed: bool
    task: GenerationTask | None = None


class TaskExecutionService:
    """Claim, heartbeat and finish one generation task."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._tasks = TaskRepository(session)
        self._projects = ProjectRepository(session)

    def claim(
        self, task_id: uuid.UUID, *, worker_id: str, now: datetime | None = None
    ) -> TaskClaim:
        """Atomically claim a PENDING task for this worker.

        A task that is missing, already claimed or already terminal is not
        claimed; the caller treats that as a duplicate delivery and does
        nothing else.
        """
        moment = now or _utc_now()
        lease_expires_at = moment + timedelta(seconds=self._settings.task_lease_seconds)
        task = self._tasks.claim_pending(
            task_id,
            worker_id=worker_id,
            now=moment,
            lease_expires_at=lease_expires_at,
        )
        if task is None:
            self._db.rollback()
            return TaskClaim(claimed=False)
        self._set_project_status(task.project_id, ProjectStatus.PROCESSING.value)
        self._db.commit()
        return TaskClaim(claimed=True, task=task)

    def heartbeat(self, task_id: uuid.UUID, *, worker_id: str, now: datetime | None = None) -> bool:
        """Renew the lease of a task this worker still owns."""
        moment = now or _utc_now()
        renewed = self._tasks.heartbeat(
            task_id,
            worker_id=worker_id,
            now=moment,
            lease_expires_at=moment + timedelta(seconds=self._settings.task_lease_seconds),
        )
        if not renewed:
            self._db.rollback()
            return False
        self._db.commit()
        return True

    def record_progress(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        stage: str | None = None,
        progress_percent: int | None = None,
        status_message: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Persist a stage or percentage actually reported by the pipeline."""
        updated = self._tasks.record_progress(
            task_id,
            worker_id=worker_id,
            now=now or _utc_now(),
            stage=stage,
            progress_percent=progress_percent,
            status_message=status_message,
        )
        if not updated:
            self._db.rollback()
            return False
        self._db.commit()
        return True

    def is_cancel_requested(self, task_id: uuid.UUID) -> bool:
        """Return whether cooperative cancellation has been requested."""
        requested_at = self._db.scalar(
            select(GenerationTask.cancel_requested_at).where(GenerationTask.id == task_id)
        )
        return requested_at is not None

    def complete(self, task_id: uuid.UUID, *, worker_id: str) -> bool:
        """Finish a task successfully, or cancel it if cancellation was requested.

        A successful completion still honours a pending cancellation request:
        the project is being deleted and no new result is exposed (data_flow.md
        Section 12.9).
        """
        task = self._tasks.get(task_id)
        if task is None:
            self._db.rollback()
            return False
        cancel_requested = task.cancel_requested_at is not None
        status = TaskStatus.CANCELLED if cancel_requested else TaskStatus.COMPLETED
        finished = self._tasks.mark_finished(
            task_id,
            worker_id=worker_id,
            status=status.value,
            finished_at=_utc_now(),
            status_message="Task cancelled" if cancel_requested else "Task completed",
        )
        if finished is None:
            self._db.rollback()
            return False
        if not cancel_requested:
            self._set_project_status(task.project_id, ProjectStatus.COMPLETED.value)
        self._db.commit()
        return True

    def fail(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        """Record a processing failure with a stable error code."""
        task = self._tasks.get(task_id)
        if task is None:
            self._db.rollback()
            return False
        cancel_requested = task.cancel_requested_at is not None
        status = TaskStatus.CANCELLED if cancel_requested else TaskStatus.FAILED
        finished = self._tasks.mark_finished(
            task_id,
            worker_id=worker_id,
            status=status.value,
            finished_at=_utc_now(),
            error_code=None if cancel_requested else error_code,
            error_message=None if cancel_requested else error_message,
            status_message="Task cancelled" if cancel_requested else error_message,
        )
        if finished is None:
            self._db.rollback()
            return False
        if not cancel_requested:
            self._set_project_status(task.project_id, ProjectStatus.FAILED.value)
        self._db.commit()
        return True

    def cancel(self, task_id: uuid.UUID, *, worker_id: str, reason: str) -> bool:
        """Stop a task cooperatively after the worker observed a cancel request."""
        finished = self._tasks.mark_finished(
            task_id,
            worker_id=worker_id,
            status=TaskStatus.CANCELLED.value,
            finished_at=_utc_now(),
            status_message=reason,
        )
        if finished is None:
            self._db.rollback()
            return False
        self._db.commit()
        return True

    def _set_project_status(self, project_id: uuid.UUID, status: str) -> None:
        """Update the project unless it has been soft-deleted meanwhile."""
        project = self._db.get(Project, project_id)
        if project is not None and project.deleted_at is None:
            self._projects.set_status(project, status)
