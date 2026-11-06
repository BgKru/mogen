"""Task Recovery service (08_infrastructure.md Section 3.10, roadmap 4.9).

The service inspects PostgreSQL, never Redis: it finds tasks whose worker lease
expired and whose heartbeat went quiet, then requeues them through the
Transactional Outbox, fails them when the retry budget is exhausted, or cancels
them when cancellation was requested. It also fails tasks that were never
dispatched at all (05_database_specification.md Section 13.6).

Every transition is a conditional database update, so several recovery
instances can run concurrently without requeueing the same task twice. The
service never creates a new ``generation_tasks`` row for an internal recovery:
``attempt_count`` records the retry and the task identity is preserved
(Section 9.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import GenerationTask, Project
from app.db.models.enums import ProjectStatus
from app.repositories import OutboxRepository, ProjectRepository, TaskRepository
from app.services.outbox_events import (
    GENERATION_AGGREGATE,
    create_generation_event,
)

logger = logging.getLogger(__name__)

WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
WORKER_INTERRUPTED_MESSAGE = "The worker stopped before the task completed."
DISPATCH_STALLED_MESSAGE = "The generation task was not dispatched in time."


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RecoverySummary:
    """Aggregated result of one recovery cycle."""

    requeued: int = 0
    failed: int = 0
    cancelled: int = 0
    dispatch_failed: int = 0

    @property
    def changed(self) -> int:
        """Return how many tasks the cycle changed."""
        return self.requeued + self.failed + self.cancelled + self.dispatch_failed


class TaskRecoveryService:
    """Detect stale PROCESSING and stranded PENDING tasks."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._tasks = TaskRepository(session)
        self._projects = ProjectRepository(session)
        self._outbox = OutboxRepository(session)

    def recover(self, *, now: datetime | None = None, limit: int | None = None) -> RecoverySummary:
        """Run one recovery cycle."""
        moment = now or _utc_now()
        batch = limit if limit is not None else self._settings.recovery_batch_size
        summary = RecoverySummary()
        summary.dispatch_failed = self._fail_stalled_dispatch(moment, batch)
        self._recover_expired(moment, batch, summary)
        return summary

    # --- never-dispatched tasks (05 Section 13.6) -------------------------

    def _fail_stalled_dispatch(self, now: datetime, limit: int) -> int:
        """Fail PENDING tasks that no live outbox event can ever dispatch."""
        queued_before = now - timedelta(seconds=self._settings.dispatch_stall_timeout_seconds)
        candidates = self._tasks.list_pending_stalled(queued_before=queued_before, limit=limit)
        failed = 0
        for task in candidates:
            if self._outbox.has_dispatchable_or_published(GENERATION_AGGREGATE, task.id):
                continue
            transitioned = self._tasks.fail_pending_stalled(
                task.id,
                now=now,
                queued_before=queued_before,
                error_code=WORKER_UNAVAILABLE,
                error_message=DISPATCH_STALLED_MESSAGE,
            )
            if transitioned is None:
                self._db.rollback()
                continue
            self._set_project_status(task.project_id, ProjectStatus.FAILED.value)
            self._db.commit()
            failed += 1
            logger.error(
                "task_dispatch_stalled",
                extra={
                    "operation": "task_recovery",
                    "project_id": str(task.project_id),
                    "task_id": str(task.id),
                    "error_code": WORKER_UNAVAILABLE,
                },
            )
        return failed

    # --- expired leases (05 Section 9.11) ---------------------------------

    def _recover_expired(self, now: datetime, limit: int, summary: RecoverySummary) -> None:
        heartbeat_before = now - timedelta(seconds=self._settings.task_stale_threshold_seconds)
        stale = self._tasks.list_stale_processing(
            now=now, heartbeat_before=heartbeat_before, limit=limit
        )
        for task in stale:
            if task.cancel_requested_at is not None or self._project_deleted(task):
                self._cancel(task, now, summary)
                continue
            if task.attempt_count < self._settings.task_recovery_max_attempts:
                self._requeue(task, now, heartbeat_before, summary)
            else:
                self._fail(task, now, summary)

    def _cancel(self, task: GenerationTask, now: datetime, summary: RecoverySummary) -> None:
        cancelled = self._tasks.cancel_stale(
            task.id,
            now=now,
            lease_before=now,
            require_cancel_request=task.cancel_requested_at is not None,
        )
        if cancelled is None:
            self._db.rollback()
            return
        self._db.commit()
        summary.cancelled += 1
        logger.info(
            "task_cancelled_after_worker_stop",
            extra={
                "operation": "task_recovery",
                "project_id": str(task.project_id),
                "task_id": str(task.id),
            },
        )

    def _requeue(
        self,
        task: GenerationTask,
        now: datetime,
        heartbeat_before: datetime,
        summary: RecoverySummary,
    ) -> None:
        requeued = self._tasks.requeue_stale(
            task.id,
            now=now,
            heartbeat_before=heartbeat_before,
            lease_before=now,
        )
        if requeued is None:
            self._db.rollback()
            return
        self._set_project_status(task.project_id, ProjectStatus.PENDING.value)
        # Redelivery must use a new outbox event; the recovery service never
        # publishes to Redis itself (08 Section 3.10).
        create_generation_event(self._outbox, requeued)
        self._db.commit()
        summary.requeued += 1
        logger.warning(
            "task_requeued_after_lease_expiry",
            extra={
                "operation": "task_recovery",
                "project_id": str(task.project_id),
                "task_id": str(task.id),
            },
        )

    def _fail(self, task: GenerationTask, now: datetime, summary: RecoverySummary) -> None:
        failed = self._tasks.fail_stale(
            task.id,
            now=now,
            lease_before=now,
            error_code=WORKER_UNAVAILABLE,
            error_message=WORKER_INTERRUPTED_MESSAGE,
        )
        if failed is None:
            self._db.rollback()
            return
        self._set_project_status(task.project_id, ProjectStatus.FAILED.value)
        self._db.commit()
        summary.failed += 1
        logger.error(
            "task_failed_after_recovery_budget",
            extra={
                "operation": "task_recovery",
                "project_id": str(task.project_id),
                "task_id": str(task.id),
                "error_code": WORKER_UNAVAILABLE,
            },
        )

    def _project_deleted(self, task: GenerationTask) -> bool:
        project = self._db.get(Project, task.project_id)
        return project is not None and project.deleted_at is not None

    def _set_project_status(self, project_id, status: str) -> None:
        project = self._db.get(Project, project_id)
        if project is not None and project.deleted_at is None:
            self._projects.set_status(project, status)
