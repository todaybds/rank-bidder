"""Smoke test — Story 1.1.

CI pytest job이 fail하지 않도록 1개 trivial assertion. Story 1.2~부터 real test 추가.
"""

from rank_bidder import __version__


def test_smoke() -> None:
    """패키지 import + version 상수 확인."""
    assert __version__ == "0.1.0"


def test_health_endpoint() -> None:
    """FastAPI /health endpoint smoke check.

    Story 1.9에서 DB heartbeat로 강화되면 integration test로 이관 예정.
    """
    from fastapi.testclient import TestClient
    from rank_bidder.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    # Story 1.9: heartbeat_id 키 추가 (DB 미설정 시 None)
    body = response.json()
    assert body["ok"] is True
    assert "heartbeat_id" in body
