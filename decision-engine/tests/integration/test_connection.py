"""AC2 — PRAGMA 강제 검증."""

from __future__ import annotations

from pathlib import Path

from rank_bidder.db import get_connection


def test_all_pragmas_applied(temp_db: Path) -> None:
    """AC2: journal_mode=WAL, synchronous=FULL(2), busy_timeout=5000,
    wal_autocheckpoint=1000, foreign_keys=1.
    """
    with get_connection() as conn:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        wal_checkpoint = conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert str(journal).lower() == "wal"
    assert int(synchronous) == 2  # FULL
    assert int(busy_timeout) == 5000
    assert int(wal_checkpoint) == 1000
    assert int(foreign_keys) == 1


def test_foreign_keys_enforced(temp_db: Path) -> None:
    """foreign_keys=1 활성화 → keywords가 존재하지 않는 site_id로 INSERT 시 IntegrityError."""
    import sqlite3

    from rank_bidder.db import write_transaction

    with write_transaction() as conn:
        try:
            conn.execute(
                """
                INSERT INTO keywords (
                    id, site_id, term, target_rank, bid_cap,
                    enabled, version, created_at, updated_at
                ) VALUES (?, 'nonexistent-site', ?, ?, ?, 1, 0,
                           datetime('now'), datetime('now'))
                """,
                ("kw-orphan", "test", 1, 500),
            )
            failed = False
        except sqlite3.IntegrityError:
            failed = True
    assert failed, "FK 위반이 차단되어야 함 (foreign_keys=1)"
