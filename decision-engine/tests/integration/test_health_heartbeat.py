"""Story 1.9 — /health endpoint inserts heartbeats row."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rank_bidder.db.connection import get_connection
from rank_bidder.main import app


def test_health_inserts_heartbeat_row(temp_db: Path) -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["heartbeat_id"] is not None

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, source FROM heartbeats WHERE id = ?",
            (body["heartbeat_id"],),
        ).fetchone()
    assert row is not None
    assert row["source"] == "health"


def test_health_multiple_calls_accumulate(temp_db: Path) -> None:
    client = TestClient(app)
    ids = [client.get("/health").json()["heartbeat_id"] for _ in range(3)]
    assert len(set(ids)) == 3
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM heartbeats").fetchone()["c"]
    assert count >= 3
