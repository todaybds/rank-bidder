"""decisions repository (Story 1.6) — append-only log of decision engine output."""

from __future__ import annotations

import sqlite3

from rank_bidder.db.models import Decision, DecisionCreate

TABLE = "decisions"


def insert(conn: sqlite3.Connection, payload: DecisionCreate) -> Decision:
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (
            keyword_id, cycle_id, decided_at, decision,
            old_bid, new_bid, rank_observed, reason,
            api_response_status, api_error
        )
        VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.keyword_id,
            payload.cycle_id,
            payload.decision,
            payload.old_bid,
            payload.new_bid,
            payload.rank_observed,
            payload.reason,
            payload.api_response_status,
            payload.api_error,
        ),
    )
    return _require(conn, cursor.lastrowid)


def get(conn: sqlite3.Connection, decision_id: int) -> Decision | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (decision_id,)).fetchone()
    return Decision.model_validate(dict(row)) if row is not None else None


def list_for_keyword(conn: sqlite3.Connection, keyword_id: str, limit: int = 100) -> list[Decision]:
    """같은 트랜잭션 내 datetime('now') 동일 microsecond 발생 시 secondary `id DESC` 보장."""
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE keyword_id = ? ORDER BY decided_at DESC, id DESC LIMIT ?",
        (keyword_id, limit),
    ).fetchall()
    return [Decision.model_validate(dict(r)) for r in rows]


def list_for_cycle(conn: sqlite3.Connection, cycle_id: str) -> list[Decision]:
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE cycle_id = ? ORDER BY decided_at, id",
        (cycle_id,),
    ).fetchall()
    return [Decision.model_validate(dict(r)) for r in rows]


def _require(conn: sqlite3.Connection, decision_id: int) -> Decision:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (decision_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"decisions({decision_id}) sudden missing")
    return Decision.model_validate(dict(row))
