"""runtime_config repository (Story 4.5) — 글로벌 시스템 통제 토글.

key/value 단일 row map. 모든 값은 TEXT — 호출자가 의미적 캐스팅.
글로벌 1행 단위라 version counter 없음. 동시 UPDATE는 SQLite WAL이 직렬화.
"""

from __future__ import annotations

import sqlite3

KEY_GENERAL_BID_PAUSED = "general_bid_paused"
TABLE = "runtime_config"


def get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(f"SELECT value FROM {TABLE} WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """UPSERT — 신규 key 도 허용. updated_at 매번 갱신."""
    conn.execute(
        f"""
        INSERT INTO {TABLE} (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
          value = excluded.value,
          updated_at = datetime('now')
        """,
        (key, value),
    )


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(f"SELECT key, value FROM {TABLE}").fetchall()
    return {r["key"]: r["value"] for r in rows}


def is_general_bid_paused(conn: sqlite3.Connection) -> bool:
    """Story 4.5 cycle_full 가 매 KW PUT 직전 호출. 누락 row면 False fallback."""
    raw = get(conn, KEY_GENERAL_BID_PAUSED)
    return raw == "true"
