"""Naver SA API HMAC-SHA256 인증 helper — Story 1.3 spike, Story 1.5에서 풀세트로 흡수.

Naver 공식 signature 패턴:
    msg = f"{timestamp_ms}.{method}.{uri}"
    signature = base64(HMAC-SHA256(secret_key, msg))

Headers 4종: X-Timestamp / X-API-KEY / X-Customer / X-Signature.
참고: https://github.com/naver/searchad-apidoc
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time


def make_signature(method: str, uri: str, timestamp_ms: str, secret_key: str) -> str:
    """Naver SA HMAC-SHA256 signature.

    Args:
        method: HTTP method (대문자, e.g. ``"GET"``, ``"PUT"``).
        uri: API path (query string 제외, e.g. ``"/ncc/keywords/abc123"``).
        timestamp_ms: Unix epoch milliseconds as string.
        secret_key: Naver SA SECRET_KEY (base64-encoded original value 그대로).

    Returns:
        base64-encoded HMAC digest.
    """
    msg = f"{timestamp_ms}.{method}.{uri}"
    digest = hmac.new(
        secret_key.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def now_timestamp_ms() -> str:
    """현재 시각의 Unix epoch milliseconds string. NTP 동기화 필수 (>5s drift = 403)."""
    return str(int(time.time() * 1000))


def build_headers(
    method: str,
    uri: str,
    *,
    api_key: str,
    secret_key: str,
    customer_id: str,
    timestamp_ms: str | None = None,
) -> dict[str, str]:
    """완전한 Naver SA 인증 헤더 dict.

    Args:
        method: HTTP method (대문자).
        uri: API path (query string 제외).
        api_key: ``NAVER_API_KEY``.
        secret_key: ``NAVER_SECRET_KEY``.
        customer_id: ``NAVER_CUSTOMER_ID``.
        timestamp_ms: 명시 시점 (테스트용 — invalid timestamp 시뮬레이션 등). None이면 현재 시각.
    """
    ts = timestamp_ms if timestamp_ms is not None else now_timestamp_ms()
    return {
        "X-Timestamp": ts,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": make_signature(method, uri, ts, secret_key),
        "Content-Type": "application/json",
    }
