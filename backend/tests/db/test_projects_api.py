"""Project API and authorization tests against PostgreSQL.

Traceability: BE-AC-06, BE-AC-07, BE-AC-08; API-AC-01, API-AC-02, API-AC-03,
API-AC-05, API-AC-06, API-AC-07, API-AC-15, API-AC-16, API-AC-17; DB-AC-05,
DB-AC-16; TEST-AC-03, TEST-AC-04, TEST-AC-05 (project transactions),
TEST-AC-06 (task cancellation on deletion). Contracts:
api_contracts.md Sections 5.9, 5.10, 7.1-7.4 and 11; 09_testing.md Sections
7.3, 8.4 and 8.5.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import GenerationTask, Project, StorageCleanupJob, User
from app.repositories import ImageRepository, ResultRepository, TaskRepository

pytestmark = [pytest.mark.integration, pytest.mark.api]

PROJECTS_URL = "/api/v1/projects"


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _create_project(
    client: TestClient,
    *,
    name: str = "Test project",
    project_type: str = "OBJECT",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = client.post(
        PROJECTS_URL,
        json={"name": name, "type": project_type},
        headers=_csrf(client) if headers is None else headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_image(session: Session, project_id: uuid.UUID, *, position: int = 0) -> None:
    ImageRepository(session).create(
        project_id=project_id,
        original_filename=f"photo-{position}.jpg",
        storage_key=f"projects/{project_id}/source/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=1024,
        sha256="0" * 64,
        width=640,
        height=480,
        position=position,
    )


def _add_task(
    session: Session, project_id: uuid.UUID, *, status: str = "PENDING"
) -> GenerationTask:
    return TaskRepository(session).create(
        project_id=project_id,
        task_type="OBJECT",
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="f" * 64,
        parameters={},
        status=status,
    )


def _add_current_result(session: Session, project_id: uuid.UUID, task_id: uuid.UUID) -> uuid.UUID:
    result = ResultRepository(session).create(
        project_id=project_id,
        task_id=task_id,
        format="GLB",
        mime_type="model/gltf-binary",
        storage_key=f"projects/{project_id}/results/{uuid.uuid4().hex}.glb",
        file_size_bytes=2048,
        sha256="1" * 64,
        metadata={"vertices_count": 100},
        is_current=True,
    )
    return result.id


@dataclass(frozen=True)
class _Seed:
    """Identifiers of a seeded project with a completed result and images."""

    project_id: uuid.UUID
    task_id: uuid.UUID
    result_id: uuid.UUID


def _seed_completed_project(session: Session, project: dict[str, Any]) -> _Seed:
    project_id = uuid.UUID(project["id"])
    _add_image(session, project_id, position=0)
    _add_image(session, project_id, position=1)
    task = _add_task(session, project_id, status="COMPLETED")
    result_id = _add_current_result(session, project_id, task.id)
    session.commit()
    return _Seed(project_id=project_id, task_id=task.id, result_id=result_id)


# --- creation (api_contracts 7.1) -----------------------------------------


def test_create_project_returns_the_documented_response(
    registered_client: TestClient, inspection_session: Session
) -> None:
    response = registered_client.post(
        PROJECTS_URL,
        json={"name": "  Chair  ", "type": "OBJECT"},
        headers=_csrf(registered_client),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "name",
        "type",
        "status",
        "source_image_count",
        "result_available",
        "current_result",
        "latest_task",
        "created_at",
        "updated_at",
    }
    assert body["name"] == "Chair"
    assert body["type"] == "OBJECT"
    assert body["status"] == "CREATED"
    assert body["source_image_count"] == 0
    assert body["result_available"] is False
    assert body["current_result"] is None
    assert body["latest_task"] is None
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == timedelta(0)

    owner = inspection_session.scalar(select(User).where(User.email == "user@example.com"))
    stored = inspection_session.get(Project, uuid.UUID(body["id"]))
    assert owner is not None
    assert stored is not None
    assert stored.user_id == owner.id
    assert stored.name == "Chair"
    assert stored.deleted_at is None
    # Creation must never start generation (Section 7.1).
    assert inspection_session.scalar(select(func.count()).select_from(GenerationTask)) == 0


def test_create_project_accepts_both_project_types(registered_client: TestClient) -> None:
    object_project = _create_project(registered_client, name="Object", project_type="OBJECT")
    scene_project = _create_project(registered_client, name="Scene", project_type="SCENE")

    assert object_project["type"] == "OBJECT"
    assert scene_project["type"] == "SCENE"
    assert object_project["id"] != scene_project["id"]


@pytest.mark.parametrize(
    ("name", "detail_code"),
    [
        ("", "STRING_TOO_SHORT"),
        ("   ", "STRING_TOO_SHORT"),
        ("x" * 151, "STRING_TOO_LONG"),
    ],
)
def test_create_project_rejects_invalid_names(
    registered_client: TestClient, name: str, detail_code: str
) -> None:
    response = registered_client.post(
        PROJECTS_URL,
        json={"name": name, "type": "OBJECT"},
        headers=_csrf(registered_client),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "PROJECT_NAME_INVALID"
    assert body["error"]["details"][0]["field"] == "name"
    assert body["error"]["details"][0]["code"] == detail_code


def test_create_project_rejects_an_unknown_type(registered_client: TestClient) -> None:
    response = registered_client.post(
        PROJECTS_URL,
        json={"name": "Chair", "type": "VIDEO"},
        headers=_csrf(registered_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_project_requires_a_name(registered_client: TestClient) -> None:
    response = registered_client.post(
        PROJECTS_URL, json={"type": "OBJECT"}, headers=_csrf(registered_client)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_project_requires_authentication(api_client: TestClient) -> None:
    response = api_client.post(PROJECTS_URL, json={"name": "Chair", "type": "OBJECT"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_create_project_requires_csrf(registered_client: TestClient) -> None:
    missing = registered_client.post(PROJECTS_URL, json={"name": "Chair", "type": "OBJECT"})
    mismatched = registered_client.post(
        PROJECTS_URL,
        json={"name": "Chair", "type": "OBJECT"},
        headers={"X-CSRF-Token": "wrong"},
    )

    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


# --- listing (api_contracts 7.2) ------------------------------------------


def test_list_returns_only_the_callers_active_projects(
    registered_client: TestClient, register_client: Callable[..., TestClient]
) -> None:
    mine = _create_project(registered_client, name="Mine")
    other_client = register_client(email="other@example.com")
    _create_project(other_client, name="Theirs")

    response = registered_client.get(PROJECTS_URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total_count", "limit", "offset"}
    assert body["total_count"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [mine["id"]]
    assert other_client.get(PROJECTS_URL).json()["total_count"] == 1


def test_list_excludes_soft_deleted_projects(
    registered_client: TestClient, inspection_session: Session
) -> None:
    _create_project(registered_client, name="Keep")
    deleted = _create_project(registered_client, name="Gone")
    inspection_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(deleted["id"]))
        .values(deleted_at=datetime.now(UTC))
    )
    inspection_session.commit()

    body = registered_client.get(PROJECTS_URL).json()

    assert body["total_count"] == 1
    assert [item["name"] for item in body["items"]] == ["Keep"]


def test_list_paginates_with_a_total_count(registered_client: TestClient) -> None:
    created = {
        _create_project(registered_client, name=f"Project {index}")["id"] for index in range(5)
    }

    first_page = registered_client.get(PROJECTS_URL, params={"limit": 2, "offset": 0}).json()
    last_page = registered_client.get(PROJECTS_URL, params={"limit": 2, "offset": 4}).json()

    assert first_page["limit"] == 2
    assert first_page["offset"] == 0
    assert first_page["total_count"] == 5
    assert len(first_page["items"]) == 2
    assert last_page["total_count"] == 5
    assert last_page["offset"] == 4
    assert len(last_page["items"]) == 1
    paged_ids = [item["id"] for item in first_page["items"] + last_page["items"]]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids).issubset(created)


def test_list_caps_the_limit_at_the_configured_maximum(
    register_client: Callable[..., TestClient],
) -> None:
    client = register_client(email="paged@example.com", max_page_size=2)
    for index in range(3):
        _create_project(client, name=f"Project {index}")

    body = client.get(PROJECTS_URL, params={"limit": 100}).json()

    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["total_count"] == 3


def test_list_sorts_by_creation_date(
    registered_client: TestClient, inspection_session: Session
) -> None:
    projects = [
        _create_project(registered_client, name=name) for name in ("First", "Second", "Third")
    ]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, project in enumerate(projects):
        inspection_session.execute(
            update(Project)
            .where(Project.id == uuid.UUID(project["id"]))
            .values(created_at=base + timedelta(minutes=index))
        )
    inspection_session.commit()

    descending = registered_client.get(PROJECTS_URL).json()
    ascending = registered_client.get(PROJECTS_URL, params={"sort": "created_at_asc"}).json()

    assert [item["name"] for item in descending["items"]] == ["Third", "Second", "First"]
    assert [item["name"] for item in ascending["items"]] == ["First", "Second", "Third"]


def test_list_filters_by_type_and_status(
    registered_client: TestClient, inspection_session: Session
) -> None:
    object_project = _create_project(registered_client, name="Object", project_type="OBJECT")
    _create_project(registered_client, name="Scene", project_type="SCENE")
    inspection_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(object_project["id"]))
        .values(status="COMPLETED")
    )
    inspection_session.commit()

    by_type = registered_client.get(PROJECTS_URL, params={"type": "SCENE"}).json()
    by_status = registered_client.get(PROJECTS_URL, params={"status": "COMPLETED"}).json()
    combined = registered_client.get(
        PROJECTS_URL, params={"type": "SCENE", "status": "COMPLETED"}
    ).json()

    assert [item["name"] for item in by_type["items"]] == ["Scene"]
    assert by_type["total_count"] == 1
    assert [item["name"] for item in by_status["items"]] == ["Object"]
    assert combined["total_count"] == 0


def test_list_includes_nested_summaries(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="With result")
    seed = _seed_completed_project(inspection_session, project)

    response = registered_client.get(PROJECTS_URL)

    item = response.json()["items"][0]
    assert item["source_image_count"] == 2
    assert item["result_available"] is True
    assert item["current_result"]["id"] == str(seed.result_id)
    assert item["current_result"]["format"] == "GLB"
    assert item["current_result"]["file_size_bytes"] == 2048
    assert item["current_result"]["created_at"]
    assert item["latest_task"]["id"] == str(seed.task_id)
    assert item["latest_task"]["status"] == "COMPLETED"
    # No storage keys or physical paths may leak (API-AC-16).
    assert "storage_key" not in response.text
    assert f"projects/{seed.project_id}/" not in response.text


def test_result_availability_is_independent_of_project_status(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Regeneration failed")
    seed = _seed_completed_project(inspection_session, project)
    inspection_session.execute(
        update(Project).where(Project.id == seed.project_id).values(status="FAILED")
    )
    inspection_session.commit()

    item = registered_client.get(PROJECTS_URL).json()["items"][0]

    assert item["status"] == "FAILED"
    assert item["result_available"] is True
    assert item["current_result"]["id"] == str(seed.result_id)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"offset": -1},
        {"type": "VIDEO"},
        {"status": "DONE"},
        {"sort": "name"},
    ],
)
def test_list_rejects_invalid_query_parameters(
    registered_client: TestClient, params: dict[str, Any]
) -> None:
    response = registered_client.get(PROJECTS_URL, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(PROJECTS_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


# --- detail (api_contracts 7.3) -------------------------------------------


def test_get_returns_the_project_with_nested_summaries(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Detail")
    seed = _seed_completed_project(inspection_session, project)

    response = registered_client.get(f"{PROJECTS_URL}/{seed.project_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(seed.project_id)
    assert body["name"] == "Detail"
    assert body["source_image_count"] == 2
    assert body["result_available"] is True
    assert body["current_result"]["format"] == "GLB"
    assert body["latest_task"]["status"] == "COMPLETED"


def test_get_returns_404_for_another_users_project(
    registered_client: TestClient, register_client: Callable[..., TestClient]
) -> None:
    other_client = register_client(email="other@example.com")
    project = _create_project(other_client, name="Theirs")

    response = registered_client.get(f"{PROJECTS_URL}/{project['id']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert registered_client.get(PROJECTS_URL).json()["total_count"] == 0


def test_get_returns_404_for_deleted_and_unknown_projects(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Gone")
    inspection_session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project["id"]))
        .values(deleted_at=datetime.now(UTC))
    )
    inspection_session.commit()

    deleted = registered_client.get(f"{PROJECTS_URL}/{project['id']}")
    unknown = registered_client.get(f"{PROJECTS_URL}/{uuid.uuid4()}")
    invalid = registered_client.get(f"{PROJECTS_URL}/not-a-uuid")

    assert deleted.status_code == 404
    assert unknown.status_code == 404
    assert deleted.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert invalid.status_code == 422


def test_get_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(f"{PROJECTS_URL}/{uuid.uuid4()}")

    assert response.status_code == 401


# --- deletion (api_contracts 7.4) -----------------------------------------


def test_delete_soft_deletes_cancels_pending_tasks_and_schedules_cleanup(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Queued")
    project_id = uuid.UUID(project["id"])
    pending_task = _add_task(inspection_session, project_id, status="PENDING")
    completed_task = _add_task(inspection_session, project_id, status="COMPLETED")
    inspection_session.commit()

    response = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers=_csrf(registered_client)
    )

    assert response.status_code == 202
    assert response.json() == {
        "project_id": str(project_id),
        "deletion_status": "PENDING",
    }

    inspection_session.expire_all()
    stored = inspection_session.get(Project, project_id)
    assert stored is not None
    assert stored.deleted_at is not None

    pending_row = inspection_session.get(GenerationTask, pending_task.id)
    completed_row = inspection_session.get(GenerationTask, completed_task.id)
    assert pending_row is not None
    assert pending_row.status == "CANCELLED"
    assert pending_row.finished_at is not None
    assert completed_row is not None
    assert completed_row.status == "COMPLETED"
    assert completed_row.finished_at is None

    job = inspection_session.scalar(
        select(StorageCleanupJob).where(StorageCleanupJob.project_id == project_id)
    )
    assert job is not None
    assert job.storage_key == f"projects/{project_id}/"
    assert job.target_type == "DIRECTORY"
    assert job.status == "PENDING"
    assert job.attempts == 0

    # The project disappears immediately from ordinary retrieval and listing.
    assert registered_client.get(f"{PROJECTS_URL}/{project_id}").status_code == 404
    assert registered_client.get(PROJECTS_URL).json()["total_count"] == 0


def test_delete_requests_cooperative_cancellation_of_a_processing_task(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Running")
    project_id = uuid.UUID(project["id"])
    processing_task = _add_task(inspection_session, project_id, status="PROCESSING")
    inspection_session.commit()

    response = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers=_csrf(registered_client)
    )

    assert response.status_code == 202
    inspection_session.expire_all()
    task_row = inspection_session.get(GenerationTask, processing_task.id)
    assert task_row is not None
    assert task_row.status == "PROCESSING"
    assert task_row.cancel_requested_at is not None


def test_repeated_delete_returns_404_and_creates_no_duplicate_cleanup_job(
    registered_client: TestClient, inspection_session: Session
) -> None:
    project = _create_project(registered_client, name="Delete twice")
    project_id = uuid.UUID(project["id"])

    first = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers=_csrf(registered_client)
    )
    second = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers=_csrf(registered_client)
    )

    assert first.status_code == 202
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    job_count = inspection_session.scalar(
        select(func.count())
        .select_from(StorageCleanupJob)
        .where(StorageCleanupJob.project_id == project_id)
    )
    assert job_count == 1


def test_delete_is_scoped_to_the_owner(
    registered_client: TestClient,
    register_client: Callable[..., TestClient],
    inspection_session: Session,
) -> None:
    other_client = register_client(email="other@example.com")
    project = _create_project(other_client, name="Theirs")
    project_id = uuid.UUID(project["id"])
    task = _add_task(inspection_session, project_id, status="PENDING")
    inspection_session.commit()

    response = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers=_csrf(registered_client)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    inspection_session.expire_all()
    stored = inspection_session.get(Project, project_id)
    task_row = inspection_session.get(GenerationTask, task.id)
    assert stored is not None
    assert stored.deleted_at is None
    assert task_row is not None
    assert task_row.status == "PENDING"
    assert (
        inspection_session.scalar(
            select(func.count())
            .select_from(StorageCleanupJob)
            .where(StorageCleanupJob.project_id == project_id)
        )
        == 0
    )


def test_delete_requires_csrf(registered_client: TestClient) -> None:
    project = _create_project(registered_client, name="Protected")
    project_id = uuid.UUID(project["id"])

    missing = registered_client.delete(f"{PROJECTS_URL}/{project_id}")
    mismatched = registered_client.delete(
        f"{PROJECTS_URL}/{project_id}", headers={"X-CSRF-Token": "wrong"}
    )

    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert registered_client.get(f"{PROJECTS_URL}/{project_id}").status_code == 200


def test_delete_requires_authentication(api_client: TestClient) -> None:
    response = api_client.delete(f"{PROJECTS_URL}/{uuid.uuid4()}")

    assert response.status_code == 401


# --- documented contract (API-AC-01, API-AC-17) ---------------------------


def test_openapi_documents_the_project_contract(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()
    paths = schema["paths"]

    assert {"get", "post"} <= set(paths["/api/v1/projects"])
    assert {"get", "delete"} <= set(paths["/api/v1/projects/{project_id}"])
    assert "201" in paths["/api/v1/projects"]["post"]["responses"]
    assert "202" in paths["/api/v1/projects/{project_id}"]["delete"]["responses"]
    parameters = {parameter["name"] for parameter in paths["/api/v1/projects"]["get"]["parameters"]}
    assert {"limit", "offset", "type", "status", "sort"} <= parameters
