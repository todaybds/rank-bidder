"""put_bid — production bidAmt 변경 (Story 1.5, AC1).

Story 1.3 dry_run_client.put_bid 패치 결과 반영:
- body에 ``nccAdgroupId`` + ``useGroupBidAmt=False`` 동시 전달 필수 (누락 시 3705 400)
- fields=``bidAmt,useGroupBidAmt``
- PUT 200 → 즉시 APPLIED (D15 (i) calibrated 2026-05-27)

PUT은 same body → same end state이므로 본질적으로 idempotent —
tenacity 재시도가 동일 bidAmt를 중복 적용해도 부작용 없음 (Naver 서버 no-op).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from rank_bidder.naver_sa.client import call_with_retry

BID_MIN = 100  # Naver 최저
BID_MAX = 100_000  # FR-2 spec
_KW_ID_RE = re.compile(r"^nkw-[A-Za-z0-9_-]+$")
_AG_ID_RE = re.compile(r"^grp-[A-Za-z0-9_-]+$")


def _is_strict_int(value: object) -> bool:
    """엄격 int 검사 — bool/float/Decimal/numpy.int 등 silent truncation 방지 (P12)."""
    return isinstance(value, int) and not isinstance(value, bool)


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
        bid_amt: 새 입찰가 (KRW Long, [100, 100,000]) — **반드시 builtin int** (bool/float 거부)
        adgroup_id: nccAdgroupId — Naver API 가 body에 요구 (3705 fix)
        client: 테스트용 httpx.Client 주입. None이면 default.

    Returns:
        Naver 응답 body dict (keyword 전체 — nccKeywordId, bidAmt, useGroupBidAmt, ...)

    Raises:
        ValueError: 입력 타입/범위/포맷 위반 (P12, P26)
        NaverInvalidRequest / NaverKeywordDeleted / NaverAuthError / NaverSANtpDrift /
        NaverSAUnavailable
    """
    if not _is_strict_int(bid_amt):
        raise ValueError(
            f"bid_amt must be a builtin int (got {type(bid_amt).__name__}); "
            "bool/float/Decimal/numpy types are rejected to avoid silent truncation"
        )
    if not (BID_MIN <= bid_amt <= BID_MAX):
        raise ValueError(f"bid_amt must be in [{BID_MIN}, {BID_MAX}], got {bid_amt}")
    if not isinstance(keyword_id, str) or not _KW_ID_RE.fullmatch(keyword_id):
        raise ValueError(f"keyword_id must match {_KW_ID_RE.pattern}, got {keyword_id!r}")
    if not isinstance(adgroup_id, str) or not _AG_ID_RE.fullmatch(adgroup_id):
        raise ValueError(f"adgroup_id must match {_AG_ID_RE.pattern}, got {adgroup_id!r}")

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
