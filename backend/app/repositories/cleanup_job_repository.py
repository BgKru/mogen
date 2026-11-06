"""Repository for storage cleanup jobs (05_database_specification.md Section 12)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from app.db.models import StorageCleanupJob
from app.db.models.enums import CleanupStatus
from app.repositories.base import BaseRepository

# Statuses the partial unique index treats as an in-flight cleanup (Section 12.5).
ACTIVE_CLEANUP_STATUSES = (CleanupStatus.PENDING.value, CleanupStatus.PROCESSING.value)


class CleanupJobRepository(BaseRepository[StorageCleanupJob]):
    """Database access for durable file cleanup requests.

    The cleanup worker that processes these rows is implemented in a later
    phase; this repository only records and reads them.
    """

    model = StorageCleanupJob

    def create(
        self,
        *,
        project_id: uuid.UUID | None,
        storage_key: str,
        target_type: str,
        status: str = CleanupStatus.PENDING.value,
    ) -> StorageCleanupJob:
        """Insert a cleanup job. ``project_id`` is optional (Section 12.1)."""
        return self.add(
            StorageCleanupJob(
                project_id=project_id,
                storage_key=storage_key,
                target_type=target_type,
                status=status,
            )
        )

    def get_active_for_target(self, storage_key: str) -> StorageCleanupJob | None:
        """Return the in-flight cleanup job for a storage key, if any.

        Lets callers avoid queueing a second cleanup for the same target; the
        partial unique index remains the final safeguard (Section 12.5).
        """
        statement = select(StorageCleanupJob).where(
            StorageCleanupJob.storage_key == storage_key,
            StorageCleanupJob.status.in_(ACTIVE_CLEANUP_STATUSES),
        )
        return self.session.scalar(statement)

    def get_for_update(self, job_id: uuid.UUID) -> StorageCleanupJob | None:
        """Lock one cleanup job for processing.

        A worker holds this lock from the claim until the transaction commits,
        so a crash rolls the claim back instead of leaving the job stuck in
        ``PROCESSING`` (05 Section 12.3).
        """
        statement = (
            select(StorageCleanupJob).where(StorageCleanupJob.id == job_id).with_for_update()
        )
        return self.session.scalar(statement)

    def get_pending_for_update(
        self, *, exclude_ids: Sequence[uuid.UUID] = ()
    ) -> StorageCleanupJob | None:
        """Lock the oldest pending job that another worker is not processing.

        ``FOR UPDATE ... SKIP LOCKED`` lets concurrent workers claim different
        jobs instead of waiting for the same row, while the row lock keeps the
        claim exclusive (09_testing.md Section 8.5).
        """
        statement = (
            select(StorageCleanupJob)
            .where(StorageCleanupJob.status == CleanupStatus.PENDING.value)
            .order_by(StorageCleanupJob.created_at, StorageCleanupJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if exclude_ids:
            statement = statement.where(StorageCleanupJob.id.not_in(exclude_ids))
        return self.session.scalar(statement)

    def list_pending(self, *, limit: int) -> Sequence[StorageCleanupJob]:
        """Return pending cleanup jobs in creation order."""
        statement = (
            select(StorageCleanupJob)
            .where(StorageCleanupJob.status == CleanupStatus.PENDING.value)
            .order_by(StorageCleanupJob.created_at, StorageCleanupJob.id)
            .limit(limit)
        )
        return self.session.scalars(statement).all()

    def list_for_project(self, project_id: uuid.UUID) -> Sequence[StorageCleanupJob]:
        """Return the cleanup history of a project, newest first."""
        statement = (
            select(StorageCleanupJob)
            .where(StorageCleanupJob.project_id == project_id)
            .order_by(StorageCleanupJob.created_at.desc(), StorageCleanupJob.id.desc())
        )
        return self.session.scalars(statement).all()

    def set_status(
        self,
        job: StorageCleanupJob,
        status: str,
        *,
        completed_at: datetime | None = None,
        last_error: str | None = None,
    ) -> None:
        """Update a cleanup job's state and optional diagnostic fields."""
        job.status = status
        if completed_at is not None:
            job.completed_at = completed_at
        if last_error is not None:
            job.last_error = last_error
        self.session.flush()
