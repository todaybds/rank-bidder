"""Story 1.3 spike — 최소 PUT/GET bidAmt client.

⚠️ DEPRECATED (Story 1.5, 2026-05-27): production code는 ``naver_sa.bid.put_bid`` +
``naver_sa.estimate.average_position_bid`` 사용. 본 모듈은 ``test_naver_semantics_dryrun``
측정 호환 보존용. Story 1.6에서 삭제 예정.
"""

from __future__ import annotations

import time
import warnings
from typing import Any

import httpx

from rank_bidder.naver_sa.auth import build_headers

warnings.warn(
    "rank_bidder.naver_sa.dry_run_client is DEPRECATED (Story 1.5). "
    "Use rank_bidder.naver_sa.bid / rank_bidder.naver_sa.estimate. "
    "This module will be removed in Story 1.6.",
    DeprecationWarning,
    stacklevel=2,
)


def get_keyword(
    keyword_id: str,
    *,
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
    timestamp_ms_override: str | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, dict[str, Any] | None, float]:
    """``GET /ncc/keywords/{keyword_id}``.

    Returns:
        ``(status_code, response_body_or_None, latency_ms)``. 4xx/5xx도 raise 안 함 — 측정용.
    """
    uri = f"/ncc/keywords/{keyword_id}"
    headers = build_headers(
        "GET",
        uri,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
        timestamp_ms=timestamp_ms_override,
    )
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=base_url, timeout=timeout_s) as client:
            response = client.get(uri, headers=headers)
    finally:
        latency_ms = (time.perf_counter() - started) * 1000

    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — 측정용
        body = None
    return response.status_code, body, round(latency_ms, 2)


def put_bid(
    keyword_id: str,
    bid_amt: int,
    *,
    adgroup_id: str,
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
    timeout_s: float = 30.0,
) -> tuple[int, dict[str, Any] | None, float]:
    """``PUT /ncc/keywords/{keyword_id}?fields=bidAmt,useGroupBidAmt``.

    body ``{"nccAdgroupId": <id>, "bidAmt": <int>, "useGroupBidAmt": false}``.

    Story 1.3 환경 부재 fix (2026-05-27): nccAdgroupId 누락 시 3705 "Invalid ad group number"
    400 거부. body에 ad group ID + useGroupBidAmt=false 동시 전달해야 PUT 성공.
    그룹입찰가 사용 KW에 개별 bid 적용 시 useGroupBidAmt 자동 false 전환됨.

    Returns:
        ``(status_code, response_body_or_None, latency_ms)``. 4xx/5xx도 raise 안 함 — 측정용.
    """
    uri = f"/ncc/keywords/{keyword_id}"
    headers = build_headers(
        "PUT",
        uri,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
    )
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=base_url, timeout=timeout_s) as client:
            response = client.put(
                uri,
                params={"fields": "bidAmt,useGroupBidAmt"},
                json={
                    "nccAdgroupId": adgroup_id,
                    "bidAmt": bid_amt,
                    "useGroupBidAmt": False,
                },
                headers=headers,
            )
    finally:
        latency_ms = (time.perf_counter() - started) * 1000

    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = None
    return response.status_code, body, round(latency_ms, 2)


def restore_use_group_bid(
    keyword_id: str,
    *,
    adgroup_id: str,
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
    timeout_s: float = 30.0,
) -> tuple[int, dict[str, Any] | None, float]:
    """그룹입찰가 사용으로 복원 (``useGroupBidAmt=True``).

    Story 1.3 측정 후 ``put_bid`` 가 자동 useGroupBidAmt=False 로 전환시킨 KW를
    원래 그룹입찰 사용 상태로 복원. 측정 종료 후 try/finally 안에서 호출.
    """
    uri = f"/ncc/keywords/{keyword_id}"
    headers = build_headers(
        "PUT",
        uri,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
    )
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=base_url, timeout=timeout_s) as client:
            response = client.put(
                uri,
                params={"fields": "useGroupBidAmt"},
                json={"nccAdgroupId": adgroup_id, "useGroupBidAmt": True},
                headers=headers,
            )
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = None
    return response.status_code, body, round(latency_ms, 2)


def get_keyword_with_bad_timestamp(
    keyword_id: str,
    *,
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
    drift_seconds: int = 3600,
) -> tuple[int, dict[str, Any] | None, float]:
    """일부러 timestamp를 ``drift_seconds`` 만큼 어긋나게 보내 403 invalid timestamp 유도.

    NTP guard 검증용 spike — Story 1.5의 ``ntp_guard`` 가 사전 차단할 시나리오 확인.
    """
    drift_ms = str(int(time.time() * 1000) + drift_seconds * 1000)
    return get_keyword(
        keyword_id,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
        base_url=base_url,
        timestamp_ms_override=drift_ms,
    )


def get_current_bid(
    keyword_id: str,
    *,
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
) -> int:
    """편의: bidAmt 값만 빼서 반환. 측정 시작 전 원래 bid 캡처 → 종료 후 복원용.

    Raises:
        RuntimeError: GET 응답이 200이 아니거나 body에 bidAmt가 없을 때.
    """
    status, body, _ = get_keyword(
        keyword_id,
        api_key=api_key,
        secret_key=secret_key,
        customer_id=customer_id,
        base_url=base_url,
    )
    if status != 200 or body is None or "bidAmt" not in body:
        raise RuntimeError(f"GET 실패 — status={status}, body={body}. 원래 bid 캡처 불가.")
    return int(body["bidAmt"])
