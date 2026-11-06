"""Standalone Outbox Dispatcher process (08_infrastructure.md Section 3.9).

Runs independently of the API and of every Celery worker. It polls PostgreSQL
for committed outbox events, publishes them to Redis through Celery, and
recovers its own expired claims. It never serves HTTP and never opens a port.

The loop writes a heartbeat file each cycle. The Compose healthcheck reads that
file, so a process that is alive but stuck cannot report healthy.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory
from app.services.outbox_service import (
    dispatcher_identity,
    run_dispatch_cycle,
)
from app.tasks.celery_app import celery_app
from app.tasks.outbox_publisher import CeleryPublisher

logger = logging.getLogger(__name__)

HEALTH_FILE = Path("/tmp/outbox-dispatcher.heartbeat")
# The healthcheck tolerates a few missed cycles before declaring the loop dead.
HEALTH_MAX_AGE_SECONDS = 120


def touch_health(path: Path = HEALTH_FILE) -> None:
    """Record that the dispatch loop completed a cycle."""
    try:
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.warning("outbox_health_write_failed", extra={"operation": "dispatcher"})


def main() -> None:
    """Run the dispatcher until SIGTERM or SIGINT."""
    settings = get_settings()
    configure_logging("outbox-dispatcher", settings.log_level)
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    publisher = CeleryPublisher(celery_app)
    identity = dispatcher_identity(socket.gethostname(), os.getpid())

    stop = threading.Event()

    def _request_stop(signum: int, _frame: object) -> None:
        logger.info(
            "outbox_dispatcher_stop_requested signal=%d",
            signum,
            extra={"operation": "dispatcher"},
        )
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    logger.info(
        "outbox_dispatcher_started dispatcher_id=%s",
        identity,
        extra={"operation": "dispatcher", "settings": settings.redacted()},
    )
    try:
        while not stop.is_set():
            try:
                summary = run_dispatch_cycle(
                    settings=settings,
                    session_factory=session_factory,
                    publisher=publisher,
                    dispatcher_id=identity,
                )
                if summary.claimed or summary.expired_locks:
                    logger.info(
                        "outbox_dispatch_cycle claimed=%d published=%d "
                        "retried=%d failed=%d released=%d",
                        summary.claimed,
                        summary.published,
                        summary.retried,
                        summary.failed,
                        summary.expired_locks,
                        extra={"operation": "dispatcher"},
                    )
            except Exception:
                # A broker or database interruption must not kill the
                # dispatcher: the committed outbox rows are still there.
                logger.exception("outbox_dispatch_cycle_failed", extra={"operation": "dispatcher"})
            finally:
                touch_health()
            stop.wait(settings.outbox_poll_interval_seconds)
    finally:
        engine.dispose()
        logger.info("outbox_dispatcher_stopped", extra={"operation": "dispatcher"})


if __name__ == "__main__":
    main()
