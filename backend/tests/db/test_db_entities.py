"""Entity, default and relationship tests for the ORM models.

Traceability: DB-AC-02, DB-AC-03..08, DB-AC-10, DB-AC-13..16, DB-AC-20,
DB-AC-23; 09_testing.md Section 8.2; TEST-AC-05.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.db.models import (
    GenerationResult,
    GenerationTask,
    GenerationTaskImage,
    OutboxMessage,
    Project,
    ProjectImage,
    StorageCleanupJob,
    User,
    UserSession,
)

pytestmark = pytest.mark.integration


def test_all_entities_can_be_created_and_read(
    db_session,
    make_user,
    make_session,
    make_project,
    make_image,
    make_task,
    make_task_image,
    make_result,
    make_cleanup_job,
    make_outbox_message,
) -> None:
    """Every MVP entity, including OutboxMessage, persists and round-trips."""
    user = make_user(email="owner@example.com")
    session = make_session(user)
    project = make_project(user, name="Chair", type="OBJECT", status="CREATED")
    image = make_image(project)
    task = make_task(project)
    make_task_image(task, image)
    result = make_result(project, task, is_current=True)
    cleanup = make_cleanup_job(project)
    outbox = make_outbox_message(task)

    db_session.expire_all()

    assert db_session.get(User, user.id).email == "owner@example.com"
    assert db_session.get(UserSession, session.id).user_id == user.id
    assert db_session.get(Project, project.id).name == "Chair"
    assert db_session.get(ProjectImage, image.id).sha256 == image.sha256
    assert db_session.get(GenerationTask, task.id).idempotency_key == task.idempotency_key
    assert db_session.get(GenerationTaskImage, (task.id, image.id)).position == 0
    assert db_session.get(GenerationResult, result.id).storage_key == result.storage_key
    assert db_session.get(StorageCleanupJob, cleanup.id).target_type == "DIRECTORY"
    assert db_session.get(OutboxMessage, outbox.id).aggregate_id == task.id


@pytest.mark.parametrize("project_type", ["OBJECT", "SCENE"])
def test_a_user_can_own_multiple_projects_of_each_type(
    make_user, make_project, project_type
) -> None:
    """DB-AC-05: both generation types are storable, with several per user."""
    owner = make_user()
    first = make_project(owner, name=f"{project_type} one", type=project_type)
    second = make_project(owner, name=f"{project_type} two", type=project_type)

    assert {first.type, second.type} == {project_type}
    assert {first.user_id, second.user_id} == {owner.id}


@pytest.mark.parametrize("mime_type", ["image/jpeg", "image/png"])
def test_both_supported_image_mime_types_are_accepted(
    make_user, make_project, make_image, mime_type
) -> None:
    """DB-AC-06: JPEG and PNG metadata are both supported."""
    owner = make_user()
    project = make_project(owner)
    image = make_image(project, mime_type=mime_type)

    assert image.mime_type == mime_type


def test_column_defaults_come_from_the_database(
    db_session,
    make_user,
    make_project,
    make_image,
    make_task,
    make_result,
    make_cleanup_job,
    make_outbox_message,
) -> None:
    """Defaults required by Section 5, 9, 11, 12 and 13 are applied."""
    user = make_user()
    project = make_project(user)
    image = make_image(project)
    task = make_task(project)
    result = make_result(project, task)
    cleanup = make_cleanup_job(project)
    outbox = make_outbox_message(task)

    assert user.is_active is True
    assert task.attempt_count == 0
    assert result.is_current is False
    assert cleanup.attempts == 0
    assert outbox.schema_version == 1
    assert outbox.attempts == 0
    assert outbox.status == "PENDING"
    assert image.position == 0


def test_timestamps_are_timezone_aware(make_user, make_project, make_task) -> None:
    """Section 3.3 requires TIMESTAMPTZ values returned as aware datetimes."""
    user = make_user()
    project = make_project(user)
    task = make_task(project)

    assert user.created_at.tzinfo is not None
    assert user.updated_at.tzinfo is not None
    assert project.created_at.tzinfo is not None
    assert task.created_at.tzinfo is not None


def test_relationships_are_navigable(
    db_session,
    make_user,
    make_session,
    make_project,
    make_image,
    make_task,
    make_task_image,
    make_result,
    make_cleanup_job,
) -> None:
    """Relationships required by Sections 5.3, 6.3, 7.5, 8.5, 9.9 and 12.4."""
    user = make_user()
    auth_session = make_session(user)
    project = make_project(user)
    image = make_image(project)
    task = make_task(project)
    task_image = make_task_image(task, image)
    result = make_result(project, task)
    cleanup = make_cleanup_job(project)

    db_session.expire_all()

    assert {item.id for item in user.sessions} == {auth_session.id}
    assert {item.id for item in user.projects} == {project.id}
    assert {item.id for item in project.images} == {image.id}
    assert {item.id for item in project.tasks} == {task.id}
    assert {item.id for item in project.results} == {result.id}
    assert {item.id for item in project.cleanup_jobs} == {cleanup.id}
    assert {item.image_id for item in task.task_images} == {image.id}
    assert task_image.project_id == project.id
    assert task.result is not None
    assert task.result.id == result.id
    assert image.task_images[0].task_id == task.id
    assert auth_session.user.id == user.id
    assert result.task.id == task.id
    assert result.project.id == project.id
    assert cleanup.project is not None
    assert cleanup.project.id == project.id


def test_outbox_message_survives_aggregate_deletion(
    db_session, make_user, make_project, make_task, make_outbox_message
) -> None:
    """OutboxMessage deliberately has no foreign key (Section 4.1, 13)."""
    user = make_user()
    project = make_project(user)
    task = make_task(project)
    outbox = make_outbox_message(task)

    db_session.execute(delete(Project).where(Project.id == project.id))
    db_session.flush()

    assert db_session.scalar(select(func.count()).select_from(GenerationTask)) == 0
    assert db_session.get(OutboxMessage, outbox.id) is not None
