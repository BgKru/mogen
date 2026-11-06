"""SQLAlchemy models for every persistent entity.

Importing this package registers all models with ``Base.metadata`` so that
Alembic autogenerate and the repository layer see the complete schema.
The module order below follows the dependency order of
05_database_specification.md Section 20.3.
"""

from app.db.models.enums import (
    CleanupStatus,
    CleanupTargetType,
    ImageMimeType,
    OutboxEventType,
    OutboxStatus,
    ProjectStatus,
    ProjectType,
    ResultFormat,
    TaskStatus,
    TaskType,
    sql_values,
)
from app.db.models.generation_result import GenerationResult
from app.db.models.generation_task import GenerationTask
from app.db.models.generation_task_image import GenerationTaskImage
from app.db.models.outbox_message import OutboxMessage
from app.db.models.project import Project
from app.db.models.project_image import ProjectImage
from app.db.models.storage_cleanup_job import StorageCleanupJob
from app.db.models.user import User
from app.db.models.user_session import UserSession

__all__ = [
    "CleanupStatus",
    "CleanupTargetType",
    "GenerationResult",
    "GenerationTask",
    "GenerationTaskImage",
    "ImageMimeType",
    "OutboxEventType",
    "OutboxMessage",
    "OutboxStatus",
    "Project",
    "ProjectImage",
    "ProjectStatus",
    "ProjectType",
    "ResultFormat",
    "StorageCleanupJob",
    "TaskStatus",
    "TaskType",
    "User",
    "UserSession",
    "sql_values",
]
