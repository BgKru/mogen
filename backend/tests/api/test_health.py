"""Health endpoint behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings


def test_liveness_reports_ok(client: TestClient, settings: Settings) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == settings.version


def test_readiness_reports_unavailable_database(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.database_is_available", lambda engine: False)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_readiness_reports_ready_database(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.database_is_available", lambda engine: True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_dependency_report_is_degraded_without_redis(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.database_is_available", lambda engine: True)
    monkeypatch.setattr("app.api.health._redis_is_available", lambda url: False)

    response = client.get("/health/dependencies")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "unavailable"
