"""In-process fixed-window rate limiting for sensitive endpoints.

The MVP runs a single API process per deployment, so a small in-memory limiter
is enough to slow down online password guessing and bulk account creation
without adding a network dependency to the request path. Redis was deliberately
not used: the API must keep accepting project and generation requests while the
broker is unavailable (``INF-AC-23``), and an authentication dependency on
Redis would break that rule.

The limiter is intentionally tiny:

* a request *hits* a key, which counts it in the current fixed window;
* the first ``limit`` hits in a window are allowed, later ones are rejected
  with a retry delay;
* expired windows are pruned lazily, and the key map is bounded so a hostile
  client cannot grow it without limit.

Counters are per process. Behind more than one API replica the effective limit
is multiplied by the replica count; that limitation is recorded in the Phase 9
close-out. The deployment's single API container makes the configured limit
exact in the shipped Compose stack.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

# Above this many tracked keys, expired windows are pruned on every hit; above
# the hard cap, the oldest windows are dropped. Both bounds are generous for a
# single API process and keep memory finite under abuse.
_PRUNE_THRESHOLD = 4096
_MAX_ENTRIES = 8192


class FixedWindowRateLimiter:
    """A thread-safe fixed-window counter keyed by an arbitrary string."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            message = "limit must be at least 1"
            raise ValueError(message)
        if window_seconds < 1:
            message = "window_seconds must be at least 1"
            raise ValueError(message)
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    @property
    def limit(self) -> int:
        """Maximum allowed hits per window."""
        return self._limit

    @property
    def window_seconds(self) -> int:
        """Length of the fixed window, in seconds."""
        return self._window_seconds

    def hit(self, key: str) -> tuple[bool, int]:
        """Count one hit for ``key``.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds`` is
        ``0`` when the hit is allowed and a positive integer when the window is
        exhausted, so it can be returned verbatim in a ``Retry-After`` header.
        """
        now = self._clock()
        with self._lock:
            window_start, count = self._windows.get(key, (now, 0))
            if now - window_start >= self._window_seconds:
                window_start, count = now, 0
            count += 1
            self._windows[key] = (window_start, count)
            self._prune(now)
            if count > self._limit:
                remaining = window_start + self._window_seconds - now
                return False, max(1, math.ceil(remaining))
            return True, 0

    def reset(self) -> None:
        """Forget every window (used by tests and explicit administrative resets)."""
        with self._lock:
            self._windows.clear()

    def tracked_keys(self) -> int:
        """Return the number of tracked keys (a bounded diagnostic)."""
        with self._lock:
            return len(self._windows)

    def _prune(self, now: float) -> None:
        if len(self._windows) < _PRUNE_THRESHOLD:
            return
        expired = [
            key
            for key, (window_start, _count) in self._windows.items()
            if now - window_start >= self._window_seconds
        ]
        for key in expired:
            del self._windows[key]
        if len(self._windows) > _MAX_ENTRIES:
            overflow = len(self._windows) - _MAX_ENTRIES
            for key in list(self._windows)[:overflow]:
                del self._windows[key]
