"""average_position_bid — Naver 공식 추정가 API (Story 1.5, AC2).

GET ``/estimate/average-position-bid/keyword`` — 키워드별 N위 도달 추정 bid.
Story 1.6+ 결정 엔진이 ↑BID_UP 시 적정선 산출에 활용.

응답 예 (단일 KW):
    ``{"estimate": [{"keyword": "...", "position": 2, "bid": 21500}]}`` 또는 유사 wrapper.
v1은 단일 KW 호출 → 첫 estimate.bid 반환.
"""

from __future__ import annotations

from typing import Any

import httpx

from rank_bidder.naver_sa.client import call_with_retry

TARGET_RANK_MIN = 1
TARGET_RANK_MAX = 10  # FR-1 spec


def average_position_bid(
    keyword_id: str,
    target_rank: int,
    *,
    client: httpx.Client | None = None,
) -> int:
    """N위 도달 추정 bid (KRW int).

    Args:
        keyword_id: nccKeywordId
        target_rank: 목표 순위 [1, 10] (FR-1)
        client: 테스트용 주입.

    Returns:
        추정 bid (KRW int). 응답 형식 차이로 estimate가 빈 list면 0.

    Raises:
        ValueError: target_rank 범위 위반
        NaverInvalidRequest / NaverKeywordDeleted / NaverSANtpDrift / NaverSAUnavailable
    """
    if not (TARGET_RANK_MIN <= target_rank <= TARGET_RANK_MAX):
        raise ValueError(
            f"target_rank must be in [{TARGET_RANK_MIN}, {TARGET_RANK_MAX}], got {target_rank}"
        )
    if not keyword_id:
        raise ValueError("keyword_id must be non-empty")

    _, body = call_with_retry(
        "GET",
        "/estimate/average-position-bid/keyword",
        params={"nccKeywordId": keyword_id, "position": str(target_rank)},
        client=client,
    )
    return _extract_bid(body)


def _extract_bid(body: dict[str, Any]) -> int:
    """응답 wrapper 형식 차이를 흡수해 첫 estimate bid 반환.

    Naver는 시기에 따라 ``{estimate: [{bid: N}]}`` 또는 ``{keywordEstimatedBid: [...]}`` 등
    필드명이 다를 수 있어 보수적 탐색.
    """
    for key in ("estimate", "keywordEstimatedBid", "keywordEstimate"):
        rows = body.get(key)
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                bid = first.get("bid") or first.get("bidAmt")
                if isinstance(bid, (int, float)):
                    return int(bid)
    # top-level bid도 시도
    top_bid = body.get("bid") or body.get("bidAmt")
    if isinstance(top_bid, (int, float)):
        return int(top_bid)
    return 0
