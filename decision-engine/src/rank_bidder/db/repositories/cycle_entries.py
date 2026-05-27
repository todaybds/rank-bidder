"""cycle_entries repository — D15 (b) state machine row (Story 1.6).

State 전이 enforcement는 Story 1.7 (state_machine.py) — 본 모듈은 schema 그대로의
upsert / get / list_active 만 제공. CHECK constraint(state IN 6값)이 DB 레벨 가드.
"""

from __future__ import annotations

import sqlite3

from rank_bidder.db.models import CycleEntry, CycleEntryCreate

TABLE = "cycle_entries"


def upsert(conn: sqlite3.Connection, payload: CycleEntryCreate) -> CycleEntry:
    """Insert or update — 동일 (cycle_id, keyword_id) 있으면 state 갱신.

    State 전이 가드 없음 (Story 1.7 책임). created_at 보존, updated_at만 갱신.
    """
    conn.execute(
        f"""
        INSERT INTO {TABLE} (cycle_id, keyword_id, state, created_at, updated_at)
        VALUES (?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(cycle_id, keyword_id) DO UPDATE SET
          state = excluded.state,
          updated_at = datetime('now')
        """,
        (payload.cycle_id, payload.keyword_id, payload.state),
    )
    return _require(conn, payload.cycle_id, payload.keyword_id)


def get(conn: sqlite3.Connection, cycle_id: str, keyword_id: str) -> CycleEntry | None:
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE cycle_id = ? AND keyword_id = ?",
        (cycle_id, keyword_id),
    ).fetchone()
    return CycleEntry.model_validate(dict(row)) if row is not None else None


def list_active(conn: sqlite3.Connection) -> list[CycleEntry]:
    """PLANNED + PUT_SENT 상태만 — partial index 사용 (D15 (c) 사이클 진행/reconcile)."""
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE state IN ('PLANNED', 'PUT_SENT') "
        f"ORDER BY cycle_id, keyword_id"
    ).fetchall()
    return [CycleEntry.model_validate(dict(r)) for r in rows]


def list_by_cycle(conn: sqlite3.Connection, cycle_id: str) -> list[CycleEntry]:
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE cycle_id = ? ORDER BY keyword_id",
        (cycle_id,),
    ).fetchall()
    return [CycleEntry.model_validate(dict(r)) for r in rows]


def _require(conn: sqlite3.Connection, cycle_id: str, keyword_id: str) -> CycleEntry:
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE cycle_id = ? AND keyword_id = ?",
        (cycle_id, keyword_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"cycle_entries({cycle_id},{keyword_id}) sudden missing — should not happen"
        )
    return CycleEntry.model_validate(dict(row))
