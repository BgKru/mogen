"""Project request and response schemas (api_contracts.md Sections 5.9, 5.10 and 7).

Fields follow the documented snake_case contract; ``current_result`` and
``latest_task`` are the compact summaries defined for project listings, not the
full result and task responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models.enums import ProjectStatus, ProjectType

# Input guard only: the business limit is PROJECT_NAME_MAX_LENGTH, enforced by
# ProjectService so that every name violation returns the documented code.
_MAX_PROJECT_NAME_INPUT = 1024


class ProjectSort(StrEnum):
    """Accepted ``sort`` values for project listing.

    The contract does not enumerate them; unknown values are rejected with 422
    rather than silently ignored.
    """

    CREATED_AT_DESC = "created_at_desc"
    CREATED_AT_ASC = "created_at_asc"


class ProjectCreateRequest(BaseModel):
    """Project creation payload (api_contracts.md Section 7.1)."""

    name: str = Field(max_length=_MAX_PROJECT_NAME_INPUT)
    type: ProjectType


class ProjectCurrentResult(BaseModel):
    """Current-result summary embedded in a project response (`5.9`)."""

    id: uuid.UUID
    format: str
    file_size_bytes: int
    created_at: datetime


class ProjectLatestTask(BaseModel):
    """Latest-task summary embedded in a project response (`5.9`)."""

    id: uuid.UUID
    status: str


class ProjectResponse(BaseModel):
    """Project representation returned by create, list and detail (`5.9`)."""

    id: uuid.UUID
    name: str
    type: ProjectType
    status: ProjectStatus
    source_image_count: int
    result_available: bool
    current_result: ProjectCurrentResult | None
    latest_task: ProjectLatestTask | None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """One page of projects (api_contracts.md Section 7.2)."""

    items: list[ProjectResponse]
    total_count: int
    limit: int
    offset: int


class ProjectDeleteResponse(BaseModel):
    """Accepted deletion response (api_contracts.md Section 7.4)."""

    project_id: uuid.UUID
    deletion_status: Literal["PENDING"] = "PENDING"
