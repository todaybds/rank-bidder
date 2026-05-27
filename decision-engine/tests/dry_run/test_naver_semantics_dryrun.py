"""AC1+AC2+AC3 — Naver SA PUT bidAmt 시점별 GET 응답 측정.

시퀀스 (3회 반복, 각 ~5분):
    PUT(new_bid) → GET(0s) → sleep30 → GET(30s) → sleep30 → GET(1m)
    → sleep120 → GET(3m) → sleep120 → GET(5m)

종료 시 원래 bid로 자동 복원.

결과: ``results/naver-put-get-<timestamp>.jsonl`` (append-only, 각 줄 1 호출).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from rank_bidder.naver_sa.dry_run_client import (
    get_current_bid,
    get_keyword,
    get_keyword_with_bad_timestamp,
    put_bid,
    restore_use_group_bid,
)

# bid 시퀀스 (원: Naver 최저 100 ~ 안전한 저가 범위)
BID_SEQUENCE = [100, 200, 150]

# GET sampling 시점 (PUT 후 경과 초)
GET_OFFSETS_SECONDS = [0, 30, 60, 180, 300]


@pytest.mark.naver_live
def test_invalid_timestamp_returns_403(naver_creds, results_dir, run_timestamp) -> None:
    """AC1 후반 — drift 1시간 → 403 invalid timestamp 확인."""
    status, body, latency_ms = get_keyword_with_bad_timestamp(
        naver_creds.test_keyword_id,
        api_key=naver_creds.api_key,
        secret_key=naver_creds.secret_key,
        customer_id=naver_creds.customer_id,
        base_url=naver_creds.base_url,
        drift_seconds=3600,
    )
    _append_jsonl(
        results_dir / f"naver-403-probe-{run_timestamp}.jsonl",
        {"step": "bad_timestamp", "status": status, "body": body, "latency_ms": latency_ms},
    )
    assert status == 403, f"403 기대, 실제 {status}. body={body}"


@pytest.mark.naver_live
def test_put_get_sequence_5min_x3(naver_creds, results_dir, run_timestamp) -> None:
    """AC2+AC3 — 3 시퀀스 측정 + 끝나면 원래 bid 복원."""
    output_path = results_dir / f"naver-put-get-{run_timestamp}.jsonl"

    # 시작 전 원래 상태(bid + adgroup) 캡처 — 복원용.
    initial_status, initial_body, _ = get_keyword(
        naver_creds.test_keyword_id,
        api_key=naver_creds.api_key,
        secret_key=naver_creds.secret_key,
        customer_id=naver_creds.customer_id,
        base_url=naver_creds.base_url,
    )
    assert initial_status == 200 and initial_body, f"GET 초기 실패 status={initial_status}"
    original_bid = int(initial_body["bidAmt"])
    original_ugb = bool(initial_body.get("useGroupBidAmt"))
    adgroup_id = initial_body["nccAdgroupId"]
    _append_jsonl(
        output_path,
        {
            "step": "capture_original_state",
            "original_bid": original_bid,
            "original_useGroupBidAmt": original_ugb,
            "adgroup_id": adgroup_id,
            "kw_id": naver_creds.test_keyword_id,
        },
    )

    try:
        for seq_idx, target_bid in enumerate(BID_SEQUENCE, start=1):
            _run_one_sequence(
                seq_idx,
                target_bid,
                adgroup_id,
                naver_creds,
                output_path,
            )
    finally:
        # 복원 — 측정 실패해도 반드시. 두 단계:
        # 1) PUT 원래 bid (개별 입찰가 복원)
        # 2) 만약 원래 useGroupBidAmt=True 였다면 그룹입찰가 사용으로 되돌림
        restore_status, restore_body, restore_latency = put_bid(
            naver_creds.test_keyword_id,
            original_bid,
            adgroup_id=adgroup_id,
            api_key=naver_creds.api_key,
            secret_key=naver_creds.secret_key,
            customer_id=naver_creds.customer_id,
            base_url=naver_creds.base_url,
        )
        _append_jsonl(
            output_path,
            {
                "step": "restore_original_bid",
                "restored_to": original_bid,
                "status": restore_status,
                "latency_ms": restore_latency,
                "body": restore_body,
            },
        )
        if original_ugb:
            ugb_status, ugb_body, ugb_latency = restore_use_group_bid(
                naver_creds.test_keyword_id,
                adgroup_id=adgroup_id,
                api_key=naver_creds.api_key,
                secret_key=naver_creds.secret_key,
                customer_id=naver_creds.customer_id,
                base_url=naver_creds.base_url,
            )
            _append_jsonl(
                output_path,
                {
                    "step": "restore_use_group_bid",
                    "status": ugb_status,
                    "latency_ms": ugb_latency,
                    "body": ugb_body,
                },
            )
            assert ugb_status == 200, (
                f"⚠️ useGroupBidAmt 복원 실패! 수동 확인 필요: KW={naver_creds.test_keyword_id} "
                f"status={ugb_status}, body={ugb_body}"
            )
        assert restore_status == 200, (
            f"⚠️ 원래 bid 복원 실패! 수동 확인 필요: KW={naver_creds.test_keyword_id} "
            f"target={original_bid}, status={restore_status}, body={restore_body}"
        )


def _run_one_sequence(
    seq_idx: int,
    target_bid: int,
    adgroup_id: str,
    creds,
    output_path: Path,
) -> None:
    put_started_at = time.time()
    put_status, put_body, put_latency = put_bid(
        creds.test_keyword_id,
        target_bid,
        adgroup_id=adgroup_id,
        api_key=creds.api_key,
        secret_key=creds.secret_key,
        customer_id=creds.customer_id,
        base_url=creds.base_url,
    )
    _append_jsonl(
        output_path,
        {
            "seq": seq_idx,
            "step": "put",
            "target_bid": target_bid,
            "status": put_status,
            "latency_ms": put_latency,
            "body": put_body,
            "elapsed_since_put_ms": 0,
            "wall_clock": put_started_at,
        },
    )

    for offset_s in GET_OFFSETS_SECONDS:
        elapsed = time.time() - put_started_at
        wait_s = offset_s - elapsed
        if wait_s > 0:
            time.sleep(wait_s)
        get_status, get_body, get_latency = get_keyword(
            creds.test_keyword_id,
            api_key=creds.api_key,
            secret_key=creds.secret_key,
            customer_id=creds.customer_id,
            base_url=creds.base_url,
        )
        actual_bid = (get_body or {}).get("bidAmt") if get_body else None
        _append_jsonl(
            output_path,
            {
                "seq": seq_idx,
                "step": f"get_{offset_s}s",
                "target_bid": target_bid,
                "actual_bid": actual_bid,
                "match": actual_bid == target_bid if actual_bid is not None else None,
                "status": get_status,
                "latency_ms": get_latency,
                "elapsed_since_put_ms": round((time.time() - put_started_at) * 1000),
                "body": get_body,
            },
        )


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
