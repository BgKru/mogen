"""Repository dependency wiring for FastAPI endpoints.

Traceability: TEST-AC-01; 09_testing.md Section 7.8 (dependency overrides).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import dependencies
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

pytestmark = pytest.mark.unit

REPOSITORY_PROVIDERS = [
    (dependencies.get_user_repository, UserRepository),
    (dependencies.get_session_repository, SessionRepository),
    (dependencies.get_project_repository, ProjectRepository),
    (dependencies.get_image_repository, ImageRepository),
    (dependencies.get_task_repository, TaskRepository),
    (dependencies.get_result_repository, ResultRepository),
    (dependencies.get_outbox_repository, OutboxRepository),
    (dependencies.get_cleanup_job_repository, CleanupJobRepository),
]


@pytest.mark.parametrize(("provider", "repository_type"), REPOSITORY_PROVIDERS)
def test_repository_provider_binds_the_request_session(provider, repository_type) -> None:
    session = Session()
    try:
        repository = provider(session)

        assert isinstance(repository, repository_type)
        assert repository.session is session
    finally:
        session.close()


def test_fastapi_resolves_a_repository_through_dependency_overrides() -> None:
    """A dependency override replaces ``get_db`` exactly as API tests will."""
    app = FastAPI()

    @app.get("/probe")
    def probe(
        repository: Annotated[UserRepository, Depends(dependencies.get_user_repository)],
    ) -> dict[str, str]:
        return {"repository": type(repository).__name__}

    session = Session()
    app.dependency_overrides[dependencies.get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/probe")
    finally:
        session.close()

    assert response.status_code == 200
    assert response.json() == {"repository": "UserRepository"}
