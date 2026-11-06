"""Storage cleanup processing (05_database_specification.md Section 12.3).

The API never deletes files inside a request: project and image deletion remove
metadata and record a cleanup job, and this service performs the filesystem
work later (api_contracts.md 8.4). PostgreSQL stays authoritative; the job row
is the unit of work.

Claiming locks the job row with ``FOR UPDATE ... SKIP LOCKED`` and keeps the
transaction open until the job is finished. A crash therefore rolls the claim
back and the job stays ``PENDING`` for the next attempt, instead of leaving it
stuck in ``PROCESSING``. Deleting an already absent target counts as success
(Section 12.3), which makes a retried deletion safe.

A directory job waits while the project still has an active generation task:
the worker must never delete files that a task may still be reading
(08_infrastructure.md Section 3.7; data_flow.md Section 14.4).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import StorageCleanupJob
from app.db.models.enums import CleanupStatus, CleanupTargetType
from app.repositories import CleanupJobRepository, TaskRepository
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

# ``last_error`` is TEXT, but a bounded diagnostic keeps rows and logs readable.
MAX_ERROR_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """What happened to one cleanup job during an attempt."""

    job_id: uuid.UUID
    storage_key: str
    target_type: str
    status: str
    attempts: int
    deferred: bool = False

    @property
    def completed(self) -> bool:
        return self.status == CleanupStatus.COMPLETED.value

    @property
    def failed(self) -> bool:
        return self.status == CleanupStatus.FAILED.value


@dataclass(slots=True)
class CleanupSummary:
    """Aggregated result of one worker cycle."""

    attempted: int = 0
    completed: int = 0
    retried: int = 0
    failed: int = 0
    deferred: int = 0

    def record(self, outcome: CleanupOutcome) -> None:
        """Count one outcome."""
        if outcome.deferred:
            self.deferred += 1
            return
        self.attempted += 1
        if outcome.completed:
            self.completed += 1
        elif outcome.failed:
            self.failed += 1
        else:
            self.retried += 1


def _now() -> datetime:
    return datetime.now(UTC)


class CleanupService:
    """Claim and execute queued file cleanup jobs."""

    def __init__(self, session: Session, settings: Settings, storage: StorageBackend) -> None:
        self._db = session
        self._settings = settings
        self._storage = storage
        self._jobs = CleanupJobRepository(session)
        self._tasks = TaskRepository(session)

    def process_pending(self, *, limit: int | None = None) -> CleanupSummary:
        """Process up to ``limit`` pending jobs (default: configured batch size).

        Each pending row is picked up at most once per cycle: deferred jobs are
        skipped for the rest of the cycle so one project with a long-running
        task cannot starve the queue, and a job that failed and returned to
        ``PENDING`` waits for the next cycle instead of burning every attempt
        in one batch. Deferrals do not count against the batch limit because no
        filesystem work was attempted.
        """
        batch = limit if limit is not None else self._settings.cleanup_batch_size
        summary = CleanupSummary()
        excluded_ids: list[uuid.UUID] = []
        scans = 0
        # Bounded scan: every iteration either attempts a job, defers one, or
        # finds nothing left to claim.
        while summary.attempted < batch and scans < batch * 2:
            outcome = self.process_next(exclude_ids=excluded_ids)
            if outcome is None:
                break
            scans += 1
            summary.record(outcome)
            excluded_ids.append(outcome.job_id)
        return summary

    def process_next(self, *, exclude_ids: Sequence[uuid.UUID] = ()) -> CleanupOutcome | None:
        """Claim and process the oldest pending job, or return ``None``."""
        job = self._jobs.get_pending_for_update(exclude_ids=exclude_ids)
        if job is None:
            return None
        return self._process(job)

    def process_job(self, job_id: uuid.UUID) -> CleanupOutcome | None:
        """Process one specific job, for a targeted dispatch.

        A job that is no longer ``PENDING`` is skipped, so a duplicate message
        delivery cannot repeat a completed deletion (09_testing.md Section
        16.8).
        """
        job = self._jobs.get_for_update(job_id)
        if job is None or job.status != CleanupStatus.PENDING.value:
            self._db.rollback()
            return None
        return self._process(job)

    def _process(self, job: StorageCleanupJob) -> CleanupOutcome:
        """Execute one locked job and persist its outcome."""
        if self._is_deferred(job):
            attempts = job.attempts
            logger.info(
                "cleanup_deferred",
                extra={
                    "operation": "cleanup",
                    "cleanup_job_id": str(job.id),
                    "project_id": str(job.project_id) if job.project_id else None,
                },
            )
            # Nothing changed: release the lock so the row stays claimable.
            self._db.rollback()
            return CleanupOutcome(
                job_id=job.id,
                storage_key=job.storage_key,
                target_type=job.target_type,
                status=CleanupStatus.PENDING.value,
                attempts=attempts,
                deferred=True,
            )

        job.attempts += 1
        self._jobs.set_status(job, CleanupStatus.PROCESSING.value)
        try:
            self._storage.delete(job.storage_key)
        except Exception as exc:
            return self._record_failure(job, exc)

        self._jobs.set_status(job, CleanupStatus.COMPLETED.value, completed_at=_now())
        self._db.commit()
        logger.info(
            "cleanup_completed",
            extra={
                "operation": "cleanup",
                "cleanup_job_id": str(job.id),
                "project_id": str(job.project_id) if job.project_id else None,
            },
        )
        return CleanupOutcome(
            job_id=job.id,
            storage_key=job.storage_key,
            target_type=job.target_type,
            status=CleanupStatus.COMPLETED.value,
            attempts=job.attempts,
        )

    def _record_failure(self, job: StorageCleanupJob, exc: Exception) -> CleanupOutcome:
        """Record a failed attempt and decide whether another one is allowed."""
        message = (str(exc) or exc.__class__.__name__)[:MAX_ERROR_LENGTH]
        exhausted = job.attempts >= self._settings.cleanup_max_attempts
        status = CleanupStatus.FAILED.value if exhausted else CleanupStatus.PENDING.value
        self._jobs.set_status(job, status, last_error=message)
        self._db.commit()
        logger.error(
            "cleanup_failed",
            extra={
                "operation": "cleanup",
                "cleanup_job_id": str(job.id),
                "project_id": str(job.project_id) if job.project_id else None,
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return CleanupOutcome(
            job_id=job.id,
            storage_key=job.storage_key,
            target_type=job.target_type,
            status=status,
            attempts=job.attempts,
        )

    def _is_deferred(self, job: StorageCleanupJob) -> bool:
        """Return whether the job must wait for an active generation task.

        Directory jobs address a whole project tree, so they wait while any
        ``PENDING`` or ``PROCESSING`` task still belongs to that project. File
        jobs address objects whose metadata is already gone and whose deletion
        was refused while a task was active, so they are always safe.
        """
        if job.target_type != CleanupTargetType.DIRECTORY.value or job.project_id is None:
            return False
        return self._tasks.get_active_for_project(job.project_id) is not None
