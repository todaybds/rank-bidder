"""average_position_bid — Naver 공식 추정가 API (Story 1.5 + 2026-05-28 POST fix).

**2026-05-28 silent bug fix**: 기존 GET 호출은 Naver 응답 wrapper에 ``MethodNotAllowed``
(supported methods are POST)로 silent fail됨 (HTTP 200으로 포장). 정정:

- ``POST /estimate/average-position-bid/keyword``
- body: ``{"device": "MOBILE", "items": [{"key": keyword_term, "position": int}]}``
- ``items[].key`` 는 **키워드 텍스트** (nccKeywordId 아님 — Naver doc 박제)

Story 1.6+ 결정 엔진이 ↑BID_UP 적정선 산출 + ``bid_decision_estimate.decide_by_estimate``
에 활용.

**caller contract (D3):** 반환 ``Optional[int]``
- ``int`` (0 포함): Naver가 명시한 추정가. 0은 valid (추정 데이터 없음 매체 응답).
- ``None``: 응답 shape 파싱 실패 / items 빈 list / Naver wrapper error.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from rank_bidder.naver_sa.client import call_with_retry

log = structlog.get_logger(__name__)

TARGET_RANK_MIN = 1
TARGET_RANK_MAX = 10  # FR-1 spec
_KW_ID_RE = re.compile(r"^nkw-[A-Za-z0-9_-]+$")
#: Naver SA estimate API의 device — MOBILE 우선 (우리 운영은 모바일 SERP 기준).
_DEFAULT_DEVICE = "MOBILE"


def _is_strict_int(value: object) -> bool:
    """엄격 int — bool 거부 (True/False가 1/0으로 통과되는 silent bug 방지, P13)."""
    return isinstance(value, int) and not isinstance(value, bool)


def average_position_bid(
    keyword_id: str,
    keyword_term: str,
    target_rank: int,
    *,
    device: str = _DEFAULT_DEVICE,
    client: httpx.Client | None = None,
) -> int | None:
    """N위 도달 추정 bid (KRW int) 또는 None(파싱 실패).

    Args:
        keyword_id: nccKeywordId — 로그/디버깅용 (Naver는 텍스트 기반이라 payload엔 안 보냄).
        keyword_term: 키워드 텍스트 (Naver API의 ``items[].key``).
        target_rank: 목표 순위 [1, 10] (FR-1) — **반드시 builtin int** (bool 거부).
        device: "MOBILE" 또는 "PC". 디폴트 MOBILE (운영 매체 기준).
        client: 테스트용 주입.

    Returns:
        ``int`` 추정 bid (0 포함 valid), 또는 ``None`` (응답 shape 파싱 실패).

    Raises:
        ValueError: 입력 타입/범위/포맷 위반
        NaverInvalidRequest / NaverKeywordDeleted / NaverAuthError / NaverSANtpDrift /
        NaverSAUnavailable
    """
    if not _is_strict_int(target_rank):
        raise ValueError(f"target_rank must be a builtin int (got {type(target_rank).__name__})")
    if not (TARGET_RANK_MIN <= target_rank <= TARGET_RANK_MAX):
        raise ValueError(
            f"target_rank must be in [{TARGET_RANK_MIN}, {TARGET_RANK_MAX}], got {target_rank}"
        )
    if not isinstance(keyword_id, str) or not _KW_ID_RE.fullmatch(keyword_id):
        raise ValueError(f"keyword_id must match {_KW_ID_RE.pattern}, got {keyword_id!r}")
    if not isinstance(keyword_term, str) or not keyword_term.strip():
        raise ValueError(f"keyword_term must be a non-empty string, got {keyword_term!r}")
    if device not in ("MOBILE", "PC", "BOTH"):
        raise ValueError(f"device must be MOBILE/PC/BOTH, got {device!r}")

    payload = {
        "device": device,
        "items": [{"key": keyword_term.strip(), "position": target_rank}],
    }
    _, body = call_with_retry(
        "POST",
        "/estimate/average-position-bid/keyword",
        json_body=payload,
        client=client,
    )
    bid = _extract_bid(body)
    if bid is None:
        log.info(
            "naver_sa.estimate_no_bid",
            keyword_id=keyword_id,
            term=keyword_term,
            target_rank=target_rank,
            body_snippet=str(body)[:200] if body else None,
        )
    return bid


def _extract_bid(body: Any) -> int | None:
    """응답 wrapper 형식 차이를 흡수해 첫 estimate bid 반환.

    Naver API 응답 예 (추정):
        ``{"estimate": [{"bid": 21500, "position": 2, ...}], ...}``
    또는 ``{"keywordEstimate": [...]}``. POST/items 응답이므로 list 길이가 items 길이와 같음.
    v1은 단일 item POST → 첫 estimate.bid 반환.

    silent bug 회피 (2026-05-28): 응답이 error wrapper인 경우 ``name``/``status`` 키 검사.
    """
    if not isinstance(body, dict):
        return None

    # Naver 응답 wrapper 안 명시적 error 신호 차단 (HTTP 200 wrapper bug 방어).
    if "name" in body and "status" in body and isinstance(body.get("status"), int):
        # 예: {"name": "MethodNotAllowed", "status": 405, ...} — error response
        if body["status"] >= 400:
            return None

    for key in ("estimate", "keywordEstimatedBid", "keywordEstimate"):
        rows = body.get(key)
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                bid = _pick_bid(first)
                if bid is not None:
                    return bid
    # top-level bid도 시도 (fallback)
    return _pick_bid(body)


def _pick_bid(d: dict[str, Any]) -> int | None:
    """``bid`` 키 우선, 없으면 ``bidAmt`` (0 포함 valid — `in` 검사로 명시)."""
    if "bid" in d:
        val = d["bid"]
    elif "bidAmt" in d:
        val = d["bidAmt"]
    else:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return int(val)
    return None
