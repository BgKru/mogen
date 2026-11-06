"""Storage abstraction tests (04_backend_specification.md Section 10.10).

These are filesystem-only unit tests: they use pytest's ``tmp_path`` and never
touch PostgreSQL, so they run without the Compose database (TEST-AC-02). The
upload, retrieval and cleanup scenarios of TEST-AC-09 extend them in later
increments.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.api.dependencies import get_storage
from app.core.config import Settings
from app.core.exceptions import AppError
from app.storage import LocalStorage
from app.storage.keys import (
    STORAGE_KEY_MAX_LENGTH,
    parse_storage_key,
    resolve_storage_path,
)

pytestmark = pytest.mark.unit

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
KEY = f"projects/{PROJECT_ID}/source/photo.jpg"
DIRECTORY_KEY = f"projects/{PROJECT_ID}/"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """A storage backend rooted in a fresh temporary directory."""
    return LocalStorage(tmp_path / "data")


# --- saving and reading (Section 10.10) -----------------------------------


def test_save_stores_bytes_and_reports_the_size(storage: LocalStorage) -> None:
    payload = b"\x89PNG\r\n\x1a\n-image-bytes"

    written = storage.save(payload, KEY)

    assert written == len(payload)
    assert storage.exists(KEY) is True
    assert storage.get_size(KEY) == len(payload)
    with storage.open(KEY) as handle:
        assert handle.read() == payload
    assert (storage.root / KEY).is_file()


def test_save_accepts_a_binary_stream(storage: LocalStorage) -> None:
    stream = io.BytesIO(b"jpeg-bytes")

    written = storage.save(stream, KEY)

    assert written == len(b"jpeg-bytes")
    with storage.open(KEY) as handle:
        assert handle.read() == b"jpeg-bytes"


def test_save_creates_missing_directories(storage: LocalStorage) -> None:
    storage.save(b"payload", "temporary/deep/nested/file.bin")

    assert storage.exists("temporary/deep/nested/file.bin") is True


def test_save_rejects_unsupported_sources(storage: LocalStorage) -> None:
    with pytest.raises(TypeError):
        storage.save("text", KEY)  # type: ignore[arg-type]

    assert storage.exists(KEY) is False
    assert list(storage.root.rglob(".upload-*")) == []


def test_save_removes_its_temporary_file(storage: LocalStorage) -> None:
    storage.save(b"payload", KEY)

    assert list(storage.root.rglob(".upload-*")) == []


def test_failed_save_is_atomic_and_cleans_up(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_replace(source: object, destination: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.storage.local.os.replace", failing_replace)

    with pytest.raises(AppError) as exc_info:
        storage.save(b"payload", KEY)

    error = exc_info.value
    assert error.status_code == 503
    assert error.code == "STORAGE_UNAVAILABLE"
    assert storage.exists(KEY) is False
    assert list(storage.root.rglob(".upload-*")) == []


def test_open_and_get_size_raise_for_missing_objects(storage: LocalStorage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.open(KEY)
    with pytest.raises(FileNotFoundError):
        storage.get_size(KEY)


def test_exists_is_false_for_an_absent_key(storage: LocalStorage) -> None:
    assert storage.exists(KEY) is False


# --- filesystem failures (09_testing.md Section 16.4) ---------------------


def test_open_reports_an_unreadable_object_as_storage_unavailable(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_open(self: Path, *args: object, **kwargs: object) -> object:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(AppError) as exc_info:
        storage.open(KEY)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "STORAGE_UNAVAILABLE"


def test_get_size_reports_an_unreadable_object_as_storage_unavailable(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_stat(self: Path) -> object:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "stat", failing_stat)

    with pytest.raises(AppError) as exc_info:
        storage.get_size(KEY)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "STORAGE_UNAVAILABLE"


def test_exists_reports_an_unreadable_root_as_storage_unavailable(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_stat(self: Path) -> object:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "stat", failing_stat)

    with pytest.raises(AppError) as exc_info:
        storage.exists(KEY)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "STORAGE_UNAVAILABLE"


def test_delete_reports_an_unremovable_target_as_storage_unavailable(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(AppError) as exc_info:
        storage.delete(KEY)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "STORAGE_UNAVAILABLE"


# --- deletion (Section 12.3) ----------------------------------------------


def test_delete_removes_a_file_and_is_idempotent(storage: LocalStorage) -> None:
    storage.save(b"payload", KEY)

    storage.delete(KEY)
    storage.delete(KEY)

    assert storage.exists(KEY) is False


def test_delete_removes_a_directory_tree(storage: LocalStorage) -> None:
    storage.save(b"image", f"{DIRECTORY_KEY}source/photo.jpg")
    storage.save(b"model", f"{DIRECTORY_KEY}results/model.glb")

    storage.delete(DIRECTORY_KEY)

    assert storage.exists(DIRECTORY_KEY) is False
    assert storage.exists(f"projects/{PROJECT_ID}/source/photo.jpg") is False
    assert not (storage.root / "projects" / PROJECT_ID).exists()


def test_delete_of_an_absent_directory_is_success(storage: LocalStorage) -> None:
    storage.delete("projects/unknown-project/")


# --- key validation and containment (Section 10.10, 08 Section 17.4) -----


@pytest.mark.parametrize("key", [KEY, DIRECTORY_KEY, "temporary/", "photo.jpg"])
def test_valid_keys_are_accepted(key: str) -> None:
    assert str(parse_storage_key(key)) == key.rstrip("/")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "..",
        "projects/../../etc/passwd",
        "projects/./photo.jpg",
        "projects//photo.jpg",
        "projects\\photo.jpg",
        "C:/temp/photo.jpg",
        "projects/photo.jpg\x00",
        "x" * (STORAGE_KEY_MAX_LENGTH + 1),
    ],
)
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        parse_storage_key(key)


def test_resolve_keeps_the_path_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "data"

    resolved = resolve_storage_path(root, KEY)

    assert resolved == root.resolve() / KEY
    assert resolved.is_relative_to(root.resolve())


def test_symlinked_directory_cannot_escape_the_root(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(ValueError):
        LocalStorage(root).save(b"payload", "link/escape.bin")

    assert not (outside / "escape.bin").exists()


# --- dependency wiring (09_testing.md Section 7.8) ------------------------


def test_get_storage_uses_the_configured_root(tmp_path: Path) -> None:
    backend = get_storage(Settings(storage_root=tmp_path / "data"))

    backend.save(b"payload", KEY)

    assert (tmp_path / "data" / KEY).is_file()
