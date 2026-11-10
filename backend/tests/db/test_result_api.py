"""Result read/download API against PostgreSQL.

Traceability: BE-AC-19 (validated result management), BE-AC-20 (authorized
download), API-AC-09..12 (current result shape, no storage paths, ownership),
API-AC-13 (404 semantics), DB-AC-10..12 (current result), 06_object_generation.md
Section 14.3, TEST-AC-14 and roadmap 5.8.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import GenerationResult, GenerationTask, Project
from app.services.result_service import result_storage_key
from app.storage import LocalStorage

pytestmark = [pytest.mark.integration]

PROJECTS_URL = "/api/v1/projects"
SHA256_SAMPLE = "0123456789abcdef" * 4
GLB_BYTES = b"glTF\x02\x00\x00\x00" + b"validated-result-bytes"


def _csrf(client) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _create_project(client, *, name: str = "Result project") -> dict:
    response = client.post(
        PROJECTS_URL,
        json={"name": name, "type": "OBJECT"},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_result(
    session_factory: sessionmaker[Session],
    storage_root,
    project_id: uuid.UUID,
    *,
    body: bytes = GLB_BYTES,
    is_current: bool = True,
    write_file: bool = True,
    project_status: str = "COMPLETED",
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Insert a completed task and one result, writing its stored GLB."""
    storage = LocalStorage(storage_root)
    with session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        project.status = project_status
        task = GenerationTask(
            project_id=project_id,
            task_type="OBJECT",
            status="COMPLETED",
            idempotency_key=uuid.uuid4().hex,
            request_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
            parameters={"algorithm": "TripoSR", "output_format": "GLB"},
            finished_at=datetime.now(UTC),
        )
        session.add(task)
        session.flush()
        key = result_storage_key(project_id, task.id)
        result = GenerationResult(
            project_id=project_id,
            task_id=task.id,
            format="GLB",
            mime_type="model/gltf-binary",
            storage_key=key,
            file_size_bytes=len(body),
            sha256=SHA256_SAMPLE,
            result_metadata={"vertices_count": 42, "faces_count": 80, "meshes_count": 1},
            is_current=is_current,
        )
        session.add(result)
        session.commit()
        if write_file:
            storage.save(body, key)
        return task.id, result.id, key


def test_result_and_download_require_authentication(api_client, register_client) -> None:
    owner = register_client()
    project = _create_project(owner)
    anonymous = api_client

    for suffix in ("result", "download"):
        response = anonymous.get(f"{PROJECTS_URL}/{project['id']}/{suffix}")
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_result_is_404_when_the_project_has_no_result(register_client) -> None:
    client = register_client()
    project = _create_project(client)

    response = client.get(f"{PROJECTS_URL}/{project['id']}/result")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_NOT_FOUND"


def test_result_returns_contract_metadata_and_no_storage_key(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    client = register_client(storage_root=str(storage_root))
    project = _create_project(client)
    task_id, result_id, storage_key = _seed_result(
        session_factory, storage_root, uuid.UUID(project["id"])
    )

    response = client.get(f"{PROJECTS_URL}/{project['id']}/result")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == str(result_id)
    assert payload["project_id"] == project["id"]
    assert payload["task_id"] == str(task_id)
    assert payload["format"] == "GLB"
    assert payload["mime_type"] == "model/gltf-binary"
    assert payload["file_size_bytes"] == len(GLB_BYTES)
    assert payload["is_current"] is True
    assert payload["metadata"]["vertices_count"] == 42
    assert "storage_key" not in payload
    assert storage_key not in response.text
    assert str(storage_root) not in response.text


def test_download_streams_the_current_glb_with_documented_headers(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    client = register_client(storage_root=str(storage_root))
    project = _create_project(client, name="Object 42")
    _, _, _ = _seed_result(session_factory, storage_root, uuid.UUID(project["id"]))

    response = client.get(f"{PROJECTS_URL}/{project['id']}/download")

    assert response.status_code == 200, response.text
    assert response.content == GLB_BYTES
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-length"] == str(len(GLB_BYTES))
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="Object_42.glb"' in disposition
    assert "filename*=UTF-8''Object%2042.glb" in disposition


def test_download_reports_a_missing_stored_file(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    client = register_client(storage_root=str(storage_root))
    project = _create_project(client)
    _seed_result(session_factory, storage_root, uuid.UUID(project["id"]), write_file=False)

    response = client.get(f"{PROJECTS_URL}/{project['id']}/download")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_FILE_MISSING"


def test_result_and_download_are_scoped_to_the_owner(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    owner = register_client(email="owner@example.com", storage_root=str(storage_root))
    other = register_client(email="other@example.com", storage_root=str(storage_root))
    project = _create_project(owner)
    _seed_result(session_factory, storage_root, uuid.UUID(project["id"]))

    for suffix in ("result", "download"):
        response = other.get(f"{PROJECTS_URL}/{project['id']}/{suffix}")
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_soft_deleted_project_hides_its_result(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    client = register_client(storage_root=str(storage_root))
    project = _create_project(client)
    _seed_result(session_factory, storage_root, uuid.UUID(project["id"]))
    with session_factory() as session:
        row = session.get(Project, uuid.UUID(project["id"]))
        assert row is not None
        row.deleted_at = datetime.now(UTC)
        session.commit()

    response = client.get(f"{PROJECTS_URL}/{project['id']}/result")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_only_the_current_result_is_returned(
    register_client, session_factory: sessionmaker[Session], tmp_path
) -> None:
    storage_root = tmp_path / "storage"
    client = register_client(storage_root=str(storage_root))
    project = _create_project(client)
    project_id = uuid.UUID(project["id"])
    _seed_result(session_factory, storage_root, project_id, body=b"old", is_current=False)
    _, current_id, _ = _seed_result(session_factory, storage_root, project_id)

    response = client.get(f"{PROJECTS_URL}/{project_id}/result")

    assert response.status_code == 200
    assert response.json()["id"] == str(current_id)


def test_download_filename_handles_cyrillic_and_unsafe_characters(register_client) -> None:
    """The header is safe and carries the Unicode name through RFC 5987."""
    client = register_client()
    project = _create_project(client, name='Модель "кресла" 100%')

    # No result yet, so the handler cannot build the header. Use the helper
    # through the service unit path instead.
    from app.services.result_service import content_disposition

    header = content_disposition(project["name"])

    assert "\r" not in header and "\n" not in header
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in header
    assert "%D0%9C" in header  # Cyrillic is percent-encoded, not raw
    assert header.endswith(".glb")
