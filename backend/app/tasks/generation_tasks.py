"""Celery entry points for generation work (roadmap 4.1-4.3, 4.5, 4.7).

Phase 4 delivers the worker-side lifecycle: atomic claiming, heartbeat, the
terminal transitions and duplicate-delivery protection. The ML pipelines
themselves arrive in Phases 5 and 6; until then no pipeline is registered and a
claimed task fails with the documented ``WORKER_UNAVAILABLE`` code instead of
pretending to process. That is deliberately not simulated ML work.

A pipeline is registered per task type with :func:`register_pipeline` and
receives a :class:`TaskContext` that exposes heartbeat, progress reporting and
cooperative cancellation checks. Tests inject a pipeline directly, so the whole
lifecycle is exercised without any model.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import GenerationTask
from app.db.models.enums import TaskType
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.services.task_execution_service import TaskExecutionService
from app.storage import LocalStorage, StorageBackend
from app.tasks.celery_app import (
    OBJECT_GENERATION_TASK,
    SCENE_RECONSTRUCTION_TASK,
    celery_app,
)

logger = logging.getLogger(__name__)

WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
GENERATION_FAILED = "GENERATION_FAILED"
PIPELINE_UNAVAILABLE_MESSAGE = "Generation processing is not available in this deployment."

# Engine and storage are process-wide: a Celery worker executes many tasks.
_runtime: tuple[sessionmaker[Session], StorageBackend] | None = None

WorkerStatus = Literal["completed", "failed", "cancelled", "skipped"]


class GenerationCancelled(Exception):
    """Raised by a pipeline that observed a cooperative cancellation request."""


class GenerationFailure(Exception):
    """A pipeline failure with a stable machine-readable error code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class TaskContext:
    """What a pipeline may do with the task it owns."""

    task: GenerationTask
    settings: Settings
    storage: StorageBackend
    worker_id: str
    session: Session
    heartbeat: Callable[[], bool]
    report_progress: Callable[..., bool]
    is_cancel_requested: Callable[[], bool]

    def raise_if_cancelled(self) -> None:
        """Stop processing when the project asked for cancellation."""
        if self.is_cancel_requested():
            raise GenerationCancelled("cancellation requested")


Pipeline = Callable[[TaskContext], None]

_pipelines: dict[TaskType, Pipeline] = {}


def register_pipeline(task_type: TaskType, pipeline: Pipeline) -> None:
    """Register the ML pipeline for a task type (Phases 5 and 6)."""
    _pipelines[task_type] = pipeline


def resolve_pipeline(task_type: TaskType) -> Pipeline | None:
    """Return the registered pipeline for a task type, if one exists."""
    return _pipelines.get(task_type)


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    """What one worker invocation did with the task."""

    task_id: uuid.UUID
    status: WorkerStatus
    error_code: str | None = None


class _HeartbeatMonitor:
    """Renew the task lease while a long pipeline runs.

    A separate session is used because the pipeline owns the main session; the
    lease update is a conditional SQL statement, so it cannot overwrite the
    pipeline's work. The monitor stops when the lease is no longer renewable,
    which means another worker or the recovery service took over.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        task_id: uuid.UUID,
        worker_id: str,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._task_id = task_id
        self._worker_id = worker_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="task-heartbeat", daemon=True)

    def __enter__(self) -> _HeartbeatMonitor:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(5.0, float(self._settings.task_heartbeat_seconds)))

    def _run(self) -> None:
        interval = max(1, self._settings.task_heartbeat_seconds)
        while not self._stop.wait(interval):
            try:
                with self._session_factory() as session:
                    renewed = TaskExecutionService(session, self._settings).heartbeat(
                        self._task_id, worker_id=self._worker_id
                    )
            except Exception:
                logger.exception(
                    "task_heartbeat_failed",
                    extra={"operation": "generation", "task_id": str(self._task_id)},
                )
                return
            if not renewed:
                logger.warning(
                    "task_lease_lost",
                    extra={"operation": "generation", "task_id": str(self._task_id)},
                )
                return


def run_generation(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    task_id: uuid.UUID,
    task_type: TaskType,
    worker_id: str,
    pipeline: Pipeline | None = None,
) -> WorkerOutcome:
    """Claim and execute one task, without involving Celery.

    Kept broker-free so the whole worker path can be tested against a scratch
    database (09_testing.md Sections 7.5 and 9.7).
    """
    with session_scope(session_factory) as session:
        service = TaskExecutionService(session, settings)
        claim = service.claim(task_id, worker_id=worker_id)
        if not claim.claimed or claim.task is None:
            logger.info(
                "generation_claim_skipped",
                extra={"operation": "generation", "task_id": str(task_id)},
            )
            return WorkerOutcome(task_id=task_id, status="skipped")

        task = claim.task
        context = TaskContext(
            task=task,
            settings=settings,
            storage=storage,
            worker_id=worker_id,
            session=session,
            heartbeat=lambda: service.heartbeat(task_id, worker_id=worker_id),
            report_progress=lambda **kwargs: service.record_progress(
                task_id, worker_id=worker_id, **kwargs
            ),
            is_cancel_requested=lambda: service.is_cancel_requested(task_id),
        )

        if service.is_cancel_requested(task_id):
            service.cancel(task_id, worker_id=worker_id, reason="Task cancelled")
            return WorkerOutcome(task_id=task_id, status="cancelled")

        selected = pipeline if pipeline is not None else resolve_pipeline(task_type)
        if selected is None:
            # No ML pipeline is installed yet. Fail honestly instead of
            # fabricating progress or a result (10_development_roadmap.md 4.3).
            service.fail(
                task_id,
                worker_id=worker_id,
                error_code=WORKER_UNAVAILABLE,
                error_message=PIPELINE_UNAVAILABLE_MESSAGE,
            )
            logger.warning(
                "generation_pipeline_unavailable",
                extra={
                    "operation": "generation",
                    "task_id": str(task_id),
                    "project_id": str(task.project_id),
                    "error_code": WORKER_UNAVAILABLE,
                },
            )
            return WorkerOutcome(task_id=task_id, status="failed", error_code=WORKER_UNAVAILABLE)

        try:
            with _HeartbeatMonitor(
                settings=settings,
                session_factory=session_factory,
                task_id=task_id,
                worker_id=worker_id,
            ):
                selected(context)
        except GenerationCancelled:
            service.cancel(task_id, worker_id=worker_id, reason="Task cancelled")
            return WorkerOutcome(task_id=task_id, status="cancelled")
        except Exception as exc:
            error_code = getattr(exc, "error_code", GENERATION_FAILED)
            error_message = str(exc) or exc.__class__.__name__
            logger.exception(
                "generation_pipeline_failed",
                extra={
                    "operation": "generation",
                    "task_id": str(task_id),
                    "project_id": str(task.project_id),
                    "error_code": error_code,
                },
            )
            service.fail(
                task_id,
                worker_id=worker_id,
                error_code=str(error_code),
                error_message=error_message,
            )
            return WorkerOutcome(task_id=task_id, status="failed", error_code=str(error_code))

        service.complete(task_id, worker_id=worker_id)
        logger.info(
            "generation_task_completed",
            extra={
                "operation": "generation",
                "task_id": str(task_id),
                "project_id": str(task.project_id),
            },
        )
        return WorkerOutcome(task_id=task_id, status="completed")


def _runtime_for(settings: Settings) -> tuple[sessionmaker[Session], StorageBackend]:
    """Return the worker's session factory and storage, creating them once."""
    global _runtime  # noqa: PLW0603 - one connection pool per worker process
    if _runtime is None:
        engine = create_db_engine(settings)
        _runtime = (create_session_factory(engine), LocalStorage(settings.storage_root))
    return _runtime


def _worker_identity(request: object) -> str:
    """Return ``hostname:pid`` for the lease owner."""
    hostname = getattr(request, "hostname", None) or socket.gethostname()
    return f"{hostname}:{os.getpid()}"


def _execute(task_type: TaskType, task_id: str, worker_id: str) -> dict[str, str | None]:
    settings = get_settings()
    session_factory, storage = _runtime_for(settings)
    outcome = run_generation(
        settings=settings,
        session_factory=session_factory,
        storage=storage,
        task_id=uuid.UUID(task_id),
        task_type=task_type,
        worker_id=worker_id,
    )
    return {
        "task_id": str(outcome.task_id),
        "status": outcome.status,
        "error_code": outcome.error_code,
    }


@celery_app.task(name=OBJECT_GENERATION_TASK, bind=True)
def generate_object_task(
    self: object,
    task_id: str,
    project_id: str | None = None,
    task_type: str | None = None,
) -> dict[str, str | None]:
    """Claim and execute one object-generation task.

    ``project_id`` and ``task_type`` are routing metadata from the Celery
    message; PostgreSQL remains the authority for both.
    """
    return _execute(TaskType.OBJECT, task_id, _worker_identity(getattr(self, "request", self)))


@celery_app.task(name=SCENE_RECONSTRUCTION_TASK, bind=True)
def reconstruct_scene_task(
    self: object,
    task_id: str,
    project_id: str | None = None,
    task_type: str | None = None,
) -> dict[str, str | None]:
    """Claim and execute one scene-reconstruction task."""
    return _execute(TaskType.SCENE, task_id, _worker_identity(getattr(self, "request", self)))
