"""System 통제 endpoint — Story 4.5 (FR-28).

운영자 1인용 전체 자동입찰 일시정지 / 재개. runtime_config 영속 →
프로세스 재시작 후에도 유지. cycle_full 가 매 KW PUT 직전 체크.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import runtime_config

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status")
def get_status() -> dict:
    with get_connection() as conn:
        cfg = runtime_config.get_all(conn)
    return {
        "general_bid_paused": cfg.get(runtime_config.KEY_GENERAL_BID_PAUSED, "false") == "true",
        "raw_config": cfg,
    }


@router.post("/pause-all")
def pause_all() -> dict:
    """전체 자동입찰 일시정지 — 다음 사이클부터 BID_UP/BID_DOWN PUT skip."""
    with write_transaction() as conn:
        runtime_config.set_value(conn, runtime_config.KEY_GENERAL_BID_PAUSED, "true")
    log.warning("system.pause_all")
    return {
        "result": "paused",
        "general_bid_paused": True,
        "note": "현재 사이클은 진행 중인 그대로 끝. 다음 사이클부터 일반 KW 입찰 PUT skip. 측정/HOLD/CAP_REACHED는 정상.",
    }


@router.post("/resume")
def resume() -> dict:
    """자동입찰 재개."""
    with write_transaction() as conn:
        runtime_config.set_value(conn, runtime_config.KEY_GENERAL_BID_PAUSED, "false")
    log.warning("system.resume")
    return {"result": "resumed", "general_bid_paused": False}
