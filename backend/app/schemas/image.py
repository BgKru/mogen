"""Image request and response schemas (api_contracts.md Sections 5.6 and 8).

Uploads use multipart/form-data; responses expose metadata only. Storage keys
and physical paths are never returned (API-AC-16).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImageResponse(BaseModel):
    """Image metadata representation returned by upload and listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size_bytes: int
    width: int
    height: int
    position: int
    created_at: datetime


class ImageListResponse(BaseModel):
    """All images of one project (api_contracts.md Section 8.2)."""

    items: list[ImageResponse]
    total_count: int
