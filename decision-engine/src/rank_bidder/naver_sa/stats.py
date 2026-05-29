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
    """필요한 필드만 추출 + 안전 변환. 모두 부재면 None."""
    if not isinstance(d, dict):
        return None
    # int 변환 필드 + float 그대로 유지 필드 분리
    int_keys = ("impCnt", "clkCnt", "salesAmt")
    float_keys = ("cpc", "ctr", "avgRnk", "recentAvgRnk")
    out: dict[str, Any] = {}
    for k in int_keys:
        if k in d:
            v = d[k]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[k] = int(v)
    for k in float_keys:
        if k in d:
            v = d[k]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[k] = float(v)
    return out if out else None


#: 2026-05-28 박제 — avgRnk가 통계적으로 의미 있으려면 최소 노출 수.
#: impCnt < 이 값이면 avgRnk가 우연/단편 표본이라 신뢰 안 함 (100원 KW가 한밤중
#: 잠깐 노출 시 운 좋게 1~2위 박혀서 avgRnk=2 같은 통계 왜곡 차단).
MIN_IMPRESSIONS_FOR_RANK = 30


#: 허용 datePreset — Naver stats API 기간 프리셋.
VALID_DATE_PRESETS = ("today", "yesterday", "last7days", "last30days")


def fetch_avg_rank(
    naver_id: str,
    *,
    date_preset: str = "today",
    client: httpx.Client | None = None,
) -> tuple[float | None, int]:
    """주어진 기간(datePreset)의 평균 순위(avgRnk) + 노출수(impCnt) 조회. 2026-05-29.

    Naver 공식 API라 SERP 차단 무관. cycle_full_estimate가 폴백 체인(today→last7days)으로 호출.

    **노출수 검증 (silent stat 왜곡 차단)**:
    - impCnt < ``MIN_IMPRESSIONS_FOR_RANK`` (30회) → avgRnk 신뢰 안 함, ``(None, imp)``.
      100원 KW가 우연히 한두 번 노출돼서 avgRnk=2 박는 silent 왜곡 차단.
    - avgRnk=0/None (노출 0 또는 미집계) → ``(None, imp)``.
    - impCnt >= 30 + avgRnk > 0 → ``(float, imp)``.

    Args:
        naver_id: nccKeywordId / nccAdgroupId.
        date_preset: today / yesterday / last7days / last30days.
            today는 네이버 집계 지연으로 낮엔 빌 수 있음 → caller가 last7days로 폴백.
        client: 테스트용.

    Returns:
        ``(avg_rank, impressions)`` — 노출 부족/데이터 없음 시 ``(None, impCnt)``.
    """
    if not naver_id or not isinstance(naver_id, str):
        raise ValueError(f"naver_id must be a non-empty string, got {naver_id!r}")
    if date_preset not in VALID_DATE_PRESETS:
        raise ValueError(f"date_preset must be one of {VALID_DATE_PRESETS}, got {date_preset!r}")
    params = {
        "id": naver_id,
        "fields": json.dumps(["avgRnk", "impCnt"]),
        "timeIncrement": "summary",
        "datePreset": date_preset,
    }
    _, body = call_with_retry("GET", "/stats", params=params, client=client)
    stat = _extract_summary(body)
    if stat is None:
        return None, 0
    avg = stat.get("avgRnk")
    imp = int(stat.get("impCnt", 0) or 0)
    # avgRnk=0 또는 None = Naver 데이터 없음 (노출 0)
    if avg is None or avg == 0:
        return None, imp
    # 노출수 부족 → 통계 왜곡 가능, 신뢰 안 함
    if imp < MIN_IMPRESSIONS_FOR_RANK:
        return None, imp
    return float(avg), imp


def fetch_today_avg_rank(
    naver_id: str,
    *,
    client: httpx.Client | None = None,
) -> tuple[float | None, int]:
    """오늘 평균 순위 (avgRnk + impCnt) — ``fetch_avg_rank(date_preset="today")`` 래퍼 (하위호환)."""
    return fetch_avg_rank(naver_id, date_preset="today", client=client)
