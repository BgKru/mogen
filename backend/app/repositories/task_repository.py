"""Repository for generation tasks (05_database_specification.md Section 9)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import selectinload

from app.db.models import GenerationTask, GenerationTaskImage, ProjectImage
from app.db.models.enums import TaskStatus
from app.repositories.base import BaseRepository

# Statuses counted as an active task by uq_generation_task_active_project.
ACTIVE_TASK_STATUSES = (TaskStatus.PENDING.value, TaskStatus.PROCESSING.value)


class TaskRepository(BaseRepository[GenerationTask]):
    """Database access for generation tasks and their input snapshots.

    Task lifecycle policy (allowed transitions, idempotency decisions, worker
    claiming) belongs to services; this layer only reads and writes rows.
    """

    model = GenerationTask

    def create(
        self,
        *,
        project_id: uuid.UUID,
        task_type: str,
        idempotency_key: str,
        request_fingerprint: str,
        parameters: dict[str, object],
        status: str = TaskStatus.PENDING.value,
        celery_task_id: str | None = None,
        task_id: uuid.UUID | None = None,
        queued_at: datetime | None = None,
        status_message: str | None = None,
    ) -> GenerationTask:
        """Insert a generation task owned by a project (Section 16.4).

        ``celery_task_id`` is the task identifier itself: the Celery task ID
        must equal ``GenerationTask.id`` so redeliveries correlate to one
        logical task (data_flow.md Section 7.2).
        """
        return self.add(
            GenerationTask(
                id=task_id or uuid.uuid4(),
                project_id=project_id,
                task_type=task_type,
                status=status,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                parameters=parameters,
                celery_task_id=celery_task_id,
                queued_at=queued_at,
                status_message=status_message,
            )
        )

    def get_by_idempotency_key(
        self, project_id: uuid.UUID, idempotency_key: str
    ) -> GenerationTask | None:
        """Return the task stored under a project-scoped idempotency key."""
        statement = select(GenerationTask).where(
            GenerationTask.project_id == project_id,
            GenerationTask.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)

    def get_active_for_project(self, project_id: uuid.UUID) -> GenerationTask | None:
        """Return the project's PENDING or PROCESSING task, if any."""
        statement = select(GenerationTask).where(
            GenerationTask.project_id == project_id,
            GenerationTask.status.in_(ACTIVE_TASK_STATUSES),
        )
        return self.session.scalar(statement)

    def list_for_project(
        self, project_id: uuid.UUID, *, limit: int, offset: int = 0
    ) -> Sequence[GenerationTask]:
        """Return one page of a project's task history, newest first."""
        statement = (
            select(GenerationTask)
            .where(GenerationTask.project_id == project_id)
            .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self.session.scalars(statement).all()

    def count_for_project(self, project_id: uuid.UUID) -> int:
        """Return how many tasks a project has ever had."""
        return (
            self.session.scalar(
                select(func.count())
                .select_from(GenerationTask)
                .where(GenerationTask.project_id == project_id)
            )
            or 0
        )

    def latest_by_project_ids(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, GenerationTask]:
        """Return the newest task for each project in one query, for listings."""
        if not project_ids:
            return {}
        statement = (
            select(GenerationTask)
            .ext(distinct_on(GenerationTask.project_id))
            .where(GenerationTask.project_id.in_(project_ids))
            .order_by(
                GenerationTask.project_id,
                GenerationTask.created_at.desc(),
                GenerationTask.id.desc(),
            )
        )
        return {task.project_id: task for task in self.session.scalars(statement).all()}

    def add_input_images(
        self,
        *,
        task_id: uuid.UUID,
        project_id: uuid.UUID,
        images: Sequence[ProjectImage],
    ) -> list[GenerationTaskImage]:
        """Persist the ordered input snapshot for a task (Section 10).

        Positions follow the order of ``images``. The composite foreign keys
        reject an image from another project at flush time.
        """
        task_images = [
            GenerationTaskImage(
                task_id=task_id,
                image_id=image.id,
                project_id=project_id,
                position=position,
            )
            for position, image in enumerate(images)
        ]
        self.session.add_all(task_images)
        self.session.flush()
        return task_images

    def list_input_images(self, task_id: uuid.UUID) -> Sequence[GenerationTaskImage]:
        """Return a task's input snapshot in processing order, with images loaded."""
        statement = (
            select(GenerationTaskImage)
            .where(GenerationTaskImage.task_id == task_id)
            .options(selectinload(GenerationTaskImage.image))
            .order_by(GenerationTaskImage.position, GenerationTaskImage.image_id)
        )
        return self.session.scalars(statement).all()

    def is_image_referenced(self, image_id: uuid.UUID) -> bool:
        """Return whether any generation task snapshot still uses the image.

        Generation history protects its inputs, so an image referenced by
        ``generation_task_images`` must stay immutable (05 Section 8.5). The
        database enforces the same rule with a ``RESTRICT`` foreign key.
        """
        statement = (
            select(GenerationTaskImage.image_id)
            .where(GenerationTaskImage.image_id == image_id)
            .limit(1)
        )
        return self.session.scalar(statement) is not None

    def set_status(
        self,
        task: GenerationTask,
        status: str,
        *,
        finished_at: datetime | None = None,
    ) -> None:
        """Set a task status, optionally recording its completion time."""
        task.status = status
        if finished_at is not None:
            task.finished_at = finished_at
        self.session.flush()

    def cancel_pending_for_project(
        self, project_id: uuid.UUID, *, finished_at: datetime | None = None
    ) -> int:
        """Move a project's PENDING tasks to CANCELLED in one statement.

        Used by project deletion (05_database_specification.md Section 12.4).
        Returns the number of tasks cancelled.
        """
        values: dict[str, object] = {"status": TaskStatus.CANCELLED.value}
        if finished_at is not None:
            values["finished_at"] = finished_at
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.project_id == project_id,
                GenerationTask.status == TaskStatus.PENDING.value,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        cancelled = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return cancelled

    def request_cancellation_for_processing(
        self, project_id: uuid.UUID, *, requested_at: datetime
    ) -> int:
        """Ask a project's PROCESSING tasks to stop cooperatively.

        The worker owns the terminal transition, so the status is left alone and
        only ``cancel_requested_at`` is recorded (Section 12.4). An earlier
        request time is preserved. Returns the number of tasks flagged.
        """
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.project_id == project_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=requested_at)
            .execution_options(synchronize_session=False)
        )
        flagged = self.session.execute(statement).rowcount or 0
        self.session.flush()
        return flagged

    # --- worker claiming, leases and recovery (Section 9.11) ---------------

    def claim_pending(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> GenerationTask | None:
        """Atomically claim a PENDING task for one worker.

        The conditional ``UPDATE ... WHERE status = 'PENDING'`` is the claim:
        only one of several duplicate deliveries can change the row, so a
        second worker never starts another inference or reconstruction
        (data_flow.md Section 7.4).
        """
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PENDING.value,
            )
            .values(
                status=TaskStatus.PROCESSING.value,
                worker_id=worker_id,
                started_at=func.coalesce(GenerationTask.started_at, now),
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                queued_at=func.coalesce(GenerationTask.queued_at, now),
                status_message="Processing started",
                error_code=None,
                error_message=None,
                updated_at=now,
            )
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task

    def heartbeat(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        """Renew the lease of a task still held by ``worker_id``."""
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.worker_id == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        renewed = (self.session.execute(statement).rowcount or 0) > 0
        self.session.flush()
        return renewed

    def record_progress(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        now: datetime,
        stage: str | None = None,
        progress_percent: int | None = None,
        status_message: str | None = None,
    ) -> bool:
        """Persist an actual processing stage, percentage or message."""
        values: dict[str, object] = {"updated_at": now}
        if stage is not None:
            values["stage"] = stage
        if progress_percent is not None:
            values["progress_percent"] = progress_percent
        if status_message is not None:
            values["status_message"] = status_message
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.worker_id == worker_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        updated = (self.session.execute(statement).rowcount or 0) > 0
        self.session.flush()
        return updated

    def mark_finished(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        status: str,
        finished_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        status_message: str | None = None,
    ) -> GenerationTask | None:
        """Move a task held by ``worker_id`` to a terminal state."""
        values: dict[str, object] = {
            "status": status,
            "finished_at": finished_at,
            "lease_expires_at": None,
            "updated_at": finished_at,
        }
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if status_message is not None:
            values["status_message"] = status_message
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.worker_id == worker_id,
            )
            .values(**values)
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task

    def list_stale_processing(
        self, *, now: datetime, heartbeat_before: datetime, limit: int
    ) -> Sequence[GenerationTask]:
        """Return PROCESSING tasks whose lease expired and heartbeat went quiet.

        Both conditions are required: a single missed heartbeat must never be
        treated as proof that the worker terminated (data_flow.md Section 12.8).
        The query uses ``ix_generation_tasks_status_lease_expires_at``.
        """
        statement = (
            select(GenerationTask)
            .where(
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.lease_expires_at.is_not(None),
                GenerationTask.lease_expires_at <= now,
                or_(
                    GenerationTask.heartbeat_at.is_(None),
                    GenerationTask.heartbeat_at <= heartbeat_before,
                ),
            )
            .order_by(GenerationTask.lease_expires_at, GenerationTask.id)
            .limit(limit)
        )
        return self.session.scalars(statement).all()

    def requeue_stale(
        self,
        task_id: uuid.UUID,
        *,
        now: datetime,
        heartbeat_before: datetime,
        lease_before: datetime,
    ) -> GenerationTask | None:
        """Return a stale PROCESSING task to PENDING for another attempt.

        The conditional update makes concurrent recovery instances safe, and
        increments ``attempt_count`` instead of creating a new task (Section
        9.3). A cancellation request is never requeued.
        """
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.lease_expires_at.is_not(None),
                GenerationTask.lease_expires_at <= lease_before,
                or_(
                    GenerationTask.heartbeat_at.is_(None),
                    GenerationTask.heartbeat_at <= heartbeat_before,
                ),
                GenerationTask.cancel_requested_at.is_(None),
            )
            .values(
                status=TaskStatus.PENDING.value,
                attempt_count=GenerationTask.attempt_count + 1,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                queued_at=now,
                status_message="Task requeued after worker interruption",
                error_code=None,
                error_message=None,
                updated_at=now,
            )
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task

    def fail_stale(
        self,
        task_id: uuid.UUID,
        *,
        now: datetime,
        lease_before: datetime,
        error_code: str,
        error_message: str,
        status_message: str | None = None,
    ) -> GenerationTask | None:
        """Mark a stale PROCESSING task FAILED when it cannot be retried."""
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PROCESSING.value,
                GenerationTask.lease_expires_at.is_not(None),
                GenerationTask.lease_expires_at <= lease_before,
            )
            .values(
                status=TaskStatus.FAILED.value,
                finished_at=now,
                worker_id=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=error_message,
                status_message=status_message or error_message,
                updated_at=now,
            )
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task

    def cancel_stale(
        self,
        task_id: uuid.UUID,
        *,
        now: datetime,
        lease_before: datetime,
        status_message: str = "Task cancelled",
        require_cancel_request: bool = True,
    ) -> GenerationTask | None:
        """Mark a requested cancellation CANCELLED after its worker stopped.

        Only a task whose lease expired can be cancelled this way, so the
        transition never races a worker that is still executing (Section 9.11;
        data_flow.md Section 12.9). A deleted project may be cancelled even when
        the flag is missing, because the project is already gone.
        """
        conditions = [
            GenerationTask.id == task_id,
            GenerationTask.status == TaskStatus.PROCESSING.value,
            GenerationTask.lease_expires_at.is_not(None),
            GenerationTask.lease_expires_at <= lease_before,
        ]
        if require_cancel_request:
            conditions.append(GenerationTask.cancel_requested_at.is_not(None))
        statement = (
            update(GenerationTask)
            .where(*conditions)
            .values(
                status=TaskStatus.CANCELLED.value,
                finished_at=now,
                lease_expires_at=None,
                status_message=status_message,
                updated_at=now,
            )
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task

    def list_pending_stalled(
        self, *, queued_before: datetime, limit: int
    ) -> Sequence[GenerationTask]:
        """Return PENDING tasks that have waited too long for dispatch."""
        statement = (
            select(GenerationTask)
            .where(
                GenerationTask.status == TaskStatus.PENDING.value,
                GenerationTask.queued_at.is_not(None),
                GenerationTask.queued_at <= queued_before,
            )
            .order_by(GenerationTask.queued_at, GenerationTask.id)
            .limit(limit)
        )
        return self.session.scalars(statement).all()

    def fail_pending_stalled(
        self,
        task_id: uuid.UUID,
        *,
        now: datetime,
        queued_before: datetime,
        error_code: str,
        error_message: str,
    ) -> GenerationTask | None:
        """Fail a task that was never dispatched within the stall timeout."""
        statement = (
            update(GenerationTask)
            .where(
                GenerationTask.id == task_id,
                GenerationTask.status == TaskStatus.PENDING.value,
                GenerationTask.queued_at.is_not(None),
                GenerationTask.queued_at <= queued_before,
            )
            .values(
                status=TaskStatus.FAILED.value,
                finished_at=now,
                error_code=error_code,
                error_message=error_message,
                status_message=error_message,
                updated_at=now,
            )
            .returning(GenerationTask)
            .execution_options(synchronize_session=False)
        )
        task = self.session.scalars(statement).first()
        self.session.flush()
        return task
