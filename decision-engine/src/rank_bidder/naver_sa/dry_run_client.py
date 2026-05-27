"""Story 1.3 spike — 최소 PUT/GET bidAmt client.

Story 1.5에서 풀세트 client (`pyrate-limiter` + `tenacity` + `ntp_guard`)가
이 모듈을 deprecated 시킴. 본 파일은 측정 spike 전용 — 재시도 없음, rate limit 없음.

NFR-8 단순성: stdlib + ``httpx`` (Story 1.1에 이미 pin)만 사용. 신규 dep 없음.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from rank_bidder.naver_sa.auth import build_headers


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
    api_key: str,
    secret_key: str,
    customer_id: str,
    base_url: str = "https://api.searchad.naver.com",
    timeout_s: float = 30.0,
) -> tuple[int, dict[str, Any] | None, float]:
    """``PUT /ncc/keywords/{keyword_id}?fields=bidAmt`` body ``{"bidAmt": <int>}``.

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
                params={"fields": "bidAmt"},
                json={"bidAmt": bid_amt},
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
