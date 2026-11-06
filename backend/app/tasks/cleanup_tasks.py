"""Cleanup worker task (08_infrastructure.md Section 3.7, roadmap 2.9/4.8).

The task is a thin adapter: it builds a database session and a storage backend,
then delegates to :class:`~app.services.cleanup_service.CleanupService`. Keeping
that logic outside the Celery decorator means the processing rules are testable
without a broker.

Two invocation styles share one task:

* no argument — the periodic beat scan the worker runs until the Outbox
  Dispatcher exists, so jobs recorded by project and image deletion are still
  consumed and a missed message can never strand a file;
* ``job_id`` — a targeted dispatch of one job (the Phase 4 dispatcher will use
  this once ``cleanup.requested`` events are published).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory, session_scope
from app.services.cleanup_service import CleanupService, CleanupSummary
from app.storage import LocalStorage, StorageBackend
from app.tasks.celery_app import CLEANUP_TASK_NAME, celery_app

logger = logging.getLogger(__name__)

# Engine and storage are process-wide: a Celery worker executes many tasks.
_runtime: tuple[sessionmaker[Session], StorageBackend] | None = None


def _runtime_for(settings: Settings) -> tuple[sessionmaker[Session], StorageBackend]:
    """Return the worker's session factory and storage, creating them once."""
    global _runtime  # noqa: PLW0603 - one connection pool per worker process
    if _runtime is None:
        engine = create_db_engine(settings)
        _runtime = (create_session_factory(engine), LocalStorage(settings.storage_root))
    return _runtime


def run_cleanup(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    storage: StorageBackend,
    job_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> CleanupSummary:
    """Run one cleanup cycle, optionally targeting a single job.

    Kept free of Celery so tests can exercise the whole worker path against a
    scratch database and a temporary storage root.
    """
    with session_scope(session_factory) as session:
        service = CleanupService(session, settings, storage)
        if job_id is not None:
            summary = CleanupSummary()
            outcome = service.process_job(job_id)
            if outcome is not None:
                summary.record(outcome)
            return summary
        return service.process_pending(limit=limit)


@celery_app.task(name=CLEANUP_TASK_NAME, bind=True)
def cleanup_storage_task(self: object, job_id: str | None = None) -> dict[str, int]:
    """Process queued cleanup jobs and report the cycle summary."""
    settings = get_settings()
    session_factory, storage = _runtime_for(settings)

    summary = run_cleanup(
        settings=settings,
        session_factory=session_factory,
        storage=storage,
        job_id=uuid.UUID(job_id) if job_id is not None else None,
        limit=settings.cleanup_batch_size,
    )
    logger.info(
        "cleanup_cycle_finished attempted=%d completed=%d retried=%d failed=%d deferred=%d",
        summary.attempted,
        summary.completed,
        summary.retried,
        summary.failed,
        summary.deferred,
        extra={"operation": "cleanup"},
    )
    return {
        "attempted": summary.attempted,
        "completed": summary.completed,
        "retried": summary.retried,
        "failed": summary.failed,
        "deferred": summary.deferred,
    }
