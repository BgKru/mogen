"""Served result of a successful generation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class GenerationResultResponse(BaseModel):
    """Full result representation (api_contracts.md Section 5.8).

    The storage key and resolved filesystem path are deliberately absent.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    format: str
    mime_type: str
    file_size_bytes: int
    metadata: dict[str, Any]
    is_current: bool
    created_at: datetime
