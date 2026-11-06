"""Password, session-token and CSRF primitives.

Traceability: BE-AC-03, BE-AC-04, BE-AC-05; 09_testing.md Section 7.2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_DEV_CSRF_SECRET, Settings
from app.core.security import (
    csrf_token_matches,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    normalize_email,
    verify_password,
)

pytestmark = pytest.mark.unit

SECRET = "unit-test-csrf-secret-0123456789abcdef"


def test_password_hash_is_argon2id_and_verifies() -> None:
    password_hash = hash_password("SecurePassword123")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("SecurePassword123", password_hash) is True
    assert verify_password("WrongPassword123", password_hash) is False


def test_password_hashes_use_unique_salts() -> None:
    assert hash_password("SamePassword123") != hash_password("SamePassword123")


def test_password_verification_rejects_a_malformed_hash() -> None:
    assert verify_password("anything", "not-an-argon2-hash") is False


def test_session_tokens_are_random_and_hash_to_sha256_hex() -> None:
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert len(first) >= 40
    digest = hash_session_token(first)
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    assert hash_session_token(first) == digest


def test_email_normalization() -> None:
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_csrf_token_is_deterministic_and_verifies() -> None:
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    token = generate_csrf_token(secret=SECRET, session_id=session_id, created_at=created_at)

    assert token == generate_csrf_token(secret=SECRET, session_id=session_id, created_at=created_at)
    assert csrf_token_matches(
        secret=SECRET, session_id=session_id, created_at=created_at, token=token
    )


def test_csrf_token_is_bound_to_the_secret() -> None:
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    token = generate_csrf_token(secret=SECRET, session_id=session_id, created_at=created_at)

    assert not csrf_token_matches(
        secret="another-secret",
        session_id=session_id,
        created_at=created_at,
        token=token,
    )


def test_csrf_token_is_bound_to_the_session() -> None:
    created_at = datetime.now(UTC)
    token = generate_csrf_token(secret=SECRET, session_id=uuid.uuid4(), created_at=created_at)

    assert not csrf_token_matches(
        secret=SECRET,
        session_id=uuid.uuid4(),
        created_at=created_at,
        token=token,
    )


def test_csrf_token_is_bound_to_the_session_creation_time() -> None:
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    token = generate_csrf_token(secret=SECRET, session_id=session_id, created_at=created_at)

    assert not csrf_token_matches(
        secret=SECRET,
        session_id=session_id,
        created_at=created_at + timedelta(seconds=1),
        token=token,
    )


def test_csrf_token_rejects_tampering() -> None:
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    token = generate_csrf_token(secret=SECRET, session_id=session_id, created_at=created_at)
    tampered = ("A" if token[0] != "A" else "B") + token[1:]

    assert not csrf_token_matches(
        secret=SECRET, session_id=session_id, created_at=created_at, token=tampered
    )
    assert not csrf_token_matches(
        secret=SECRET, session_id=session_id, created_at=created_at, token=""
    )


def test_production_rejects_the_development_csrf_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            csrf_secret=DEFAULT_DEV_CSRF_SECRET,
            session_cookie_secure=True,
        )


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", csrf_secret="x" * 64, session_cookie_secure=False)


def test_password_policy_bounds_are_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(password_min_length=4)
    with pytest.raises(ValidationError):
        Settings(password_min_length=20, password_max_length=10)
    with pytest.raises(ValidationError):
        Settings(password_max_length=2048)
