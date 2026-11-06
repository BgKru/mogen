"""Transactional Outbox dispatcher against PostgreSQL (05 Section 13).

Traceability: DB-AC-16 (transaction boundaries), DB-AC-20 (durable dispatch,
expired-lock recovery, failed publications return to PENDING), INF-AC-21
(dispatcher independence), INF-AC-24 (Redis outage recoverability), TEST-AC-08
(outbox reliability), roadmap 4.4 and 4.9.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import OutboxMessage
from app.services.outbox_service import PermanentDispatchError, dispatch_pending

pytestmark = [pytest.mark.integration]

OBJECT_TASK_PAYLOAD = {
    "event_id": str(uuid.uuid4()),
    "event_type": "generation.requested",
    "schema_version": 1,
    "task_id": str(uuid.uuid4()),
    "project_id": str(uuid.uuid4()),
    "task_type": "OBJECT",
}


@pytest.fixture
def dispatcher_settings() -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        outbox_batch_size=10,
        outbox_poll_interval_seconds=1,
        outbox_retry_base_seconds=2,
        outbox_retry_max_seconds=300,
        outbox_max_attempts=3,
        outbox_lock_timeout_seconds=60,
    )


class RecordingPublisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.published: list[uuid.UUID] = []
        self.error = error

    def publish(self, message: OutboxMessage) -> None:
        if self.error is not None:
            raise self.error
        self.published.append(message.id)


def _add_message(db_session: Session, **overrides) -> OutboxMessage:
    now = datetime.now(UTC)
    values = {
        "event_type": "generation.requested",
        "aggregate_type": "GenerationTask",
        "aggregate_id": uuid.uuid4(),
        "payload": dict(OBJECT_TASK_PAYLOAD),
        "schema_version": 1,
        "status": "PENDING",
        "attempts": 0,
        "available_at": now - timedelta(minutes=1),
        "locked_at": None,
        "locked_by": None,
    }
    values.update(overrides)
    message = OutboxMessage(**values)
    db_session.add(message)
    db_session.commit()
    return message


def _reload(session_factory: sessionmaker[Session], message_id: uuid.UUID) -> OutboxMessage:
    with session_factory() as session:
        message = session.get(OutboxMessage, message_id)
        assert message is not None
        return message


def _dispatch(
    session_factory: sessionmaker[Session],
    settings: Settings,
    publisher,
    *,
    now: datetime | None = None,
    rng=None,
):
    with session_factory() as session:
        return dispatch_pending(
            session,
            settings=settings,
            publisher=publisher,
            dispatcher_id="dispatcher-test",
            now=now,
            rng=rng or (lambda low, high: high),
        )


def test_a_pending_message_is_claimed_published_and_recorded(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    message = _add_message(db_session)
    publisher = RecordingPublisher()

    summary = _dispatch(session_factory, dispatcher_settings, publisher)

    assert (summary.claimed, summary.published, summary.retried, summary.failed) == (1, 1, 0, 0)
    assert publisher.published == [message.id]
    reloaded = _reload(session_factory, message.id)
    assert reloaded.status == "PUBLISHED"
    assert reloaded.published_at is not None
    assert reloaded.attempts == 1
    assert reloaded.locked_at is None
    assert reloaded.locked_by is None


def test_a_future_message_is_not_claimed(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    now = datetime.now(UTC)
    _add_message(db_session, available_at=now + timedelta(hours=1))
    publisher = RecordingPublisher()

    summary = _dispatch(session_factory, dispatcher_settings, publisher, now=now)

    assert summary.claimed == 0
    assert publisher.published == []


def test_a_transient_failure_returns_the_message_to_pending(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    now = datetime.now(UTC)
    message = _add_message(db_session)
    publisher = RecordingPublisher(ConnectionError("redis is unavailable"))

    summary = _dispatch(session_factory, dispatcher_settings, publisher, now=now)

    assert summary.retried == 1
    assert summary.failed == 0
    reloaded = _reload(session_factory, message.id)
    assert reloaded.status == "PENDING"
    assert reloaded.attempts == 1
    assert reloaded.available_at >= now + timedelta(seconds=2)
    assert reloaded.last_error == "redis is unavailable"
    assert reloaded.published_at is None


def test_a_retry_wait_is_not_claimed_immediately(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    now = datetime.now(UTC)
    _add_message(db_session)
    publisher = RecordingPublisher(ConnectionError("redis is unavailable"))
    _dispatch(session_factory, dispatcher_settings, publisher, now=now)

    summary = _dispatch(session_factory, dispatcher_settings, RecordingPublisher(), now=now)

    assert summary.claimed == 0


def test_the_retry_budget_is_bounded(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    message = _add_message(db_session, attempts=dispatcher_settings.outbox_max_attempts - 1)
    publisher = RecordingPublisher(ConnectionError("redis is unavailable"))

    summary = _dispatch(session_factory, dispatcher_settings, publisher)

    assert summary.failed == 1
    assert summary.retried == 0
    reloaded = _reload(session_factory, message.id)
    assert reloaded.status == "FAILED"
    assert reloaded.attempts == dispatcher_settings.outbox_max_attempts


def test_a_permanent_failure_is_not_retried(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    message = _add_message(db_session)
    publisher = RecordingPublisher(PermanentDispatchError("unsupported schema_version"))

    summary = _dispatch(session_factory, dispatcher_settings, publisher)

    assert summary.failed == 1
    reloaded = _reload(session_factory, message.id)
    assert reloaded.status == "FAILED"
    assert reloaded.attempts == 1


def test_an_expired_dispatcher_lock_is_released_and_reclaimed(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    now = datetime.now(UTC)
    message = _add_message(
        db_session,
        status="PROCESSING",
        attempts=1,
        locked_at=now - timedelta(seconds=120),
        locked_by="dead-dispatcher",
        available_at=now - timedelta(minutes=5),
    )
    publisher = RecordingPublisher()

    summary = _dispatch(session_factory, dispatcher_settings, publisher, now=now)

    assert summary.expired_locks == 1
    assert summary.published == 1
    reloaded = _reload(session_factory, message.id)
    assert reloaded.status == "PUBLISHED"
    assert reloaded.attempts == 2


def test_a_message_is_published_only_once(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    _add_message(db_session)
    publisher = RecordingPublisher()

    _dispatch(session_factory, dispatcher_settings, publisher)
    second = _dispatch(session_factory, dispatcher_settings, publisher)

    assert len(publisher.published) == 1
    assert second.claimed == 0


def test_another_dispatchers_live_claim_is_not_stolen(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    now = datetime.now(UTC)
    _add_message(
        db_session,
        status="PROCESSING",
        attempts=1,
        locked_at=now,
        locked_by="live-dispatcher",
    )

    summary = _dispatch(session_factory, dispatcher_settings, RecordingPublisher(), now=now)

    assert summary.expired_locks == 0
    assert summary.claimed == 0


class _ClaimStatePublisher:
    """Publishes while observing the committed claim from another connection."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.status: str | None = None
        self.locked_by: str | None = None
        self.attempts: int | None = None
        self.lock_error: Exception | None = None

    def publish(self, message: OutboxMessage) -> None:
        with self._session_factory() as session:
            observed = session.get(OutboxMessage, message.id)
            assert observed is not None
            self.status = observed.status
            self.locked_by = observed.locked_by
            self.attempts = observed.attempts
            try:
                session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.id == message.id)
                    .with_for_update(nowait=True)
                ).scalar_one()
            except Exception as exc:  # noqa: BLE001 - the probe records the lock
                self.lock_error = exc
            finally:
                session.rollback()


def test_the_claim_is_committed_before_publishing(
    db_session: Session,
    session_factory: sessionmaker[Session],
    dispatcher_settings: Settings,
) -> None:
    _add_message(db_session)
    publisher = _ClaimStatePublisher(session_factory)

    _dispatch(session_factory, dispatcher_settings, publisher)

    assert publisher.status == "PROCESSING"
    assert publisher.locked_by == "dispatcher-test"
    assert publisher.attempts == 1
    # ``FOR UPDATE NOWAIT`` succeeds, so no row lock is held during publishing.
    assert publisher.lock_error is None
