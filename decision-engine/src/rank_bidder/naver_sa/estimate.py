"""average_position_bid — Naver 공식 추정가 API (Story 1.5, AC2).

GET ``/estimate/average-position-bid/keyword`` — 키워드별 N위 도달 추정 bid.
Story 1.6+ 결정 엔진이 ↑BID_UP 시 적정선 산출에 활용.

응답 예 (단일 KW):
    ``{"estimate": [{"keyword": "...", "position": 2, "bid": 21500}]}`` 또는 유사 wrapper.
v1은 단일 KW 호출 → 첫 estimate.bid 반환.

**caller contract (D3, 2026-05-27 code-review 박제):** 반환 ``Optional[int]``
- ``int`` (0 포함): Naver가 명시한 추정가. 0은 valid (예: 추정 데이터 없음 매체 응답).
- ``None``: 응답 shape 파싱 실패 (Naver 응답 형식 변화 / 비정상 응답). caller가 fallback 결정.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from rank_bidder.naver_sa.client import call_with_retry

TARGET_RANK_MIN = 1
TARGET_RANK_MAX = 10  # FR-1 spec
_KW_ID_RE = re.compile(r"^nkw-[A-Za-z0-9_-]+$")


def _is_strict_int(value: object) -> bool:
    """엄격 int — bool 거부 (True/False가 1/0으로 통과되는 silent bug 방지, P13)."""
    return isinstance(value, int) and not isinstance(value, bool)


def average_position_bid(
    keyword_id: str,
    target_rank: int,
    *,
    client: httpx.Client | None = None,
) -> int | None:
    """N위 도달 추정 bid (KRW int) 또는 None(파싱 실패).

    Args:
        keyword_id: nccKeywordId
        target_rank: 목표 순위 [1, 10] (FR-1) — **반드시 builtin int** (bool 거부)
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

    _, body = call_with_retry(
        "GET",
        "/estimate/average-position-bid/keyword",
        params={"nccKeywordId": keyword_id, "position": str(target_rank)},
        client=client,
    )
    return _extract_bid(body)


def _extract_bid(body: dict[str, Any]) -> int | None:
    """응답 wrapper 형식 차이를 흡수해 첫 estimate bid 반환.

    Naver는 시기에 따라 ``{estimate: [{bid: N}]}`` 또는 ``{keywordEstimatedBid: [...]}`` 등
    필드명이 다를 수 있어 보수적 탐색. P11: ``or`` coalesce 제거 — 0 KRW가 falsy로
    bidAmt fallback 처리되던 silent bug 차단.
    """
    if not isinstance(body, dict):
        return None

    for key in ("estimate", "keywordEstimatedBid", "keywordEstimate"):
        rows = body.get(key)
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                bid = _pick_bid(first)
                if bid is not None:
                    return bid
    # top-level bid도 시도
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
