"""Authentication business logic (04_backend_specification.md Section 8).

The service owns validation, Argon2id hashing, session lifetime, CSRF token
issuance and transaction boundaries. Repositories only read and write rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import (
    csrf_token_matches,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    normalize_email,
    spend_password_verification,
    verify_password,
)
from app.db.models import User, UserSession
from app.repositories import SessionRepository, UserRepository


@dataclass(frozen=True, slots=True)
class AuthContext:
    """An authenticated user and the session that proved it."""

    user: User
    session: UserSession


class AuthService:
    """Registration, login, logout, session validation and CSRF issuance."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._users = UserRepository(session)
        self._sessions = SessionRepository(session)

    def register(self, email: str, password: str) -> tuple[User, str, str]:
        """Create a user and an authenticated session.

        Returns the user, the raw session token and the CSRF token. The raw
        session token is never persisted (Section 8.1).
        """
        normalized_email = normalize_email(email)
        self._validate_password(password)
        if self._users.get_by_email(normalized_email) is not None:
            raise AppError(
                400,
                "EMAIL_ALREADY_REGISTERED",
                "An account with this email already exists.",
            )
        try:
            user = self._users.create(email=normalized_email, password_hash=hash_password(password))
        except IntegrityError as exc:  # concurrent registration for the same email
            self._db.rollback()
            raise AppError(
                400,
                "EMAIL_ALREADY_REGISTERED",
                "An account with this email already exists.",
            ) from exc

        session_token, csrf_token = self._start_session(user)
        self._db.commit()
        return user, session_token, csrf_token

    def login(self, email: str, password: str) -> tuple[User, str, str]:
        """Verify credentials and open a new session.

        Unknown emails and wrong passwords produce the same response and spend
        comparable time, so the endpoint cannot be used to enumerate accounts.
        """
        normalized_email = normalize_email(email)
        user = self._users.get_by_email(normalized_email)
        if user is None:
            spend_password_verification(password)
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password.")
        password_ok = verify_password(password, user.password_hash)
        if not password_ok or not user.is_active:
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password.")

        session_token, csrf_token = self._start_session(user)
        self._db.commit()
        return user, session_token, csrf_token

    def logout(self, auth_session: UserSession) -> None:
        """Revoke the current session."""
        self._sessions.revoke(auth_session, datetime.now(UTC))
        self._db.commit()

    def authenticate(self, raw_session_token: str | None) -> AuthContext:
        """Resolve a raw session cookie into an authenticated user.

        Missing, unknown, revoked, expired and inactive-account sessions all
        fail with HTTP 401 (api_contracts Section 3.5).
        """
        if not raw_session_token:
            raise AppError(401, "UNAUTHORIZED", "Authentication is required.")

        auth_session = self._sessions.get_by_token_hash(hash_session_token(raw_session_token))
        if auth_session is None:
            raise AppError(401, "UNAUTHORIZED", "Authentication is required.")

        if auth_session.revoked_at is not None or auth_session.expires_at <= datetime.now(UTC):
            raise AppError(401, "SESSION_EXPIRED", "The session is invalid or has expired.")

        user = self._users.get(auth_session.user_id)
        if user is None or not user.is_active:
            raise AppError(401, "UNAUTHORIZED", "Authentication is required.")

        return AuthContext(user=user, session=auth_session)

    def issue_csrf_token(self, auth_session: UserSession) -> str:
        """Return the signed CSRF token bound to this session."""
        return generate_csrf_token(
            secret=self._settings.csrf_secret,
            session_id=auth_session.id,
            created_at=auth_session.created_at,
        )

    def csrf_token_is_valid(self, auth_session: UserSession, token: str) -> bool:
        """Return whether a token is signed for this exact session."""
        if not token:
            return False
        return csrf_token_matches(
            secret=self._settings.csrf_secret,
            session_id=auth_session.id,
            created_at=auth_session.created_at,
            token=token,
        )

    def _start_session(self, user: User) -> tuple[str, str]:
        """Create a session row and return its raw token and CSRF token."""
        now = datetime.now(UTC)
        session_token = generate_session_token()
        auth_session = self._sessions.create(
            user_id=user.id,
            token_hash=hash_session_token(session_token),
            expires_at=now + timedelta(hours=self._settings.session_ttl_hours),
            last_used_at=now,
        )
        csrf_token = generate_csrf_token(
            secret=self._settings.csrf_secret,
            session_id=auth_session.id,
            created_at=auth_session.created_at,
        )
        return session_token, csrf_token

    def _validate_password(self, password: str) -> None:
        """Enforce the configurable password policy (Section 17.2)."""
        minimum = self._settings.password_min_length
        maximum = self._settings.password_max_length
        if len(password) < minimum:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "The request is invalid.",
                details=[
                    {
                        "field": "password",
                        "code": "TOO_SHORT",
                        "message": f"Password must be at least {minimum} characters.",
                    }
                ],
            )
        if len(password) > maximum:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "The request is invalid.",
                details=[
                    {
                        "field": "password",
                        "code": "TOO_LONG",
                        "message": f"Password must be at most {maximum} characters.",
                    }
                ],
            )
