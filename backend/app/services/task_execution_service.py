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
from app.db.models import GenerationResult, GenerationTask, Project
from app.db.models.enums import CleanupTargetType, ProjectStatus, TaskStatus
from app.repositories import (
    CleanupJobRepository,
    OutboxRepository,
    ProjectRepository,
    ResultRepository,
    TaskRepository,
)
from app.services.outbox_events import create_cleanup_event

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
        self._results = ResultRepository(session)
        self._cleanup_jobs = CleanupJobRepository(session)
        self._outbox = OutboxRepository(session)

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
        task = self._tasks.get_refreshed(task_id)
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

    def complete_with_result(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        storage_key: str,
        format: str,
        mime_type: str,
        file_size_bytes: int,
        sha256: str,
        metadata: dict[str, object],
    ) -> bool:
        """Register the validated result and finish the task in one transaction.

        The task row is locked first, so duplicate delivery cannot create a
        second result or complete an already terminal task. Clearing the old
        current result, inserting the new current result, completing the task
        and completing the project either all commit or none do
        (05_database_specification.md Sections 11.4 and 16.5).

        A cancellation request that won the race marks the task ``CANCELLED``
        and registers nothing. The caller deletes the stored file, so a
        cancelled attempt never displaces the previous result (OBJ-AC-15).
        """
        task = self._tasks.get_for_update(task_id)
        if (
            task is None
            or task.status != TaskStatus.PROCESSING.value
            or task.worker_id != worker_id
        ):
            self._db.rollback()
            return False

        if task.cancel_requested_at is not None:
            finished = self._tasks.mark_finished(
                task_id,
                worker_id=worker_id,
                status=TaskStatus.CANCELLED.value,
                finished_at=_utc_now(),
                status_message="Task cancelled",
            )
            if finished is None:
                self._db.rollback()
                return False
            self._db.commit()
            return False

        try:
            superseded = self._results.get_current_for_project(task.project_id)
            self._results.clear_current(task.project_id)
            self._results.create(
                project_id=task.project_id,
                task_id=task.id,
                format=format,
                mime_type=mime_type,
                storage_key=storage_key,
                file_size_bytes=file_size_bytes,
                sha256=sha256,
                metadata=metadata,
                is_current=True,
            )
            self._queue_superseded_cleanup(task.project_id, superseded, storage_key)
            finished = self._tasks.mark_finished(
                task_id,
                worker_id=worker_id,
                status=TaskStatus.COMPLETED.value,
                finished_at=_utc_now(),
                status_message="Task completed",
            )
            if finished is None:
                self._db.rollback()
                return False
            self._set_project_status(task.project_id, ProjectStatus.COMPLETED.value)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
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
        task = self._tasks.get_refreshed(task_id)
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

    def _queue_superseded_cleanup(
        self,
        project_id: uuid.UUID,
        superseded: GenerationResult | None,
        new_storage_key: str,
    ) -> None:
        """Queue deletion of the result a successful regeneration replaced.

        The previous result row stays as history, but its GLB is unreachable
        through the API once it is no longer current, so keeping the file would
        grow storage without bound (05 Section 14.6: "Cleanup of obsolete assets
        must be explicit"; 07 Section 15.7). The job commits with the new result,
        so a file is only ever scheduled after the replacement is durable, and
        the cleanup worker performs the deletion outside the transaction.
        """
        if superseded is None or superseded.storage_key == new_storage_key:
            return
        if self._cleanup_jobs.get_active_for_target(superseded.storage_key) is not None:
            return
        job = self._cleanup_jobs.create(
            project_id=project_id,
            storage_key=superseded.storage_key,
            target_type=CleanupTargetType.FILE.value,
        )
        create_cleanup_event(self._outbox, job)
        logger.info(
            "superseded_result_cleanup_queued",
            extra={
                "operation": "result_registration",
                "project_id": str(project_id),
                "cleanup_job_id": str(job.id),
            },
        )

    def _set_project_status(self, project_id: uuid.UUID, status: str) -> None:
        """Update the project unless it has been soft-deleted meanwhile."""
        project = self._db.get(Project, project_id)
        if project is not None and project.deleted_at is None:
            self._projects.set_status(project, status)
