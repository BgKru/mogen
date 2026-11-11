"""Celery application and queue topology (08_infrastructure.md Section 7).

Traceability: BE-AC-14 (queue separation), INF-AC-10 (per-worker delivery),
INF-AC-15 (health checks are possible because each worker answers on its queue),
roadmap tasks 4.1-4.3; TEST-AC-01 (worker infrastructure is testable without a
broker).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.tasks.celery_app import (
    ALL_QUEUES,
    CLEANUP_QUEUE,
    CLEANUP_TASK_NAME,
    GENERATION_QUEUES,
    OBJECT_GENERATION_QUEUE,
    OBJECT_GENERATION_TASK,
    SCENE_RECONSTRUCTION_QUEUE,
    SCENE_RECONSTRUCTION_TASK,
    SESSION_CLEANUP_TASK_NAME,
    WORKSPACE_SWEEP_TASK_NAME,
    create_celery_app,
)

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "log_level": "WARNING",
        "celery_broker_url": "redis://broker:6379/1",
        "cleanup_poll_interval_seconds": 7,
        "cleanup_task_time_limit_seconds": 300,
        "object_task_time_limit_seconds": 3000,
        "scene_task_time_limit_seconds": 8000,
    }
    values.update(overrides)
    return Settings(**values)


def test_the_three_documented_queues_exist() -> None:
    assert set(ALL_QUEUES) == {"object_generation", "scene_reconstruction", "file_cleanup"}
    assert set(GENERATION_QUEUES) == {"object_generation", "scene_reconstruction"}
    assert OBJECT_GENERATION_QUEUE == "object_generation"
    assert SCENE_RECONSTRUCTION_QUEUE == "scene_reconstruction"
    assert CLEANUP_QUEUE == "file_cleanup"


def test_each_task_is_routed_to_its_own_queue() -> None:
    app = create_celery_app(_settings())

    assert app.conf.task_routes[OBJECT_GENERATION_TASK] == {"queue": OBJECT_GENERATION_QUEUE}
    assert app.conf.task_routes[SCENE_RECONSTRUCTION_TASK] == {"queue": SCENE_RECONSTRUCTION_QUEUE}
    assert app.conf.task_routes[CLEANUP_TASK_NAME] == {"queue": CLEANUP_QUEUE}
    # The retention sweep is cleanup work, so it never blocks generation.
    assert app.conf.task_routes[WORKSPACE_SWEEP_TASK_NAME] == {"queue": CLEANUP_QUEUE}
    assert app.conf.task_routes[SESSION_CLEANUP_TASK_NAME] == {"queue": CLEANUP_QUEUE}


def test_no_result_backend_is_configured() -> None:
    app = create_celery_app(_settings())

    assert app.conf.result_backend is None
    assert app.conf.task_ignore_result is True


def test_worker_reliability_settings() -> None:
    app = create_celery_app(_settings())

    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.broker_connection_retry_on_startup is True


def test_time_limits_are_per_pipeline() -> None:
    app = create_celery_app(_settings())

    assert app.conf.task_annotations[OBJECT_GENERATION_TASK] == {
        "time_limit": 3000,
        "soft_time_limit": 2970,
    }
    assert app.conf.task_annotations[SCENE_RECONSTRUCTION_TASK] == {
        "time_limit": 8000,
        "soft_time_limit": 7970,
    }
    assert app.conf.task_annotations[CLEANUP_TASK_NAME] == {
        "time_limit": 300,
        "soft_time_limit": 270,
    }
    assert app.conf.task_annotations[WORKSPACE_SWEEP_TASK_NAME] == {
        "time_limit": 300,
        "soft_time_limit": 270,
    }
    assert app.conf.task_annotations[SESSION_CLEANUP_TASK_NAME] == {
        "time_limit": 300,
        "soft_time_limit": 270,
    }
    # The global fallback covers the longest configured task.
    assert app.conf.task_time_limit == 8000


def test_visibility_timeout_exceeds_the_longest_task() -> None:
    app = create_celery_app(_settings())

    assert app.conf.broker_transport_options["visibility_timeout"] == 8300


def test_beat_polls_for_pending_cleanup_jobs() -> None:
    app = create_celery_app(_settings(cleanup_poll_interval_seconds=7))

    entry = app.conf.beat_schedule["cleanup-poll"]
    assert entry["task"] == CLEANUP_TASK_NAME
    assert entry["schedule"] == 7


def test_beat_sweeps_scene_workspaces_on_its_own_schedule() -> None:
    app = create_celery_app(_settings(scene_workspace_sweep_interval_seconds=1234))

    entry = app.conf.beat_schedule["scene-workspace-sweep"]
    assert entry["task"] == WORKSPACE_SWEEP_TASK_NAME
    assert entry["schedule"] == 1234


def test_beat_cleans_up_sessions_on_its_own_schedule() -> None:
    app = create_celery_app(_settings(session_cleanup_interval_seconds=2345))

    entry = app.conf.beat_schedule["session-cleanup"]
    assert entry["task"] == SESSION_CLEANUP_TASK_NAME
    assert entry["schedule"] == 2345


def test_the_broker_url_comes_from_settings() -> None:
    app = create_celery_app(_settings(celery_broker_url="redis://other:6379/2"))

    assert app.conf.broker_url == "redis://other:6379/2"


def test_every_queue_task_is_registered() -> None:
    from app.tasks import cleanup_tasks, generation_tasks  # noqa: F401  # register tasks
    from app.tasks.celery_app import celery_app

    for name in (
        OBJECT_GENERATION_TASK,
        SCENE_RECONSTRUCTION_TASK,
        CLEANUP_TASK_NAME,
        WORKSPACE_SWEEP_TASK_NAME,
        SESSION_CLEANUP_TASK_NAME,
    ):
        assert name in celery_app.tasks
