"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Settings that do not depend on the local environment."""
    return Settings(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://app:change_me@localhost:5432/app",
        redis_url="redis://localhost:6379/0",
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Test client with the application lifespan running."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
