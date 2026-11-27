"""Celery application and queue topology for background work.

The application separates the three workloads defined by
``08_infrastructure.md`` Section 7.2 so a long scene reconstruction can never
delay object generation or file deletion:

* ``object_generation`` — :func:`generate_object_task`, consumed by the Object
  Worker;
* ``scene_reconstruction`` — :func:`reconstruct_scene_task`, consumed by the
  Scene Worker;
* ``file_cleanup`` — :func:`cleanup_storage_task`, consumed by the Cleanup
  Worker.

Broker state is never authoritative: every task and every cleanup job lives in
PostgreSQL and the worker updates that state. No result backend is configured
(08 Section 7.6); task state is read from the database, never from Celery.

The cleanup and generation tasks are included lazily by name so a worker that
only consumes one queue still registers every task. The periodic cleanup scan
remains the recovery path for a ``cleanup.requested`` message that was lost or
never dispatched; the Outbox Dispatcher is the normal delivery path.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

OBJECT_GENERATION_QUEUE = "object_generation"
SCENE_RECONSTRUCTION_QUEUE = "scene_reconstruction"
# Dedicated queue for the opt-in neural scene representation (15 Section 4.2).
# The mesh and splat workers run different dependency stacks, so they must not
# consume the same queue; the dispatcher picks the queue from the persisted
# task representation.
SCENE_SPLAT_QUEUE = "scene_gaussian_splat"
CLEANUP_QUEUE = "file_cleanup"

ALL_QUEUES = (OBJECT_GENERATION_QUEUE, SCENE_RECONSTRUCTION_QUEUE, SCENE_SPLAT_QUEUE, CLEANUP_QUEUE)
GENERATION_QUEUES = (OBJECT_GENERATION_QUEUE, SCENE_RECONSTRUCTION_QUEUE, SCENE_SPLAT_QUEUE)

OBJECT_GENERATION_TASK = "generate_object_task"
SCENE_RECONSTRUCTION_TASK = "reconstruct_scene_task"
CLEANUP_TASK_NAME = "cleanup_storage_task"
WORKSPACE_SWEEP_TASK_NAME = "cleanup_scene_workspaces_task"
SESSION_CLEANUP_TASK_NAME = "cleanup_sessions_task"

CLEANUP_TASK_MODULE = "app.tasks.cleanup_tasks"
GENERATION_TASK_MODULE = "app.tasks.generation_tasks"

# Explicit routing keeps the dispatcher and the workers in agreement even when a
# task is sent without an explicit queue (08 Section 7.4).
TASK_ROUTES = {
    OBJECT_GENERATION_TASK: {"queue": OBJECT_GENERATION_QUEUE},
    SCENE_RECONSTRUCTION_TASK: {"queue": SCENE_RECONSTRUCTION_QUEUE},
    CLEANUP_TASK_NAME: {"queue": CLEANUP_QUEUE},
    WORKSPACE_SWEEP_TASK_NAME: {"queue": CLEANUP_QUEUE},
    SESSION_CLEANUP_TASK_NAME: {"queue": CLEANUP_QUEUE},
}

# Seconds of soft-limit headroom before the hard limit kills the task.
_SOFT_LIMIT_MARGIN_SECONDS = 30
# Extra visibility-timeout headroom over the longest configured task limit, so a
# message is not redelivered while its worker is still allowed to run
# (04 Section 18.2).
_VISIBILITY_TIMEOUT_MARGIN_SECONDS = 300


def create_celery_app(settings: Settings) -> Celery:
    """Build the Celery application for this process.

    ``acks_late`` plus a prefetch of one keeps a worker from hoarding messages
    it is not executing. Every task is idempotent, so a redelivered message is
    safe (data_flow.md Sections 7.3 and 7.4).
    """
    cleanup_limit = settings.cleanup_task_time_limit_seconds
    object_limit = settings.object_task_time_limit_seconds
    scene_limit = settings.scene_task_time_limit_seconds
    longest_limit = max(cleanup_limit, object_limit, scene_limit)
    app = Celery(
        "mogen",
        broker=settings.celery_broker_url,
        include=[CLEANUP_TASK_MODULE, GENERATION_TASK_MODULE],
    )
    app.conf.update(
        task_ignore_result=settings.celery_task_ignore_result,
        # Queue the dispatcher uses for a scene task persisted as GAUSSIAN_SPLAT.
        # It is deployment-configurable but never overrides the persisted
        # representation; the dispatcher always passes the queue explicitly.
        mogen_scene_splat_queue=settings.scene_splat_worker_queue,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_default_queue=CLEANUP_QUEUE,
        task_routes=TASK_ROUTES,
        # Per-pipeline limits; the global values are only a fallback for a task
        # that is added without an annotation.
        task_annotations={
            OBJECT_GENERATION_TASK: {
                "time_limit": object_limit,
                "soft_time_limit": max(1, object_limit - _SOFT_LIMIT_MARGIN_SECONDS),
            },
            SCENE_RECONSTRUCTION_TASK: {
                "time_limit": scene_limit,
                "soft_time_limit": max(1, scene_limit - _SOFT_LIMIT_MARGIN_SECONDS),
            },
            CLEANUP_TASK_NAME: {
                "time_limit": cleanup_limit,
                "soft_time_limit": max(1, cleanup_limit - _SOFT_LIMIT_MARGIN_SECONDS),
            },
            WORKSPACE_SWEEP_TASK_NAME: {
                "time_limit": cleanup_limit,
                "soft_time_limit": max(1, cleanup_limit - _SOFT_LIMIT_MARGIN_SECONDS),
            },
            SESSION_CLEANUP_TASK_NAME: {
                "time_limit": cleanup_limit,
                "soft_time_limit": max(1, cleanup_limit - _SOFT_LIMIT_MARGIN_SECONDS),
            },
        },
        task_time_limit=longest_limit,
        task_soft_time_limit=max(1, longest_limit - _SOFT_LIMIT_MARGIN_SECONDS),
        # A message stays invisible to other workers for longer than any task is
        # allowed to run, so a slow task is not redelivered mid-flight.
        broker_transport_options={
            "visibility_timeout": longest_limit + _VISIBILITY_TIMEOUT_MARGIN_SECONDS
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        # Leave logging to this application: the JSON formatter and the
        # service name are configured once at import, and Celery must not
        # replace the root handler or redirect stdout inside task processes.
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
        beat_schedule={
            "cleanup-poll": {
                "task": CLEANUP_TASK_NAME,
                "schedule": settings.cleanup_poll_interval_seconds,
            },
            "scene-workspace-sweep": {
                "task": WORKSPACE_SWEEP_TASK_NAME,
                "schedule": settings.scene_workspace_sweep_interval_seconds,
            },
            "session-cleanup": {
                "task": SESSION_CLEANUP_TASK_NAME,
                "schedule": settings.session_cleanup_interval_seconds,
            },
        },
    )
    return app


celery_app = create_celery_app(get_settings())
# The service name is per worker container; Compose sets WORKER_SERVICE_NAME.
configure_logging(get_settings().worker_service_name, get_settings().log_level)
