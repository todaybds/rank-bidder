"""Story 1.3 사전 작업 — 브레인시티 캠페인의 KW 목록 조회.

API key/secret는 .env에서 로드. 운영 KW 목록만 조회(read-only — bidAmt 변경 X).
실측 대상 KW 선택은 사용자가 출력 보고 결정.

실행:
    cd c:/Users/ok/rank-bidder
    uv run python decision-engine/tests/dry_run/list_brainstreet_keywords.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# repo root .env
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from rank_bidder.naver_sa.auth import build_headers  # noqa: E402

API_KEY = os.environ["RANKBIDDER_NAVER_SA_API_KEY"]
SECRET_KEY = os.environ["RANKBIDDER_NAVER_SA_SECRET_KEY"]
CUSTOMER_ID = os.environ["RANKBIDDER_NAVER_SA_CUSTOMER_ID"]
BASE_URL = os.environ.get("RANKBIDDER_NAVER_SA_BASE_URL", "https://api.searchad.naver.com")

TARGET_CAMPAIGN_NAME = "브레인시티 비스타동원"


def get(uri: str, params: dict | None = None) -> tuple[int, list | dict | None]:
    headers = build_headers(
        "GET", uri, api_key=API_KEY, secret_key=SECRET_KEY, customer_id=CUSTOMER_ID
    )
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        r = client.get(uri, headers=headers, params=params)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def main() -> int:
    # 1. campaigns
    status, campaigns = get("/ncc/campaigns")
    if status != 200 or not isinstance(campaigns, list):
        print(f"FAIL campaigns: status={status}, body={campaigns}", file=sys.stderr)
        return 1

    target = next(
        (c for c in campaigns if c.get("name") == TARGET_CAMPAIGN_NAME),
        None,
    )
    if not target:
        names = [c.get("name") for c in campaigns]
        print(f"FAIL: '{TARGET_CAMPAIGN_NAME}' not found. Available: {names}", file=sys.stderr)
        return 2

    campaign_id = target["nccCampaignId"]
    print(f"=== Campaign: {TARGET_CAMPAIGN_NAME} ({campaign_id}) ===")

    # 2. adgroups
    status, adgroups = get("/ncc/adgroups", params={"nccCampaignId": campaign_id})
    if status != 200 or not isinstance(adgroups, list):
        print(f"FAIL adgroups: status={status}, body={adgroups}", file=sys.stderr)
        return 3

    print(f"\n=== AdGroups ({len(adgroups)}) ===")
    for ag in adgroups:
        ag_id = ag.get("nccAdgroupId")
        ag_name = ag.get("name")
        enabled = ag.get("userLock") == "N" and ag.get("status") == "ELIGIBLE"
        print(f"  - {ag_name}  | id={ag_id}  | enabled={enabled}")

    # 3. keywords per adgroup
    print("\n=== Keywords ===")
    print(f"{'term':<30} {'bid':>8} {'group_bid':>9} {'useGB':>6} {'status':<12} {'nccKeywordId'}")
    print("-" * 110)
    for ag in adgroups:
        ag_id = ag.get("nccAdgroupId")
        ag_name = ag.get("name")
        status, kws = get("/ncc/keywords", params={"nccAdgroupId": ag_id})
        if status != 200 or not isinstance(kws, list):
            print(f"  (adgroup {ag_name}: keywords fetch failed status={status})")
            continue
        print(f"\n  [AdGroup: {ag_name}]  ({len(kws)} kw)")
        for kw in kws:
            term = (kw.get("keyword") or "")[:28]
            bid = kw.get("bidAmt", "-")
            use_gb = "Y" if kw.get("useGroupBidAmt") else "N"
            ag_bid = ag.get("bidAmt", "-")
            kw_status = kw.get("status", "?")
            kid = kw.get("nccKeywordId", "?")
            print(f"  {term:<30} {str(bid):>8} {str(ag_bid):>9} {use_gb:>6} {kw_status:<12} {kid}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
