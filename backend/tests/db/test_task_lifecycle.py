"""Generation task claim, heartbeat and terminal transitions.

Traceability: BE-AC-13 (task execution lifecycle), BE-AC-16 (one active task),
DB-AC-23 (persistent worker leases), data_flow.md Sections 7.4 and 12.3,
TEST-AC-06/07/17, roadmap 4.5, 4.7 and 4.9.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import GenerationTask, Project
from app.db.models.enums import TaskType
from app.services.task_execution_service import TaskExecutionService
from app.storage import LocalStorage
from app.tasks.generation_tasks import (
    GenerationCancelled,
    GenerationFailure,
    run_generation,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture
def lifecycle_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(tmp_path),
        task_lease_seconds=300,
        task_heartbeat_seconds=30,
        task_stale_threshold_seconds=900,
        task_recovery_max_attempts=3,
    )


def _storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def _reload(db_session: Session, task_id: uuid.UUID) -> GenerationTask:
    db_session.expire_all()
    task = db_session.get(GenerationTask, task_id)
    assert task is not None
    return task


# --- claiming -------------------------------------------------------------


def test_claim_transitions_pending_to_processing(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    claim = TaskExecutionService(db_session, lifecycle_settings).claim(
        task.id, worker_id="worker-a"
    )

    assert claim.claimed is True
    assert claim.task is not None
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "PROCESSING"
    assert reloaded.worker_id == "worker-a"
    assert reloaded.started_at is not None
    assert reloaded.heartbeat_at is not None
    assert reloaded.lease_expires_at is not None
    assert db_session.get(Project, project.id).status == "PROCESSING"


def test_a_second_worker_cannot_claim_the_same_task(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    assert service.claim(task.id, worker_id="worker-a").claimed is True

    second = service.claim(task.id, worker_id="worker-b")

    assert second.claimed is False
    assert _reload(db_session, task.id).worker_id == "worker-a"


def test_a_terminal_task_cannot_be_claimed(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project, status="FAILED")
    db_session.commit()

    claim = TaskExecutionService(db_session, lifecycle_settings).claim(
        task.id, worker_id="worker-a"
    )

    assert claim.claimed is False


def test_claiming_is_atomic_under_concurrency(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    barrier = threading.Barrier(2)
    outcomes: list[bool] = []

    def _claim(worker_id: str) -> None:
        with session_factory() as session:
            service = TaskExecutionService(session, lifecycle_settings)
            barrier.wait()
            outcomes.append(service.claim(task.id, worker_id=worker_id).claimed)

    threads = [
        threading.Thread(target=_claim, args=("worker-a",)),
        threading.Thread(target=_claim, args=("worker-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == [False, True]
    assert _reload(db_session, task.id).status == "PROCESSING"


# --- heartbeat and progress ----------------------------------------------


def test_only_the_lease_owner_can_renew(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")
    first_lease = _reload(db_session, task.id).lease_expires_at

    later = datetime.now(UTC) + timedelta(seconds=60)
    assert service.heartbeat(task.id, worker_id="worker-b", now=later) is False
    assert service.heartbeat(task.id, worker_id="worker-a", now=later) is True

    reloaded = _reload(db_session, task.id)
    assert reloaded.heartbeat_at is not None
    assert reloaded.lease_expires_at > first_lease


def test_progress_is_persisted(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")

    updated = service.record_progress(
        task.id,
        worker_id="worker-a",
        stage="MODEL_GENERATION",
        progress_percent=55,
        status_message="Generating 3D geometry",
    )

    assert updated is True
    reloaded = _reload(db_session, task.id)
    assert reloaded.stage == "MODEL_GENERATION"
    assert reloaded.progress_percent == 55
    assert reloaded.status_message == "Generating 3D geometry"


def test_progress_from_another_worker_is_rejected(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")

    assert service.record_progress(task.id, worker_id="worker-b", stage="MODEL_EXPORT") is False


# --- terminal transitions -------------------------------------------------


def test_completion_updates_task_and_project(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")

    assert service.complete(task.id, worker_id="worker-a") is True

    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "COMPLETED"
    assert reloaded.finished_at is not None
    assert reloaded.lease_expires_at is None
    assert db_session.get(Project, project.id).status == "COMPLETED"


def test_failure_records_the_error_and_fails_the_project(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")

    assert (
        service.fail(
            task.id,
            worker_id="worker-a",
            error_code="GPU_OUT_OF_MEMORY",
            error_message="CUDA out of memory",
        )
        is True
    )

    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "FAILED"
    assert reloaded.error_code == "GPU_OUT_OF_MEMORY"
    assert reloaded.error_message == "CUDA out of memory"
    assert reloaded.finished_at is not None
    assert db_session.get(Project, project.id).status == "FAILED"


def test_a_cancellation_request_is_honoured_on_completion(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")
    task = _reload(db_session, task.id)
    task.cancel_requested_at = datetime.now(UTC)
    db_session.commit()

    assert service.complete(task.id, worker_id="worker-a") is True

    assert _reload(db_session, task.id).status == "CANCELLED"


def test_cancel_stops_a_held_task(
    db_session: Session, make_user, make_project, make_task, lifecycle_settings: Settings
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    service = TaskExecutionService(db_session, lifecycle_settings)
    service.claim(task.id, worker_id="worker-a")

    assert service.cancel(task.id, worker_id="worker-a", reason="Task cancelled") is True

    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "CANCELLED"
    assert reloaded.finished_at is not None


# --- broker-free worker path ---------------------------------------------


def test_the_worker_runs_a_pipeline_once(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    calls: list[str] = []

    def _pipeline(context) -> None:
        calls.append("ran")
        assert context.heartbeat() is True
        assert (
            context.report_progress(
                stage="IMAGE_PREPARATION",
                progress_percent=10,
                status_message="Preparing image",
            )
            is True
        )

    first = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_pipeline,
    )
    second = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-b",
        pipeline=_pipeline,
    )

    assert first.status == "completed"
    assert second.status == "skipped"
    assert calls == ["ran"]
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "COMPLETED"
    assert reloaded.stage == "IMAGE_PREPARATION"
    assert reloaded.progress_percent == 10


def test_a_long_pipeline_is_heartbeated_automatically(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    settings = lifecycle_settings.model_copy(update={"task_heartbeat_seconds": 1})
    observed: dict[str, datetime | None] = {}

    def _pipeline(context) -> None:
        observed["claimed"] = context.task.heartbeat_at
        time.sleep(1.3)
        with session_factory() as probe:
            observed["later"] = probe.scalar(
                select(GenerationTask.heartbeat_at).where(GenerationTask.id == task.id)
            )

    outcome = run_generation(
        settings=settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_pipeline,
    )

    assert outcome.status == "completed"
    assert observed["claimed"] is not None
    assert observed["later"] is not None
    assert observed["later"] > observed["claimed"]


def test_the_worker_fails_honestly_without_a_pipeline(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    outcome = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "WORKER_UNAVAILABLE"
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "FAILED"
    assert reloaded.error_code == "WORKER_UNAVAILABLE"
    assert reloaded.error_message is not None


def test_a_pipeline_failure_is_recorded(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    def _failing(_context) -> None:
        raise GenerationFailure("GPU_OUT_OF_MEMORY", "CUDA out of memory")

    outcome = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_failing,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "GPU_OUT_OF_MEMORY"
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "FAILED"
    assert reloaded.error_code == "GPU_OUT_OF_MEMORY"


def test_a_pipeline_cancellation_marks_the_task_cancelled(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    def _cancelled(_context) -> None:
        raise GenerationCancelled("stop")

    outcome = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_cancelled,
    )

    assert outcome.status == "cancelled"
    assert _reload(db_session, task.id).status == "CANCELLED"


def test_a_cancel_request_before_execution_skips_the_pipeline(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    task = _reload(db_session, task.id)
    task.cancel_requested_at = datetime.now(UTC)
    db_session.commit()
    calls: list[str] = []

    outcome = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: calls.append("ran"),
    )

    assert outcome.status == "cancelled"
    assert calls == []
    assert _reload(db_session, task.id).status == "CANCELLED"


def test_a_pipeline_observes_cancellation_during_execution(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    lifecycle_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    def _pipeline(context) -> None:
        with session_factory() as other:
            row = other.get(GenerationTask, task.id)
            assert row is not None
            row.cancel_requested_at = datetime.now(UTC)
            other.commit()
        context.raise_if_cancelled()

    outcome = run_generation(
        settings=lifecycle_settings,
        session_factory=session_factory,
        storage=_storage(tmp_path),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_pipeline,
    )

    assert outcome.status == "cancelled"
    assert _reload(db_session, task.id).status == "CANCELLED"


def test_the_pipeline_registry_resolves_a_registered_pipeline() -> None:
    from app.tasks import generation_tasks as module

    def _pipeline(_context) -> None:
        return None

    assert module.resolve_pipeline(TaskType.SCENE) is None
    module.register_pipeline(TaskType.SCENE, _pipeline)
    try:
        assert module.resolve_pipeline(TaskType.SCENE) is _pipeline
    finally:
        module._pipelines.pop(TaskType.SCENE, None)
