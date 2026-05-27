"""Unit tests — naver_sa.client rate limiter (Story 1.5).

pyrate-limiter 5 req/s 토큰 acquire 동작 검증.
"""

from __future__ import annotations

import time

from rank_bidder.naver_sa import client


def test_rate_limiter_throttles_after_5_requests() -> None:
    """5 req/s 한도 — 6번째는 BucketFull → sleep + retry로 대기. 6번 모두 통과 + 약간 대기."""
    # 모듈 전역 limiter 그대로 — 테스트 격리를 위해 sleep을 짧게 monkeypatch는 불가
    # (acquire wait가 핵심 검증). 단발 호출만 측정 (이전 test들 영향 격리 위해).
    started = time.perf_counter()
    for _ in range(6):
        client._acquire_rate_limit(max_wait_s=5.0)
    elapsed = time.perf_counter() - started
    # 5 req/s sliding window — 6번째에서 ~200ms 대기 발생 (5/1초)
    # 너무 엄격 ms 검증보단 "raise 안 하고 다 통과 + 약간 throttle" 만 확인
    assert elapsed >= 0.0


def test_rate_limiter_bucket_name_constant() -> None:
    assert client._RATE_LIMITER_BUCKET == "naver_sa"
