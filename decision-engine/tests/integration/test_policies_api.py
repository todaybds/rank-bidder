"""Story 3.3 — policies CRUD API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rank_bidder.db.connection import write_transaction
from rank_bidder.db.models import KeywordCreate, SiteCreate
from rank_bidder.db.repositories import keywords, sites
from rank_bidder.main import app


def _seed(conn) -> None:
    sites.create(conn, SiteCreate(id="s1", name="Site 1"))
    keywords.create(
        conn,
        KeywordCreate(id="kw1", site_id="s1", term="t", target_rank=2, bid_cap=3000),
    )


def test_create_then_list(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)

    payload = {
        "scope_type": "site",
        "scope_id": "s1",
        "start_minute_of_week": 9 * 60,
        "duration_minutes": 180,
        "target_rank": 3,
        "bid_cap": 5000,
    }
    create_resp = client.post("/api/v1/policies", json=payload)
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["id"] > 0
    assert created["scope_type"] == "site"
    assert created["version"] == 0

    list_resp = client.get("/api/v1/policies", params={"scope_type": "site", "scope_id": "s1"})
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == created["id"]


def test_create_404_when_scope_not_found(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "nonexistent",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 1,
            "bid_cap": 1000,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "SCOPE_NOT_FOUND"


def test_create_keyword_scope_404(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "keyword",
            "scope_id": "bogus-kw",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 1,
            "bid_cap": 1000,
        },
    )
    assert resp.status_code == 404


def test_update_bumps_version(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    created = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "s1",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 2,
            "bid_cap": 3000,
        },
    ).json()
    resp = client.put(
        f"/api/v1/policies/{created['id']}",
        json={"if_match_version": 0, "bid_cap": 4500},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bid_cap"] == 4500
    assert body["version"] == 1


def test_update_409_version_mismatch(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    created = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "s1",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 2,
            "bid_cap": 3000,
        },
    ).json()
    resp = client.put(
        f"/api/v1/policies/{created['id']}",
        json={"if_match_version": 99, "bid_cap": 4500},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"]["code"] == "VERSION_MISMATCH"


def test_update_404_when_policy_missing(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.put(
        "/api/v1/policies/99999",
        json={"if_match_version": 0, "bid_cap": 5000},
    )
    assert resp.status_code == 404


def test_delete_with_correct_version(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    created = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "s1",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 2,
            "bid_cap": 3000,
        },
    ).json()
    resp = client.delete(
        f"/api/v1/policies/{created['id']}",
        params={"if_match_version": 0},
    )
    assert resp.status_code == 200
    # 다시 list 시 미존재
    after = client.get(
        "/api/v1/policies", params={"scope_type": "site", "scope_id": "s1"}
    ).json()
    assert after["count"] == 0


def test_delete_409_version_mismatch(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    created = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "s1",
            "start_minute_of_week": 0,
            "duration_minutes": 60,
            "target_rank": 2,
            "bid_cap": 3000,
        },
    ).json()
    resp = client.delete(
        f"/api/v1/policies/{created['id']}",
        params={"if_match_version": 99},
    )
    assert resp.status_code == 409


def test_delete_404_when_not_exists(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.delete("/api/v1/policies/99999", params={"if_match_version": 0})
    assert resp.status_code == 404


def test_invalid_scope_type_422(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.get(
        "/api/v1/policies", params={"scope_type": "BOGUS", "scope_id": "s1"}
    )
    assert resp.status_code == 422


def test_validation_minute_of_week_out_of_range(temp_db: Path) -> None:
    with write_transaction() as conn:
        _seed(conn)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/policies",
        json={
            "scope_type": "site",
            "scope_id": "s1",
            "start_minute_of_week": 99999,
            "duration_minutes": 60,
            "target_rank": 1,
            "bid_cap": 1000,
        },
    )
    assert resp.status_code == 422


def test_list_filters_by_scope(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        sites.create(conn, SiteCreate(id="s2", name="Site 2"))
    client = TestClient(app)
    for sid in ("s1", "s2"):
        client.post(
            "/api/v1/policies",
            json={
                "scope_type": "site",
                "scope_id": sid,
                "start_minute_of_week": 0,
                "duration_minutes": 60,
                "target_rank": 1,
                "bid_cap": 1000,
            },
        )
    s1 = client.get(
        "/api/v1/policies", params={"scope_type": "site", "scope_id": "s1"}
    ).json()
    s2 = client.get(
        "/api/v1/policies", params={"scope_type": "site", "scope_id": "s2"}
    ).json()
    assert s1["count"] == 1
    assert s2["count"] == 1
    assert s1["items"][0]["scope_id"] == "s1"
    assert s2["items"][0]["scope_id"] == "s2"
