"""keywords repository — D1 schema + D5 version counter.

호출자가 ``write_transaction()`` (for mutations) 또는 ``get_connection()`` (for reads)으로
connection 수명을 관리. site_id FK 검증은 SQLite ON DELETE RESTRICT에 위임.
"""

from __future__ import annotations

import sqlite3

from rank_bidder.db.models import Keyword, KeywordCreate, KeywordUpdate
from rank_bidder.db.version import VersionConflictError, update_with_version

TABLE = "keywords"


def create(conn: sqlite3.Connection, payload: KeywordCreate) -> Keyword:
    conn.execute(
        f"""
        INSERT INTO {TABLE} (
            id, site_id, term, target_rank, bid_cap, enabled,
            version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, datetime('now'), datetime('now'))
        """,
        (
            payload.id,
            payload.site_id,
            payload.term,
            payload.target_rank,
            payload.bid_cap,
            int(payload.enabled),
        ),
    )
    return _require_row(conn, payload.id)


def get(conn: sqlite3.Connection, keyword_id: str) -> Keyword | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (keyword_id,)).fetchone()
    return Keyword.model_validate(dict(row)) if row is not None else None


def list_keywords(
    conn: sqlite3.Connection,
    site_id: str | None = None,
    enabled: bool | None = None,
) -> list[Keyword]:
    where: list[str] = []
    params: list = []
    if site_id is not None:
        where.append("site_id = ?")
        params.append(site_id)
    if enabled is not None:
        where.append("enabled = ?")
        params.append(int(enabled))
    sql = f"SELECT * FROM {TABLE}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY term"
    rows = conn.execute(sql, params).fetchall()
    return [Keyword.model_validate(dict(r)) for r in rows]


def update(
    conn: sqlite3.Connection,
    keyword_id: str,
    payload: KeywordUpdate,
    expected_version: int,
) -> Keyword:
    set_parts: list[str] = []
    set_params: list = []
    if payload.term is not None:
        set_parts.append("term = ?")
        set_params.append(payload.term)
    if payload.target_rank is not None:
        set_parts.append("target_rank = ?")
        set_params.append(payload.target_rank)
    if payload.bid_cap is not None:
        set_parts.append("bid_cap = ?")
        set_params.append(payload.bid_cap)
    if payload.enabled is not None:
        set_parts.append("enabled = ?")
        set_params.append(int(payload.enabled))
    if not set_parts:
        # no-op update — 그래도 version 검증은 필요 (stale client lost-update 차단).
        existing = get(conn, keyword_id)
        if existing is None:
            raise VersionConflictError(TABLE, keyword_id, expected_version, None)
        if existing.version != expected_version:
            raise VersionConflictError(TABLE, keyword_id, expected_version, existing.version)
        return existing

    update_with_version(
        conn,
        table=TABLE,
        row_id=keyword_id,
        expected_version=expected_version,
        set_clause=", ".join(set_parts),
        set_params=tuple(set_params),
    )
    return _require_row(conn, keyword_id)


def delete(conn: sqlite3.Connection, keyword_id: str, expected_version: int) -> None:
    """Atomic delete with D5 version check (TOCTOU-free)."""
    cursor = conn.execute(
        f"DELETE FROM {TABLE} WHERE id = ? AND version = ?",
        (keyword_id, expected_version),
    )
    if cursor.rowcount == 0:
        row = conn.execute(f"SELECT version FROM {TABLE} WHERE id = ?", (keyword_id,)).fetchone()
        current = int(row["version"]) if row is not None else None
        raise VersionConflictError(TABLE, keyword_id, expected_version, current)


def _require_row(conn: sqlite3.Connection, keyword_id: str) -> Keyword:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (keyword_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"keywords({keyword_id}) sudden missing — should not happen")
    return Keyword.model_validate(dict(row))
