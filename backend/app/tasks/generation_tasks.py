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

import hashlib
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.models import GenerationTask
from app.db.models.enums import TaskType
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.services.result_service import result_storage_key
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


@dataclass(frozen=True, slots=True)
class PipelineArtifact:
    """A validated asset a pipeline produced and wants registered.

    The pipeline owns preprocessing, inference, export and validation; the
    worker owns the persistent write and the database transaction. Keeping the
    two apart is what lets ``run_generation`` register the result and finish the
    task atomically (06_object_generation.md Sections 12.4-12.5, 13.2).
    """

    path: Path
    sha256: str
    file_size_bytes: int
    format: str = "GLB"
    mime_type: str = "model/gltf-binary"
    metadata: dict[str, Any] = field(default_factory=dict)
    storage_key: str | None = None
    cleanup_dir: Path | None = None


Pipeline = Callable[[TaskContext], PipelineArtifact | None]

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

        artifact: PipelineArtifact | None = None
        try:
            with _HeartbeatMonitor(
                settings=settings,
                session_factory=session_factory,
                task_id=task_id,
                worker_id=worker_id,
            ):
                artifact = selected(context)
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

        if artifact is not None:
            # A pipeline that produced an asset gets its result registered in
            # the same transaction that finishes the task (roadmap 5.8).
            try:
                completed = _persist_artifact(
                    service=service,
                    storage=storage,
                    task=task,
                    artifact=artifact,
                    worker_id=worker_id,
                )
            except GenerationCancelled:
                service.cancel(task_id, worker_id=worker_id, reason="Task cancelled")
                return WorkerOutcome(task_id=task_id, status="cancelled")
            except Exception as exc:
                error_code = getattr(exc, "error_code", GENERATION_FAILED)
                error_message = str(exc) or exc.__class__.__name__
                logger.exception(
                    "generation_result_persistence_failed",
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

            if not completed:
                if service.is_cancel_requested(task_id):
                    return WorkerOutcome(task_id=task_id, status="cancelled")
                logger.warning(
                    "generation_completion_not_owned",
                    extra={
                        "operation": "generation",
                        "task_id": str(task_id),
                        "project_id": str(task.project_id),
                    },
                )
                return WorkerOutcome(task_id=task_id, status="skipped")
            _cleanup_work_dir(artifact)
        else:
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


STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
RESULT_PERSISTENCE_FAILED = "RESULT_PERSISTENCE_FAILED"
_HASH_CHUNK_SIZE = 4 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 of a local artifact, streaming it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _delete_quietly(storage: StorageBackend, key: str) -> None:
    """Remove a stored object if the task failed before registering it."""
    try:
        storage.delete(key)
    except Exception:
        logger.warning(
            "generation_result_cleanup_failed",
            extra={"operation": "generation", "storage_key": key},
        )


def _cleanup_work_dir(artifact: PipelineArtifact) -> None:
    """Remove task-specific intermediate files after a successful store."""
    directory = artifact.cleanup_dir
    if directory is None:
        return
    try:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        logger.warning(
            "generation_work_dir_cleanup_failed",
            extra={"operation": "generation", "work_dir": str(directory)},
        )


def _persist_artifact(
    *,
    service: TaskExecutionService,
    storage: StorageBackend,
    task: GenerationTask,
    artifact: PipelineArtifact,
    worker_id: str,
) -> bool:
    """Store a validated artifact, then register it atomically.

    The asset is written before the transaction because a database transaction
    must not span a potentially large file write. The file is removed again when
    registration raises or when a cancellation won the race, so a failed attempt
    never leaves a current result behind (06 Section 12.4; OBJ-AC-15).
    """
    key = artifact.storage_key or result_storage_key(task.project_id, task.id)
    path = Path(artifact.path)

    if not path.is_file():
        raise GenerationFailure(STORAGE_WRITE_FAILED, "The generated asset is not readable.")
    if _sha256_file(path) != artifact.sha256.strip().lower():
        raise GenerationFailure(
            RESULT_PERSISTENCE_FAILED, "The generated asset checksum changed before storage."
        )
    if path.stat().st_size != artifact.file_size_bytes:
        raise GenerationFailure(
            RESULT_PERSISTENCE_FAILED, "The generated asset size changed before storage."
        )

    try:
        with path.open("rb") as stream:
            written = storage.save(stream, key)
    except AppError as exc:
        raise GenerationFailure(
            STORAGE_WRITE_FAILED, "The generated asset could not be stored."
        ) from exc
    except OSError as exc:
        raise GenerationFailure(
            STORAGE_WRITE_FAILED, "The generated asset could not be stored."
        ) from exc
    if written != artifact.file_size_bytes:
        _delete_quietly(storage, key)
        raise GenerationFailure(
            RESULT_PERSISTENCE_FAILED, "The stored asset does not match the generated file."
        )

    try:
        completed = service.complete_with_result(
            task.id,
            worker_id=worker_id,
            storage_key=key,
            format=artifact.format,
            mime_type=artifact.mime_type,
            file_size_bytes=artifact.file_size_bytes,
            sha256=artifact.sha256,
            metadata=artifact.metadata,
        )
    except Exception as exc:
        _delete_quietly(storage, key)
        raise GenerationFailure(
            RESULT_PERSISTENCE_FAILED, "The generation result could not be registered."
        ) from exc

    if not completed:
        # A cancellation request means this result must never become current.
        # A lost lease is different: recovery may still own the same task key,
        # so the file is left in place for the recovering attempt.
        if service.is_cancel_requested(task.id):
            _delete_quietly(storage, key)
        return False
    return True


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
