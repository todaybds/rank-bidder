"""measurements repository (Story 1.6) — append-only log of sampler outputs."""

from __future__ import annotations

import json
import sqlite3

from rank_bidder.db.models import Measurement, MeasurementCreate

TABLE = "measurements"


def insert(conn: sqlite3.Connection, payload: MeasurementCreate) -> Measurement:
    cursor = conn.execute(
        f"""
        INSERT INTO {TABLE} (keyword_id, measured_at, rank_samples, rank_final, current_bid)
        VALUES (?, datetime('now'), ?, ?, ?)
        """,
        (
            payload.keyword_id,
            json.dumps(payload.rank_samples),
            payload.rank_final,
            payload.current_bid,
        ),
    )
    new_id = cursor.lastrowid
    return _require(conn, new_id)


def get(conn: sqlite3.Connection, measurement_id: int) -> Measurement | None:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (measurement_id,)).fetchone()
    return Measurement.model_validate(dict(row)) if row is not None else None


def latest_for_keyword(conn: sqlite3.Connection, keyword_id: str) -> Measurement | None:
    """가장 최근 measurement 1건 — `(keyword_id, measured_at DESC)` 인덱스 활용.

    같은 트랜잭션 내 datetime('now') 동일 microsecond 발생 시 secondary `id DESC` 로 보장.
    """
    row = conn.execute(
        f"SELECT * FROM {TABLE} WHERE keyword_id = ? ORDER BY measured_at DESC, id DESC LIMIT 1",
        (keyword_id,),
    ).fetchone()
    return Measurement.model_validate(dict(row)) if row is not None else None


def list_for_keyword(
    conn: sqlite3.Connection, keyword_id: str, limit: int = 100
) -> list[Measurement]:
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE keyword_id = ? ORDER BY measured_at DESC, id DESC LIMIT ?",
        (keyword_id, limit),
    ).fetchall()
    return [Measurement.model_validate(dict(r)) for r in rows]


def _require(conn: sqlite3.Connection, measurement_id: int) -> Measurement:
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (measurement_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"measurements({measurement_id}) sudden missing")
    return Measurement.model_validate(dict(row))
