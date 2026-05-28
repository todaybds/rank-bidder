"""Naver SA API production client (Story 1.5, D14).

- ``httpx.Client`` sync + HMAC-SHA256 (Story 1.3 ``auth.py`` 재사용)
- ``pyrate-limiter`` 5 req/s 토큰버킷
- ``tenacity`` 1→2→4초 지수 백오프 (429/5xx, 최대 3회 재시도)
- 403 invalid-timestamp → ``ntp.resync_ntp()`` 후 1회 재시도 → ``NaverSANtpDrift``
- 403 (그 외) → ``NaverAuthError`` (키 해지/IP 차단/권한 변경 — NTP path와 구별)
- 404 → ``NaverKeywordDeleted`` (재시도 X)
- 400 → ``NaverInvalidRequest`` (재시도 X)

cycle 사이에 instance 재활용 가능 (httpx Session keep-alive). 보통 process 전역 1개.

**단일 프로세스 invariant (D4, 2026-05-27 code-review 박제):**
``_RATE_LIMITER`` 는 PID-local in-memory 버킷이다. 멀티-워커/멀티-프로세스 동시 실행
금지 — 각 PID가 독립 5 RPS 버킷을 가져 NFR-4 (Naver SA 5-8 req/s) 위반함.
운영 = 단일 cron + 단일 측정 worker (architecture I1·I2·D24). FastAPI uvicorn은 단일
워커로만 구동 (`workers=1`). 멀티-프로세스가 필요해지면 SQLiteBucket으로 전환 + 본
invariant 재검토 필요.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from pyrate_limiter import BucketFullException, Duration, Limiter, Rate
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rank_bidder.naver_sa.auth import build_headers
from rank_bidder.naver_sa.exceptions import (
    NaverAuthError,
    NaverInvalidRequest,
    NaverKeywordDeleted,
    NaverSAError,
    NaverSANtpDrift,
    NaverSAUnavailable,
)
from rank_bidder.naver_sa.ntp import resync_ntp

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 4  # tenacity stop_after_attempt(MAX_ATTEMPTS) = 1 original + 3 retries
_INVALID_TIMESTAMP_RE = re.compile(r"invalid[- _]?timestamp", re.IGNORECASE)


@dataclass(frozen=True)
class _Credentials:
    api_key: str
    secret_key: str
    customer_id: str
    base_url: str


def _load_credentials() -> _Credentials:
    """env 변수에서 자격증명 로드. 누락 / 공백만 / 빈 토큰은 RuntimeError (Story 1.4 패턴 강화)."""
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
        if not val or not val.strip()
    ]
    if missing:
        raise RuntimeError(f"Naver SA credentials missing: {', '.join(missing)}")
    return _Credentials(
        api_key.strip(),
        secret_key.strip(),
        customer_id.strip(),
        base_url.strip().rstrip("/"),
    )


# 모듈 전역 — pyrate-limiter 5 req/s 토큰버킷. NFR-4 매체 정책 준수.
# Limiter 객체는 thread-safe, **단일 프로세스 내** 공유 안전 (모듈 docstring D4 invariant 참조).
_RATE_LIMITER: Limiter = Limiter(Rate(5, Duration.SECOND))
_RATE_LIMITER_BUCKET = "naver_sa"


def _acquire_rate_limit(max_wait_s: float = 10.0) -> None:
    """5 req/s 토큰 확보. BucketFull 시 200ms ±jitter sleep + 재시도.

    멀티-스레드 환경에서 같은 tick에 깨어나 thundering-herd 형성 방지 위해 jitter 추가.
    max_wait_s 초과 시 ``NaverSAUnavailable`` (예외 계층 일관성 — F12).
    """
    started = time.perf_counter()
    while True:
        try:
            _RATE_LIMITER.try_acquire(_RATE_LIMITER_BUCKET)
            break
        except BucketFullException as exc:
            elapsed = time.perf_counter() - started
            if elapsed > max_wait_s:
                log.warning("naver_sa.rate_limit_timeout", waited_s=elapsed)
                raise NaverSAUnavailable(
                    f"local rate-limit timeout after {elapsed:.2f}s", status_code=None, body=None
                ) from exc
            # 200ms ±50ms jitter → 5 req/s 토큰 refill 간격에 산포
            time.sleep(0.20 + random.uniform(-0.05, 0.05))
    wait_ms = round((time.perf_counter() - started) * 1000, 2)
    if wait_ms > 1.0:
        log.info("naver_sa.rate_limit_wait", wait_ms=wait_ms, bucket=_RATE_LIMITER_BUCKET)


def _safe_body(body: object) -> str:
    """structlog 출력용 — JSONRenderer가 깨질 만한 타입(bytes/datetime/set)을 안전 직렬화 (P25)."""
    try:
        return json.dumps(body, default=str, ensure_ascii=False)[:500]
    except (TypeError, ValueError):
        return repr(body)[:500]


def _is_invalid_timestamp_403(body: object) -> bool:
    """403 body가 Naver "invalid timestamp" 시그널인지 판정 (P9).

    Naver는 ``{"type": "urn:naver:api:problem:invalid-timestamp"}`` 또는 title/message에
    "invalid timestamp" 문자열 포함. 그 외 403(키 해지/IP 차단)은 False → ``NaverAuthError``.
    """
    if not isinstance(body, dict):
        return False
    for key in ("type", "title", "message", "detail", "code"):
        val = body.get(key)
        if isinstance(val, str) and _INVALID_TIMESTAMP_RE.search(val):
            return True
    return False


def _is_code_1016(body: object) -> bool:
    """1016 (too-many-connections) 검사 — Naver 응답에서 code는 int OR str로 옴 (P10)."""
    if not isinstance(body, dict):
        return False
    code = body.get("code")
    return str(code) == "1016"


def _raise_for_status(
    status: int, body: object, *, uri: str = "", method: str = "", hint: str = ""
) -> None:
    """status별 적절한 예외 raise. 재시도 가능(429/5xx)은 NaverSAUnavailable.

    404 NaverKeywordDeleted 직전 ``naver_sa.keyword_deleted`` 이벤트 발생 (AC6 / P2).
    """
    if status == 400:
        raise NaverInvalidRequest(
            f"Naver SA 400: {body} {hint}".strip(), status_code=status, body=body
        )
    if status == 404:
        log.warning(
            "naver_sa.keyword_deleted",
            method=method,
            uri=uri,
            status=404,
            body=_safe_body(body),
        )
        raise NaverKeywordDeleted(
            f"Naver SA 404 (keyword deleted): {body}", status_code=status, body=body
        )
    if status == 429 or _is_code_1016(body):
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
    """단발 HTTP — **호출마다 fresh HMAC 헤더 생성** (P8 — tenacity 재시도가 stale 서명
    재사용해 5초+ 지연 시 Naver 403 invalid-timestamp 유발하는 문제 차단). status/body 반환.

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
        if method == "POST":
            return c.post(uri, params=params, json=json_body, headers=headers)
        raise ValueError(f"unsupported method: {method}")

    if client is not None:
        response = _do(client)
    else:
        with httpx.Client(base_url=creds.base_url, timeout=timeout_s) as c:
            response = _do(c)

    body: dict[str, Any] | None = None
    try:
        body = response.json()
    except (ValueError, httpx.DecodingError, json.JSONDecodeError):
        # non-JSON 응답 — status만 보고 분기
        body = None
    return response.status_code, body


def _log_retry(retry_state: Any) -> None:  # noqa: ANN401 — tenacity retry_state 타입 미공개
    """tenacity ``before_sleep`` 콜백 — AC7 `naver_sa.retry` 이벤트 발생 (P1).

    ``attempt_number``, 다음 wait(ms), 마지막 outcome 정보 박제 — observability 핵심.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    last_status = getattr(exc, "status_code", None) if exc is not None else None
    next_wait_ms = round(retry_state.next_action.sleep * 1000, 2) if retry_state.next_action else 0
    log.warning(
        "naver_sa.retry",
        attempt=retry_state.attempt_number,
        next_wait_ms=next_wait_ms,
        last_status=last_status,
        last_error=str(exc) if exc else None,
    )


# tenacity 데코레이터 — 429/5xx (NaverSAUnavailable) 만 재시도.
# 1→2→4초 wait, 최대 ``MAX_ATTEMPTS`` attempt (즉 3 재시도).
_retry_unavailable = retry(
    retry=retry_if_exception_type(NaverSAUnavailable),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    reraise=True,
    before_sleep=_log_retry,
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
) -> tuple[int, dict[str, Any]]:
    """rate-limit + tenacity 백오프 + 403 NTP 재시도까지 묶은 정식 API 호출.

    Returns:
        (status, body). status는 항상 200 (예외 외 경로 없음).

    Raises:
        NaverInvalidRequest, NaverKeywordDeleted, NaverAuthError, NaverSANtpDrift,
        NaverSAUnavailable.
    """
    if creds is None:
        creds = _load_credentials()

    started = time.perf_counter()
    log.info(
        "naver_sa.request_started",
        method=method,
        uri=uri,
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
        # 429/5xx/1016만 즉시 raise → tenacity가 retry. 다른 비-200(400/403/404)은 그대로 반환.
        if st == 429 or st >= 500 or _is_code_1016(bd):
            raise NaverSAUnavailable(f"Naver SA transient {st}: {bd}", status_code=st, body=bd)
        return st, bd

    try:
        status, body = _attempt()
    except NaverSAUnavailable:
        log.warning("naver_sa.unavailable", method=method, uri=uri, attempts=MAX_ATTEMPTS)
        raise

    # 403 분기 — invalid-timestamp만 NTP path. 그 외(키 해지/IP 차단/권한)는 NaverAuthError (P9).
    if status == 403:
        if not _is_invalid_timestamp_403(body):
            log.error(
                "naver_sa.auth_error",
                method=method,
                uri=uri,
                body=_safe_body(body),
            )
            raise NaverAuthError(
                f"403 non-timestamp (auth/permission): {body}", status_code=403, body=body
            )

        log.warning(
            "naver_sa.ntp_drift_detected",
            method=method,
            uri=uri,
            body=_safe_body(body),
        )
        synced = resync_ntp()
        if not synced:
            log.warning("naver_sa.ntp_resync_unavailable", method=method, uri=uri)

        # 1회 인라인 재시도 — recursion 안 함 (P5: retry 예산 doubling 방지).
        # rate-limit acquire는 한 번 더; tenacity 재시도 budget은 reset 안 함.
        _acquire_rate_limit()
        status, body = _http_call(
            method,
            uri,
            creds=creds,
            params=params,
            json_body=json_body,
            timeout_s=timeout_s,
            client=client,
        )
        if status == 403:
            log.error(
                "naver_sa.ntp_drift_persists",
                method=method,
                uri=uri,
                body=_safe_body(body),
                synced=synced,
            )
            raise NaverSANtpDrift(
                f"403 persists after NTP resync (synced={synced}): {body}",
                status_code=403,
                body=body,
            )

    if status != 200:
        # 400/404/429/5xx — 분기 후 raise. (429/5xx는 tenacity가 이미 잡았어야 하나 안전망)
        _raise_for_status(status, body, uri=uri, method=method)

    if body is None:
        # P7: -O 플래그로 assert strip 방지 — 명시적 raise
        raise NaverSAError("200 응답인데 JSON body가 None") from None

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "naver_sa.request_completed",
        method=method,
        uri=uri,
        status=200,
        latency_ms=latency_ms,
    )
    return status, body
