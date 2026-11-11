"""API behaviour of the authentication rate limiter.

Traceability: ``TEST-AC-03`` (unsuccessful request scenarios, including the
documented ``429``), ``TEST-AC-04`` (authentication abuse). The limiter is
disabled for ordinary API tests so unrelated suites can register many users;
these cases enable it per client.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PASSWORD = "SecurePassword123"


def register_payload(stem: str) -> dict[str, str]:
    """A unique valid registration body."""
    return {"email": f"{stem}@example.com", "password": PASSWORD}


def login_payload(email: str) -> dict[str, str]:
    """A login body for an arbitrary address."""
    return {"email": email, "password": PASSWORD}


def test_login_is_rate_limited_with_the_documented_envelope(api_client_factory) -> None:
    email = "limited-login@example.com"
    seed = api_client_factory(auth_rate_limit_enabled=False)
    assert (
        seed.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "SecurePassword123"},
        ).status_code
        == 201
    )

    limited = api_client_factory(
        auth_rate_limit_enabled=True, auth_rate_limit_attempts=2, auth_rate_limit_window_seconds=60
    )
    bad_credentials = {"email": email, "password": "WrongPassword123"}

    assert limited.post("/api/v1/auth/login", json=bad_credentials).status_code == 401
    assert limited.post("/api/v1/auth/login", json=bad_credentials).status_code == 401

    response = limited.post("/api/v1/auth/login", json=bad_credentials)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) >= 1


def test_registration_is_rate_limited(api_client_factory) -> None:
    client = api_client_factory(
        auth_rate_limit_enabled=True, auth_rate_limit_attempts=2, auth_rate_limit_window_seconds=60
    )

    assert client.post("/api/v1/auth/register", json=register_payload("rl-1")).status_code == 201
    assert client.post("/api/v1/auth/register", json=register_payload("rl-2")).status_code == 201

    response = client.post("/api/v1/auth/register", json=register_payload("rl-3"))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_login_and_registration_have_independent_budgets(api_client_factory) -> None:
    client = api_client_factory(
        auth_rate_limit_enabled=True, auth_rate_limit_attempts=1, auth_rate_limit_window_seconds=60
    )

    assert (
        client.post("/api/v1/auth/register", json=register_payload("budget-1")).status_code == 201
    )
    assert (
        client.post("/api/v1/auth/register", json=register_payload("budget-2")).status_code == 429
    )

    # The registration budget is exhausted, but a login attempt still reaches
    # the credential check (401 for the unknown address) instead of 429.
    response = client.post("/api/v1/auth/login", json=login_payload("unknown@example.com"))

    assert response.status_code == 401


def test_the_limiter_can_be_disabled(api_client_factory) -> None:
    client = api_client_factory(
        auth_rate_limit_enabled=False,
        auth_rate_limit_attempts=1,
        auth_rate_limit_window_seconds=60,
    )

    for index in range(3):
        response = client.post(
            "/api/v1/auth/register",
            json=register_payload(f"disabled-{index}"),
        )
        assert response.status_code == 201, response.text
