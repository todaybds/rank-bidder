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


@pytest.fixture(autouse=True)
def _skip_warmup(monkeypatch: pytest.MonkeyPatch):
    """2026-05-28 봇 회피 패치 — fetch_serp_html 첫 호출 시 _warmup_session이 m.naver.com을
    GET함. 테스트는 SERP fetch만 검증하므로 warmup은 mock으로 no-op 처리.
    """
    monkeypatch.setattr(http_client, "_warmup_session", lambda timeout=10.0: None)


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


def test_build_headers_returns_mobile_ua_and_kor_lang() -> None:
    """2026-05-28 봇 회피 갱신: _build_headers()가 매 호출 모바일 UA 풀에서 회전 +
    한국어 Accept-Language + Referer 박제 검증.
    """
    headers = http_client._build_headers(referer="https://m.naver.com/")
    assert "Mobile" in headers["User-Agent"] or "iPhone" in headers["User-Agent"]
    assert "ko-KR" in headers["Accept-Language"]
    assert headers["Connection"] == "keep-alive"
    assert headers["Referer"] == "https://m.naver.com/"
    # UA pool 자체 검증 — 5개 이상의 다양한 UA 박제
    assert len(http_client._MOBILE_UA_POOL) >= 4


def test_build_headers_rotates_user_agent() -> None:
    """반복 호출 시 UA가 회전 (단일 시그너처 박히는 거 회피)."""
    uas = {http_client._build_headers()["User-Agent"] for _ in range(50)}
    assert len(uas) >= 2  # 50회 시도면 최소 2개 이상 다른 UA 박힘 (확률적으로 사실상 보장)


def test_custom_timeout_passed_to_session() -> None:
    fake_response = _make_response(200, "ok")
    with patch.object(http_client._SESSION, "get", return_value=fake_response) as fake_get:
        http_client.fetch_serp_html("수자인", timeout=5.5)
    assert fake_get.call_args.kwargs["timeout"] == pytest.approx(5.5)
