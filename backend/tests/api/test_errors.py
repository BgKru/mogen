"""Error envelope and request correlation behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_unknown_route_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"]


def test_request_id_is_echoed_in_header_and_error(client: TestClient) -> None:
    response = client.get("/does-not-exist", headers={"X-Request-ID": "test-request-1"})

    assert response.headers["X-Request-ID"] == "test-request-1"
    assert response.json()["error"]["request_id"] == "test-request-1"


def test_field_validation_errors_use_the_documented_detail_schema(
    client: TestClient,
) -> None:
    """API-AC-15 and api_contracts 12.2: details carry field, code and message."""
    response = client.post("/api/v1/auth/register", json={"email": "user@example.com"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    detail = body["error"]["details"][0]
    assert set(detail) == {"field", "code", "message"}
    assert detail["field"] == "password"
    assert detail["code"] == "MISSING"


def test_unhandled_error_does_not_leak_details(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        message = "internal secret detail"
        raise RuntimeError(message)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "internal secret detail" not in response.text
