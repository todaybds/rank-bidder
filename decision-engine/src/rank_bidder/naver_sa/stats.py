"""Naver SA stats endpoint — 광고비/노출/클릭 수집 (Story 4.4).

GET /stats — Naver 공식 통계 endpoint.
  - ids: 캠페인/그룹/키워드 ID (단일 또는 comma-separated, 단 단일 호출에선 `id`)
  - fields: ["impCnt", "clkCnt", "salesAmt"] 등 (URL은 JSON 문자열)
  - timeIncrement: summary / daily (summary는 기간 합계)
  - datePreset: yesterday / last7days / last30days 등
  - 또는 startDate, endDate (yyyyMMdd)

응답 (summary):
    {"data": [{"impCnt": 123, "clkCnt": 4, "salesAmt": 5670}], ...}
또는:
    {"impCnt": ..., "salesAmt": ...} (단일 entity, wrapping 차이)

caller contract: Optional[dict] (None = parse 실패 / API 빈 응답)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from rank_bidder.naver_sa.client import call_with_retry

log = structlog.get_logger(__name__)


def fetch_yesterday_summary(
    naver_id: str,
    *,
    fields: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """단일 캠페인/그룹/키워드 ID의 어제 통계 summary 반환.

    Args:
        naver_id: nccCampaignId / nccAdgroupId / nccKeywordId.
        fields: 디폴트 ["impCnt", "clkCnt", "salesAmt"].
        client: 테스트용 주입.

    Returns:
        ``{"impCnt": int, "clkCnt": int, "salesAmt": int}`` 또는 None (parse 실패).
    """
    if fields is None:
        fields = ["impCnt", "clkCnt", "salesAmt"]
    if not naver_id or not isinstance(naver_id, str):
        raise ValueError(f"naver_id must be a non-empty string, got {naver_id!r}")

    params = {
        "id": naver_id,
        "fields": json.dumps(fields),
        "timeIncrement": "summary",
        "datePreset": "yesterday",
    }
    _, body = call_with_retry("GET", "/stats", params=params, client=client)
    return _extract_summary(body)


def _extract_summary(body: Any) -> dict[str, Any] | None:
    """응답 wrapper 차이 흡수. silent HTTP 200 wrapped error 가드."""
    if not isinstance(body, dict):
        return None
    # silent error guard (2026-05-28 박제 패턴)
    if "name" in body and isinstance(body.get("status"), int) and body["status"] >= 400:
        return None

    # 시기에 따라 {"data": [{...}]} 또는 단일 dict
    data = body.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return _normalize_stat(first)
    # top-level
    return _normalize_stat(body)


def _normalize_stat(d: dict[str, Any]) -> dict[str, Any] | None:
    """필요한 필드만 추출 + 안전 int 변환. 모두 부재면 None."""
    if not isinstance(d, dict):
        return None
    keys = ("impCnt", "clkCnt", "salesAmt", "cpc", "ctr")
    out: dict[str, Any] = {}
    for k in keys:
        if k in d:
            v = d[k]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[k] = v if k in ("cpc", "ctr") else int(v)
    return out if out else None
