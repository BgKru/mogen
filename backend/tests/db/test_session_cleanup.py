"""Scheduled removal of expired and revoked sessions.

Traceability: ``BE-AC-05`` (session lifecycle), ``DB-AC-05`` (session rows),
``TEST-AC-05``, and the Phase 9 decision to schedule the session cleanup that
Phase 8 left open. The broker-free entry point is exercised against the scratch
database; the Celery route and beat entry are asserted by
``tests/unit/test_celery_config.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import User, UserSession
from app.tasks.cleanup_tasks import run_session_cleanup

pytestmark = pytest.mark.integration


def _seed_sessions(session_factory) -> None:
    """Create one active, one expired and one revoked session."""
    now = datetime.now(UTC)
    created = now - timedelta(days=2)
    with session_factory() as session:
        user = User(email="sessions@example.com", password_hash="argon2id-placeholder")
        session.add(user)
        session.flush()
        session.add_all(
            [
                UserSession(
                    user_id=user.id,
                    token_hash="a" * 64,
                    expires_at=now + timedelta(hours=1),
                    created_at=created,
                ),
                UserSession(
                    user_id=user.id,
                    token_hash="b" * 64,
                    expires_at=now - timedelta(hours=1),
                    created_at=created,
                ),
                UserSession(
                    user_id=user.id,
                    token_hash="c" * 64,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=now - timedelta(minutes=5),
                    created_at=created,
                ),
            ]
        )
        session.commit()


def test_only_expired_and_revoked_sessions_are_removed(clean_database, session_factory) -> None:
    _seed_sessions(session_factory)

    result = run_session_cleanup(session_factory=session_factory)

    assert result.expired_removed == 1
    assert result.revoked_removed == 1
    assert result.total_removed == 2

    with session_factory() as session:
        remaining = session.scalars(select(UserSession)).all()

    assert len(remaining) == 1
    assert remaining[0].token_hash == "a" * 64


def test_a_second_cleanup_is_a_no_op(clean_database, session_factory) -> None:
    _seed_sessions(session_factory)
    run_session_cleanup(session_factory=session_factory)

    result = run_session_cleanup(session_factory=session_factory)

    assert result.expired_removed == 0
    assert result.revoked_removed == 0


def test_an_active_session_is_never_touched(clean_database, session_factory) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        user = User(email="active-only@example.com", password_hash="argon2id-placeholder")
        session.add(user)
        session.flush()
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="d" * 64,
                expires_at=now + timedelta(minutes=1),
                last_used_at=now,
            )
        )
        session.commit()

    result = run_session_cleanup(session_factory=session_factory)

    assert result.total_removed == 0
    with session_factory() as session:
        assert session.scalar(select(UserSession)) is not None
