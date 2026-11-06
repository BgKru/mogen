"""Repository layer.

Repositories isolate SQL from services (05_database_specification.md Section
19.3) and never commit; the service owns the transaction boundary.
"""

from app.repositories.base import BaseRepository
from app.repositories.cleanup_job_repository import CleanupJobRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.outbox_repository import OutboxRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "CleanupJobRepository",
    "ImageRepository",
    "OutboxRepository",
    "ProjectRepository",
    "ResultRepository",
    "SessionRepository",
    "TaskRepository",
    "UserRepository",
]
