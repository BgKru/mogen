"""Scheduled cleanup of expired and revoked authentication sessions.

Sessions are server-managed rows (``05_database_specification.md`` Section 6).
Authentication checks ``expires_at`` on every request, so an expired row is
never accepted, and logout/security actions stamp ``revoked_at``. The rows would
otherwise accumulate for the lifetime of the deployment. The cleanup worker's
beat schedule runs this short, retry-safe job hourly; deleting a row can never
invalidate a live session because only ``expires_at <= now`` and revoked rows
are removed.

The service stays broker-free so it is testable against a scratch database
(``09_testing.md`` Section 7.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.repositories.session_repository import SessionRepository


@dataclass(frozen=True)
class SessionCleanupResult:
    """Counts removed by one cleanup pass."""

    expired_removed: int = 0
    revoked_removed: int = 0

    @property
    def total_removed(self) -> int:
        """Total number of deleted session rows."""
        return self.expired_removed + self.revoked_removed


class SessionCleanupService:
    """Delete terminal session rows in one transaction."""

    def __init__(self, session: Session) -> None:
        self._db = session
        self._sessions = SessionRepository(session)

    def prune(self, *, now: datetime | None = None) -> SessionCleanupResult:
        """Remove expired sessions first, then revoked ones.

        ``now`` is injectable so a test can place rows in the past without
        sleeping. The service owns its transaction, like the other worker
        services; a failure leaves both deletes uncommitted.
        """
        current = now or datetime.now(UTC)
        expired_removed = self._sessions.delete_expired(current)
        revoked_removed = self._sessions.delete_revoked()
        self._db.commit()
        return SessionCleanupResult(
            expired_removed=expired_removed,
            revoked_removed=revoked_removed,
        )
