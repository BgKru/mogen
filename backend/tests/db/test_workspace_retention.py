"""Scene workspace retention and temporary-storage monitoring (roadmap 8.5).

Traceability: 07 Section 15.7 ("Track temporary storage usage", "Remove obsolete
intermediate files safely", "Avoid cleaning directories still used by active
tasks"), 05 Section 12, INF-AC-19 (retention for file storage), TEST-AC-09.

The policy is deliberately conservative: only direct children of
``scene_work_dir`` whose name is a task UUID are considered, active tasks are
never touched, and deletion is queued as a ``DIRECTORY`` cleanup job so the
cleanup worker performs and retries it.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import StorageCleanupJob
from app.services.cleanup_service import CleanupService
from app.services.workspace_retention_service import SceneWorkspaceRetentionService
from app.storage import LocalStorage

pytestmark = [pytest.mark.integration]

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def retention_settings(tmp_path: Path) -> Settings:
    storage_root = tmp_path / "storage"
    return Settings(
        app_env="test",
        log_level="WARNING",
        storage_root=str(storage_root),
        scene_work_dir=str(storage_root / "work" / "scene"),
        scene_workspace_retention_hours=24,
        scene_workspace_sweep_interval_seconds=3600,
    )


def _workspace(settings: Settings, task_id: uuid.UUID, *, size: int = 8) -> Path:
    directory = Path(settings.scene_work_dir) / str(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "openmvs.bin").write_bytes(b"x" * size)
    return directory


def _task_with_finished_at(
    db_session: Session, make_user, make_project, make_task, *args, **kwargs
):
    project = make_project(make_user())
    task = make_task(project, *args, **kwargs)
    db_session.commit()
    return project, task


def _sweep(settings: Settings, session_factory: sessionmaker[Session]):
    with session_factory() as session:
        return SceneWorkspaceRetentionService(session, settings).prune(now=NOW)


def _jobs(db_session: Session) -> list[StorageCleanupJob]:
    db_session.expire_all()
    return list(db_session.scalars(select(StorageCleanupJob)).all())


def test_an_expired_terminal_workspace_is_queued_and_deleted_by_the_cleanup_worker(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _project, task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(hours=48),
    )
    workspace = _workspace(retention_settings, task.id, size=32)

    summary = _sweep(retention_settings, session_factory)

    assert summary.scanned == 1
    assert summary.queued == 1
    assert summary.bytes_total == 32
    jobs = _jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].target_type == "DIRECTORY"
    assert jobs[0].status == "PENDING"
    assert jobs[0].storage_key == f"work/scene/{task.id}"
    assert jobs[0].project_id == task.project_id
    assert workspace.is_dir()

    with session_factory() as session:
        completed = CleanupService(
            session, retention_settings, LocalStorage(retention_settings.storage_root)
        ).process_pending()

    assert completed.completed == 1
    assert workspace.exists() is False
    assert not any(workspace.parent.iterdir())


def test_a_recent_terminal_workspace_is_kept_for_diagnostics(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _project, task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(hours=1),
    )
    workspace = _workspace(retention_settings, task.id)

    summary = _sweep(retention_settings, session_factory)

    assert summary.retained == 1
    assert summary.queued == 0
    assert _jobs(db_session) == []
    assert workspace.is_dir()


def test_a_processing_workspace_is_never_touched(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _project, task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="PROCESSING",
    )
    workspace = _workspace(retention_settings, task.id)

    summary = _sweep(retention_settings, session_factory)

    assert summary.active == 1
    assert summary.queued == 0
    assert _jobs(db_session) == []
    assert workspace.is_dir()


def test_an_orphan_workspace_is_pruned_once_the_directory_is_old_enough(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
) -> None:
    orphan_id = uuid.uuid4()
    workspace = _workspace(retention_settings, orphan_id)
    old = (NOW - timedelta(hours=48)).timestamp()
    os.utime(workspace, (old, old))

    summary = _sweep(retention_settings, session_factory)

    assert summary.queued == 1
    jobs = _jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].project_id is None
    assert jobs[0].storage_key == f"work/scene/{orphan_id}"


def test_a_directory_that_is_not_a_task_id_is_ignored(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
) -> None:
    stray = Path(retention_settings.scene_work_dir) / "not-a-task"
    stray.mkdir(parents=True)
    (stray / "keep.txt").write_text("operator data", encoding="utf-8")
    old = (NOW - timedelta(days=30)).timestamp()
    os.utime(stray, (old, old))

    summary = _sweep(retention_settings, session_factory)

    assert summary.scanned == 0
    assert summary.queued == 0
    assert _jobs(db_session) == []
    assert (stray / "keep.txt").is_file()


def test_zero_retention_disables_pruning_but_still_reports_usage(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _project, task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(days=365),
    )
    _workspace(retention_settings, task.id, size=64)
    disabled = retention_settings.model_copy(update={"scene_workspace_retention_hours": 0})

    summary = _sweep(disabled, session_factory)

    assert summary.retained == 1
    assert summary.queued == 0
    assert summary.bytes_total == 64
    assert _jobs(db_session) == []


def test_a_second_sweep_does_not_queue_the_same_workspace_twice(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _project, task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(hours=48),
    )
    _workspace(retention_settings, task.id)

    first = _sweep(retention_settings, session_factory)
    second = _sweep(retention_settings, session_factory)

    assert first.queued == 1
    assert second.queued == 0
    assert second.already_queued == 1
    assert len(_jobs(db_session)) == 1


def test_usage_counters_cover_every_workspace(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    make_user,
    make_project,
    make_task,
) -> None:
    _p1, old_task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(hours=48),
    )
    _p2, fresh_task = _task_with_finished_at(
        db_session,
        make_user,
        make_project,
        make_task,
        status="FAILED",
        finished_at=NOW - timedelta(hours=1),
    )
    _workspace(retention_settings, old_task.id, size=100)
    _workspace(retention_settings, fresh_task.id, size=25)

    summary = _sweep(retention_settings, session_factory)

    assert summary.scanned == 2
    assert summary.bytes_total == 125
    assert summary.bytes_queued == 100
    assert summary.queued == 1
    assert summary.retained == 1


def test_a_workspace_outside_the_storage_root_is_not_queued(
    db_session: Session,
    session_factory: sessionmaker[Session],
    retention_settings: Settings,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside" / "work"
    outside.mkdir(parents=True)
    workspace = outside / str(uuid.uuid4())
    workspace.mkdir()
    old = (NOW - timedelta(days=30)).timestamp()
    os.utime(workspace, (old, old))
    settings = retention_settings.model_copy(update={"scene_work_dir": str(outside)})

    summary = _sweep(settings, session_factory)

    assert summary.queued == 0
    assert _jobs(db_session) == []
    assert workspace.is_dir()
