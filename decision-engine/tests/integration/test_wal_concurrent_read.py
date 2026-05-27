"""AC5 — WAL 모드에서 write 진행 중에도 read는 non-blocking."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rank_bidder.db import get_connection, write_transaction
from rank_bidder.db.models import SiteCreate
from rank_bidder.db.repositories import sites as sites_repo


def test_read_does_not_block_during_write(temp_db: Path) -> None:
    """Writer thread가 transaction 안에서 sleep 중일 때, reader는 즉시 반환."""
    writer_in_tx = threading.Event()
    writer_release = threading.Event()

    def writer() -> None:
        with write_transaction() as conn:
            sites_repo.create(conn, SiteCreate(id="pre-commit", name="pre"))
            writer_in_tx.set()
            writer_release.wait(timeout=10)

    t = threading.Thread(target=writer)
    t.start()
    assert writer_in_tx.wait(timeout=5)

    # writer가 transaction 점유 중 — read는 즉시 반환되어야 함.
    started = time.perf_counter()
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM sites").fetchall()
    elapsed = time.perf_counter() - started

    # WAL 정상이면 sub-100ms. 3s 상한은 cold-start/안티바이러스 스캔 관용.
    assert elapsed < 3.0, f"read가 너무 느림: {elapsed:.2f}s (WAL이면 sub-100ms 기대)"
    # write 미커밋이라 결과 0건이어야 함 (snapshot isolation).
    assert [r["id"] for r in rows] == []

    writer_release.set()
    t.join(timeout=5)

    # commit 후에는 보임.
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM sites").fetchall()
    assert [r["id"] for r in rows] == ["pre-commit"]
