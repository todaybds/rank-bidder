"""AC3 — 10초 동안 GET 20회 연속 → rate limit 임계 측정.

429 + error code 1016 (too many connections) 발생 빈도 + latency 분포 측정.
Story 1.5 ``pyrate-limiter`` 토큰버킷 파라미터 결정 input.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from rank_bidder.naver_sa.dry_run_client import get_keyword

PROBE_DURATION_SECONDS = 10
PROBE_CALL_COUNT = 20


@pytest.mark.naver_live
def test_rate_limit_probe(naver_creds, results_dir, run_timestamp) -> None:
    output_path = results_dir / f"naver-rate-limit-{run_timestamp}.jsonl"
    interval_s = PROBE_DURATION_SECONDS / PROBE_CALL_COUNT  # 0.5s = 2 RPS

    for i in range(PROBE_CALL_COUNT):
        loop_start = time.time()
        status, body, latency_ms = get_keyword(
            naver_creds.test_keyword_id,
            api_key=naver_creds.api_key,
            secret_key=naver_creds.secret_key,
            customer_id=naver_creds.customer_id,
            base_url=naver_creds.base_url,
        )
        error_code = None
        if isinstance(body, dict):
            error_code = body.get("code")
        _append_jsonl(
            output_path,
            {
                "iter": i + 1,
                "status": status,
                "error_code": error_code,
                "latency_ms": latency_ms,
                "wall_clock": loop_start,
            },
        )
        # 다음 호출까지 일정 간격 유지.
        elapsed = time.time() - loop_start
        sleep_s = interval_s - elapsed
        if sleep_s > 0:
            time.sleep(sleep_s)


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
