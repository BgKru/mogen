"""Password hashing, session tokens and signed CSRF tokens.

Passwords are hashed with Argon2id (04_backend_specification.md Section 17.2).
Session tokens are opaque 256-bit values and only their SHA-256 hash is stored
(05_database_specification.md Section 6).

The CSRF token is a stateless HMAC over the session identifier and its creation
time. It is therefore bound to one session, stays valid for exactly the session
lifetime, and needs no CSRF state in the database (api_contracts Section 3.3).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_COOKIE_NAME = "session"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_TOKEN_BYTES = 32


@lru_cache(maxsize=1)
def _password_hasher() -> PasswordHasher:
    """Return the process-wide Argon2id hasher with library-default parameters."""
    return PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _password_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether ``password`` matches the stored Argon2id hash."""
    try:
        return _password_hasher().verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def spend_password_verification(password: str) -> None:
    """Burn one hashing cycle when an account does not exist.

    This keeps login timing from disclosing whether an email is registered
    (04_backend_specification.md Section 8.3).
    """
    _password_hasher().hash(password)


def normalize_email(email: str) -> str:
    """Normalize an email for storage and lookup (Section 8.2, 05 Section 5.2)."""
    return email.strip().lower()


def generate_session_token() -> str:
    """Generate a cryptographically random opaque session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in ``user_sessions.token_hash``."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token(*, secret: str, session_id: uuid.UUID, created_at: datetime) -> str:
    """Derive the signed, session-bound CSRF token.

    The token carries no readable payload and is deterministic for one session,
    so reissuing it never creates a second valid token. ``created_at`` is
    normalized to UTC so the token does not change with the database session
    time zone or a process restart.
    """
    message = f"csrf:{session_id}:{created_at.astimezone(UTC).isoformat()}".encode()
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def csrf_token_matches(
    *,
    secret: str,
    session_id: uuid.UUID,
    created_at: datetime,
    token: str,
) -> bool:
    """Verify a CSRF token's signature and session binding in constant time."""
    expected = generate_csrf_token(secret=secret, session_id=session_id, created_at=created_at)
    return hmac.compare_digest(expected, token)
