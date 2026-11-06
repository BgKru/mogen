"""Bounded exponential backoff with full jitter (05 Section 13.6).

Traceability: DB-AC-20 (failed publications return to PENDING and retry with a
bounded budget), roadmap 4.4.
"""

from __future__ import annotations

import pytest

from app.services.outbox_service import retry_delay_seconds

pytestmark = pytest.mark.unit


def test_the_first_retry_uses_the_base_delay() -> None:
    calls: list[tuple[float, float]] = []

    def rng(low: float, high: float) -> float:
        calls.append((low, high))
        return high

    delay = retry_delay_seconds(1, base_seconds=2, max_seconds=300, rng=rng)

    assert calls == [(0, 2)]
    assert delay == 2


def test_the_delay_doubles_per_attempt() -> None:
    ceilings = []

    def rng(low: float, high: float) -> float:
        ceilings.append(high)
        return low

    for attempts in (1, 2, 3, 4):
        retry_delay_seconds(attempts, base_seconds=2, max_seconds=300, rng=rng)

    assert ceilings == [2, 4, 8, 16]


def test_the_delay_is_capped() -> None:
    ceilings = []

    def rng(low: float, high: float) -> float:
        ceilings.append(high)
        return high

    retry_delay_seconds(20, base_seconds=2, max_seconds=300, rng=rng)

    assert ceilings == [300]


def test_the_delay_never_exceeds_the_ceiling() -> None:
    for attempts in range(1, 25):
        delay = retry_delay_seconds(attempts, base_seconds=2, max_seconds=300)
        assert 0 <= delay <= 300
