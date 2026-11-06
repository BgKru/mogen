"""Generation task creation and status (04_backend_specification.md Section 11).

The generation endpoint does not run processing and does not publish to Redis.
One PostgreSQL transaction creates the task, records its immutable input
snapshot, moves the project to ``PENDING`` and inserts the transactional outbox
event; the Outbox Dispatcher publishes it afterwards
(data_flow.md Section 6.3).

``Idempotency-Key`` is mandatory and project-scoped. The stored
``request_fingerprint`` lets a repeated request with the same key return the
existing task while a reused key with a different request is rejected with
HTTP 409 (Section 9.6; api_contracts.md Section 9.2).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import GenerationResult, GenerationTask, Project
from app.db.models.enums import ProjectStatus, TaskStatus, TaskType
from app.repositories import (
    ImageRepository,
    OutboxRepository,
    ProjectRepository,
    ResultRepository,
    TaskRepository,
)
from app.services.outbox_events import create_generation_event

logger = logging.getLogger(__name__)

GENERATION_ALREADY_RUNNING = "GENERATION_ALREADY_RUNNING"
GENERATION_INPUT_MISSING = "GENERATION_INPUT_MISSING"
IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
INVALID_PROJECT_STATE = "INVALID_PROJECT_STATE"

# Project states that may start a new generation attempt (05 Section 7.7).
STARTABLE_PROJECT_STATUSES = frozenset(
    {
        ProjectStatus.CREATED.value,
        ProjectStatus.COMPLETED.value,
        ProjectStatus.FAILED.value,
    }
)

# Logical generation settings stored in the task's JSONB snapshot
# (05 Section 9.7). They are part of the request fingerprint.
TASK_PARAMETERS: dict[TaskType, dict[str, str]] = {
    TaskType.OBJECT: {"algorithm": "TripoSR", "output_format": "GLB"},
    TaskType.SCENE: {"algorithm": "COLMAP_OPENMVS", "output_format": "GLB"},
}


def task_parameters_for(task_type: TaskType) -> dict[str, str]:
    """Return a copy of the logical parameters for a task type."""
    return dict(TASK_PARAMETERS[task_type])


def compute_request_fingerprint(
    *,
    project_id: uuid.UUID,
    task_type: TaskType,
    image_ids: list[uuid.UUID],
    parameters: dict[str, str],
) -> str:
    """Return the canonical SHA-256 fingerprint of a generation request.

    The fingerprint covers the project, the task type, the ordered source image
    identifiers and every generation parameter that affects the result, so a
    reused key with a different operation is detectable (05 Section 9.6).
    """
    canonical = json.dumps(
        {
            "project_id": str(project_id),
            "task_type": task_type.value,
            "image_ids": [str(image_id) for image_id in image_ids],
            "parameters": parameters,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _project_not_found() -> AppError:
    return AppError(404, "PROJECT_NOT_FOUND", "Project not found.")


def _already_running() -> AppError:
    return AppError(
        409,
        GENERATION_ALREADY_RUNNING,
        "A generation task is already running for this project.",
    )


def _idempotency_key_reused() -> AppError:
    return AppError(
        409,
        IDEMPOTENCY_KEY_REUSED,
        "The idempotency key was already used for a different request.",
    )


def _invalid_state(status: str) -> AppError:
    return AppError(
        409,
        INVALID_PROJECT_STATE,
        f"The project state '{status}' does not allow starting generation.",
    )


def _input_missing(message: str) -> AppError:
    return AppError(409, GENERATION_INPUT_MISSING, message)


def validate_generation_inputs(
    task_type: TaskType, *, image_count: int, settings: Settings
) -> None:
    """Enforce the per-type source image requirements (04 Sections 10.4-10.5)."""
    if task_type is TaskType.OBJECT:
        if image_count != 1:
            raise _input_missing("An OBJECT project requires exactly one source image.")
        return
    if image_count < settings.min_scene_images:
        raise _input_missing(
            f"A SCENE project requires at least {settings.min_scene_images} source images."
        )
    if image_count > settings.max_scene_images:
        raise _input_missing(
            f"A SCENE project accepts at most {settings.max_scene_images} source images."
        )


@dataclass(frozen=True, slots=True)
class TaskStart:
    """A created or previously created task returned to the client."""

    task: GenerationTask
    created: bool


@dataclass(frozen=True, slots=True)
class ProjectStatusView:
    """Project processing status response data (api_contracts.md Section 9.3)."""

    project: Project
    latest_task: GenerationTask | None
    current_result: GenerationResult | None

    @property
    def result_available(self) -> bool:
        """Follow the current result, not the latest task status."""
        return self.current_result is not None


class GenerationService:
    """Create generation tasks and report project processing status."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._projects = ProjectRepository(session)
        self._images = ImageRepository(session)
        self._tasks = TaskRepository(session)
        self._results = ResultRepository(session)
        self._outbox = OutboxRepository(session)

    def start_generation(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        idempotency_key: str,
    ) -> TaskStart:
        """Create the task, its snapshot, the project transition and the outbox event."""
        project = self._projects.get_active_for_update(project_id)
        if project is None or project.user_id != user_id:
            raise _project_not_found()

        task_type = TaskType(project.type)
        images = list(self._images.list_for_project(project_id))
        parameters = task_parameters_for(task_type)
        fingerprint = compute_request_fingerprint(
            project_id=project_id,
            task_type=task_type,
            image_ids=[image.id for image in images],
            parameters=parameters,
        )

        # Idempotency is resolved before the active-task and state checks so a
        # repeated request for a task that is already running still returns the
        # existing task (api_contracts.md Section 9.2).
        existing = self._tasks.get_by_idempotency_key(project_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint == fingerprint:
                return TaskStart(task=existing, created=False)
            raise _idempotency_key_reused()

        if self._tasks.get_active_for_project(project_id) is not None:
            raise _already_running()
        if project.status not in STARTABLE_PROJECT_STATUSES:
            raise _invalid_state(project.status)
        validate_generation_inputs(task_type, image_count=len(images), settings=self._settings)

        now = datetime.now(UTC)
        task_id = uuid.uuid4()
        try:
            task = self._tasks.create(
                task_id=task_id,
                project_id=project_id,
                task_type=task_type.value,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                parameters=parameters,
                status=TaskStatus.PENDING.value,
                celery_task_id=str(task_id),
                queued_at=now,
                status_message="Generation task accepted",
            )
            self._tasks.add_input_images(task_id=task.id, project_id=project_id, images=images)
            self._projects.set_status(project, ProjectStatus.PENDING.value)
            create_generation_event(self._outbox, task)
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            resolved = self._resolve_concurrent_conflict(project_id, idempotency_key, fingerprint)
            if resolved is not None:
                return resolved
            raise
        logger.info(
            "generation_task_created",
            extra={
                "operation": "generation_start",
                "project_id": str(project_id),
                "task_id": str(task.id),
                "user_id": str(user_id),
            },
        )
        return TaskStart(task=task, created=True)

    def get_status(self, *, user_id: uuid.UUID, project_id: uuid.UUID) -> ProjectStatusView:
        """Return the latest persisted task state for an owned project."""
        project = self._projects.get_active_for_user(project_id, user_id)
        if project is None:
            raise _project_not_found()
        latest = self._tasks.list_for_project(project_id, limit=1)
        return ProjectStatusView(
            project=project,
            latest_task=latest[0] if latest else None,
            current_result=self._results.get_current_for_project(project_id),
        )

    def _resolve_concurrent_conflict(
        self, project_id: uuid.UUID, idempotency_key: str, fingerprint: str
    ) -> TaskStart | None:
        """Translate a persistence-level uniqueness violation into its contract error.

        The project row lock normally serialises creation, so this path only
        runs when a database constraint is the final arbiter. ``None`` means the
        violation was unrelated and must propagate.
        """
        existing = self._tasks.get_by_idempotency_key(project_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint == fingerprint:
                return TaskStart(task=existing, created=False)
            raise _idempotency_key_reused()
        if self._tasks.get_active_for_project(project_id) is not None:
            raise _already_running()
        return None
