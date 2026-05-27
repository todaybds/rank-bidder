"""Story 4.5 — system pause/resume + cycle_full skip + chat health stub."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, SiteCreate
from rank_bidder.db.repositories import keywords, runtime_config, sites
from rank_bidder.main import app


def test_0008_creates_runtime_config_table(temp_db: Path) -> None:
    with get_connection() as conn:
        tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        row = conn.execute(
            "SELECT value FROM runtime_config WHERE key = 'general_bid_paused'"
        ).fetchone()
    assert "runtime_config" in tables
    assert row is not None
    assert row["value"] == "false"


def test_system_status_default(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["general_bid_paused"] is False


def test_pause_then_resume_toggle(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.post("/api/v1/system/pause-all")
    assert resp.status_code == 200
    assert resp.json()["general_bid_paused"] is True

    status = client.get("/api/v1/system/status").json()
    assert status["general_bid_paused"] is True

    resp2 = client.post("/api/v1/system/resume")
    assert resp2.status_code == 200
    assert resp2.json()["general_bid_paused"] is False


def test_pause_persists_across_connections(temp_db: Path) -> None:
    """DB 영속 — 토글 후 새 connection 으로도 보임."""
    client = TestClient(app)
    client.post("/api/v1/system/pause-all")
    with get_connection() as conn:
        assert runtime_config.is_general_bid_paused(conn) is True


def test_chat_health_stub_200(temp_db: Path) -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/chat/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_cycle_full_skips_put_when_paused(temp_db: Path) -> None:
    """일시정지 상태에서 cycle_full 실행 → BID_UP/BID_DOWN 결정도 HOLD로 rewrite, PUT 호출 안 됨."""
    from rank_bidder.jobs import cycle_full

    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site"))
        keywords.create(
            conn,
            KeywordCreate(
                id="kw1",
                site_id="s1",
                term="t",
                target_rank=2,
                bid_cap=5000,
                adgroup_id="grp-1",
            ),
        )
        runtime_config.set_value(conn, runtime_config.KEY_GENERAL_BID_PAUSED, "true")

    fake_results = [{"id": "kw1", "samples": [5, 5, 5], "chosen_rank": 5}]

    with (
        patch(
            "rank_bidder.jobs.cycle_full.measure_keywords",
            return_value=fake_results,
        ),
        patch("rank_bidder.jobs.cycle_full.sa_put_bid") as mock_put,
    ):
        summary = cycle_full.run_cycle(samples_n=3)

    assert mock_put.called is False  # paused → PUT 안 함
    assert summary["committed"] >= 1  # 결정 row insert는 정상 진행

    # decision row reason 확인
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT decision, reason FROM decisions WHERE keyword_id = 'kw1' ORDER BY id DESC LIMIT 1"
        ).fetchall()
    assert rows
    assert rows[0]["decision"] == "HOLD"
    assert "SYSTEM_PAUSED" in (rows[0]["reason"] or "")


def test_cycle_full_does_put_when_not_paused(temp_db: Path) -> None:
    """비교군 — paused 아닐 때 BID_UP 결정 + PUT 호출."""
    from rank_bidder.jobs import cycle_full

    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site"))
        keywords.create(
            conn,
            KeywordCreate(
                id="kw1",
                site_id="s1",
                term="t",
                target_rank=2,
                bid_cap=5000,
                adgroup_id="grp-1",
            ),
        )
    fake_results = [{"id": "kw1", "samples": [5, 5, 5], "chosen_rank": 5}]
    with (
        patch(
            "rank_bidder.jobs.cycle_full.measure_keywords",
            return_value=fake_results,
        ),
        patch("rank_bidder.jobs.cycle_full.sa_put_bid", new=MagicMock(return_value=None)) as mock_put,
    ):
        cycle_full.run_cycle(samples_n=3)

    assert mock_put.called is True  # 정상 → PUT 호출
