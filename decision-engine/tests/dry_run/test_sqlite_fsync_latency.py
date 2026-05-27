"""AC4 — SQLite ``synchronous=FULL`` fsync latency 1000회 측정.

Story 1.2 ``write_transaction()`` 그대로 사용 (file lock 오버헤드 포함 — production cycle 동일 경로).
Architecture 가정 "~5ms × 100 PUT/min ≈ 9% 비용" 실측 검증.

결과: ``results/sqlite-fsync-<timestamp>.json`` (p50, p90, p99, max).
"""

from __future__ import annotations

import json
import platform
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import pytest
from rank_bidder.db import configure, write_transaction

N_ITERATIONS = 1000


@pytest.mark.slow
def test_fsync_latency_1000_iterations(tmp_path: Path, results_dir, run_timestamp) -> None:
    db_path = tmp_path / "fsync.db"
    configure(db_path)
    try:
        # 임시 테이블 — Story 1.2 migrations와 격리 (그것은 sites/keywords).
        with write_transaction() as conn:
            conn.execute("CREATE TABLE fsync_probe (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")

        latencies_ms: list[float] = []
        payload = "x" * 100  # 100바이트 더미

        for i in range(N_ITERATIONS):
            started = time.perf_counter_ns()
            with write_transaction() as conn:
                conn.execute(
                    "INSERT INTO fsync_probe (id, payload) VALUES (?, ?)",
                    (i + 1, payload),
                )
            duration_ns = time.perf_counter_ns() - started
            latencies_ms.append(duration_ns / 1_000_000)

        result = {
            "n_iterations": N_ITERATIONS,
            "p50_ms": round(statistics.median(latencies_ms), 3),
            "p90_ms": round(_percentile(latencies_ms, 0.90), 3),
            "p99_ms": round(_percentile(latencies_ms, 0.99), 3),
            "max_ms": round(max(latencies_ms), 3),
            "mean_ms": round(statistics.mean(latencies_ms), 3),
            "min_ms": round(min(latencies_ms), 3),
            "python_version": sys.version.split()[0],
            "sqlite_version": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "wall_clock_started": run_timestamp,
        }

        output_path = results_dir / f"sqlite-fsync-{run_timestamp}.json"
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        configure(None)


def _percentile(sorted_or_not: list[float], q: float) -> float:
    """statistics.quantiles 사용 (3.13 stdlib). 1000샘플이면 충분히 정확."""
    if not sorted_or_not:
        return 0.0
    sorted_vals = sorted(sorted_or_not)
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)
