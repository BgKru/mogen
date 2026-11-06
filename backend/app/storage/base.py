"""Storage backend interface (04_backend_specification.md Section 10.10).

Business services depend on this interface, so moving from local filesystem
storage to S3-compatible object storage later does not change them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageBackend(ABC):
    """Read, write, inspect and delete objects identified by storage keys.

    Implementations must reject keys that escape the storage root and must
    never expose a resolved filesystem path to callers.
    """

    @abstractmethod
    def save(self, source: bytes | BinaryIO, key: str) -> int:
        """Store ``source`` under ``key``; return the number of bytes written."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Open a stored object for binary reading."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a file or directory tree; an absent target is a success."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether ``key`` resolves to a stored file or directory."""

    @abstractmethod
    def get_size(self, key: str) -> int:
        """Return the size in bytes of a stored file."""
