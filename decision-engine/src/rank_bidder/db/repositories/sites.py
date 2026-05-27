"""sites repository — D1 schema + D5 version counter.

호출자가 ``write_transaction()`` (for mutations) 또는 ``get_connection()`` (for reads)으로
connection 수명을 관리. 본 모듈은 connection을 인자로만 받는다 (D15 h 일관성).
"""

from __future__ import annotations

import sqlite3

from rank_bidder.db.models import Site, SiteCreate, SiteUpdate
from rank_bidder.db.version import update_with_version

TABLE = "sites"


def create(conn: sqlite3.Connection, payload: SiteCreate) -> Site:
    conn.execute(
        f"""
        INSERT INTO {TABLE} (id, name, enabled, version, created_at, updated_at)
        VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))
        """,
        (payload.id, payload.name, int(payload.enabled)),
    )
    return _require_row(conn, payload.id)


def get(conn: sqlite3.Connection, site_id: str) -> Site | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (site_id,)).fetchone()
    return Site.model_validate(dict(row)) if row is not None else None


def list_sites(conn: sqlite3.Connection, enabled: bool | None = None) -> list[Site]:
    if enabled is None:
        rows = conn.execute(f"SELECT * FROM {TABLE} ORDER BY name").fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM {TABLE} WHERE enabled = ? ORDER BY name",
            (int(enabled),),
        ).fetchall()
    return [Site.model_validate(dict(r)) for r in rows]


def update(
    conn: sqlite3.Connection,
    site_id: str,
    payload: SiteUpdate,
    expected_version: int,
) -> Site:
    set_parts: list[str] = []
    set_params: list = []
    if payload.name is not None:
        set_parts.append("name = ?")
        set_params.append(payload.name)
    if payload.enabled is not None:
        set_parts.append("enabled = ?")
        set_params.append(int(payload.enabled))
    if not set_parts:
        # no-op update — return current
        existing = get(conn, site_id)
        if existing is None:
            from rank_bidder.db.version import VersionConflictError

            raise VersionConflictError(TABLE, site_id, expected_version, None)
        return existing

    update_with_version(
        conn,
        table=TABLE,
        row_id=site_id,
        expected_version=expected_version,
        set_clause=", ".join(set_parts),
        set_params=tuple(set_params),
    )
    return _require_row(conn, site_id)


def delete(conn: sqlite3.Connection, site_id: str, expected_version: int) -> None:
    row = conn.execute(f"SELECT version FROM {TABLE} WHERE id = ?", (site_id,)).fetchone()
    if row is None:
        from rank_bidder.db.version import VersionConflictError

        raise VersionConflictError(TABLE, site_id, expected_version, None)
    current = int(row["version"])
    if current != expected_version:
        from rank_bidder.db.version import VersionConflictError

        raise VersionConflictError(TABLE, site_id, expected_version, current)
    conn.execute(f"DELETE FROM {TABLE} WHERE id = ?", (site_id,))


def _require_row(conn: sqlite3.Connection, site_id: str) -> Site:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (site_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"sites({site_id}) sudden missing — should not happen")
    return Site.model_validate(dict(row))
