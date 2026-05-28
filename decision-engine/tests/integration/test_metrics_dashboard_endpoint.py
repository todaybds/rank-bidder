"""Story 4.2 — GET /api/v1/metrics/dashboard endpoint integration test."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rank_bidder.auth.bearer import ENV_VAR
from rank_bidder.main import app


@pytest.fixture
def authed_env(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "dashboard-test-token"
    monkeypatch.setenv(ENV_VAR, token)
    return token


def test_dashboard_endpoint_returns_5_widgets_schema(temp_db: Path, authed_env: str) -> None:
    """5위젯 필드 모두 존재 + generated_at 박제 + Bearer 통과."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/metrics/dashboard",
        headers={"authorization": f"Bearer {authed_env}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 5위젯 + generated_at 필드 박제
    for key in [
        "generated_at",
        "hit_rate_24h",
        "current_serp_vs_target",
        "system_failures_24h",
        "movers_top5",
        "spend_cum",
    ]:
        assert key in body, f"missing widget: {key}"

    # 각 위젯 타입
    assert isinstance(body["hit_rate_24h"], dict)
    assert isinstance(body["current_serp_vs_target"], list)
    assert isinstance(body["system_failures_24h"], list)
    assert isinstance(body["movers_top5"], list)
    assert isinstance(body["spend_cum"], dict)

    # spend_cum은 Story 4.4 완료 → spend_daily 테이블 존재 → available=true (데이터 0)
    assert body["spend_cum"]["available"] is True
    assert body["spend_cum"]["today_krw"] == 0

    # generated_at은 KST(+09:00) ISO 문자열
    assert "+09:00" in body["generated_at"]


def test_dashboard_endpoint_requires_bearer(temp_db: Path, authed_env: str) -> None:
    """Bearer 토큰 없으면 401."""
    client = TestClient(app)
    resp = client.get("/api/v1/metrics/dashboard")
    assert resp.status_code == 401


def test_dashboard_endpoint_widget_error_isolation(
    temp_db: Path, authed_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """위젯 1개 query 실패 시 endpoint는 200 OK + 그 위젯만 error dict, 나머지 정상."""
    # hit_rate_24h만 강제 raise하도록 monkeypatch
    from rank_bidder.db.repositories import metrics as metrics_repo

    def _broken(conn):
        raise RuntimeError("simulated query failure")

    monkeypatch.setattr(
        metrics_repo,
        "hit_rate_24h",
        lambda conn: metrics_repo._safe("hit_rate_24h", lambda: _broken(conn)),
    )

    client = TestClient(app)
    resp = client.get(
        "/api/v1/metrics/dashboard",
        headers={"authorization": f"Bearer {authed_env}"},
    )
    assert resp.status_code == 200  # endpoint 자체는 200
    body = resp.json()
    # hit_rate_24h만 error dict
    assert "error" in body["hit_rate_24h"]
    assert body["hit_rate_24h"]["error"]["code"] == "WIDGET_QUERY_FAILED"
    # 다른 위젯들은 정상 (error 키 없음)
    assert isinstance(body["current_serp_vs_target"], list)
    assert isinstance(body["system_failures_24h"], list)
    assert isinstance(body["movers_top5"], list)
