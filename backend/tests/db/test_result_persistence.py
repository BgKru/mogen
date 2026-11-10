"""Worker result persistence and failure preservation.

Traceability: OBJ-AC-11 (persistent result registration), OBJ-AC-13/15 (failure
handling and previous-result preservation), DB-AC-10..12 (result storage,
versioning, preservation), BE-AC-19 (validated result management),
TEST-AC-14/18, roadmap 5.7-5.8.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import GenerationResult, GenerationTask, StorageCleanupJob
from app.db.models.enums import TaskType
from app.services.cleanup_service import CleanupService
from app.services.result_service import result_storage_key
from app.services.task_execution_service import TaskExecutionService
from app.storage import LocalStorage
from app.tasks.generation_tasks import PipelineArtifact, run_generation

pytestmark = [pytest.mark.integration]

SHA256_SAMPLE = "0123456789abcdef" * 4
GLB_BODY = b"glTF\x02\x00\x00\x00-persisted-result"


@pytest.fixture
def worker_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(tmp_path / "storage"),
        task_lease_seconds=300,
        task_heartbeat_seconds=30,
        task_stale_threshold_seconds=900,
        task_recovery_max_attempts=3,
    )


def _artifact(tmp_path: Path, body: bytes = GLB_BODY) -> PipelineArtifact:
    path = tmp_path / f"artifact-{uuid.uuid4().hex}.glb"
    path.write_bytes(body)
    return PipelineArtifact(
        path=path,
        sha256=hashlib.sha256(body).hexdigest(),
        file_size_bytes=len(body),
        format="GLB",
        mime_type="model/gltf-binary",
        metadata={"vertices_count": 12, "faces_count": 8, "meshes_count": 1},
    )


def _count_results(session: Session, project_id: uuid.UUID) -> int:
    session.expire_all()
    return (
        session.scalar(
            select(func.count())
            .select_from(GenerationResult)
            .where(GenerationResult.project_id == project_id)
        )
        or 0
    )


def test_a_successful_pipeline_registers_the_current_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()

    artifact = _artifact(tmp_path)
    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: artifact,
    )

    assert outcome.status == "completed"
    db_session.expire_all()
    finished = db_session.get(GenerationTask, task.id)
    assert finished is not None and finished.status == "COMPLETED"
    result = db_session.scalar(select(GenerationResult).where(GenerationResult.task_id == task.id))
    assert result is not None
    assert result.is_current is True
    assert result.format == "GLB"
    assert result.mime_type == "model/gltf-binary"
    assert result.file_size_bytes == len(GLB_BODY)
    assert result.sha256 == hashlib.sha256(GLB_BODY).hexdigest()
    assert result.storage_key == result_storage_key(project.id, task.id)
    assert result.result_metadata["vertices_count"] == 12
    stored = Path(worker_settings.storage_root) / result.storage_key
    assert stored.read_bytes() == GLB_BODY
    project_row = db_session.get(type(project), project.id)
    assert project_row is not None and project_row.status == "COMPLETED"


def test_a_new_success_replaces_the_current_result_and_keeps_the_old_one(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    old_bytes = b"old-result"
    LocalStorage(worker_settings.storage_root).save(old_bytes, old_result.storage_key)
    new_task = make_task(project)
    db_session.commit()

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: _artifact(tmp_path),
    )

    assert outcome.status == "completed"
    db_session.expire_all()
    assert db_session.get(GenerationResult, old_result.id).is_current is False
    current = db_session.scalar(
        select(GenerationResult).where(
            GenerationResult.project_id == project.id,
            GenerationResult.is_current.is_(True),
        )
    )
    assert current is not None and current.task_id == new_task.id
    assert _count_results(db_session, project.id) == 2
    assert (Path(worker_settings.storage_root) / old_result.storage_key).read_bytes() == old_bytes


def test_a_successful_replacement_queues_the_superseded_file_for_cleanup(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    """A replaced result's GLB is deleted by the cleanup worker, not leaked.

    Traceability: 05 Section 14.6 ("Cleanup of obsolete assets must be
    explicit"), 07 Section 15.7, roadmap 8.4/8.5, TEST-AC-09/18. The result row
    stays as history and the current result is unaffected.
    """
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    old_bytes = b"old-result-to-be-deleted"
    storage = LocalStorage(worker_settings.storage_root)
    storage.save(old_bytes, old_result.storage_key)
    new_task = make_task(project)
    db_session.commit()

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=storage,
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: _artifact(tmp_path),
    )
    assert outcome.status == "completed"

    db_session.expire_all()
    job = db_session.scalar(
        select(StorageCleanupJob).where(StorageCleanupJob.storage_key == old_result.storage_key)
    )
    assert job is not None
    assert job.target_type == "FILE"
    assert job.status == "PENDING"
    assert job.project_id == project.id
    current = db_session.scalar(
        select(GenerationResult).where(
            GenerationResult.project_id == project.id,
            GenerationResult.is_current.is_(True),
        )
    )
    assert current is not None and current.task_id == new_task.id
    # The superseded row is history; only its file is scheduled for deletion.
    assert db_session.get(GenerationResult, old_result.id).is_current is False
    assert storage.exists(old_result.storage_key) is True

    with session_factory() as session:
        summary = CleanupService(session, worker_settings, storage).process_pending()
    assert summary.completed == 1
    assert storage.exists(old_result.storage_key) is False
    assert storage.exists(current.storage_key) is True


def test_a_failed_regeneration_queues_no_cleanup_job(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    """Preservation means the previous file is neither replaced nor deleted."""
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    new_task = make_task(project)
    db_session.commit()

    from app.tasks.generation_tasks import GenerationFailure

    def _fail(_context):
        raise GenerationFailure("GPU_OUT_OF_MEMORY", "CUDA out of memory")

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_fail,
    )

    assert outcome.status == "failed"
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(StorageCleanupJob).where(StorageCleanupJob.storage_key == old_result.storage_key)
        )
        is None
    )


def test_a_failed_pipeline_preserves_the_previous_current_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    make_result,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user(), status="COMPLETED")
    old_task = make_task(project, status="COMPLETED")
    old_result = make_result(project, old_task, is_current=True)
    new_task = make_task(project)
    db_session.commit()

    from app.tasks.generation_tasks import GenerationFailure

    def _fail(_context):
        raise GenerationFailure("GPU_OUT_OF_MEMORY", "CUDA out of memory")

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=new_task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=_fail,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "GPU_OUT_OF_MEMORY"
    db_session.expire_all()
    assert db_session.get(GenerationResult, old_result.id).is_current is True
    assert _count_results(db_session, project.id) == 1
    failed = db_session.get(GenerationTask, new_task.id)
    assert failed is not None and failed.status == "FAILED"
    assert failed.error_code == "GPU_OUT_OF_MEMORY"


def test_a_duplicate_delivery_does_not_create_a_second_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    artifact = _artifact(tmp_path)

    first = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: artifact,
    )
    second = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-b",
        pipeline=lambda _context: artifact,
    )

    assert first.status == "completed"
    assert second.status == "skipped"
    assert _count_results(db_session, project.id) == 1


def test_an_unreadable_artifact_fails_with_storage_write_failed(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    missing = PipelineArtifact(
        path=tmp_path / "missing.glb",
        sha256=SHA256_SAMPLE,
        file_size_bytes=10,
        metadata={},
    )

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: missing,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "STORAGE_WRITE_FAILED"
    assert _count_results(db_session, project.id) == 0


def test_an_artifact_with_a_changed_checksum_is_rejected(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    artifact = _artifact(tmp_path)
    tampered = PipelineArtifact(
        path=artifact.path,
        sha256="0" * 64,
        file_size_bytes=artifact.file_size_bytes,
        metadata={},
    )

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: tampered,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "RESULT_PERSISTENCE_FAILED"
    assert _count_results(db_session, project.id) == 0


def test_an_artifact_with_a_changed_size_is_rejected(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    artifact = _artifact(tmp_path)
    tampered = PipelineArtifact(
        path=artifact.path,
        sha256=artifact.sha256,
        file_size_bytes=artifact.file_size_bytes + 1,
        metadata={},
    )

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=LocalStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: tampered,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "RESULT_PERSISTENCE_FAILED"
    assert _count_results(db_session, project.id) == 0


def test_a_storage_failure_is_recorded_as_storage_write_failed(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    from app.core.exceptions import AppError

    class FailingStorage(LocalStorage):
        def save(self, source, key: str) -> int:
            raise AppError(503, "STORAGE_UNAVAILABLE", "The storage backend is unavailable.")

    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    artifact = _artifact(tmp_path)

    outcome = run_generation(
        settings=worker_settings,
        session_factory=session_factory,
        storage=FailingStorage(worker_settings.storage_root),
        task_id=task.id,
        task_type=TaskType.OBJECT,
        worker_id="worker-a",
        pipeline=lambda _context: artifact,
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "STORAGE_WRITE_FAILED"
    assert _count_results(db_session, project.id) == 0


def test_completion_honours_a_cancel_request_and_does_not_register_a_result(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    with session_factory() as session:
        service = TaskExecutionService(session, worker_settings)
        assert service.claim(task.id, worker_id="worker-a").claimed is True
        session.execute(
            GenerationTask.__table__.update()
            .where(GenerationTask.id == task.id)
            .values(cancel_requested_at=datetime.now(UTC))
        )
        session.commit()

    with session_factory() as session:
        service = TaskExecutionService(session, worker_settings)
        registered = service.complete_with_result(
            task.id,
            worker_id="worker-a",
            storage_key=result_storage_key(project.id, task.id),
            format="GLB",
            mime_type="model/gltf-binary",
            file_size_bytes=4,
            sha256=SHA256_SAMPLE,
            metadata={},
        )

    assert registered is False
    db_session.expire_all()
    assert db_session.get(GenerationTask, task.id).status == "CANCELLED"
    assert _count_results(db_session, project.id) == 0


def test_completion_rejects_a_task_owned_by_another_worker(
    db_session: Session,
    session_factory: sessionmaker[Session],
    make_user,
    make_project,
    make_task,
    worker_settings: Settings,
    tmp_path: Path,
) -> None:
    project = make_project(make_user())
    task = make_task(project)
    db_session.commit()
    with session_factory() as session:
        assert (
            TaskExecutionService(session, worker_settings)
            .claim(task.id, worker_id="worker-a")
            .claimed
            is True
        )

    with session_factory() as session:
        registered = TaskExecutionService(session, worker_settings).complete_with_result(
            task.id,
            worker_id="worker-b",
            storage_key=result_storage_key(project.id, task.id),
            format="GLB",
            mime_type="model/gltf-binary",
            file_size_bytes=4,
            sha256=SHA256_SAMPLE,
            metadata={},
        )

    assert registered is False
    assert _count_results(db_session, project.id) == 0
