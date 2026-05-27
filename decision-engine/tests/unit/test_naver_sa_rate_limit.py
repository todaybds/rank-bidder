"""Unit tests — naver_sa.client rate limiter (Story 1.5).

pyrate-limiter 5 req/s 토큰 acquire 동작 검증. P18(review 2026-05-27): 의미 있는
lower bound assert로 강화 — `elapsed >= 0.0` tautology 제거.
"""

from __future__ import annotations

import time

import pytest
from rank_bidder.naver_sa import client
from rank_bidder.naver_sa.exceptions import NaverSAUnavailable


def test_rate_limiter_throttles_after_5_requests() -> None:
    """5 req/s — 6번째에서 sleep + retry로 throttle 발생.

    실측 lower bound: pyrate-limiter sliding window 1초이므로 6번째 acquire 시
    최소 ~150ms 대기 (jitter 폭 ±50ms 고려한 안전한 lower bound).
    """
    started = time.perf_counter()
    for _ in range(6):
        client._acquire_rate_limit(max_wait_s=5.0)
    elapsed = time.perf_counter() - started
    # 6번째 호출이 반드시 throttle → 최소 150ms 대기 (200ms ±50 jitter lower)
    assert elapsed >= 0.15, f"6 acquire 호출이 throttle 되지 않음: elapsed={elapsed:.3f}s"


def test_rate_limiter_bucket_name_constant() -> None:
    assert client._RATE_LIMITER_BUCKET == "naver_sa"


def test_rate_limiter_timeout_raises_naver_sa_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """F12 / P16: max_wait 초과 시 BucketFullException leak 차단 — NaverSAUnavailable로 wrap.

    토큰 acquire를 항상 BucketFull 던지도록 mock + max_wait_s=0.01로 즉시 timeout.
    """
    from pyrate_limiter import BucketFullException

    class _ForcedFull(BucketFullException):
        def __init__(self) -> None:
            Exception.__init__(self, "forced")

    def _always_full(*_a: object, **_k: object) -> None:
        raise _ForcedFull()

    monkeypatch.setattr(client._RATE_LIMITER, "try_acquire", _always_full)
    monkeypatch.setattr("rank_bidder.naver_sa.client.time.sleep", lambda *_a, **_k: None)

    with pytest.raises(NaverSAUnavailable, match=r"local rate-limit timeout"):
        client._acquire_rate_limit(max_wait_s=0.01)
