"""Story 2.1 — POST /api/v1/imports endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import SiteCreate
from rank_bidder.db.repositories import keywords, sites
from rank_bidder.main import app


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_API_KEY", "test-key")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "1")
    yield


@pytest.fixture
def seeded_site(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="vista", name="비스타동원"))
    return "vista"


def _mock_fetch(naver_kws: list[dict]):
    """fetch_campaign_keywords를 patch — Naver 호출 우회."""
    return patch(
        "rank_bidder.api.imports.fetch_campaign_keywords",
        return_value=naver_kws,
    )


def test_happy_import_5_keywords(seeded_site: str) -> None:
    naver_kws = [
        {"nccKeywordId": f"nkw-{i}", "keyword": f"키워드{i}", "nccAdgroupId": "grp-1"}
        for i in range(5)
    ]
    with _mock_fetch(naver_kws):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/imports",
            json={
                "campaign_id": "cmp-1",
                "site_id": seeded_site,
                "target_rank": 2,
                "bid_cap": 3000,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"imported": 5, "skipped": 0, "default_cap_applied": 0, "errors": []}

    with get_connection() as conn:
        rows = keywords.list_keywords(conn, site_id=seeded_site)
    assert len(rows) == 5
    assert all(kw.bid_cap == 3000 for kw in rows)
    assert all(kw.target_rank == 2 for kw in rows)


def test_skip_duplicates(seeded_site: str) -> None:
    naver_kws = [
        {"nccKeywordId": "nkw-1", "keyword": "키워드1", "nccAdgroupId": "grp-1"},
        {"nccKeywordId": "nkw-2", "keyword": "키워드2", "nccAdgroupId": "grp-1"},
    ]
    with _mock_fetch(naver_kws):
        client = TestClient(app)
        # 첫 호출 — 2 import
        first = client.post(
            "/api/v1/imports",
            json={"campaign_id": "cmp-1", "site_id": seeded_site, "bid_cap": 2000},
        )
        # 두번째 호출 — 같은 응답 → 2 skip
        second = client.post(
            "/api/v1/imports",
            json={"campaign_id": "cmp-1", "site_id": seeded_site, "bid_cap": 2000},
        )
    assert first.json()["imported"] == 2
    assert first.json()["skipped"] == 0
    assert second.json()["imported"] == 0
    assert second.json()["skipped"] == 2


def test_default_cap_applied_when_omitted(seeded_site: str) -> None:
    naver_kws = [{"nccKeywordId": "nkw-a", "keyword": "k", "nccAdgroupId": "grp"}]
    with _mock_fetch(naver_kws):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/imports",
            json={"campaign_id": "cmp-1", "site_id": seeded_site},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["default_cap_applied"] == 1
    with get_connection() as conn:
        kw = keywords.get(conn, "nkw-a")
    assert kw is not None and kw.bid_cap == 5000


def test_site_not_found_returns_400(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/imports",
        json={"campaign_id": "cmp-1", "site_id": "ghost"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "SITE_NOT_FOUND"


def test_naver_fetch_failure_returns_502(seeded_site: str) -> None:
    def _fail(*_a, **_kw):
        raise RuntimeError("Naver down")

    with patch("rank_bidder.api.imports.fetch_campaign_keywords", side_effect=_fail):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/imports",
            json={"campaign_id": "cmp-1", "site_id": seeded_site},
        )
    assert resp.status_code == 502
    assert resp.json()["detail"]["error"]["code"] == "NAVER_FETCH_FAILED"


def test_invalid_request_validation(seeded_site: str) -> None:
    """target_rank 11 → 422 (Pydantic validation)."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/imports",
        json={"campaign_id": "cmp-1", "site_id": seeded_site, "target_rank": 11},
    )
    assert resp.status_code == 422
