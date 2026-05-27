"""Story 2.2 — POST /api/v1/keywords/{id}/toggle."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, SiteCreate
from rank_bidder.db.repositories import keywords, sites
from rank_bidder.main import app


@pytest.fixture
def seeded_kw(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id="kw1", site_id="s1", term="t", target_rank=1, bid_cap=1000),
        )
    return "kw1"


def test_toggle_off_increments_version(seeded_kw: str) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/keywords/{seeded_kw}/toggle",
        json={"enabled": False, "if_match_version": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["version"] == 1
    with get_connection() as conn:
        kw = keywords.get(conn, seeded_kw)
    assert kw is not None and kw.enabled is False


def test_version_mismatch_returns_409(seeded_kw: str) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/keywords/{seeded_kw}/toggle",
        json={"enabled": False, "if_match_version": 99},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"]["code"] == "VERSION_MISMATCH"
    assert detail["error"]["current_version"] == 0


def test_toggle_round_trip(seeded_kw: str) -> None:
    client = TestClient(app)
    # OFF
    r1 = client.post(
        f"/api/v1/keywords/{seeded_kw}/toggle",
        json={"enabled": False, "if_match_version": 0},
    )
    v1 = r1.json()["version"]
    # 다시 ON — 새 version 필요
    r2 = client.post(
        f"/api/v1/keywords/{seeded_kw}/toggle",
        json={"enabled": True, "if_match_version": v1},
    )
    assert r2.status_code == 200
    assert r2.json()["enabled"] is True
    assert r2.json()["version"] == v1 + 1


def test_invalid_request_validation(seeded_kw: str) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/keywords/{seeded_kw}/toggle",
        json={"enabled": "maybe", "if_match_version": 0},
    )
    assert resp.status_code == 422
