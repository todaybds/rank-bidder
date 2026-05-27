"""Chat health stub — Story 4.5 (FR-30).

home.js 가 60s 마다 ping → 5xx/timeout 시 "챗 사용 불가" 배너 표시.
Story 5.4에서 실제 Claude API ping으로 강화 (anthropic SDK minimal call).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.get("/health")
def chat_health() -> dict:
    """Stub — 항상 200. Story 5.4에서 anthropic API ping으로 교체."""
    return {"ok": True, "stub": True}
