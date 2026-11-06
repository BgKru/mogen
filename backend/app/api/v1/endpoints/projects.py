"""Project endpoints (api_contracts.md Section 7).

Every route authenticates the session and derives ownership from the
authenticated user. Missing, soft-deleted and other users' projects all return
404 so the API never discloses that a project exists (Section 13).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_user, get_project_service, require_csrf
from app.db.models import User
from app.db.models.enums import ProjectStatus, ProjectType
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectCurrentResult,
    ProjectDeleteResponse,
    ProjectLatestTask,
    ProjectListResponse,
    ProjectResponse,
    ProjectSort,
)
from app.services.project_service import ProjectService, ProjectView

router = APIRouter(prefix="/projects", tags=["projects"])

DEFAULT_PAGE_LIMIT = 20


def _project_response(view: ProjectView) -> ProjectResponse:
    """Map a service view onto the documented project representation (5.9)."""
    project = view.project
    current_result = view.current_result
    latest_task = view.latest_task
    return ProjectResponse(
        id=project.id,
        name=project.name,
        type=project.type,
        status=project.status,
        source_image_count=view.source_image_count,
        result_available=view.result_available,
        current_result=(
            ProjectCurrentResult(
                id=current_result.id,
                format=current_result.format,
                file_size_bytes=current_result.file_size_bytes,
                created_at=current_result.created_at,
            )
            if current_result is not None
            else None
        ),
        latest_task=(
            ProjectLatestTask(id=latest_task.id, status=latest_task.status)
            if latest_task is not None
            else None
        ),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.post(
    "",
    status_code=201,
    response_model=ProjectResponse,
    dependencies=[Depends(require_csrf)],
    summary="Create a project",
)
def create_project(
    payload: ProjectCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    """Create a project owned by the caller; generation is never started here."""
    view = service.create_project(user_id=user.id, name=payload.name, project_type=payload.type)
    return _project_response(view)


@router.get("", response_model=ProjectListResponse, summary="List projects")
def list_projects(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProjectService, Depends(get_project_service)],
    limit: Annotated[
        int,
        Query(ge=1, description="Page size; values above MAX_PAGE_SIZE are capped."),
    ] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_type: Annotated[
        ProjectType | None, Query(alias="type", description="OBJECT or SCENE")
    ] = None,
    project_status: Annotated[
        ProjectStatus | None, Query(alias="status", description="Project status")
    ] = None,
    sort: Annotated[ProjectSort, Query()] = ProjectSort.CREATED_AT_DESC,
) -> ProjectListResponse:
    """Return one page of the caller's non-deleted projects."""
    page = service.list_projects(
        user_id=user.id,
        limit=limit,
        offset=offset,
        project_type=project_type,
        status=project_status,
        newest_first=sort == ProjectSort.CREATED_AT_DESC,
    )
    return ProjectListResponse(
        items=[_project_response(view) for view in page.items],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get a project")
def get_project(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    """Return one active project owned by the caller."""
    return _project_response(service.get_project(user_id=user.id, project_id=project_id))


@router.delete(
    "/{project_id}",
    status_code=202,
    response_model=ProjectDeleteResponse,
    dependencies=[Depends(require_csrf)],
    summary="Delete a project",
)
def delete_project(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectDeleteResponse:
    """Soft-delete the project and schedule asynchronous file cleanup."""
    service.delete_project(user_id=user.id, project_id=project_id)
    return ProjectDeleteResponse(project_id=project_id)
