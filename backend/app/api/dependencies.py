"""FastAPI dependencies shared by API endpoints."""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    csrf_token_matches,
)
from app.db.models import User
from app.db.session import session_scope
from app.repositories import (
    CleanupJobRepository,
    ImageRepository,
    OutboxRepository,
    ProjectRepository,
    ResultRepository,
    SessionRepository,
    TaskRepository,
    UserRepository,
)
from app.services.auth_service import AuthContext, AuthService
from app.services.generation_service import GenerationService
from app.services.image_service import ImageService
from app.services.project_service import ProjectService
from app.storage import LocalStorage, StorageBackend


def get_settings(request: Request) -> Settings:
    """Return the settings bound to the running application."""
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """Provide a database session scoped to the request."""
    with session_scope(request.app.state.session_factory) as session:
        yield session


def get_user_repository(db: Annotated[Session, Depends(get_db)]) -> UserRepository:
    """Provide a user repository bound to the request session."""
    return UserRepository(db)


def get_session_repository(
    db: Annotated[Session, Depends(get_db)],
) -> SessionRepository:
    """Provide a session repository bound to the request session."""
    return SessionRepository(db)


def get_project_repository(
    db: Annotated[Session, Depends(get_db)],
) -> ProjectRepository:
    """Provide a project repository bound to the request session."""
    return ProjectRepository(db)


def get_image_repository(db: Annotated[Session, Depends(get_db)]) -> ImageRepository:
    """Provide an image repository bound to the request session."""
    return ImageRepository(db)


def get_task_repository(db: Annotated[Session, Depends(get_db)]) -> TaskRepository:
    """Provide a generation task repository bound to the request session."""
    return TaskRepository(db)


def get_result_repository(db: Annotated[Session, Depends(get_db)]) -> ResultRepository:
    """Provide a generation result repository bound to the request session."""
    return ResultRepository(db)


def get_outbox_repository(db: Annotated[Session, Depends(get_db)]) -> OutboxRepository:
    """Provide an outbox repository bound to the request session."""
    return OutboxRepository(db)


def get_cleanup_job_repository(
    db: Annotated[Session, Depends(get_db)],
) -> CleanupJobRepository:
    """Provide a cleanup job repository bound to the request session."""
    return CleanupJobRepository(db)


def get_auth_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    """Provide the authentication service bound to the request session."""
    return AuthService(db, settings)


def get_project_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProjectService:
    """Provide the project service bound to the request session."""
    return ProjectService(db, settings)


def get_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StorageBackend:
    """Provide the configured storage backend.

    The backend is stateless apart from its resolved root, so a per-request
    instance is cheap and tests can override this dependency with a temporary
    storage root (09_testing.md Section 7.8).
    """
    return LocalStorage(settings.storage_root)


def get_image_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
) -> ImageService:
    """Provide the image service bound to the request session and storage."""
    return ImageService(db, settings, storage)


def get_generation_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GenerationService:
    """Provide the generation service bound to the request session."""
    return GenerationService(db, settings)


def get_current_auth(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthContext:
    """Authenticate the session cookie, or fail with HTTP 401."""
    return service.authenticate(request.cookies.get(SESSION_COOKIE_NAME))


def get_current_user(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> User:
    """Provide the authenticated user."""
    return auth.user


def require_allowed_origin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Reject a state-changing request whose Origin is not allowed.

    Requests without an Origin header (non-browser clients) are allowed here;
    CSRF token validation still protects authenticated operations.
    """
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise AppError(
            403,
            "CSRF_VALIDATION_FAILED",
            "The request origin is not allowed.",
        )


def require_csrf(
    request: Request,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Validate the Origin, the double-submit pair and the session-bound signature."""
    require_allowed_origin(request, settings)

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise AppError(403, "CSRF_VALIDATION_FAILED", "CSRF validation failed.")

    if not csrf_token_matches(
        secret=settings.csrf_secret,
        session_id=auth.session.id,
        created_at=auth.session.created_at,
        token=cookie_token,
    ):
        raise AppError(403, "CSRF_VALIDATION_FAILED", "CSRF validation failed.")
