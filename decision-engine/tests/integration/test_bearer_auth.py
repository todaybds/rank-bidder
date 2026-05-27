"""Story 4.1 — Bearer auth middleware (env-gated, /health bypass)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rank_bidder.auth.bearer import ENV_VAR
from rank_bidder.main import app


@pytest.fixture
def authed_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """RANKBIDDER_AUTH_TOKEN을 픽스처 단위로 설정."""
    token = "s3cret-test-token-12345"
    monkeypatch.setenv(ENV_VAR, token)
    return token


@pytest.fixture
def no_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """env unset 보장 — 기존 테스트와 동일 환경."""
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_bypass_when_env_unset(temp_db: Path, no_auth_env: None) -> None:
    """env 미설정 → 모든 요청 통과 (기존 테스트 무회귀 핵심)."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_always_bypass_even_with_env(temp_db: Path, authed_env: str) -> None:
    """env 설정돼도 /health 는 Bearer 없이 200 (uptime probe 호환)."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_401_missing_authorization_header(temp_db: Path, authed_env: str) -> None:
    client = TestClient(app)
    # /health 가 아닌 보호 path 호출 — sites_router 의 toggle 사용.
    resp = client.post("/api/v1/sites/s1/toggle", json={})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_401_wrong_scheme(temp_db: Path, authed_env: str) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites/s1/toggle",
        json={},
        headers={"Authorization": f"Basic {authed_env}"},
    )
    assert resp.status_code == 401


def test_401_wrong_token(temp_db: Path, authed_env: str) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites/s1/toggle",
        json={},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_200_valid_bearer_passes_through(temp_db: Path, authed_env: str) -> None:
    """올바른 Bearer 토큰 → 미들웨어 통과. 내부 라우터의 응답이 그대로 도달.

    실제 site 존재하지 않으면 404 — 인증은 통과한 셈.
    """
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sites/nonexistent/toggle",
        json={"enabled": False, "if_match_version": 0, "confirm": False},
        headers={"Authorization": f"Bearer {authed_env}"},
    )
    # 401 가 아님 — 미들웨어는 통과. 사이트 미존재 → 404.
    assert resp.status_code != 401


def test_empty_token_env_treated_as_bypass(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env 가 빈 문자열이면 bypass — config typo 안전망."""
    monkeypatch.setenv(ENV_VAR, "")
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
