"""Unit tests — http_client.fetch_serp_html.

requests_mock 같은 외부 lib 회피 — unittest.mock.patch.object로 _SESSION.get만 mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from measurer import http_client


def _make_response(status_code: int, text: str = "") -> MagicMock:
    """P2 review (2026-05-27): http_client는 stream=True + iter_content + utf-8 decode 사용.

    Mock은 iter_content가 UTF-8 인코딩된 단일 chunk를 yield하도록.
    """
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text  # 호환용 (호출 안 됨)
    encoded = text.encode("utf-8") if text else b""
    resp.iter_content = MagicMock(return_value=iter([encoded] if encoded else []))
    resp.close = MagicMock()
    return resp


def test_happy_path_200_returns_text_and_status() -> None:
    fake_response = _make_response(200, "<html>SERP body</html>")
    with patch.object(http_client._SESSION, "get", return_value=fake_response) as fake_get:
        html, status = http_client.fetch_serp_html("수자인")

    assert html == "<html>SERP body</html>"
    assert status == 200
    fake_get.assert_called_once()
    # URL 검증 — query string에 term이 URL-encoded로 들어갔는지.
    call_args = fake_get.call_args
    url = call_args.args[0]
    parsed = urlparse(url)
    assert parsed.netloc == "m.search.naver.com"
    assert parsed.path == "/search.naver"
    query_params = parse_qs(parsed.query)
    assert query_params["query"] == ["수자인"]


def test_500_returns_none_with_status() -> None:
    fake_response = _make_response(500)
    with patch.object(http_client._SESSION, "get", return_value=fake_response):
        html, status = http_client.fetch_serp_html("수자인")
    assert html is None
    assert status == 500


def test_timeout_returns_none_zero() -> None:
    with patch.object(http_client._SESSION, "get", side_effect=requests.Timeout):
        html, status = http_client.fetch_serp_html("수자인")
    assert html is None
    assert status == 0


def test_connection_error_returns_none_zero() -> None:
    with patch.object(http_client._SESSION, "get", side_effect=requests.ConnectionError):
        html, status = http_client.fetch_serp_html("수자인")
    assert html is None
    assert status == 0


def test_generic_request_exception_returns_none_zero() -> None:
    with patch.object(http_client._SESSION, "get", side_effect=requests.RequestException("boom")):
        html, status = http_client.fetch_serp_html("수자인")
    assert html is None
    assert status == 0


def test_session_headers_contain_mobile_ua_and_kor_lang() -> None:
    """Module-level Session에 모바일 UA + ko-KR 박제 확인."""
    assert "Mobile Safari" in http_client._SESSION.headers["User-Agent"]
    assert http_client._SESSION.headers["Accept-Language"] == "ko-KR,ko;q=0.9"
    assert http_client._SESSION.headers["Connection"] == "keep-alive"


def test_custom_timeout_passed_to_session() -> None:
    fake_response = _make_response(200, "ok")
    with patch.object(http_client._SESSION, "get", return_value=fake_response) as fake_get:
        http_client.fetch_serp_html("수자인", timeout=5.5)
    assert fake_get.call_args.kwargs["timeout"] == pytest.approx(5.5)
