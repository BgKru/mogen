"""Generation endpoints (api_contracts.md Section 9).

Starting generation returns HTTP 202 for a new task and HTTP 200 when an
idempotent repeat returns the task that was already created. The handler never
runs processing and never publishes to Redis: the transactional outbox event is
committed with the task and the Outbox Dispatcher publishes it afterwards.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response

from app.api.dependencies import get_current_user, get_generation_service, require_csrf
from app.db.models import User
from app.schemas.generation import (
    GenerationRequest,
    GenerationStartResponse,
    GenerationTaskResponse,
    GenerationTaskSummary,
    ProjectStatusResponse,
)
from app.services.generation_service import (
    GenerationService,
    ProjectStatusView,
    TaskStart,
)

router = APIRouter(prefix="/projects", tags=["generation"])


def _task_response(start: TaskStart) -> GenerationTaskResponse:
    """Map a task onto the documented representation (`5.7`)."""
    task = start.task
    return GenerationTaskResponse(
        id=task.id,
        project_id=task.project_id,
        task_type=task.task_type,
        status=task.status,
        stage=task.stage,
        progress_percent=task.progress_percent,
        status_message=task.status_message,
        error_code=task.error_code,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def _status_response(view: ProjectStatusView) -> ProjectStatusResponse:
    """Map a project and its latest task onto the status response (`9.3`)."""
    task = view.latest_task
    latest = (
        GenerationTaskSummary(
            id=task.id,
            task_type=task.task_type,
            status=task.status,
            stage=task.stage,
            progress_percent=task.progress_percent,
            status_message=task.status_message,
            error_code=task.error_code,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
        )
        if task is not None
        else None
    )
    return ProjectStatusResponse(
        project_id=view.project.id,
        project_status=view.project.status,
        result_available=view.result_available,
        latest_task=latest,
    )


@router.post(
    "/{project_id}/generate",
    status_code=202,
    response_model=GenerationStartResponse,
    dependencies=[Depends(require_csrf)],
    summary="Start generation",
)
def start_generation(
    project_id: uuid.UUID,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GenerationService, Depends(get_generation_service)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            description="Mandatory project-scoped idempotency key.",
        ),
    ],
    payload: GenerationRequest | None = None,
) -> GenerationStartResponse:
    """Create a generation task, or return the existing one for a repeated key."""
    start = service.start_generation(
        user_id=user.id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if not start.created:
        # A repeated request returns the existing task with HTTP 200
        # (api_contracts.md Section 9.2).
        response.status_code = 200
    return GenerationStartResponse(task=_task_response(start))


@router.get(
    "/{project_id}/status",
    response_model=ProjectStatusResponse,
    summary="Get project processing status",
)
def get_project_status(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GenerationService, Depends(get_generation_service)],
) -> ProjectStatusResponse:
    """Return the persisted project state, latest task and result availability."""
    return _status_response(service.get_status(user_id=user.id, project_id=project_id))
