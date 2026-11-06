"""Storage abstraction (04_backend_specification.md Section 10.10).

Services depend on ``StorageBackend``; the MVP implementation is
``LocalStorage`` over the configured storage root.
"""

from app.storage.base import StorageBackend
from app.storage.local import LocalStorage

__all__ = ["LocalStorage", "StorageBackend"]
