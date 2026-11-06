"""Authentication API tests against PostgreSQL.

Traceability: BE-AC-03, BE-AC-04, BE-AC-05, BE-AC-06 (session-level);
api_contracts.md Sections 3 and 6; 09_testing.md Sections 7.2 and 15.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.security import generate_session_token, hash_password, hash_session_token
from app.db.models import User, UserSession
from app.repositories import SessionRepository, UserRepository

pytestmark = [pytest.mark.integration, pytest.mark.api]

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
CSRF_URL = "/api/v1/auth/csrf"
PASSWORD = "SecurePassword123"
ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture
def auth_client(api_client: TestClient) -> TestClient:
    """The shared database-backed client, used unauthenticated here."""
    return api_client


def _register(
    client: TestClient,
    *,
    email: str = "user@example.com",
    password: str = PASSWORD,
    headers: dict[str, str] | None = None,
):
    return client.post(
        REGISTER_URL,
        json={"email": email, "password": password},
        headers=headers or {},
    )


def _login(
    client: TestClient,
    *,
    email: str = "user@example.com",
    password: str = PASSWORD,
    headers: dict[str, str] | None = None,
):
    return client.post(
        LOGIN_URL,
        json={"email": email, "password": password},
        headers=headers or {},
    )


def _set_cookie_header(response, name: str) -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"no Set-Cookie header for {name}: {response.headers}")


def _insert_session(
    inspection_session, *, email: str, expired: bool = False, revoked: bool = False
) -> str:
    users = UserRepository(inspection_session)
    sessions = SessionRepository(inspection_session)
    user = users.create(email=email, password_hash=hash_password(PASSWORD))
    token = generate_session_token()
    now = datetime.now(UTC)
    auth_session = sessions.create(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=now + timedelta(minutes=1),
    )
    if expired:
        inspection_session.execute(
            update(UserSession)
            .where(UserSession.id == auth_session.id)
            .values(
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
        )
    if revoked:
        sessions.revoke(auth_session, now)
    inspection_session.commit()
    return token


# --- registration (api_contracts 6.1) -------------------------------------


def test_register_creates_user_and_authenticated_session(
    auth_client: TestClient, inspection_session
) -> None:
    response = _register(auth_client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"user"}
    assert set(body["user"]) == {"id", "email", "created_at"}
    assert body["user"]["email"] == "user@example.com"
    assert "password" not in response.text
    assert "$argon2" not in response.text

    raw_session = auth_client.cookies.get("session")
    assert raw_session
    assert auth_client.cookies.get("csrf_token")

    session_header = _set_cookie_header(response, "session")
    csrf_header = _set_cookie_header(response, "csrf_token")
    assert "httponly" in session_header.lower()
    assert "httponly" not in csrf_header.lower()
    assert "samesite=lax" in session_header.lower()
    assert "path=/" in session_header.lower()
    assert "secure" not in session_header.lower()

    user = inspection_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    stored = inspection_session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(raw_session))
    )
    assert stored is not None
    assert stored.user_id == user.id
    assert stored.expires_at > datetime.now(UTC)
    assert stored.revoked_at is None


def test_register_normalizes_the_email(auth_client: TestClient, inspection_session) -> None:
    response = _register(auth_client, email="Mixed@Example.COM")

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "mixed@example.com"
    assert (
        inspection_session.scalar(
            select(func.count()).select_from(User).where(User.email == "mixed@example.com")
        )
        == 1
    )


def test_register_rejects_a_duplicate_email(auth_client: TestClient) -> None:
    _register(auth_client)

    response = _register(auth_client)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_rejects_invalid_email_and_password(auth_client: TestClient) -> None:
    invalid_email = auth_client.post(
        REGISTER_URL, json={"email": "not-an-email", "password": PASSWORD}
    )
    short_password = _register(auth_client, email="short@example.com", password="short")

    assert invalid_email.status_code == 422
    assert invalid_email.json()["error"]["code"] == "VALIDATION_ERROR"
    assert short_password.status_code == 422
    details = short_password.json()["error"]["details"]
    assert details[0]["field"] == "password"
    assert details[0]["code"] == "TOO_SHORT"


def test_register_rejects_an_overlong_password(auth_client: TestClient) -> None:
    response = _register(auth_client, password="x" * 129)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["code"] == "TOO_LONG"


# --- login and current user (api_contracts 6.2, 6.4) ----------------------


def test_login_opens_a_new_session(auth_client: TestClient) -> None:
    _register(auth_client)
    auth_client.cookies.clear()

    response = _login(auth_client)

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "user@example.com"
    assert auth_client.cookies.get("session")
    assert auth_client.get(ME_URL).status_code == 200


def test_login_uses_a_generic_error_for_bad_credentials(auth_client: TestClient) -> None:
    _register(auth_client)
    auth_client.cookies.clear()

    wrong_password = _login(auth_client, password="WrongPassword123")
    unknown_email = _login(auth_client, email="missing@example.com")

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


def test_login_rejects_an_inactive_user(auth_client: TestClient, inspection_session) -> None:
    _register(auth_client)
    auth_client.cookies.clear()
    user = inspection_session.scalar(select(User).where(User.email == "user@example.com"))
    user.is_active = False
    inspection_session.commit()

    response = _login(auth_client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_me_requires_a_valid_session(auth_client: TestClient) -> None:
    unauthenticated = auth_client.get(ME_URL)
    garbage = auth_client.get(ME_URL, headers={"Cookie": "session=not-a-real-token"})

    assert unauthenticated.status_code == 401
    assert garbage.status_code == 401
    assert garbage.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_session_is_rejected(auth_client: TestClient, inspection_session) -> None:
    token = _insert_session(inspection_session, email="expired@example.com", expired=True)

    response = auth_client.get(ME_URL, headers={"Cookie": f"session={token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_revoked_session_is_rejected(auth_client: TestClient, inspection_session) -> None:
    token = _insert_session(inspection_session, email="revoked@example.com", revoked=True)

    response = auth_client.get(ME_URL, headers={"Cookie": f"session={token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_deactivated_user_session_is_rejected(auth_client: TestClient, inspection_session) -> None:
    _register(auth_client)
    raw_session = auth_client.cookies.get("session")
    user = inspection_session.scalar(select(User).where(User.email == "user@example.com"))
    user.is_active = False
    inspection_session.commit()
    auth_client.cookies.clear()

    response = auth_client.get(ME_URL, headers={"Cookie": f"session={raw_session}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_csrf_endpoint_reissues_an_invalid_cookie(auth_client: TestClient) -> None:
    _register(auth_client)
    raw_session = auth_client.cookies.get("session")
    auth_client.cookies.clear()

    response = auth_client.get(
        CSRF_URL,
        headers={"Cookie": f"session={raw_session}; csrf_token=not-a-valid-token"},
    )

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert token != "not-a-valid-token"
    assert auth_client.cookies.get("csrf_token") == token


# --- CSRF and logout (api_contracts 3.3, 6.3, 6.5) ------------------------


def test_csrf_endpoint_returns_the_session_bound_token(auth_client: TestClient) -> None:
    _register(auth_client)
    cookie_token = auth_client.cookies.get("csrf_token")

    response = auth_client.get(CSRF_URL)

    assert response.status_code == 200
    assert response.json()["csrf_token"] == cookie_token
    assert _set_cookie_header(response, "csrf_token").startswith("csrf_token=")


def test_csrf_endpoint_requires_authentication(auth_client: TestClient) -> None:
    response = auth_client.get(CSRF_URL)

    assert response.status_code == 401


def test_logout_requires_a_matching_csrf_token(auth_client: TestClient) -> None:
    _register(auth_client)
    token = auth_client.cookies.get("csrf_token")

    missing = auth_client.post(LOGOUT_URL)
    mismatched = auth_client.post(LOGOUT_URL, headers={"X-CSRF-Token": "wrong"})
    tampered = auth_client.post(LOGOUT_URL, headers={"X-CSRF-Token": f"{token}x"})

    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert tampered.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_logout_revokes_the_session_and_clears_cookies(
    auth_client: TestClient, inspection_session
) -> None:
    _register(auth_client)
    csrf_token = auth_client.cookies.get("csrf_token")
    raw_session = auth_client.cookies.get("session")

    response = auth_client.post(LOGOUT_URL, headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 204
    assert auth_client.cookies.get("session") in (None, "")
    assert auth_client.cookies.get("csrf_token") in (None, "")
    stored = inspection_session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(raw_session))
    )
    assert stored is not None
    assert stored.revoked_at is not None
    assert auth_client.get(ME_URL).status_code == 401


def test_previous_session_csrf_token_is_rejected_after_login(
    auth_client: TestClient,
) -> None:
    _register(auth_client)
    previous_token = auth_client.cookies.get("csrf_token")
    _login(auth_client)
    new_token = auth_client.cookies.get("csrf_token")

    assert new_token != previous_token
    new_session = auth_client.cookies.get("session")
    auth_client.cookies.clear()

    response = auth_client.post(
        LOGOUT_URL,
        headers={
            "X-CSRF-Token": previous_token,
            "Cookie": f"session={new_session}; csrf_token={previous_token}",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


# --- origin validation (api_contracts 3.3) --------------------------------


def test_register_rejects_a_disallowed_origin(auth_client: TestClient) -> None:
    response = _register(auth_client, headers={"Origin": "http://evil.example"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert (
        auth_client.post(
            REGISTER_URL,
            json={"email": "user@example.com", "password": PASSWORD},
            headers={"Origin": ALLOWED_ORIGIN},
        ).status_code
        == 201
    )


def test_login_rejects_a_disallowed_origin(auth_client: TestClient) -> None:
    _register(auth_client)
    auth_client.cookies.clear()

    rejected = _login(auth_client, headers={"Origin": "http://evil.example"})
    accepted = _login(auth_client, headers={"Origin": ALLOWED_ORIGIN})

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert accepted.status_code == 200
