"""Outbox Dispatcher logic (data_flow.md Section 6.8, 08 Section 3.9).

The dispatcher claims committed events with ``FOR UPDATE SKIP LOCKED``,
commits the claim, and only then publishes to Redis. Holding the PostgreSQL
lock across the network call would block other dispatchers and lengthen
transactions, so the claim and the publish are deliberately separate
transactions.

Publication is at-least-once: a dispatcher can publish and then terminate
before marking the row PUBLISHED, so duplicate Celery deliveries are expected
and the workers make claiming idempotent. Transient broker failures return the
message to PENDING with bounded exponential backoff; permanent contract
failures and an exhausted retry budget move it to FAILED, where it stays as
evidence of an undelivered request (05 Section 13.6).
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import OutboxMessage
from app.db.session import session_scope
from app.repositories import OutboxRepository

logger = logging.getLogger(__name__)

# ``last_error`` is TEXT, but a bounded diagnostic keeps rows and logs readable.
MAX_ERROR_LENGTH = 2000


class PermanentDispatchError(Exception):
    """A message that must not be retried (unsupported schema, event or payload)."""


class MessagePublisher(Protocol):
    """Publishes one outbox message to the broker."""

    def publish(self, message: OutboxMessage) -> None:
        """Publish one message or raise."""


@dataclass(slots=True)
class DispatchSummary:
    """Aggregated result of one dispatch cycle."""

    expired_locks: int = 0
    claimed: int = 0
    published: int = 0
    retried: int = 0
    failed: int = 0


def retry_delay_seconds(
    attempts: int,
    *,
    base_seconds: int,
    max_seconds: int,
    rng: Callable[[float, float], float] = random.uniform,
) -> float:
    """Return the full-jitter exponential backoff for the next attempt.

    ``attempts`` is the value already incremented by the claim, so the first
    retry uses the base delay (05 Section 13.6).
    """
    exponent = max(0, attempts - 1)
    ceiling = min(max_seconds, base_seconds * (2**exponent))
    return rng(0, ceiling)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def dispatch_pending(
    session: Session,
    *,
    settings: Settings,
    publisher: MessagePublisher,
    dispatcher_id: str,
    limit: int | None = None,
    now: datetime | None = None,
    rng: Callable[[float, float], float] = random.uniform,
) -> DispatchSummary:
    """Publish due outbox messages, returning what happened.

    The caller owns the session; this function commits after each state
    transition so a crash cannot roll back a confirmed publication.
    """
    moment = now or _utc_now()
    batch = limit if limit is not None else settings.outbox_batch_size
    outbox = OutboxRepository(session)
    summary = DispatchSummary()

    summary.expired_locks = outbox.release_expired_locks(
        now=moment, timeout_seconds=settings.outbox_lock_timeout_seconds
    )
    if summary.expired_locks:
        session.commit()
        logger.warning(
            "outbox_locks_released count=%d",
            summary.expired_locks,
            extra={"operation": "dispatcher"},
        )

    messages = outbox.claim_pending(now=moment, limit=batch, locked_by=dispatcher_id)
    summary.claimed = len(messages)
    # Commit the claim before touching Redis (05 Section 13.4).
    session.commit()

    for message in messages:
        try:
            publisher.publish(message)
        except PermanentDispatchError as exc:
            outbox.mark_failed(message.id, last_error=_error_text(exc))
            session.commit()
            summary.failed += 1
            logger.error(
                "outbox_message_failed_permanently event_type=%s attempts=%d",
                message.event_type,
                message.attempts,
                extra={
                    "operation": "dispatcher",
                    "error_code": "OUTBOX_PERMANENT_FAILURE",
                },
            )
        except Exception as exc:
            if message.attempts >= settings.outbox_max_attempts:
                outbox.mark_failed(message.id, last_error=_error_text(exc))
                summary.failed += 1
                logger.error(
                    "outbox_message_failed_after_retries event_type=%s attempts=%d",
                    message.event_type,
                    message.attempts,
                    extra={"operation": "dispatcher", "error_code": "OUTBOX_RETRIES_EXHAUSTED"},
                )
            else:
                delay = retry_delay_seconds(
                    message.attempts,
                    base_seconds=settings.outbox_retry_base_seconds,
                    max_seconds=settings.outbox_retry_max_seconds,
                    rng=rng,
                )
                outbox.mark_retry(
                    message.id,
                    available_at=_utc_now() + timedelta(seconds=delay),
                    last_error=_error_text(exc),
                )
                summary.retried += 1
                logger.warning(
                    "outbox_publish_retry_scheduled event_type=%s attempts=%d delay=%.1f",
                    message.event_type,
                    message.attempts,
                    delay,
                    extra={"operation": "dispatcher"},
                )
            session.commit()
        else:
            outbox.mark_published(message.id, published_at=_utc_now())
            session.commit()
            summary.published += 1
            logger.info(
                "outbox_message_published event_type=%s aggregate_id=%s",
                message.event_type,
                message.aggregate_id,
                extra={"operation": "dispatcher"},
            )
    return summary


def run_dispatch_cycle(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    publisher: MessagePublisher,
    dispatcher_id: str,
    limit: int | None = None,
    now: datetime | None = None,
    rng: Callable[[float, float], float] = random.uniform,
) -> DispatchSummary:
    """Open a session and run one dispatch cycle."""
    with session_scope(session_factory) as session:
        return dispatch_pending(
            session,
            settings=settings,
            publisher=publisher,
            dispatcher_id=dispatcher_id,
            limit=limit,
            now=now,
            rng=rng,
        )


def _error_text(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:MAX_ERROR_LENGTH]


def dispatcher_identity(hostname: str, process_id: int) -> str:
    """Return the stable identity recorded in ``locked_by``."""
    return f"{hostname}:{process_id}"
