"""Naver SA campaign / adgroup / keyword 조회 helpers (Story 2.1).

Story 1.5 ``client.call_with_retry`` 사용 — rate-limit + tenacity + NTP guard 자동.
PUT 없는 read-only 작업이라 사이드이펙트 없음.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from rank_bidder.naver_sa.client import call_with_retry

log = structlog.get_logger(__name__)


def list_adgroups(campaign_id: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """GET /ncc/adgroups?nccCampaignId={id} — 캠페인의 광고그룹 list."""
    _, body = call_with_retry(
        "GET",
        "/ncc/adgroups",
        params={"nccCampaignId": campaign_id},
        client=client,
    )
    # Naver API는 list 그대로 반환 — body가 dict이면 wrapper 가정
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        # 빈 응답이나 wrapper 형태
        return body.get("data") or body.get("adgroups") or []
    return []


def list_keywords_in_adgroup(
    adgroup_id: str, *, client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """GET /ncc/keywords?nccAdgroupId={id} — 광고그룹의 KW list."""
    _, body = call_with_retry(
        "GET",
        "/ncc/keywords",
        params={"nccAdgroupId": adgroup_id},
        client=client,
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("data") or body.get("keywords") or []
    return []


def fetch_campaign_keywords(
    campaign_id: str,
    *,
    eligible_only: bool = True,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """캠페인 전체 KW + adgroup_id flatten. ELIGIBLE만 디폴트.

    Returns:
        ``[{nccKeywordId, keyword, nccAdgroupId, status, bidAmt, useGroupBidAmt}, ...]``
    """
    out: list[dict[str, Any]] = []
    for ag in list_adgroups(campaign_id, client=client):
        if eligible_only and ag.get("status") != "ELIGIBLE":
            continue
        agid = ag.get("nccAdgroupId")
        if not agid:
            continue
        for kw in list_keywords_in_adgroup(agid, client=client):
            if eligible_only and kw.get("status") != "ELIGIBLE":
                continue
            kw.setdefault("nccAdgroupId", agid)
            out.append(kw)
    log.info("naver_sa.fetch_campaign_keywords", campaign_id=campaign_id, count=len(out))
    return out
