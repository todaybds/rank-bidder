"""notifications_log repository (Story 2.4) — D15 (s) 묶음 알림.

실제 email 발송은 Epic 6 SMTP — 본 모듈은 row insert + 조회만.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

TABLE = "notifications_log"


@dataclass(frozen=True)
class Notification:
    id: int
    event_type: str
    related_ids: list[str]
    payload: dict
    created_at: str
    sent_at: str | None
    suppressed_until: str | None


def insert(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    related_ids: list[str],
    payload: dict,
    suppressed_until: str | None = None,
) -> Notification:
    """notifications_log row insert.

    suppressed_until: ISO datetime string (UTC, SQLite format "YYYY-MM-DD HH:MM:SS"). Story 3.2
    cap_race / cap_reached_sustained 알림이 24h 재발 suppress 용으로 사용. None 시 미설정.
    """
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (event_type, related_ids, payload, created_at, suppressed_until)
        VALUES (?, ?, ?, datetime('now'), ?)
        """,
        (
            event_type,
            json.dumps(related_ids),
            json.dumps(payload, ensure_ascii=False),
            suppressed_until,
        ),
    )
    return _require(conn, cursor.lastrowid)


def find_active_suppression(
    conn: sqlite3.Connection,
    event_type: str,
    scope_key: str,
    now_sqlite: str,
) -> Notification | None:
    """같은 event_type + scope_key (related_ids 내 포함) + suppressed_until > now 행이 있으면 반환.

    Story 3.2 — cap_race / cap_reached_sustained 알림이 24h 재발 suppress 판정.
    scope_key 매칭은 related_ids JSON 안에 들어있는지 substring 검사 + 로드 후 확인.
    """
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE event_type = ? AND suppressed_until IS NOT NULL "
        f"AND suppressed_until > ? ORDER BY created_at DESC",
        (event_type, now_sqlite),
    ).fetchall()
    for row in rows:
        n = _row(row)
        if scope_key in n.related_ids:
            return n
    return None


def get(conn: sqlite3.Connection, notification_id: int) -> Notification | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (notification_id,)).fetchone()
    return _row(row) if row is not None else None


def list_pending(conn: sqlite3.Connection, limit: int = 100) -> list[Notification]:
    """sent_at IS NULL — Epic 6 SMTP가 batch 발송 대상."""
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE sent_at IS NULL ORDER BY created_at LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row(r) for r in rows]


def _row(row) -> Notification:
    return Notification(
        id=row["id"],
        event_type=row["event_type"],
        related_ids=json.loads(row["related_ids"]),
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
        sent_at=row["sent_at"],
        suppressed_until=row["suppressed_until"],
    )


def _require(conn: sqlite3.Connection, notification_id: int) -> Notification:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (notification_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"notifications_log({notification_id}) sudden missing")
    return _row(row)
