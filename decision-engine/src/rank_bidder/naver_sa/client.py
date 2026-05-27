"""Naver SA API production client (Story 1.5, D14).

- ``httpx.Client`` sync + HMAC-SHA256 (Story 1.3 ``auth.py`` 재사용)
- ``pyrate-limiter`` 5 req/s 토큰버킷
- ``tenacity`` 1→2→4초 지수 백오프 (429/5xx, 최대 3회 재시도)
- 403 invalid-timestamp → ``ntp.resync_ntp()`` 후 1회 재시도 → ``NaverSANtpDrift``
- 404 → ``NaverKeywordDeleted`` (재시도 X)
- 400 → ``NaverInvalidRequest`` (재시도 X)

cycle 사이에 instance 재활용 가능 (httpx Session keep-alive). 보통 process 전역 1개.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from pyrate_limiter import BucketFullException, Duration, Limiter, Rate
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rank_bidder.naver_sa.auth import build_headers
from rank_bidder.naver_sa.exceptions import (
    NaverInvalidRequest,
    NaverKeywordDeleted,
    NaverSANtpDrift,
    NaverSAUnavailable,
)
from rank_bidder.naver_sa.ntp import resync_ntp

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _Credentials:
    api_key: str
    secret_key: str
    customer_id: str
    base_url: str


def _load_credentials() -> _Credentials:
    """env 변수에서 자격증명 로드. 누락 시 RuntimeError (Story 1.4 패턴 — 빈 토큰 우회 차단)."""
    api_key = os.environ.get("RANKBIDDER_NAVER_SA_API_KEY", "")
    secret_key = os.environ.get("RANKBIDDER_NAVER_SA_SECRET_KEY", "")
    customer_id = os.environ.get("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "")
    base_url = os.environ.get("RANKBIDDER_NAVER_SA_BASE_URL", "https://api.searchad.naver.com")
    missing = [
        name
        for name, val in [
            ("RANKBIDDER_NAVER_SA_API_KEY", api_key),
            ("RANKBIDDER_NAVER_SA_SECRET_KEY", secret_key),
            ("RANKBIDDER_NAVER_SA_CUSTOMER_ID", customer_id),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(f"Naver SA credentials missing: {', '.join(missing)}")
    return _Credentials(api_key, secret_key, customer_id, base_url)


# 모듈 전역 — pyrate-limiter 5 req/s 토큰버킷. NFR-4 매체 정책 준수.
# Limiter 객체는 thread-safe, process 내 공유 안전.
_RATE_LIMITER: Limiter = Limiter(Rate(5, Duration.SECOND))
_RATE_LIMITER_BUCKET = "naver_sa"


def _acquire_rate_limit(max_wait_s: float = 10.0) -> None:
    """5 req/s 토큰 확보. BucketFull 시 짧게 sleep + 재시도 (max_wait_s 초과 시 raise).

    pyrate-limiter v3 ``try_acquire`` 는 한도 초과 시 BucketFullException raise (delay 모드 아님).
    여기서는 wait-mode 흉내 — 200ms(5 req/s 간격) 단위로 재시도.
    """
    started = time.perf_counter()
    while True:
        try:
            _RATE_LIMITER.try_acquire(_RATE_LIMITER_BUCKET)
            break
        except BucketFullException:
            elapsed = time.perf_counter() - started
            if elapsed > max_wait_s:
                log.warning("naver_sa.rate_limit_timeout", waited_s=elapsed)
                raise
            time.sleep(0.21)
    wait_ms = round((time.perf_counter() - started) * 1000, 2)
    if wait_ms > 1.0:
        log.info("naver_sa.rate_limit_wait", wait_ms=wait_ms, bucket=_RATE_LIMITER_BUCKET)


def _raise_for_status(status: int, body: object, *, hint: str = "") -> None:
    """status별 적절한 예외 raise. 재시도 가능(429/5xx)은 NaverSAUnavailable."""
    if status == 400:
        raise NaverInvalidRequest(
            f"Naver SA 400: {body} {hint}".strip(), status_code=status, body=body
        )
    if status == 404:
        raise NaverKeywordDeleted(
            f"Naver SA 404 (keyword deleted): {body}", status_code=status, body=body
        )
    if status == 429 or (isinstance(body, dict) and body.get("code") == 1016):
        raise NaverSAUnavailable(f"Naver SA 429/1016: {body}", status_code=status, body=body)
    if status >= 500:
        raise NaverSAUnavailable(f"Naver SA 5xx ({status}): {body}", status_code=status, body=body)


def _http_call(
    method: str,
    uri: str,
    *,
    creds: _Credentials,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
    client: httpx.Client | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """단발 HTTP — 인증 헤더 생성 + 호출. status/body 반환. 예외는 _raise_for_status 별도.

    ``client`` 가 주어지면 그 instance 사용(테스트용 MockTransport 주입). 기본은 일회용 Client.
    """
    headers = build_headers(
        method,
        uri,
        api_key=creds.api_key,
        secret_key=creds.secret_key,
        customer_id=creds.customer_id,
    )

    def _do(c: httpx.Client) -> httpx.Response:
        if method == "GET":
            return c.get(uri, params=params, headers=headers)
        if method == "PUT":
            return c.put(uri, params=params, json=json_body, headers=headers)
        raise ValueError(f"unsupported method: {method}")

    if client is not None:
        response = _do(client)
    else:
        with httpx.Client(base_url=creds.base_url, timeout=timeout_s) as c:
            response = _do(c)

    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — non-JSON 응답도 status만 보면 됨
        body = None
    return response.status_code, body


# tenacity 데코레이터 — 429/5xx (NaverSAUnavailable) 만 재시도.
# 1→2→4초 wait, 최대 4 attempt (즉 3 재시도).
_retry_unavailable = retry(
    retry=retry_if_exception_type(NaverSAUnavailable),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    stop=stop_after_attempt(4),
    reraise=True,
)


def call_with_retry(
    method: str,
    uri: str,
    *,
    creds: _Credentials | None = None,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
    client: httpx.Client | None = None,
    ntp_resync_done: bool = False,
) -> tuple[int, dict[str, Any]]:
    """rate-limit + tenacity 백오프 + 403 NTP 재시도까지 묶은 정식 API 호출.

    Returns:
        (status, body). status는 항상 200 (예외 외 경로 없음).

    Raises:
        NaverInvalidRequest, NaverKeywordDeleted, NaverSANtpDrift, NaverSAUnavailable.
    """
    if creds is None:
        creds = _load_credentials()

    attempt = 1
    started = time.perf_counter()
    log.info(
        "naver_sa.request_started",
        method=method,
        uri=uri,
        attempt=attempt,
    )

    @_retry_unavailable
    def _attempt() -> tuple[int, dict[str, Any] | None]:
        _acquire_rate_limit()
        st, bd = _http_call(
            method,
            uri,
            creds=creds,
            params=params,
            json_body=json_body,
            timeout_s=timeout_s,
            client=client,
        )
        # 429/5xx/1016만 즉시 raise → tenacity가 retry
        # 다른 비-200(400/403/404)은 그대로 반환 → call_with_retry 본체에서 분기
        if st == 429 or st >= 500 or (isinstance(bd, dict) and bd.get("code") == 1016):
            raise NaverSAUnavailable(f"Naver SA transient {st}: {bd}", status_code=st, body=bd)
        return st, bd

    try:
        status, body = _attempt()
    except RetryError as exc:  # tenacity 최종 실패 — reraise=True라 안 도달
        log.error("naver_sa.retry_exhausted", method=method, uri=uri, error=str(exc))
        raise
    except NaverSAUnavailable:
        log.warning("naver_sa.unavailable", method=method, uri=uri, attempts=4)
        raise

    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    # 403 invalid-timestamp 분기
    if status == 403:
        if ntp_resync_done:
            log.error(
                "naver_sa.ntp_drift_persists",
                method=method,
                uri=uri,
                body=body,
            )
            raise NaverSANtpDrift(
                f"403 persists after NTP resync: {body}", status_code=403, body=body
            )
        log.warning("naver_sa.ntp_drift_detected", method=method, uri=uri, body=body)
        resync_ntp()
        # 1회 재귀 재시도 (ntp_resync_done=True로 또 403이면 raise)
        return call_with_retry(
            method,
            uri,
            creds=creds,
            params=params,
            json_body=json_body,
            timeout_s=timeout_s,
            client=client,
            ntp_resync_done=True,
        )

    if status != 200:
        # 400/404/429/5xx — 분기 후 raise. (429/5xx는 tenacity가 이미 잡았어야 하나 안전망)
        _raise_for_status(status, body)

    assert body is not None, "200 응답인데 JSON body가 None"
    log.info(
        "naver_sa.request_completed",
        method=method,
        uri=uri,
        status=200,
        latency_ms=latency_ms,
        attempts=attempt,
    )
    return status, body
