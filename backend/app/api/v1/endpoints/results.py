"""Current-result read and download endpoints (api_contracts.md Section 10).

Both endpoints require authentication and derive ownership from the session;
another user's project is a 404 rather than a 403. The download is streamed in
64 KiB chunks and exposes neither the storage key nor a filesystem path.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_current_user, get_result_service
from app.db.models import User
from app.schemas.result import GenerationResultResponse
from app.services.result_service import (
    ResultService,
    content_disposition,
    download_extension,
    result_mime_type,
    stream_result,
)

router = APIRouter(prefix="/projects", tags=["results"])


@router.get(
    "/{project_id}/result",
    response_model=GenerationResultResponse,
    summary="Get the current generation result",
)
def get_current_result(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
) -> GenerationResultResponse:
    """Return metadata for the project's current successful result."""
    result = service.get_current(user_id=user.id, project_id=project_id)
    return GenerationResultResponse(
        id=result.id,
        project_id=result.project_id,
        task_id=result.task_id,
        format=result.format,
        mime_type=result.mime_type,
        file_size_bytes=result.file_size_bytes,
        metadata=result.result_metadata or {},
        is_current=result.is_current,
        created_at=result.created_at,
    )


@router.get(
    "/{project_id}/download",
    summary="Download the current GLB result",
    response_class=StreamingResponse,
)
def download_current_result(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
) -> StreamingResponse:
    """Stream the current asset with format-correct headers.

    A GLB is served exactly as before. A Gaussian-splat PLY is served as
    ``application/octet-stream`` with a ``.ply`` filename; it is never
    mislabeled as glTF or downloaded under a ``.glb`` name (15 Section 5.5).
    """
    download = service.open_download(user_id=user.id, project_id=project_id)
    media_type = download.result.mime_type or result_mime_type(download.result.format)
    headers = {
        "Content-Type": media_type,
        "Content-Disposition": content_disposition(
            download.project.name, extension=download_extension(download.result.format)
        ),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Length": str(download.result.file_size_bytes),
    }
    return StreamingResponse(
        stream_result(download.stream),
        media_type=media_type,
        headers=headers,
    )
