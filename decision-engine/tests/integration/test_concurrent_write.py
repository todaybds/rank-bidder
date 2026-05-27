"""AC3 — file lock 직렬화 + 5s timeout 후 SQLiteBusyError."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rank_bidder.db import SQLiteBusyError, get_connection, write_transaction
from rank_bidder.db.models import SiteCreate
from rank_bidder.db.repositories import sites as sites_repo


def test_two_writes_are_serialized(temp_db: Path) -> None:
    """동일 프로세스 2개 thread가 동시 write → 둘 다 성공 + 직렬화 (timestamp 분리)."""
    results: list[str] = []
    barrier = threading.Barrier(2)

    def writer(site_id: str) -> None:
        barrier.wait()
        with write_transaction() as conn:
            sites_repo.create(conn, SiteCreate(id=site_id, name=site_id))
            results.append(site_id)

    threads = [
        threading.Thread(target=writer, args=("s-a",)),
        threading.Thread(target=writer, args=("s-b",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert sorted(results) == ["s-a", "s-b"]
    with get_connection() as conn:
        names = [row["id"] for row in conn.execute("SELECT id FROM sites ORDER BY id")]
    assert names == ["s-a", "s-b"]


def test_lock_timeout_raises_busy_error(temp_db: Path) -> None:
    """Thread1이 lock 6초간 점유 → Thread2는 5초 timeout 후 SQLiteBusyError."""
    holder_started = threading.Event()
    holder_release = threading.Event()
    error_box: list[Exception] = []

    def holder() -> None:
        with write_transaction() as conn:
            sites_repo.create(conn, SiteCreate(id="holder", name="holder"))
            holder_started.set()
            # lock + transaction을 계속 유지
            holder_release.wait(timeout=10)

    def waiter() -> None:
        try:
            with write_transaction() as conn:
                sites_repo.create(conn, SiteCreate(id="waiter", name="waiter"))
        except SQLiteBusyError as exc:
            error_box.append(exc)

    t1 = threading.Thread(target=holder)
    t1.start()
    assert holder_started.wait(timeout=5), "holder가 lock 잡지 못함"

    started = time.perf_counter()
    t2 = threading.Thread(target=waiter)
    t2.start()
    t2.join(timeout=10)
    elapsed = time.perf_counter() - started

    holder_release.set()
    t1.join(timeout=5)

    assert error_box, f"SQLiteBusyError가 raise되어야 함 — elapsed={elapsed:.2f}s"
    # lower bound 엄격 (4s 미만이면 timeout 동작 안 한 것),
    # upper bound 느슨 (느린 CI/안티바이러스 스캔/Windows arm64 emulation 허용).
    assert 4.0 < elapsed < 15.0, f"timeout ~5s 기대, 실측 {elapsed:.2f}s"
