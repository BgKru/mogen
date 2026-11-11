"""Fixed-window rate limiter used by the unauthenticated auth endpoints.

Traceability: ``TEST-AC-03`` (successful and unsuccessful request scenarios),
``TEST-AC-04`` (abuse of the authentication surface), ``TEST-AC-19`` (the
behaviour is covered by the fast suite). The limiter is pure in-process logic,
so these cases need no infrastructure.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import _MAX_ENTRIES, FixedWindowRateLimiter

pytestmark = pytest.mark.unit


class _Clock:
    """A controllable monotonic clock for deterministic window tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_hits_are_allowed_up_to_the_limit() -> None:
    limiter = FixedWindowRateLimiter(limit=3, window_seconds=60, clock=_Clock())

    results = [limiter.hit("login:127.0.0.1") for _ in range(3)]

    assert [(allowed, retry) for allowed, retry in results] == [(True, 0), (True, 0), (True, 0)]


def test_a_hit_over_the_limit_is_rejected_with_a_retry_delay() -> None:
    clock = _Clock()
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60, clock=clock)

    assert limiter.hit("login:127.0.0.1") == (True, 0)

    clock.advance(10)
    allowed, retry_after = limiter.hit("login:127.0.0.1")

    assert allowed is False
    assert retry_after == 50


def test_the_window_resets_after_its_duration() -> None:
    clock = _Clock()
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("login:127.0.0.1") == (True, 0)
    assert limiter.hit("login:127.0.0.1")[0] is False

    clock.advance(60)

    assert limiter.hit("login:127.0.0.1") == (True, 0)


def test_keys_have_independent_budgets() -> None:
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60, clock=_Clock())

    assert limiter.hit("login:a") == (True, 0)
    assert limiter.hit("register:a") == (True, 0)
    assert limiter.hit("login:b") == (True, 0)
    assert limiter.hit("login:a")[0] is False


def test_expired_windows_are_pruned_once_the_map_grows() -> None:
    clock = _Clock()
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60, clock=clock)
    for index in range(5000):
        limiter.hit(f"key-{index}")
    assert limiter.tracked_keys() <= _MAX_ENTRIES

    clock.advance(61)
    limiter.hit("fresh")

    # Every old window expired, so the map collapses to the fresh key.
    assert limiter.tracked_keys() == 1


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="limit"):
        FixedWindowRateLimiter(limit=0, window_seconds=60)
    with pytest.raises(ValueError, match="window_seconds"):
        FixedWindowRateLimiter(limit=1, window_seconds=0)
