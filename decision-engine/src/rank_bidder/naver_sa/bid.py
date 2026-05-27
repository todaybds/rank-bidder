"""put_bid — production bidAmt 변경 (Story 1.5, AC1).

Story 1.3 dry_run_client.put_bid 패치 결과 반영:
- body에 ``nccAdgroupId`` + ``useGroupBidAmt=False`` 동시 전달 필수 (누락 시 3705 400)
- fields=``bidAmt,useGroupBidAmt``
- PUT 200 → 즉시 APPLIED (D15 (i) calibrated 2026-05-27)
"""

from __future__ import annotations

from typing import Any

import httpx

from rank_bidder.naver_sa.client import call_with_retry

BID_MIN = 100  # Naver 최저
BID_MAX = 100_000  # FR-2 spec


def put_bid(
    keyword_id: str,
    bid_amt: int,
    *,
    adgroup_id: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """PUT bidAmt — 5-8 RPS + 1→2→4 백오프 + 403 NTP 재시도 + 5종 에러 분기.

    Args:
        keyword_id: nccKeywordId (e.g., ``"nkw-a001-01-..."``)
        bid_amt: 새 입찰가 (KRW Long, [100, 100,000])
        adgroup_id: nccAdgroupId — Naver API 가 body에 요구 (3705 fix)
        client: 테스트용 httpx.Client 주입. None이면 default.

    Returns:
        Naver 응답 body dict (keyword 전체 — nccKeywordId, bidAmt, useGroupBidAmt, ...)

    Raises:
        ValueError: bid_amt 범위 위반
        NaverInvalidRequest / NaverKeywordDeleted / NaverSANtpDrift / NaverSAUnavailable
    """
    if not (BID_MIN <= bid_amt <= BID_MAX):
        raise ValueError(f"bid_amt must be in [{BID_MIN}, {BID_MAX}], got {bid_amt}")
    if not keyword_id or not adgroup_id:
        raise ValueError("keyword_id and adgroup_id must be non-empty")

    uri = f"/ncc/keywords/{keyword_id}"
    _, body = call_with_retry(
        "PUT",
        uri,
        params={"fields": "bidAmt,useGroupBidAmt"},
        json_body={
            "nccAdgroupId": adgroup_id,
            "bidAmt": int(bid_amt),
            "useGroupBidAmt": False,
        },
        client=client,
    )
    return body
