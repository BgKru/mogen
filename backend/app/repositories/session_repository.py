"""Repository for authentication sessions (05_database_specification.md Section 6)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select

from app.db.models import UserSession
from app.repositories.base import BaseRepository


class SessionRepository(BaseRepository[UserSession]):
    """Database access for server-managed sessions.

    Only token hashes are stored; the raw token never reaches this layer
    (Section 6).
    """

    model = UserSession

    def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        last_used_at: datetime | None = None,
    ) -> UserSession:
        """Insert a session for an existing user."""
        return self.add(
            UserSession(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                last_used_at=last_used_at,
            )
        )

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        """Return the session with this token hash, or ``None``."""
        return self.session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))

    def list_for_user(self, user_id: uuid.UUID) -> Sequence[UserSession]:
        """Return every session belonging to a user, newest first."""
        statement = (
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc(), UserSession.id.desc())
        )
        return self.session.scalars(statement).all()

    def mark_used(self, session: UserSession, used_at: datetime) -> None:
        """Record the last time a session was presented."""
        session.last_used_at = used_at
        self.session.flush()

    def revoke(self, session: UserSession, revoked_at: datetime) -> None:
        """Mark a session as revoked."""
        session.revoked_at = revoked_at
        self.session.flush()

    def delete_expired(self, now: datetime) -> int:
        """Delete sessions that expired at or before ``now``; return the count."""
        result = self.session.execute(
            delete(UserSession)
            .where(UserSession.expires_at <= now)
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        return result.rowcount or 0

    def delete_revoked(self) -> int:
        """Delete every revoked session; return the count."""
        result = self.session.execute(
            delete(UserSession)
            .where(UserSession.revoked_at.is_not(None))
            .execution_options(synchronize_session=False)
        )
        self.session.flush()
        return result.rowcount or 0
