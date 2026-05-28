"""spend_daily repository — Story 4.4. UPSERT 패턴 (date+site+campaign UNIQUE)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

TABLE = "spend_daily"


@dataclass(frozen=True)
class SpendDaily:
    id: int
    date: str
    site_id: str | None
    campaign_id: str | None
    spend_amount: int
    click_count: int
    impression_count: int
    created_at: str


def upsert(
    conn: sqlite3.Connection,
    *,
    date: str,  # YYYY-MM-DD
    site_id: str | None,
    campaign_id: str | None,
    spend_amount: int,
    click_count: int = 0,
    impression_count: int = 0,
) -> SpendDaily:
    """upsert by (date, site_id, campaign_id) — daily collector 재실행 안전."""
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (date, site_id, campaign_id, spend_amount, click_count, impression_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, site_id, campaign_id) DO UPDATE SET
          spend_amount = excluded.spend_amount,
          click_count = excluded.click_count,
          impression_count = excluded.impression_count
        """,
        (date, site_id, campaign_id, spend_amount, click_count, impression_count),
    )
    # SQLite ON CONFLICT 후 lastrowid는 신뢰 못함 — SELECT로 가져옴.
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE date=? AND COALESCE(site_id,'')=COALESCE(?,'') "
        f"AND COALESCE(campaign_id,'')=COALESCE(?,'')",
        (date, site_id, campaign_id),
    ).fetchone()
    return _row(row)


def list_recent(conn: sqlite3.Connection, days: int = 30) -> list[SpendDaily]:
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE date >= date('now', ?, 'localtime') "
        f"ORDER BY date DESC, site_id, campaign_id",
        (f"-{days} days",),
    ).fetchall()
    return [_row(r) for r in rows]


def _row(row) -> SpendDaily:
    return SpendDaily(
        id=row["id"],
        date=row["date"],
        site_id=row["site_id"],
        campaign_id=row["campaign_id"],
        spend_amount=row["spend_amount"],
        click_count=row["click_count"],
        impression_count=row["impression_count"],
        created_at=row["created_at"],
    )
