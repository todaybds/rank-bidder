"""Story 2.4 — notifications_log repository + 0005 migration."""

from __future__ import annotations

from pathlib import Path

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import notifications


def test_0005_creates_notifications_table(temp_db: Path) -> None:
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "notifications_log" in tables


def test_insert_and_get(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw-1", "kw-2"],
            payload={"cycle_id": "c1", "count": 2},
        )
    assert n.id > 0
    assert n.event_type == "naver_keyword_deleted"
    assert n.related_ids == ["kw-1", "kw-2"]
    assert n.payload["count"] == 2
    assert n.sent_at is None


def test_list_pending_filters_sent_at_null(temp_db: Path) -> None:
    with write_transaction() as conn:
        n1 = notifications.insert(conn, event_type="e1", related_ids=["a"], payload={"x": 1})
        n2 = notifications.insert(conn, event_type="e2", related_ids=["b"], payload={"x": 2})
        # n1을 sent로 mark
        conn.execute(
            "UPDATE notifications_log SET sent_at = datetime('now') WHERE id = ?",
            (n1.id,),
        )
    with get_connection() as conn:
        pending = notifications.list_pending(conn)
    ids = [p.id for p in pending]
    assert n2.id in ids
    assert n1.id not in ids


def test_korean_payload_roundtrip(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="test",
            related_ids=["kw-한글"],
            payload={"메시지": "안녕"},
        )
    with get_connection() as conn:
        got = notifications.get(conn, n.id)
    assert got is not None
    assert got.related_ids == ["kw-한글"]
    assert got.payload == {"메시지": "안녕"}
