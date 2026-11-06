"""Standalone Task Recovery process (08_infrastructure.md Section 3.10).

Runs independently of the API, the dispatcher and the workers. It inspects
PostgreSQL for expired worker leases and stranded PENDING tasks, and repairs
them through conditional updates and new outbox events. It never publishes to
Redis itself; the Outbox Dispatcher does that.

The loop writes a heartbeat file so the Compose healthcheck proves the loop is
running, not merely that a process exists.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.services.task_recovery_service import RecoverySummary, TaskRecoveryService

logger = logging.getLogger(__name__)

HEALTH_FILE = Path("/tmp/task-recovery.heartbeat")
# The healthcheck tolerates a few missed cycles before declaring the loop dead.
HEALTH_MAX_AGE_SECONDS = 120


def touch_health(path: Path = HEALTH_FILE) -> None:
    """Record that the recovery loop completed a cycle."""
    try:
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.warning("recovery_health_write_failed", extra={"operation": "task_recovery"})


def run_recovery_cycle(
    *, settings: Settings, session_factory: sessionmaker[Session]
) -> RecoverySummary:
    """Open a session and run one recovery cycle."""
    with session_scope(session_factory) as session:
        return TaskRecoveryService(session, settings).recover()


def main() -> None:
    """Run the recovery service until SIGTERM or SIGINT."""
    settings = get_settings()
    configure_logging("task-recovery", settings.log_level)
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)

    stop = threading.Event()

    def _request_stop(signum: int, _frame: object) -> None:
        logger.info(
            "task_recovery_stop_requested signal=%d",
            signum,
            extra={"operation": "task_recovery"},
        )
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    logger.info(
        "task_recovery_started",
        extra={"operation": "task_recovery", "settings": settings.redacted()},
    )
    try:
        while not stop.is_set():
            try:
                summary = run_recovery_cycle(settings=settings, session_factory=session_factory)
                if summary.changed:
                    logger.info(
                        "task_recovery_cycle requeued=%d failed=%d cancelled=%d dispatch_failed=%d",
                        summary.requeued,
                        summary.failed,
                        summary.cancelled,
                        summary.dispatch_failed,
                        extra={"operation": "task_recovery"},
                    )
            except Exception:
                logger.exception("task_recovery_cycle_failed", extra={"operation": "task_recovery"})
            finally:
                touch_health()
            stop.wait(settings.recovery_poll_interval_seconds)
    finally:
        engine.dispose()
        logger.info("task_recovery_stopped", extra={"operation": "task_recovery"})


if __name__ == "__main__":
    main()
