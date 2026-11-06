"""Enumerated column values defined by 05_database_specification.md.

The database stores these as string columns guarded by CHECK constraints
(Section 3.6). Keeping the values in one place means the CHECK constraint SQL
and the application code that sets a value cannot drift apart.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectType(StrEnum):
    """Supported project generation types (Section 7.2)."""

    OBJECT = "OBJECT"
    SCENE = "SCENE"


class ProjectStatus(StrEnum):
    """Supported project statuses (Section 7.3)."""

    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ImageMimeType(StrEnum):
    """Verified MIME types accepted for source photographs (Section 8.2)."""

    JPEG = "image/jpeg"
    PNG = "image/png"


class TaskType(StrEnum):
    """Supported generation task types (Section 9.2)."""

    OBJECT = "OBJECT"
    SCENE = "SCENE"


class TaskStatus(StrEnum):
    """Supported generation task statuses (Section 9.3)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ResultFormat(StrEnum):
    """Asset formats the schema permits (Section 11.2)."""

    GLB = "GLB"
    OBJ = "OBJ"
    STL = "STL"


class CleanupTargetType(StrEnum):
    """Storage targets a cleanup job can address (Section 12.1)."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class CleanupStatus(StrEnum):
    """Supported cleanup job statuses (Section 12.2)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OutboxStatus(StrEnum):
    """Supported outbox publishing statuses (Section 13.2)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxEventType(StrEnum):
    """Closed enumeration of outbox event types (Section 13.7)."""

    GENERATION_REQUESTED = "generation.requested"
    CLEANUP_REQUESTED = "cleanup.requested"


def sql_values(enum_cls: type[StrEnum]) -> str:
    """Render an enumeration as a SQL ``IN`` list body.

    ``sql_values(ProjectType)`` returns ``'OBJECT', 'SCENE'``. Values are
    developer-controlled constants, never user input, so quoting them is safe.
    """
    return ", ".join(f"'{member.value}'" for member in enum_cls)
