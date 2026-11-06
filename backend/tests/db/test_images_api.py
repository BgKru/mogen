"""Image API tests against PostgreSQL: upload, listing, content and deletion.

Traceability: BE-AC-06 (ownership), BE-AC-09, BE-AC-10, BE-AC-11, BE-AC-12;
API-AC-05, API-AC-06, API-AC-08, API-AC-15, API-AC-16; DB-AC-06, DB-AC-14,
DB-AC-15, DB-AC-16; TEST-AC-03, TEST-AC-04, TEST-AC-09.
Contracts: api_contracts.md Sections 5.6, 8.1-8.4, 11 and 12.3;
04_backend_specification.md Sections 10.1-10.9; 09_testing.md Section 7.4.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.models import Project, ProjectImage, StorageCleanupJob
from app.repositories import CleanupJobRepository, ImageRepository, TaskRepository

pytestmark = [pytest.mark.integration, pytest.mark.api]

IMAGES_URL = "/api/v1/projects/{project_id}/images"
IMAGE_URL = "/api/v1/projects/{project_id}/images/{image_id}"
CONTENT_URL = "/api/v1/projects/{project_id}/images/{image_id}/content"
PROJECTS_URL = "/api/v1/projects"


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "the client has no CSRF cookie"
    return {"X-CSRF-Token": token}


def _image_bytes(image_format: str = "JPEG", *, size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(12, 34, 56)).save(buffer, format=image_format)
    return buffer.getvalue()


def _create_project(client: TestClient, *, project_type: str = "OBJECT") -> dict[str, Any]:
    response = client.post(
        PROJECTS_URL,
        json={"name": f"Project {uuid.uuid4().hex[:8]}", "type": project_type},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(
    client: TestClient,
    project_id: str,
    *,
    content: bytes | None = None,
    filename: str = "photo.jpg",
    content_type: str = "image/jpeg",
    with_csrf: bool = True,
):
    return client.post(
        IMAGES_URL.format(project_id=project_id),
        files={
            "file": (filename, content if content is not None else _image_bytes(), content_type)
        },
        headers=_csrf(client) if with_csrf else {},
    )


def _stored_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def _content_url(project_id: Any, image_id: Any) -> str:
    return CONTENT_URL.format(project_id=project_id, image_id=image_id)


def _image_url(project_id: Any, image_id: Any) -> str:
    return IMAGE_URL.format(project_id=project_id, image_id=image_id)


def _image_row(session: Session, image_id: str) -> ProjectImage | None:
    """Re-read an image row after an API call, bypassing the session cache."""
    session.expire_all()
    return session.get(ProjectImage, uuid.UUID(image_id))


def _cleanup_jobs(session: Session, project_id: str) -> list[StorageCleanupJob]:
    """Re-read a project's cleanup jobs after an API call."""
    session.expire_all()
    return list(CleanupJobRepository(session).list_for_project(uuid.UUID(project_id)))


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def make_client(register_client, storage_root: Path):
    """Register a user whose API client stores files under the test root."""

    def _make(*, email: str | None = None, **overrides: Any) -> TestClient:
        return register_client(
            email=email or f"user-{uuid.uuid4().hex}@example.com",
            storage_root=storage_root,
            **overrides,
        )

    return _make


# --- upload (api_contracts 8.1) -------------------------------------------


def test_upload_persists_metadata_and_the_stored_file(
    make_client, storage_root: Path, inspection_session: Session
) -> None:
    client = make_client()
    project = _create_project(client)
    payload = _image_bytes()

    response = _upload(client, project["id"], content=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "project_id",
        "original_filename",
        "mime_type",
        "file_size_bytes",
        "width",
        "height",
        "position",
        "created_at",
    }
    assert body["project_id"] == project["id"]
    assert body["original_filename"] == "photo.jpg"
    assert body["mime_type"] == "image/jpeg"
    assert body["file_size_bytes"] == len(payload)
    assert (body["width"], body["height"]) == (8, 8)
    assert body["position"] == 0
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.tzinfo is not None
    assert "storage_key" not in response.text

    stored = inspection_session.get(ProjectImage, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.project_id == uuid.UUID(project["id"])
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.storage_key == f"projects/{project['id']}/source/{body['id']}.jpg"
    file_path = Path(storage_root).resolve() / stored.storage_key
    assert file_path.read_bytes() == payload

    detail = client.get(f"{PROJECTS_URL}/{project['id']}").json()
    assert detail["source_image_count"] == 1


@pytest.mark.parametrize(
    ("filename", "image_format", "content_type", "mime_type", "suffix"),
    [
        ("photo.jpg", "JPEG", "image/jpeg", "image/jpeg", ".jpg"),
        ("photo.jpeg", "JPEG", "image/jpeg", "image/jpeg", ".jpg"),
        ("photo.png", "PNG", "image/png", "image/png", ".png"),
    ],
)
def test_upload_accepts_supported_formats(
    make_client,
    storage_root: Path,
    filename: str,
    image_format: str,
    content_type: str,
    mime_type: str,
    suffix: str,
) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(
        client,
        project["id"],
        content=_image_bytes(image_format),
        filename=filename,
        content_type=content_type,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mime_type"] == mime_type
    stored = [path for path in _stored_files(storage_root) if path.name.endswith(suffix)]
    assert len(stored) == 1


def test_upload_sanitizes_the_original_filename(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(client, project["id"], filename="../../etc/photo.jpg")

    assert response.status_code == 201, response.text
    assert response.json()["original_filename"] == "photo.jpg"


def test_upload_requires_csrf(make_client, storage_root: Path) -> None:
    client = make_client()
    project = _create_project(client)

    missing = _upload(client, project["id"], with_csrf=False)
    mismatched = client.post(
        IMAGES_URL.format(project_id=project["id"]),
        files={"file": ("photo.jpg", _image_bytes(), "image/jpeg")},
        headers={"X-CSRF-Token": "wrong"},
    )

    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert _stored_files(storage_root) == []


def test_upload_requires_authentication(api_client: TestClient) -> None:
    response = api_client.post(
        IMAGES_URL.format(project_id=uuid.uuid4()),
        files={"file": ("photo.jpg", _image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 401


def test_upload_returns_404_for_another_users_project(make_client, storage_root: Path) -> None:
    owner = make_client()
    stranger = make_client(email="stranger@example.com")
    project = _create_project(owner)

    response = _upload(stranger, project["id"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert _stored_files(storage_root) == []


def test_upload_returns_404_for_an_unknown_project(make_client) -> None:
    client = make_client()

    response = _upload(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# --- upload validation (04 Section 10.3) ----------------------------------


def test_upload_rejects_an_unsupported_extension(make_client, storage_root: Path) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(
        client,
        project["id"],
        content=_image_bytes("PNG"),
        filename="photo.gif",
        content_type="image/png",
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "INVALID_IMAGE_FORMAT"
    assert _stored_files(storage_root) == []


def test_upload_rejects_an_unsupported_declared_type(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(client, project["id"], content_type="text/plain")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "INVALID_IMAGE_FORMAT"


def test_upload_rejects_a_format_mismatch(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(
        client,
        project["id"],
        content=_image_bytes("PNG"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    assert response.status_code == 415


def test_upload_rejects_corrupt_content(make_client, storage_root: Path) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(client, project["id"], content=b"not-an-image")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE_CONTENT"
    assert _stored_files(storage_root) == []


def test_upload_rejects_an_empty_file(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    response = _upload(client, project["id"], content=b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE_CONTENT"


def test_upload_rejects_a_file_above_the_size_limit(make_client, storage_root: Path) -> None:
    client = make_client(max_upload_size_mb=1)
    project = _create_project(client)

    response = _upload(client, project["id"], content=b"x" * (1024 * 1024 + 1))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"
    assert _stored_files(storage_root) == []


def test_upload_rejects_an_image_above_the_dimension_limit(make_client, storage_root: Path) -> None:
    client = make_client(max_image_dimension=8)
    project = _create_project(client)

    response = _upload(client, project["id"], content=_image_bytes(size=(16, 16)))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMAGE_DIMENSIONS_EXCEEDED"
    assert _stored_files(storage_root) == []


# --- project image rules (04 Sections 10.4 and 10.5) ----------------------


def test_object_project_accepts_only_one_image(make_client, storage_root: Path) -> None:
    client = make_client()
    project = _create_project(client, project_type="OBJECT")

    first = _upload(client, project["id"])
    second = _upload(client, project["id"], content=_image_bytes(size=(9, 9)))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IMAGE_COUNT_EXCEEDED"
    assert len(_stored_files(storage_root)) == 1
    assert client.get(IMAGES_URL.format(project_id=project["id"])).json()["total_count"] == 1


def test_scene_project_enforces_the_maximum_image_count(make_client, storage_root: Path) -> None:
    client = make_client(max_scene_images=2, min_scene_images=1)
    project = _create_project(client, project_type="SCENE")

    responses = [
        _upload(client, project["id"], content=_image_bytes(size=(8, 8))) for _ in range(2)
    ]
    rejected = _upload(client, project["id"], content=_image_bytes(size=(9, 9)))

    assert [response.status_code for response in responses] == [201, 201]
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "IMAGE_COUNT_EXCEEDED"
    assert len(_stored_files(storage_root)) == 2


@pytest.mark.parametrize(
    ("project_status", "task_status"),
    [
        ("PENDING", None),
        ("PROCESSING", None),
        ("CREATED", "PENDING"),
        ("CREATED", "PROCESSING"),
    ],
)
def test_upload_is_rejected_while_generation_holds_the_project(
    make_client,
    storage_root: Path,
    inspection_session: Session,
    project_status: str,
    task_status: str | None,
) -> None:
    client = make_client()
    project = _create_project(client)
    project_id = uuid.UUID(project["id"])
    if task_status is not None:
        TaskRepository(inspection_session).create(
            project_id=project_id,
            task_type="OBJECT",
            idempotency_key=uuid.uuid4().hex,
            request_fingerprint="f" * 64,
            parameters={},
            status=task_status,
        )
    if project_status != "CREATED":
        inspection_session.execute(
            update(Project).where(Project.id == project_id).values(status=project_status)
        )
    inspection_session.commit()

    response = _upload(client, project["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"
    assert _stored_files(storage_root) == []


def test_failed_upload_leaves_the_project_usable(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    rejected = _upload(client, project["id"], content=b"not-an-image")
    assert rejected.status_code == 400
    assert client.get(f"{PROJECTS_URL}/{project['id']}").json()["status"] == "CREATED"

    accepted = _upload(client, project["id"])

    assert accepted.status_code == 201
    assert client.get(f"{PROJECTS_URL}/{project['id']}").json()["status"] == "CREATED"


def test_failed_metadata_write_removes_the_stored_file(
    make_client, storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    project = _create_project(client)

    def failing_create(self: ImageRepository, **kwargs: object) -> None:
        raise IntegrityError("INSERT INTO project_images", {}, Exception("duplicate storage key"))

    monkeypatch.setattr(ImageRepository, "create", failing_create)

    with pytest.raises(IntegrityError):
        _upload(client, project["id"])

    assert _stored_files(storage_root) == []


def test_cleanup_failure_does_not_mask_the_database_error(
    make_client, storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    project = _create_project(client)

    def failing_create(self: ImageRepository, **kwargs: object) -> None:
        raise IntegrityError("INSERT INTO project_images", {}, Exception("duplicate storage key"))

    def failing_delete(self: object, key: str) -> None:
        raise AppError(503, "STORAGE_UNAVAILABLE", "The storage backend is unavailable.")

    monkeypatch.setattr(ImageRepository, "create", failing_create)
    monkeypatch.setattr("app.storage.local.LocalStorage.delete", failing_delete)

    with pytest.raises(IntegrityError):
        _upload(client, project["id"])

    # The original failure is reported even though the cleanup also failed.
    assert len(_stored_files(storage_root)) == 1


# --- listing (api_contracts 8.2) ------------------------------------------


def test_list_returns_metadata_in_upload_order(make_client) -> None:
    client = make_client()
    project = _create_project(client, project_type="SCENE")
    first = _upload(client, project["id"], content=_image_bytes(size=(8, 8))).json()
    second = _upload(client, project["id"], content=_image_bytes(size=(9, 9))).json()

    response = client.get(IMAGES_URL.format(project_id=project["id"]))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total_count"}
    assert body["total_count"] == 2
    assert [item["id"] for item in body["items"]] == [first["id"], second["id"]]
    assert [item["position"] for item in body["items"]] == [0, 1]
    assert "storage_key" not in response.text


def test_list_of_an_empty_project_is_empty(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    body = client.get(IMAGES_URL.format(project_id=project["id"])).json()

    assert body == {"items": [], "total_count": 0}


def test_list_is_restricted_to_the_owner(make_client) -> None:
    owner = make_client()
    stranger = make_client(email="stranger@example.com")
    project = _create_project(owner)
    _upload(owner, project["id"])

    foreign = stranger.get(IMAGES_URL.format(project_id=project["id"]))
    unknown = stranger.get(IMAGES_URL.format(project_id=uuid.uuid4()))

    assert foreign.status_code == 404
    assert unknown.status_code == 404
    assert foreign.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_list_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(IMAGES_URL.format(project_id=uuid.uuid4()))

    assert response.status_code == 401


# --- content retrieval (api_contracts 8.3) --------------------------------


def test_content_returns_the_stored_jpeg(
    make_client, storage_root: Path, inspection_session: Session
) -> None:
    client = make_client()
    project = _create_project(client)
    payload = _image_bytes("JPEG", size=(12, 10))
    image = _upload(client, project["id"], content=payload).json()

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"] == 'inline; filename="photo.jpg"'
    assert response.headers["cache-control"] == "private"
    assert response.headers["x-content-type-options"] == "nosniff"

    row = _image_row(inspection_session, image["id"])
    assert row is not None
    headers = str(response.headers)
    assert row.storage_key not in headers
    assert str(Path(storage_root).resolve()) not in headers
    assert row.storage_key not in response.text


@pytest.mark.parametrize(
    ("filename", "image_format", "content_type", "mime_type"),
    [
        ("photo.jpg", "JPEG", "image/jpeg", "image/jpeg"),
        ("photo.png", "PNG", "image/png", "image/png"),
    ],
)
def test_content_uses_the_verified_mime_type(
    make_client,
    filename: str,
    image_format: str,
    content_type: str,
    mime_type: str,
) -> None:
    client = make_client()
    project = _create_project(client)
    payload = _image_bytes(image_format, size=(9, 7))
    image = _upload(
        client,
        project["id"],
        content=payload,
        filename=filename,
        content_type=content_type,
    ).json()

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == mime_type
    assert response.content == payload


def test_content_sanitizes_a_stored_filename(make_client, inspection_session: Session) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    row = _image_row(inspection_session, image["id"])
    assert row is not None
    row.original_filename = "evil\r\nX-Injected: yes.jpg"
    inspection_session.commit()

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert response.headers.get("x-injected") is None


def test_content_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(_content_url(uuid.uuid4(), uuid.uuid4()))

    assert response.status_code == 401
    assert "error" in response.json()


def test_content_is_restricted_to_the_owner(make_client) -> None:
    owner = make_client()
    stranger = make_client(email="stranger@example.com")
    project = _create_project(owner)
    image = _upload(owner, project["id"]).json()

    foreign = stranger.get(_content_url(project["id"], image["id"]))
    unknown_project = stranger.get(_content_url(uuid.uuid4(), image["id"]))

    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert unknown_project.status_code == 404


def test_content_returns_404_for_an_unknown_image(make_client) -> None:
    client = make_client()
    project = _create_project(client)

    response = client.get(_content_url(project["id"], uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"


def test_content_returns_404_for_an_image_of_another_project(make_client) -> None:
    client = make_client()
    first = _create_project(client)
    second = _create_project(client)
    image = _upload(client, first["id"]).json()

    response = client.get(_content_url(second["id"], image["id"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"


def test_content_returns_404_for_a_deleted_project(make_client) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    deleted = client.delete(f"{PROJECTS_URL}/{project['id']}", headers=_csrf(client))
    assert deleted.status_code == 202

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_content_returns_404_when_the_stored_file_is_missing(
    make_client, storage_root: Path, inspection_session: Session
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    row = _image_row(inspection_session, image["id"])
    assert row is not None
    (Path(storage_root).resolve() / row.storage_key).unlink()

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"


def test_content_reports_a_storage_failure_as_storage_unavailable(
    make_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()

    def failing_open(self: object, key: str) -> None:
        raise AppError(503, "STORAGE_UNAVAILABLE", "The storage backend is unavailable.")

    # The storage layer already maps filesystem failures to 503
    # (tests/unit/test_storage.py); this asserts the endpoint keeps that
    # documented contract instead of turning it into a generic 500.
    monkeypatch.setattr("app.storage.local.LocalStorage.open", failing_open)

    response = client.get(_content_url(project["id"], image["id"]))

    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "STORAGE_UNAVAILABLE"
    assert body["request_id"]


# --- deletion (api_contracts 8.4) -----------------------------------------


def test_delete_removes_metadata_and_schedules_a_file_cleanup_job(
    make_client, storage_root: Path, inspection_session: Session
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    row = _image_row(inspection_session, image["id"])
    assert row is not None
    storage_key = row.storage_key

    response = client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 204
    assert response.content == b""
    assert _image_row(inspection_session, image["id"]) is None

    jobs = _cleanup_jobs(inspection_session, project["id"])
    assert len(jobs) == 1
    job = jobs[0]
    assert job.storage_key == storage_key
    assert job.target_type == "FILE"
    assert job.status == "PENDING"
    assert job.project_id == uuid.UUID(project["id"])

    # The file is removed by the cleanup worker, not inside the request
    # (05_database_specification.md Section 12); the API stops serving it
    # immediately because the metadata is gone.
    assert (Path(storage_root).resolve() / storage_key).exists()
    gone = client.get(_content_url(project["id"], image["id"]))
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "IMAGE_NOT_FOUND"
    assert client.get(IMAGES_URL.format(project_id=project["id"])).json() == {
        "items": [],
        "total_count": 0,
    }
    detail = client.get(f"{PROJECTS_URL}/{project['id']}").json()
    assert detail["source_image_count"] == 0


def test_delete_keeps_the_remaining_scene_images(make_client) -> None:
    client = make_client()
    project = _create_project(client, project_type="SCENE")
    first = _upload(client, project["id"], content=_image_bytes(size=(8, 8))).json()
    second = _upload(client, project["id"], content=_image_bytes(size=(9, 9))).json()

    response = client.delete(_image_url(project["id"], first["id"]), headers=_csrf(client))

    assert response.status_code == 204
    body = client.get(IMAGES_URL.format(project_id=project["id"])).json()
    assert [item["id"] for item in body["items"]] == [second["id"]]
    # Positions are stable: deletion does not renumber the survivors.
    assert body["items"][0]["position"] == 1
    assert client.get(_content_url(project["id"], second["id"])).status_code == 200


def test_deleting_the_object_image_allows_a_replacement(make_client) -> None:
    client = make_client()
    project = _create_project(client, project_type="OBJECT")
    image = _upload(client, project["id"]).json()

    assert (
        client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client)).status_code
        == 204
    )
    replacement = _upload(client, project["id"], content=_image_bytes(size=(9, 9)))

    assert replacement.status_code == 201
    assert client.get(IMAGES_URL.format(project_id=project["id"])).json()["total_count"] == 1


def test_repeated_deletion_returns_404(make_client, inspection_session: Session) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    url = _image_url(project["id"], image["id"])

    first = client.delete(url, headers=_csrf(client))
    second = client.delete(url, headers=_csrf(client))

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "IMAGE_NOT_FOUND"
    # A single cleanup job survives the repeat request.
    assert len(_cleanup_jobs(inspection_session, project["id"])) == 1


def test_delete_requires_csrf(make_client, inspection_session: Session) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()

    response = client.delete(_image_url(project["id"], image["id"]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


def test_delete_requires_authentication(api_client: TestClient) -> None:
    response = api_client.delete(_image_url(uuid.uuid4(), uuid.uuid4()))

    assert response.status_code == 401


def test_delete_is_restricted_to_the_owner(make_client, inspection_session: Session) -> None:
    owner = make_client()
    stranger = make_client(email="stranger@example.com")
    project = _create_project(owner)
    image = _upload(owner, project["id"]).json()

    response = stranger.delete(_image_url(project["id"], image["id"]), headers=_csrf(stranger))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


def test_delete_returns_404_for_an_image_of_another_project(
    make_client, inspection_session: Session
) -> None:
    client = make_client()
    first = _create_project(client)
    second = _create_project(client)
    image = _upload(client, first["id"]).json()

    response = client.delete(_image_url(second["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMAGE_NOT_FOUND"
    assert _image_row(inspection_session, image["id"]) is not None


def test_delete_returns_404_for_a_deleted_project(make_client, inspection_session: Session) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    assert (
        client.delete(f"{PROJECTS_URL}/{project['id']}", headers=_csrf(client)).status_code == 202
    )

    response = client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert _image_row(inspection_session, image["id"]) is not None


def test_delete_is_rejected_when_generation_history_references_the_image(
    make_client, inspection_session: Session
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    project_id = uuid.UUID(project["id"])
    row = _image_row(inspection_session, image["id"])
    assert row is not None
    tasks = TaskRepository(inspection_session)
    task = tasks.create(
        project_id=project_id,
        task_type="OBJECT",
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="f" * 64,
        parameters={},
        status="COMPLETED",
    )
    tasks.add_input_images(task_id=task.id, project_id=project_id, images=[row])
    inspection_session.commit()

    response = client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMAGE_REFERENCED"
    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


def test_delete_translates_a_concurrent_reference_race_to_409(
    make_client, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    project_id = uuid.UUID(project["id"])
    row = _image_row(inspection_session, image["id"])
    assert row is not None
    tasks = TaskRepository(inspection_session)
    task = tasks.create(
        project_id=project_id,
        task_type="OBJECT",
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="f" * 64,
        parameters={},
        status="COMPLETED",
    )
    tasks.add_input_images(task_id=task.id, project_id=project_id, images=[row])
    inspection_session.commit()

    # Simulate the race the project row lock normally prevents: the pre-check
    # misses the reference, but the database RESTRICT foreign key still sees it.
    monkeypatch.setattr(TaskRepository, "is_image_referenced", lambda self, image_id: False)

    response = client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMAGE_REFERENCED"
    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


def test_delete_does_not_mask_an_unrelated_database_failure(
    make_client, inspection_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()

    def failing_delete(self: ImageRepository, instance: ProjectImage) -> None:
        raise IntegrityError("DELETE FROM project_images", {}, Exception("unexpected conflict"))

    monkeypatch.setattr(ImageRepository, "delete", failing_delete)

    # Only a foreign key violation means "referenced": anything else keeps
    # rising to the generic 500 handler instead of being reported as a 409.
    with pytest.raises(IntegrityError):
        client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


@pytest.mark.parametrize("project_status", ["PENDING", "PROCESSING"])
def test_delete_is_rejected_while_generation_owns_the_project(
    make_client, inspection_session: Session, project_status: str
) -> None:
    client = make_client()
    project = _create_project(client)
    image = _upload(client, project["id"]).json()
    inspection_session.execute(
        update(Project).where(Project.id == uuid.UUID(project["id"])).values(status=project_status)
    )
    inspection_session.commit()

    response = client.delete(_image_url(project["id"], image["id"]), headers=_csrf(client))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_PROJECT_STATE"
    assert _image_row(inspection_session, image["id"]) is not None
    assert _cleanup_jobs(inspection_session, project["id"]) == []


# --- documented contract (API-AC-08, API-AC-17) ---------------------------


def test_openapi_documents_the_image_contract(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/projects/{project_id}/images"]

    assert {"get", "post"} <= set(path)
    assert "201" in path["post"]["responses"]
    assert "multipart/form-data" in path["post"]["requestBody"]["content"]
    assert "200" in path["get"]["responses"]

    content_path = schema["paths"]["/api/v1/projects/{project_id}/images/{image_id}/content"]
    assert "get" in content_path
    assert {"image/jpeg", "image/png"} <= set(content_path["get"]["responses"]["200"]["content"])

    delete_path = schema["paths"]["/api/v1/projects/{project_id}/images/{image_id}"]
    assert "delete" in delete_path
    assert "204" in delete_path["delete"]["responses"]
