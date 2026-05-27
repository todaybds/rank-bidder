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
) -> Notification:
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (event_type, related_ids, payload, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (event_type, json.dumps(related_ids), json.dumps(payload, ensure_ascii=False)),
    )
    return _require(conn, cursor.lastrowid)


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
