"""Task Recovery service against PostgreSQL (08 Section 3.10, roadmap 4.9).

Traceability: DB-AC-20 (stranded tasks are failed and dispatch stalls detected),
DB-AC-23 (persistent leases drive recovery), BE-AC-15 (accurate status after
recovery), data_flow.md Sections 12.1 and 12.3, TEST-AC-17 (failure recovery),
roadmap 4.7 and 4.9.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import GenerationTask, OutboxMessage, Project
from app.services.task_execution_service import TaskExecutionService
from app.services.task_recovery_service import TaskRecoveryService

pytestmark = [pytest.mark.integration]


@pytest.fixture
def recovery_settings() -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        task_lease_seconds=300,
        task_heartbeat_seconds=30,
        task_stale_threshold_seconds=900,
        dispatch_stall_timeout_seconds=900,
        task_recovery_max_attempts=3,
        recovery_batch_size=50,
        recovery_poll_interval_seconds=30,
    )


def _reload(db_session: Session, task_id: uuid.UUID) -> GenerationTask:
    db_session.expire_all()
    task = db_session.get(GenerationTask, task_id)
    assert task is not None
    return task


def _events(db_session: Session, task_id: uuid.UUID) -> list[OutboxMessage]:
    db_session.expire_all()
    return list(
        db_session.query(OutboxMessage)
        .filter(
            OutboxMessage.aggregate_type == "GenerationTask",
            OutboxMessage.aggregate_id == task_id,
        )
        .all()
    )


def _stale_task(
    db_session: Session,
    make_user,
    make_project,
    make_task,
    *,
    now: datetime,
    attempt_count: int = 0,
    cancel_requested: bool = False,
    deleted: bool = False,
    heartbeat_age_seconds: int = 1000,
    lease_age_seconds: int = 10,
) -> tuple[Project, GenerationTask]:
    project = make_project(make_user())
    if deleted:
        project.deleted_at = now
    task = make_task(
        project,
        status="PROCESSING",
        worker_id="dead-worker",
        attempt_count=attempt_count,
        started_at=now - timedelta(seconds=heartbeat_age_seconds),
        heartbeat_at=now - timedelta(seconds=heartbeat_age_seconds),
        lease_expires_at=now - timedelta(seconds=lease_age_seconds),
        cancel_requested_at=now if cancel_requested else None,
    )
    db_session.commit()
    return project, task


def _pending_task(
    db_session: Session, make_user, make_project, make_task, *, now: datetime
) -> tuple[Project, GenerationTask]:
    project = make_project(make_user())
    task = make_task(
        project,
        status="PENDING",
        queued_at=now - timedelta(seconds=1000),
    )
    db_session.commit()
    return project, task


def _add_event(db_session: Session, task: GenerationTask, status: str) -> OutboxMessage:
    message = OutboxMessage(
        event_type="generation.requested",
        aggregate_type="GenerationTask",
        aggregate_id=task.id,
        payload={
            "event_id": str(uuid.uuid4()),
            "event_type": "generation.requested",
            "schema_version": 1,
            "task_id": str(task.id),
            "project_id": str(task.project_id),
            "task_type": task.task_type,
        },
        schema_version=1,
        status=status,
    )
    db_session.add(message)
    db_session.commit()
    return message


# --- expired leases -------------------------------------------------------


def test_a_stale_task_is_requeued_and_redelivered(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project, task = _stale_task(db_session, make_user, make_project, make_task, now=now)

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.requeued == 1
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "PENDING"
    assert reloaded.attempt_count == 1
    assert reloaded.worker_id is None
    assert reloaded.heartbeat_at is None
    assert reloaded.lease_expires_at is None
    assert reloaded.queued_at is not None
    assert db_session.get(Project, project.id).status == "PENDING"

    events = _events(db_session, task.id)
    assert len(events) == 1
    assert events[0].event_type == "generation.requested"
    assert events[0].status == "PENDING"
    assert events[0].payload["task_id"] == str(task.id)


def test_a_requeued_splat_task_keeps_its_persisted_representation(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    """Increment 15: recovery must not fall back to the current mesh default."""
    now = datetime.now(UTC)
    project = make_project(make_user(), type="SCENE")
    task = make_task(
        project,
        task_type="SCENE",
        status="PROCESSING",
        worker_id="dead-splat-worker",
        started_at=now - timedelta(seconds=1000),
        heartbeat_at=now - timedelta(seconds=1000),
        lease_expires_at=now - timedelta(seconds=10),
        parameters={
            "algorithm": "COLMAP_SPLATFACTO",
            "output_format": "PLY",
            "representation": "GAUSSIAN_SPLAT",
            "method": "NERFSTUDIO_SPLATFACTO",
        },
    )
    db_session.commit()

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.requeued == 1
    events = _events(db_session, task.id)
    assert len(events) == 1
    assert events[0].payload["representation"] == "GAUSSIAN_SPLAT"


def test_a_live_lease_is_left_alone(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project = make_project(make_user())
    task = make_task(
        project,
        status="PROCESSING",
        worker_id="live-worker",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=300),
    )
    db_session.commit()

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.changed == 0
    assert _reload(db_session, task.id).status == "PROCESSING"


def test_an_expired_lease_with_a_recent_heartbeat_is_not_recovered(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project = make_project(make_user())
    task = make_task(
        project,
        status="PROCESSING",
        worker_id="slow-worker",
        heartbeat_at=now,
        lease_expires_at=now - timedelta(seconds=1),
    )
    db_session.commit()

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.changed == 0
    assert _reload(db_session, task.id).status == "PROCESSING"


def test_the_recovery_budget_marks_the_task_failed(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project, task = _stale_task(
        db_session,
        make_user,
        make_project,
        make_task,
        now=now,
        attempt_count=recovery_settings.task_recovery_max_attempts,
    )

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.failed == 1
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "FAILED"
    assert reloaded.error_code == "WORKER_UNAVAILABLE"
    assert reloaded.finished_at is not None
    assert db_session.get(Project, project.id).status == "FAILED"
    assert _events(db_session, task.id) == []


def test_a_cancelled_task_is_not_requeued(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _stale_task(
        db_session,
        make_user,
        make_project,
        make_task,
        now=now,
        cancel_requested=True,
    )

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.cancelled == 1
    assert summary.requeued == 0
    assert _reload(db_session, task.id).status == "CANCELLED"
    assert _events(db_session, task.id) == []


def test_a_deleted_projects_task_is_cancelled(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _stale_task(
        db_session,
        make_user,
        make_project,
        make_task,
        now=now,
        deleted=True,
    )

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.cancelled == 1
    assert _reload(db_session, task.id).status == "CANCELLED"


def test_recovery_is_idempotent(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _stale_task(db_session, make_user, make_project, make_task, now=now)
    service = TaskRecoveryService(db_session, recovery_settings)
    assert service.recover(now=now).requeued == 1

    second = service.recover(now=now)

    assert second.changed == 0
    assert len(_events(db_session, task.id)) == 1
    assert _reload(db_session, task.id).attempt_count == 1


def test_a_requeued_task_can_be_claimed_again(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _stale_task(db_session, make_user, make_project, make_task, now=now)
    TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    claim = TaskExecutionService(db_session, recovery_settings).claim(
        task.id, worker_id="new-worker"
    )

    assert claim.claimed is True
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "PROCESSING"
    assert reloaded.attempt_count == 1
    assert reloaded.worker_id == "new-worker"


# --- dispatch stalls ------------------------------------------------------


def test_a_stalled_pending_task_without_an_event_fails(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project, task = _pending_task(db_session, make_user, make_project, make_task, now=now)

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.dispatch_failed == 1
    reloaded = _reload(db_session, task.id)
    assert reloaded.status == "FAILED"
    assert reloaded.error_code == "WORKER_UNAVAILABLE"
    assert db_session.get(Project, project.id).status == "FAILED"


def test_a_stalled_pending_task_with_a_pending_event_is_left_alone(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _pending_task(db_session, make_user, make_project, make_task, now=now)
    _add_event(db_session, task, "PENDING")

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.dispatch_failed == 0
    assert _reload(db_session, task.id).status == "PENDING"


def test_a_stalled_pending_task_with_a_published_event_is_left_alone(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _pending_task(db_session, make_user, make_project, make_task, now=now)
    _add_event(db_session, task, "PUBLISHED")

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.dispatch_failed == 0
    assert _reload(db_session, task.id).status == "PENDING"


def test_a_stalled_pending_task_with_a_failed_event_fails(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    _project, task = _pending_task(db_session, make_user, make_project, make_task, now=now)
    _add_event(db_session, task, "FAILED")

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.dispatch_failed == 1
    assert _reload(db_session, task.id).status == "FAILED"


def test_a_recent_pending_task_is_not_touched(
    db_session: Session,
    recovery_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    now = datetime.now(UTC)
    project = make_project(make_user())
    task = make_task(project, status="PENDING", queued_at=now - timedelta(seconds=10))
    db_session.commit()

    summary = TaskRecoveryService(db_session, recovery_settings).recover(now=now)

    assert summary.changed == 0
    assert _reload(db_session, task.id).status == "PENDING"
