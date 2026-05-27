"""campaigns repository (Story 2.3) — site ↔ Naver 캠페인 매핑."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

TABLE = "campaigns"


@dataclass(frozen=True)
class Campaign:
    id: str
    site_id: str
    naver_campaign_id: str
    created_at: str


def create(
    conn: sqlite3.Connection, *, campaign_id: str, site_id: str, naver_campaign_id: str
) -> Campaign:
    conn.execute(
        f"""
        INSERT INTO {TABLE} (id, site_id, naver_campaign_id, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (campaign_id, site_id, naver_campaign_id),
    )
    return _require(conn, campaign_id)


def get(conn: sqlite3.Connection, campaign_id: str) -> Campaign | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (campaign_id,)).fetchone()
    return _row(row) if row is not None else None


def list_by_site(conn: sqlite3.Connection, site_id: str) -> list[Campaign]:
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE site_id = ? ORDER BY id", (site_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def count_keywords_for_site(conn: sqlite3.Connection, site_id: str) -> int:
    """site_id에 속한 모든 캠페인의 KW 수 합계 (Story 2.3 affected_keyword_count)."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM keywords WHERE site_id = ?", (site_id,)
    ).fetchone()
    return int(row["c"]) if row else 0


def _row(row) -> Campaign:
    return Campaign(
        id=row["id"],
        site_id=row["site_id"],
        naver_campaign_id=row["naver_campaign_id"],
        created_at=row["created_at"],
    )


def _require(conn: sqlite3.Connection, campaign_id: str) -> Campaign:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"campaigns({campaign_id}) sudden missing")
    return _row(row)
