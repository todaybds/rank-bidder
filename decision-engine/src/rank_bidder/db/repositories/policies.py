"""policies repository — multi-time policy rows (Story 3.1, FR-7).

scope_type ∈ {site, keyword}, scope_id는 sites.id 또는 keywords.id 와 FK 의미적으로 일치.
DB 레벨 FK는 polymorphic이라 걸지 않음 — 호출자가 검증 책임. D5 version counter 적용.

호출자가 ``write_transaction()`` (mutations) 또는 ``get_connection()`` (reads)으로 conn 관리.
"""

from __future__ import annotations

import sqlite3

from rank_bidder.db.models import Policy, PolicyCreate, PolicyUpdate
from rank_bidder.db.version import VersionConflictError, update_with_version

TABLE = "policies"


def create(conn: sqlite3.Connection, payload: PolicyCreate) -> Policy:
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (
            scope_type, scope_id, start_minute_of_week, duration_minutes,
            target_rank, bid_cap, version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, datetime('now'), datetime('now'))
        """,
        (
            payload.scope_type,
            payload.scope_id,
            payload.start_minute_of_week,
            payload.duration_minutes,
            payload.target_rank,
            payload.bid_cap,
        ),
    )
    return _require(conn, cursor.lastrowid)


def get(conn: sqlite3.Connection, policy_id: int) -> Policy | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (policy_id,)).fetchone()
    return Policy.model_validate(dict(row)) if row is not None else None


def list_by_scope(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: str,
) -> list[Policy]:
    """scope (type+id)에 속한 모든 정책 — 활성 lookup은 ``engine.policy_eval``이 처리."""
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE scope_type = ? AND scope_id = ? ORDER BY start_minute_of_week",
        (scope_type, scope_id),
    ).fetchall()
    return [Policy.model_validate(dict(r)) for r in rows]


def update(
    conn: sqlite3.Connection,
    policy_id: int,
    payload: PolicyUpdate,
    expected_version: int,
) -> Policy:
    set_parts: list[str] = []
    set_params: list = []
    if payload.start_minute_of_week is not None:
        set_parts.append("start_minute_of_week = ?")
        set_params.append(payload.start_minute_of_week)
    if payload.duration_minutes is not None:
        set_parts.append("duration_minutes = ?")
        set_params.append(payload.duration_minutes)
    if payload.target_rank is not None:
        set_parts.append("target_rank = ?")
        set_params.append(payload.target_rank)
    if payload.bid_cap is not None:
        set_parts.append("bid_cap = ?")
        set_params.append(payload.bid_cap)
    if not set_parts:
        existing = get(conn, policy_id)
        if existing is None:
            raise VersionConflictError(TABLE, str(policy_id), expected_version, None)
        if existing.version != expected_version:
            raise VersionConflictError(
                TABLE, str(policy_id), expected_version, existing.version
            )
        return existing

    update_with_version(
        conn,
        table=TABLE,
        row_id=policy_id,  # SQLite INTEGER id — helper는 placeholder로 그대로 사용
        expected_version=expected_version,
        set_clause=", ".join(set_parts),
        set_params=tuple(set_params),
    )
    return _require(conn, policy_id)


def delete(conn: sqlite3.Connection, policy_id: int, expected_version: int) -> None:
    """Atomic delete with D5 version check (TOCTOU-free)."""
    cursor = conn.execute(
        f"DELETE FROM {TABLE} WHERE id = ? AND version = ?",
        (policy_id, expected_version),
    )
    if cursor.rowcount == 0:
        row = conn.execute(f"SELECT version FROM {TABLE} WHERE id = ?", (policy_id,)).fetchone()
        current = int(row["version"]) if row is not None else None
        raise VersionConflictError(TABLE, str(policy_id), expected_version, current)


def _require(conn: sqlite3.Connection, policy_id: int) -> Policy:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (policy_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"policies({policy_id}) sudden missing — should not happen")
    return Policy.model_validate(dict(row))
