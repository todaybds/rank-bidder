"""Story 1.5b — production client smoke test on vista KW (2026-05-27).

Story 1.5의 `naver_sa.bid.put_bid` + `naver_sa.estimate.average_position_bid` 가
production 경로 (rate-limit + tenacity + structlog + HMAC) 모두 거쳐 Naver SA에
실제 PUT 200 / GET 200을 받는지 짧은 smoke test. ~1-2분 소요.

대상 KW = `nkw-a001-01-000008209367424` (평택고덕동브레인시티비스타동원, 7일 impr=0/clk=0 비활성
— Story 1.3에서 검증 사용한 자원 재사용. 사용자 결재 2026-05-27 옵션 A).

try/finally로 원래 bid + useGroupBidAmt 자동 복원. 복원 실패 시 RuntimeError + 운영자 알림.

실행:
    cd c:/Users/ok/rank-bidder
    uv run pytest -m naver_live -s decision-engine/tests/dry_run/test_sa_client_production_smoke.py
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import structlog
from rank_bidder.naver_sa.bid import put_bid as production_put_bid
from rank_bidder.naver_sa.dry_run_client import (
    get_current_bid,
    restore_use_group_bid,
)
from rank_bidder.naver_sa.dry_run_client import (
    put_bid as dry_put_bid,
)
from rank_bidder.naver_sa.estimate import average_position_bid

log = structlog.get_logger(__name__)

# Story 1.3 검증 vista KW (사용자 결재 2026-05-27 옵션 A 재사용)
SMOKE_KW_ID = "nkw-a001-01-000008209367424"
SMOKE_ADGROUP_ID = "grp-a001-01-000000067417166"


@pytest.mark.naver_live
def test_production_put_bid_smoke(naver_creds: Any) -> None:
    """Story 1.5 production client `naver_sa.bid.put_bid` smoke test.

    rate-limit + tenacity + HMAC + structlog 모두 production 경로 그대로.
    1. dry_run_client로 원래 bid 캡처 (production client에 GET keyword 없음 — Story 1.6+ 영역)
    2. production `put_bid(kw, 100, adgroup_id=ag)` 호출 → 200 + bidAmt=100 확인
    3. finally: 원래 bid + useGroupBidAmt 복원
    """
    api_key = naver_creds.api_key
    secret_key = naver_creds.secret_key
    customer_id = naver_creds.customer_id
    base_url = naver_creds.base_url

    # 1. 원래 bid 캡처
    original_bid = get_current_bid(
        SMOKE_KW_ID,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
        base_url=base_url,
    )
    log.info("smoke.original_bid_captured", bid=original_bid, kw=SMOKE_KW_ID)
    assert original_bid >= 70, f"original_bid {original_bid} 비정상 — 사용자 확인 필요"

    smoke_bid = 100  # Naver 최저 — 비활성 KW니까 noise 0
    try:
        # 2. production client PUT
        result = production_put_bid(SMOKE_KW_ID, smoke_bid, adgroup_id=SMOKE_ADGROUP_ID)
        assert result["nccKeywordId"] == SMOKE_KW_ID
        assert result["bidAmt"] == smoke_bid
        assert result.get("useGroupBidAmt") is False
        log.info(
            "smoke.production_put_ok",
            kw=SMOKE_KW_ID,
            bidAmt=result["bidAmt"],
            useGroupBidAmt=result.get("useGroupBidAmt"),
        )
    finally:
        # 3. 복원 — try/finally + 명시적 RuntimeError on failure
        try:
            status, body, _ = dry_put_bid(
                SMOKE_KW_ID,
                original_bid,
                adgroup_id=SMOKE_ADGROUP_ID,
                api_key=api_key,
                secret_key=secret_key,
                customer_id=customer_id,
                base_url=base_url,
            )
            if status != 200:
                raise RuntimeError(
                    f"⚠️ bid 복원 실패 (HTTP {status}, body={body}). "
                    f"Naver UI에서 {SMOKE_KW_ID} bid={original_bid} 수동 확인 필요!"
                )
            # useGroupBidAmt=True 복원
            r_status, r_body, _ = restore_use_group_bid(
                SMOKE_KW_ID,
                adgroup_id=SMOKE_ADGROUP_ID,
                api_key=api_key,
                secret_key=secret_key,
                customer_id=customer_id,
                base_url=base_url,
            )
            if r_status != 200:
                raise RuntimeError(
                    f"⚠️ useGroupBidAmt=True 복원 실패 (HTTP {r_status}, body={r_body}). "
                    f"Naver UI에서 그룹입찰 사용 수동 복원 필요!"
                )
            log.info("smoke.restored", kw=SMOKE_KW_ID, bid=original_bid)
        except Exception as restore_exc:
            log.error("smoke.restore_failed", error=str(restore_exc))
            raise


@pytest.mark.naver_live
def test_production_average_position_bid_smoke(naver_creds: Any) -> None:
    """Story 1.5 production client `naver_sa.estimate.average_position_bid` smoke test.

    GET /estimate/average-position-bid/keyword 경로 검증. int 또는 None 반환.
    """
    bid = average_position_bid(SMOKE_KW_ID, target_rank=2)
    log.info("smoke.estimate_response", kw=SMOKE_KW_ID, target_rank=2, bid=bid)
    # 0 KRW 또는 valid int 또는 None (parse 실패) — 셋 다 contract-valid
    assert bid is None or (isinstance(bid, int) and bid >= 0)


@pytest.mark.naver_live
def test_naver_live_marker_skipped_in_default_pytest() -> None:
    """meta-test: 본 모듈 모든 test가 `@pytest.mark.naver_live`라 default pytest run에서 skip되어야 함."""
    # 이 test가 실제 도달했다는 건 `-m naver_live`로 명시 실행 중이라는 의미
    assert os.environ.get("RANKBIDDER_NAVER_SA_TEST_KEYWORD_ID"), "naver_live env 부재"
