"""P3+D1 — lifespan strict prod mode + defensive dev mode."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_lifespan_skips_in_non_prod_without_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_PATH 없음 + ENV != prod → warning 후 skip (TestClient 호환)."""
    monkeypatch.delenv("RANKBIDDER_DB_PATH", raising=False)
    monkeypatch.setenv("RANKBIDDER_ENV", "local")

    from rank_bidder.main import app

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    # Story 1.9: DB 미설정 시 heartbeat insert 실패 → heartbeat_id=None 안전 반환
    body = response.json()
    assert body["ok"] is True
    assert body.get("heartbeat_id") is None


def test_lifespan_raises_in_prod_without_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_PATH 없음 + ENV=prod → 즉시 RuntimeError (silent prod boot 차단)."""
    monkeypatch.delenv("RANKBIDDER_DB_PATH", raising=False)
    monkeypatch.setenv("RANKBIDDER_ENV", "prod")

    from rank_bidder.main import app

    with pytest.raises(RuntimeError, match="RANKBIDDER_DB_PATH required"), TestClient(app):
        pass


def test_lifespan_runs_migrations_when_db_path_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """DB_PATH 설정 시 startup에서 migration.up() 실행 (테이블 생성 확인)."""
    db_path = tmp_path / "lifespan.db"
    monkeypatch.setenv("RANKBIDDER_DB_PATH", str(db_path))
    monkeypatch.setenv("RANKBIDDER_ENV", "local")

    # configure 호출 안 해도 env로 fallback. 단 lifespan 끝나면 _db_path는 env 그대로.
    from rank_bidder.db import configure, get_connection
    from rank_bidder.main import app

    configure(None)  # env path 사용하도록 초기화

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200

    # 테이블 생성 확인
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "sites" in tables
    assert "keywords" in tables
    assert "schema_migrations" in tables

    configure(None)  # teardown
