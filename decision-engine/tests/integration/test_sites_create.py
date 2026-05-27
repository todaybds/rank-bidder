"""Deploy seed — POST /api/v1/sites + GET list."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rank_bidder.main import app


def test_create_then_list(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites",
        json={"id": "kantabile", "name": "칸타빌"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "kantabile"
    assert body["name"] == "칸타빌"
    assert body["enabled"] is True
    assert body["version"] == 0

    listing = client.get("/api/v1/sites").json()
    assert listing["count"] == 1
    assert listing["items"][0]["id"] == "kantabile"


def test_create_duplicate_409(temp_db: Path) -> None:
    client = TestClient(app)
    client.post("/api/v1/sites", json={"id": "s1", "name": "Site 1"})
    resp2 = client.post("/api/v1/sites", json={"id": "s1", "name": "Site 1 again"})
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["error"]["code"] == "SITE_ALREADY_EXISTS"


def test_create_disabled_explicit(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites",
        json={"id": "s2", "name": "Site 2", "enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_create_validation_empty_id(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post("/api/v1/sites", json={"id": "", "name": "x"})
    assert resp.status_code == 422
