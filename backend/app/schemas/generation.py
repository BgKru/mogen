"""Generation request and response schemas (api_contracts.md Sections 5.7, 9).

Field names follow the documented snake_case contract. ``progress_percent``
stays null unless the worker reported a reliable percentage, and ``stage``
only ever holds an actual processing stage, never a terminal task status.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models.enums import ProjectStatus, TaskStatus, TaskType


class GenerationRequest(BaseModel):
    """Optional empty generation body (api_contracts.md Section 9.1)."""


class GenerationTaskResponse(BaseModel):
    """Full task representation returned after starting generation (`5.7`)."""

    id: uuid.UUID
    project_id: uuid.UUID
    task_type: TaskType
    status: TaskStatus
    stage: str | None
    progress_percent: int | None
    status_message: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class GenerationStartResponse(BaseModel):
    """Accepted generation request (`9.1`)."""

    task: GenerationTaskResponse


class GenerationTaskSummary(BaseModel):
    """Latest-task entry embedded in the project status response (`9.3`)."""

    id: uuid.UUID
    task_type: TaskType
    status: TaskStatus
    stage: str | None
    progress_percent: int | None
    status_message: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ProjectStatusResponse(BaseModel):
    """Project processing status (`9.3`)."""

    project_id: uuid.UUID
    project_status: ProjectStatus
    result_available: bool
    latest_task: GenerationTaskSummary | None
