"""Image endpoints (api_contracts.md Section 8).

Uploads are multipart/form-data with exactly one file per request. Ownership is
derived from the authenticated user and inaccessible projects return 404, so
the API never discloses their existence.

Content is streamed from the storage abstraction with the verified media type
and a sanitised download name; the storage key and the resolved filesystem path
never appear in a response. Deletion removes metadata and queues the stored
file for the cleanup worker in one transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_current_user,
    get_image_service,
    get_settings,
    require_csrf,
)
from app.core.config import Settings
from app.db.models import User
from app.schemas.image import ImageListResponse, ImageResponse
from app.services.image_service import ImageService, content_disposition

router = APIRouter(prefix="/projects/{project_id}/images", tags=["images"])

# Chunk size for streamed delivery; large enough to keep syscalls cheap while
# never buffering a whole photograph in memory (api_contracts.md Section 8.3).
_STREAM_CHUNK_SIZE = 64 * 1024


def _stream_content(stream: BinaryIO) -> Iterator[bytes]:
    """Yield a stored file in chunks and always close the handle."""
    try:
        while chunk := stream.read(_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        stream.close()


@router.post(
    "",
    status_code=201,
    response_model=ImageResponse,
    dependencies=[Depends(require_csrf)],
    summary="Upload a project image",
)
def upload_image(
    project_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPEG or PNG photograph")],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ImageService, Depends(get_image_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ImageResponse:
    """Validate and store one photograph, returning its metadata."""
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    # Read one byte past the limit so an oversized upload is detected without
    # buffering an arbitrary amount of client data.
    data = file.file.read(max_bytes + 1)
    image = service.upload_image(
        user_id=user.id,
        project_id=project_id,
        filename=file.filename or "",
        content_type=file.content_type,
        data=data,
    )
    return ImageResponse.model_validate(image)


@router.get("", response_model=ImageListResponse, summary="List project images")
def list_images(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> ImageListResponse:
    """Return the project's image metadata in upload order."""
    images = service.list_images(user_id=user.id, project_id=project_id)
    return ImageListResponse(
        items=[ImageResponse.model_validate(image) for image in images],
        total_count=len(images),
    )


@router.get(
    "/{image_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Stored image bytes",
            "content": {"image/jpeg": {}, "image/png": {}},
        },
        404: {"description": "Image or project not found or inaccessible"},
        503: {"description": "Storage temporarily unavailable"},
    },
    summary="Retrieve image content",
)
def get_image_content(
    project_id: uuid.UUID,
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> StreamingResponse:
    """Stream one stored photograph with private, path-free response headers."""
    content = service.open_image_content(user_id=user.id, project_id=project_id, image_id=image_id)
    return StreamingResponse(
        _stream_content(content.stream),
        media_type=content.image.mime_type,
        headers={
            # The stored name is client-supplied metadata, so it is sanitised
            # again for the header (api_contracts.md Section 8.3).
            "Content-Disposition": content_disposition(content.image.original_filename),
            "Cache-Control": "private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{image_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_csrf)],
    summary="Delete a project image",
)
def delete_image(
    project_id: uuid.UUID,
    image_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ImageService, Depends(get_image_service)],
) -> Response:
    """Remove image metadata and schedule its stored file for cleanup."""
    service.delete_image(user_id=user.id, project_id=project_id, image_id=image_id)
    return Response(status_code=204)
