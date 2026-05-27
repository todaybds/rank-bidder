"""Story 2.3 — POST /api/v1/sites/{id}/toggle + 0004 migration regression."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, SiteCreate
from rank_bidder.db.repositories import keywords, sites
from rank_bidder.main import app


@pytest.fixture
def site_with_3_kw(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="vista", name="비스타동원"))
        for i in range(3):
            keywords.create(
                conn,
                KeywordCreate(
                    id=f"kw-{i}",
                    site_id="vista",
                    term=f"k{i}",
                    target_rank=1,
                    bid_cap=1000,
                    adgroup_id=f"grp-{i}",
                ),
            )
    return "vista"


def test_preview_returns_affected_count(site_with_3_kw: str) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/sites/{site_with_3_kw}/toggle",
        json={"enabled": False, "if_match_version": 0, "confirm": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["affected_keyword_count"] == 3
    assert "confirm=true" in body["next"]


def test_confirm_applies_toggle(site_with_3_kw: str) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/sites/{site_with_3_kw}/toggle",
        json={"enabled": False, "if_match_version": 0, "confirm": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["version"] == 1
    assert body["affected_keyword_count"] == 3
    with get_connection() as conn:
        s = sites.get(conn, site_with_3_kw)
    assert s is not None and s.enabled is False


def test_no_op_when_no_keywords(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="empty", name="Empty"))
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites/empty/toggle",
        json={"enabled": False, "if_match_version": 0, "confirm": False},
    )
    assert resp.json() == {"affected_keyword_count": 0, "result": "no-op"}


def test_404_when_site_missing(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites/ghost/toggle",
        json={"enabled": False, "if_match_version": 0, "confirm": True},
    )
    assert resp.status_code == 404


def test_keyword_adgroup_id_column_persists(site_with_3_kw: str) -> None:
    """0004 migration adgroup_id 컬럼이 keywords에 저장되는지 회귀."""
    with get_connection() as conn:
        kw = keywords.get(conn, "kw-0")
    assert kw is not None
    assert kw.adgroup_id == "grp-0"


def test_campaigns_table_created(temp_db: Path) -> None:
    """0004 campaigns 테이블 + 인덱스 회귀."""
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_camp%'"
            )
        }
    assert "campaigns" in tables
    assert "idx_campaigns_site_id" in indexes
