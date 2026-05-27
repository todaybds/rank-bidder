"""Unit test — Naver SA HMAC signature 결정성 + 헤더 구성.

실제 Naver API 호출 X (unit test). dry-run measurement는
``tests/dry_run/test_naver_semantics_dryrun.py`` 가 담당.
"""

from __future__ import annotations

from rank_bidder.naver_sa.auth import build_headers, make_signature, now_timestamp_ms


def test_signature_is_deterministic() -> None:
    """동일 input → 동일 signature."""
    sig1 = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    sig2 = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    assert sig1 == sig2


def test_signature_changes_with_timestamp() -> None:
    """timestamp만 달라도 signature 변경."""
    sig1 = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    sig2 = make_signature("GET", "/ncc/keywords/abc", "1700000000001", "secret")
    assert sig1 != sig2


def test_signature_changes_with_method() -> None:
    """GET vs PUT signature 다름."""
    sig_get = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    sig_put = make_signature("PUT", "/ncc/keywords/abc", "1700000000000", "secret")
    assert sig_get != sig_put


def test_signature_changes_with_uri() -> None:
    """다른 URI → 다른 signature (path 일부 바뀜 검증)."""
    sig_a = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    sig_b = make_signature("GET", "/ncc/keywords/xyz", "1700000000000", "secret")
    assert sig_a != sig_b


def test_signature_changes_with_secret() -> None:
    """다른 secret → 다른 signature (HMAC 핵심)."""
    sig_a = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret_a")
    sig_b = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret_b")
    assert sig_a != sig_b


def test_signature_is_base64() -> None:
    """SHA256 digest → base64 = 44 chars 끝에 '=' 패딩."""
    sig = make_signature("GET", "/ncc/keywords/abc", "1700000000000", "secret")
    # SHA256 digest = 32 bytes → base64 = 44 chars (with padding)
    assert len(sig) == 44
    assert sig.endswith("=")


def test_signature_matches_legacy_v85_pattern() -> None:
    """v85 (Cloudflare Worker) 구현과 동일 signature 보장.

    참조: c:/Users/ok/Desktop/ads-automation/common.py:_naver_sign.
    msg 포맷 = ``f"{ts}.{method}.{uri}"`` — 변경 시 Story 1.5 client + 기존 ops 모두 깨짐.
    """
    import base64
    import hashlib
    import hmac

    ts, method, uri, secret = "1700000000000", "GET", "/ncc/keywords/abc", "secret_xyz"
    msg = f"{ts}.{method}.{uri}"
    expected = base64.b64encode(
        hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    actual = make_signature(method, uri, ts, secret)
    assert actual == expected


def test_build_headers_has_all_four_naver_headers() -> None:
    headers = build_headers(
        "GET",
        "/ncc/keywords/abc",
        api_key="key123",
        secret_key="secret_abc",
        customer_id="2553973",
    )
    assert headers["X-API-KEY"] == "key123"
    assert headers["X-Customer"] == "2553973"
    assert "X-Timestamp" in headers
    assert "X-Signature" in headers
    assert headers["Content-Type"] == "application/json"
    # signature는 timestamp 따라 변하지만 길이는 44
    assert len(headers["X-Signature"]) == 44


def test_build_headers_with_explicit_timestamp() -> None:
    """drift 시뮬레이션용 — timestamp_ms override 검증."""
    headers = build_headers(
        "GET",
        "/ncc/keywords/abc",
        api_key="key",
        secret_key="secret",
        customer_id="123",
        timestamp_ms="1700000000000",
    )
    assert headers["X-Timestamp"] == "1700000000000"


def test_now_timestamp_ms_format() -> None:
    """13자리 string (millisecond Unix epoch)."""
    ts = now_timestamp_ms()
    assert ts.isdigit()
    assert 13 <= len(ts) <= 14  # 2026년 = 13자리, 미래엔 14자리 가능
