"""Unit tests — auth.verify_token + get_header.

mock 없음 (stdlib hmac만). 결정성 검증.
"""

from __future__ import annotations

from measurer.auth import get_header, verify_token


def test_verify_token_matching_returns_true() -> None:
    assert verify_token("abc123", "abc123") is True


def test_verify_token_mismatch_returns_false() -> None:
    assert verify_token("abc123", "abc124") is False


def test_verify_token_none_provided_returns_false() -> None:
    assert verify_token(None, "abc123") is False


def test_verify_token_empty_provided_returns_false() -> None:
    assert verify_token("", "abc123") is False


def test_verify_token_length_mismatch_returns_false() -> None:
    """hmac.compare_digest는 length 다름도 safe하게 False 반환."""
    assert verify_token("short", "longertoken") is False


def test_verify_token_korean_unicode_match() -> None:
    """UTF-8 인코딩 후 비교 — 한글 token도 정확 매치."""
    assert verify_token("토큰값", "토큰값") is True


def test_get_header_lowercase_key_lookup() -> None:
    headers = {"x-auth-token": "tok"}
    assert get_header(headers, "X-Auth-Token") == "tok"


def test_get_header_mixed_case_key_lookup() -> None:
    headers = {"X-Auth-Token": "tok"}
    assert get_header(headers, "x-auth-token") == "tok"


def test_get_header_missing_returns_none() -> None:
    assert get_header({}, "X-Auth-Token") is None


def test_get_header_other_headers_untouched() -> None:
    headers = {"content-type": "application/json", "x-auth-token": "tok"}
    assert get_header(headers, "x-auth-token") == "tok"
    assert get_header(headers, "content-type") == "application/json"
