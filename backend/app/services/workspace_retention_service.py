"""Retention sweep for scene-reconstruction workspaces (roadmap 8.5).

``07_scene_reconstruction.md`` Section 15.7 requires obsolete intermediate files
to be removed safely while directories still used by active tasks are preserved,
and permits keeping them "for debugging according to the storage retention
policy". A failed task deliberately keeps ``/data/work/scene/{task_id}`` for
diagnostics, so without a sweep that directory would grow forever.

The sweep is conservative:

* only direct children of ``scene_work_dir`` whose name is a task UUID are
  considered, so the sweep can never delete an unrelated directory;
* a workspace is eligible only when its task is terminal *and* finished before
  the retention cutoff, or when no task row exists at all (an orphan left by a
  crashed attempt) and the directory itself is old enough;
* ``PENDING``/``PROCESSING`` tasks and unknown statuses are never touched;
* deletion is *queued* as a ``DIRECTORY`` cleanup job in the caller's
  transaction, so the cleanup worker performs and retries the filesystem work
  and a crash cannot leave a half-deleted workspace behind.

``scene_workspace_retention_hours=0`` disables pruning but still reports usage.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import GenerationTask
from app.db.models.enums import CleanupTargetType, TaskStatus
from app.repositories import CleanupJobRepository, OutboxRepository
from app.services.outbox_events import create_cleanup_event

logger = logging.getLogger(__name__)

TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


@dataclass(slots=True)
class RetentionSummary:
    """Aggregated result of one workspace sweep."""

    scanned: int = 0
    active: int = 0
    retained: int = 0
    queued: int = 0
    already_queued: int = 0
    skipped: int = 0
    bytes_total: int = 0
    bytes_queued: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return the counters for a structured log or a Celery result."""
        return {
            "scanned": self.scanned,
            "active": self.active,
            "retained": self.retained,
            "queued": self.queued,
            "already_queued": self.already_queued,
            "skipped": self.skipped,
            "bytes_total": self.bytes_total,
            "bytes_queued": self.bytes_queued,
        }


def _utc_from_timestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _directory_size(path: Path) -> int:
    """Return the total size of the files below ``path``, ignoring errors."""
    total = 0
    for root, _directories, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


class SceneWorkspaceRetentionService:
    """Prune terminal scene workspaces according to the retention policy."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._cleanup_jobs = CleanupJobRepository(session)
        self._outbox = OutboxRepository(session)

    def prune(self, *, now: datetime | None = None) -> RetentionSummary:
        """Scan the workspace root and queue expired workspaces for deletion."""
        moment = now or datetime.now(UTC)
        summary = RetentionSummary()
        work_root = Path(self._settings.scene_work_dir)
        if not work_root.is_dir():
            logger.info(
                "scene_workspace_sweep_empty",
                extra={"operation": "workspace_retention"},
            )
            return summary

        key_prefix = self._storage_key_prefix(work_root)
        if key_prefix is None:
            # Fail closed: a workspace outside the managed storage root cannot
            # be deleted through the cleanup contract, so nothing is queued.
            logger.error(
                "scene_workspace_outside_storage_root",
                extra={
                    "operation": "workspace_retention",
                    "scene_work_dir": str(work_root),
                },
            )
            return summary

        retention_hours = self._settings.scene_workspace_retention_hours
        cutoff = moment - timedelta(hours=retention_hours) if retention_hours > 0 else None

        for entry in sorted(work_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            try:
                task_id = uuid.UUID(entry.name)
            except ValueError:
                # Not a task workspace; never ours to delete.
                continue
            summary.scanned += 1
            try:
                modified_at = _utc_from_timestamp(entry.stat().st_mtime)
            except OSError:
                summary.skipped += 1
                continue
            size = _directory_size(entry)
            summary.bytes_total += size

            task = self._db.get(GenerationTask, task_id)
            if task is not None and task.status not in TERMINAL_TASK_STATUSES:
                # PENDING, PROCESSING or an unknown status: the task may still
                # be writing here (07 Section 15.7).
                summary.active += 1
                continue

            finished_at = task.finished_at if task is not None else None
            completed_at = finished_at or modified_at
            if cutoff is None or completed_at > cutoff:
                summary.retained += 1
                continue

            storage_key = f"{key_prefix}/{entry.name}"
            if self._cleanup_jobs.get_active_for_target(storage_key) is not None:
                summary.already_queued += 1
                continue
            job = self._cleanup_jobs.create(
                project_id=task.project_id if task is not None else None,
                storage_key=storage_key,
                target_type=CleanupTargetType.DIRECTORY.value,
            )
            create_cleanup_event(self._outbox, job)
            summary.queued += 1
            summary.bytes_queued += size
            logger.info(
                "scene_workspace_cleanup_queued",
                extra={
                    "operation": "workspace_retention",
                    "task_id": str(task_id),
                    "cleanup_job_id": str(job.id),
                    "size_bytes": size,
                },
            )

        self._db.commit()
        logger.info(
            "scene_workspace_retention",
            extra={
                "operation": "workspace_retention",
                "retention_hours": retention_hours,
                "workspace_usage": summary.as_dict(),
            },
        )
        return summary

    def _storage_key_prefix(self, work_root: Path) -> str | None:
        """Return the workspace root relative to the storage root, if inside it."""
        storage_root = Path(self._settings.storage_root).resolve()
        resolved = work_root.resolve()
        if resolved == storage_root or not resolved.is_relative_to(storage_root):
            return None
        return resolved.relative_to(storage_root).as_posix()
