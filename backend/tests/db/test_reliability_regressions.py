"""Phase 8 reliability regressions (roadmap 8.3, 8.4 and 8.8).

These cases exercise the failure paths the roadmap names explicitly:

* a database failure while the worker registers a result (8.8);
* a worker that dies mid-task, recovery through the outbox and a successful
  retry (8.3);
* project deletion while a task is executing (8.3/8.8).

Every case asserts the two guarantees from the Phase 8 acceptance criteria:
the task/project state never stays inconsistent, and a previous successful
result is not lost.

Traceability: TEST-AC-17 (failure recovery), TEST-AC-18 (previous result
preservation), BE-AC-18 (failure handling), DB-AC-23 (task metadata),
INF-AC-22/25 (recovery and persistent leases), 05 Sections 9.11 and 12.4.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import GenerationResult, GenerationTask, Project, StorageCleanupJob
from app.db.models.enums import TaskType
from app.repositories import ResultRepository
from app.services.result_service import result_storage_key
from app.services.task_execution_service import TaskExecutionService
from app.services.task_recovery_service import TaskRecoveryService
from app.storage import LocalStorage
from app.tasks.generation_tasks import PipelineArtifact, run_generation

pytestmark = [pytest.mark.integration]

GLB_BODY = b"glTF\x02\x00\x00\x00-reliability-regression"


@pytest.fixture
def worker_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(tmp_path / "storage"),
        task_lease_seconds=300,
        task_heartbeat_seconds=30,
        task_stale_threshold_seconds=900,
        dispatch_stall_timeout_seconds=900,
        task_recovery_max_attempts=3,
    )


def _artifact(tmp_path: Path) -> PipelineArtifact:
    path = tmp_path / f"artifact-{uuid.uuid4().hex}.glb"
    path.write_bytes(GLB_BODY)
    return PipelineArtifact(
        path=path,
        sha256=hashlib.sha256(GLB_BODY).hexdigest(),
        file_size_bytes=len(GLB_BODY),
        format="GLB",
        mime_type="model/gltf-binary",
        metadata={"vertices_count": 12, "faces_count": 8, "meshes_count": 1},
    )


def _results(session: Session, project_id: uuid.UUID) -> list[GenerationResult]:
    session.expire_all()
    return list(
        session.scalars(
            select(GenerationResult)
            .where(GenerationResult.project_id == project_id)
            .order_by(GenerationResult.created_at)
        ).all()
    )


def test_a_database_failure_during_result_registration_fails_cleanly(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed registration rolls back, deletes the new file and keeps the old result."""
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    storage = LocalStorage(worker_settings.storage_root)
    storage.save(b"previous-current-result", old_result.storage_key)
    new_task = make_task(project)
    db_session.commit()

    def _explode(self, **_kwargs):
        raise RuntimeError("simulated database failure during result registration")

    monkeypatch.setattr(ResultRepository, "create", _explode)

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=storage,
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: _artifact(tmp_path),
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "RESULT_PERSISTENCE_FAILED"
    db_session.expire_all()
    failed = db_session.get(GenerationTask, new_task.id)
    assert failed is not None and failed.status == "FAILED"
    assert failed.error_code == "RESULT_PERSISTENCE_FAILED"
    results = _results(db_session, project.id)
    assert len(results) == 1
    assert results[0].id == old_result.id and results[0].is_current is True
    # The artifact written before the transaction was removed again, and the
    # previous current file was never touched.
    assert storage.exists(result_storage_key(project.id, new_task.id)) is False
    assert storage.exists(old_result.storage_key) is True


def test_a_worker_interruption_is_recovered_and_the_retry_completes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    """A dead worker's lease is recovered, the task is retried and the result replaced."""
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    storage = LocalStorage(worker_settings.storage_root)
    storage.save(b"previous-current-result", old_result.storage_key)
    new_task = make_task(project)
    db_session.commit()

    claimed_at = datetime.now(UTC)
    with session_factory() as session:
        assert (
            TaskExecutionService(session, worker_settings)
            .claim(new_task.id, worker_id="worker-dead", now=claimed_at)
            .claimed
            is True
        )

    stale_after = claimed_at + timedelta(seconds=worker_settings.task_stale_threshold_seconds + 1)
    with session_factory() as session:
        summary = TaskRecoveryService(session, worker_settings).recover(now=stale_after)
    assert summary.requeued == 1
    assert summary.failed == 0

    db_session.expire_all()
    recovered = db_session.get(GenerationTask, new_task.id)
    assert recovered is not None
    assert recovered.status == "PENDING"
    assert recovered.attempt_count == 1
    assert recovered.worker_id is None
    assert db_session.get(Project, project.id).status == "PENDING"

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=storage,
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-b",
        pipeline=lambda _context: _artifact(tmp_path),
    )

    assert outcome.status == "completed"
    db_session.expire_all()
    retried = db_session.get(GenerationTask, new_task.id)
    assert retried is not None and retried.status == "COMPLETED" and retried.attempt_count == 1
    current = db_session.scalar(
        select(GenerationResult).where(
            GenerationResult.project_id == project.id,
            GenerationResult.is_current.is_(True),
        )
    )
    assert current is not None and current.task_id == new_task.id
    assert db_session.get(GenerationResult, old_result.id).is_current is False
    assert storage.exists(old_result.storage_key) is True
    # The superseded file is queued for deletion with the replacement.
    queued = db_session.scalar(
        select(StorageCleanupJob).where(StorageCleanupJob.storage_key == old_result.storage_key)
    )
    assert queued is not None and queued.target_type == "FILE"


def test_project_deletion_during_processing_discards_the_new_asset(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    """Deleting the project while the pipeline runs cancels and leaks no file."""
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    storage = LocalStorage(worker_settings.storage_root)
    storage.save(b"previous-current-result", old_result.storage_key)
    new_task = make_task(project)
    db_session.commit()

    def _pipeline(_context):
        # The owner deletes the project while the reconstruction/inference runs.
        with session_factory() as session:
            row = session.get(Project, project.id)
            assert row is not None
            row.deleted_at = datetime.now(UTC)
            task_row = session.get(GenerationTask, new_task.id)
            assert task_row is not None
            task_row.cancel_requested_at = datetime.now(UTC)
            session.commit()
        return _artifact(tmp_path)

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=storage,
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_pipeline,
    )

    assert outcome.status == "cancelled"
    db_session.expire_all()
    cancelled = db_session.get(GenerationTask, new_task.id)
    assert cancelled is not None and cancelled.status == "CANCELLED"
    assert cancelled.error_code is None
    # The new file was written before registration, then removed by the worker.
    assert storage.exists(result_storage_key(project.id, new_task.id)) is False
    results = _results(db_session, project.id)
    assert len(results) == 1 and results[0].id == old_result.id
    assert results[0].is_current is True
    assert storage.exists(old_result.storage_key) is True
    assert (
        db_session.scalar(
            select(StorageCleanupJob).where(StorageCleanupJob.storage_key == old_result.storage_key)
        )
        is None
    )
