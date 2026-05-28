"""Unit tests — naver_sa.estimate.average_position_bid (Story 1.5 + 2026-05-28 POST fix)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from rank_bidder.naver_sa.estimate import average_position_bid
from rank_bidder.naver_sa.exceptions import NaverInvalidRequest

KW_ID = "nkw-test-est-1"
KW_TERM = "수자인"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_API_KEY", "k")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_SECRET_KEY", "s")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "1")
    monkeypatch.setattr("rank_bidder.naver_sa.client._acquire_rate_limit", lambda *a, **k: None)
    yield


def _client(h: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=h, base_url="https://api.searchad.naver.com")


def test_estimate_posts_with_items_payload() -> None:
    """2026-05-28 POST fix: device + items[{key, position}] body 박제."""

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/estimate/average-position-bid/keyword" in str(req.url)
        body = json.loads(req.content)
        assert body["device"] == "MOBILE"  # 디폴트 모바일
        assert body["items"] == [{"key": KW_TERM, "position": 3}]
        return httpx.Response(200, json={"estimate": [{"position": 3, "bid": 21500}]})

    with _client(httpx.MockTransport(handler)) as c:
        bid = average_position_bid(KW_ID, KW_TERM, 3, client=c)
    assert bid == 21500


def test_estimate_device_pc_override() -> None:
    """device PC override 박제."""

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["device"] == "PC"
        return httpx.Response(200, json={"estimate": [{"bid": 8800}]})

    with _client(httpx.MockTransport(handler)) as c:
        bid = average_position_bid(KW_ID, KW_TERM, 2, device="PC", client=c)
    assert bid == 8800


def test_estimate_alternate_wrapper_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keywordEstimatedBid": [{"bid": 9999}]})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, KW_TERM, 1, client=c) == 9999


def test_estimate_empty_returns_none() -> None:
    """D3 (2026-05-27 review): empty/unparsable shape → None (sentinel = parse-failure).

    0 KRW는 Naver의 valid 응답값 → 0과 구별돼야 함.
    """

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"estimate": []})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, KW_TERM, 5, client=c) is None


def test_estimate_zero_bid_preserved() -> None:
    """0 KRW는 valid — falsy `or` coalesce 제거 (P11)로 0이 그대로 반환돼야 함."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"estimate": [{"position": 1, "bid": 0}]})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, KW_TERM, 1, client=c) == 0


def test_estimate_silent_method_not_allowed_returns_none() -> None:
    """2026-05-28 silent bug 박제: Naver가 HTTP 200으로 ``{name,status:405}`` wrapper 응답.
    _extract_bid가 명시적 None 반환 (이전엔 bid key 부재로 None 반환 = 우연히 통과,
    명시적 guard로 정정).
    """

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "MethodNotAllowed",
                "status": 405,
                "title": "Method Not Allowed",
                "detail": "Supported methods are 'POST,'",
            },
        )

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, KW_TERM, 2, client=c) is None


def test_estimate_target_rank_bool_rejected() -> None:
    """P13: target_rank=True (== 1) 통과 silently 차단."""
    with pytest.raises(ValueError, match=r"must be a builtin int"):
        average_position_bid(KW_ID, KW_TERM, True)  # type: ignore[arg-type]


def test_estimate_target_rank_below_1_raises() -> None:
    with pytest.raises(ValueError, match=r"target_rank must be in"):
        average_position_bid(KW_ID, KW_TERM, 0)


def test_estimate_target_rank_above_10_raises() -> None:
    with pytest.raises(ValueError, match=r"target_rank must be in"):
        average_position_bid(KW_ID, KW_TERM, 11)


def test_estimate_empty_term_raises() -> None:
    with pytest.raises(ValueError, match=r"keyword_term must be a non-empty string"):
        average_position_bid(KW_ID, "", 1)


def test_estimate_invalid_device_raises() -> None:
    with pytest.raises(ValueError, match=r"device must be"):
        average_position_bid(KW_ID, KW_TERM, 1, device="TABLET")


def test_estimate_400_raises_invalid_request() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"title": "Invalid keyword id"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverInvalidRequest):
        average_position_bid(KW_ID, KW_TERM, 2, client=c)
