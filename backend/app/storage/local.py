"""Local filesystem storage backend (04_backend_specification.md Section 10.10).

Files live under the configured ``storage_root`` and are addressed by relative
storage keys. Writes are atomic and flushed to disk before the rename: the
payload goes to a temporary file in the destination directory, is ``fsync``-ed
and then renamed into place, so a reader never observes a partially written
object.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.exceptions import AppError
from app.storage.base import StorageBackend
from app.storage.keys import resolve_storage_path

_COPY_CHUNK_SIZE = 1024 * 1024


def _storage_unavailable(exc: OSError) -> AppError:
    """Translate a filesystem failure into the documented infrastructure error."""
    return AppError(503, "STORAGE_UNAVAILABLE", "The storage backend is unavailable.")


class LocalStorage(StorageBackend):
    """Storage rooted at one directory on the local filesystem.

    The root is resolved once, so a symlinked or relative root cannot be
    escaped later; every operation re-validates its key and containment
    (08_infrastructure.md Section 17.4).
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        """The resolved storage root, for diagnostics and tests."""
        return self._root

    def save(self, source: bytes | BinaryIO, key: str) -> int:
        """Write ``source`` under ``key`` atomically and return the byte count."""
        destination = resolve_storage_path(self._root, key)
        temp_path = destination.parent / f".upload-{uuid.uuid4().hex}.tmp"
        written = 0
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("wb") as handle:
                if isinstance(source, (bytes, bytearray, memoryview)):
                    payload = bytes(source)
                    handle.write(payload)
                    written = len(payload)
                elif hasattr(source, "read"):
                    while chunk := source.read(_COPY_CHUNK_SIZE):
                        handle.write(chunk)
                        written += len(chunk)
                else:
                    raise TypeError("storage source must be bytes or a binary file object")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, destination)
        except OSError as exc:
            raise _storage_unavailable(exc) from exc
        finally:
            # On success the rename already removed the temporary path.
            temp_path.unlink(missing_ok=True)
        return written

    def open(self, key: str) -> BinaryIO:
        """Open a stored object for binary reading.

        A missing object raises ``FileNotFoundError`` so callers can return a
        not-found response; other filesystem failures become 503.
        """
        path = resolve_storage_path(self._root, key)
        try:
            return path.open("rb")
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise _storage_unavailable(exc) from exc

    def delete(self, key: str) -> None:
        """Delete a file or a directory tree; an absent target succeeds.

        Treating an already absent target as success matches the cleanup
        contract (05_database_specification.md Section 12.3).
        """
        path = resolve_storage_path(self._root, key)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            raise _storage_unavailable(exc) from exc

    def exists(self, key: str) -> bool:
        """Return whether the key resolves to an existing file or directory.

        ``Path.exists`` reports permission failures as "absent"; this
        implementation uses ``stat`` so an inaccessible root becomes a 503
        instead of a misleading miss.
        """
        path = resolve_storage_path(self._root, key)
        try:
            path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _storage_unavailable(exc) from exc
        return True

    def get_size(self, key: str) -> int:
        """Return the size in bytes of a stored file.

        A missing object raises ``FileNotFoundError``, like ``open``.
        """
        path = resolve_storage_path(self._root, key)
        try:
            return path.stat().st_size
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise _storage_unavailable(exc) from exc
