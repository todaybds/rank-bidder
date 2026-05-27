"""Unit tests — naver_sa.estimate.average_position_bid (Story 1.5)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from rank_bidder.naver_sa.estimate import average_position_bid
from rank_bidder.naver_sa.exceptions import NaverInvalidRequest

KW_ID = "nkw-test-est-1"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_API_KEY", "k")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_SECRET_KEY", "s")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "1")
    monkeypatch.setattr("rank_bidder.naver_sa.client._acquire_rate_limit", lambda *a, **k: None)
    yield


def _client(h: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=h, base_url="https://api.searchad.naver.com")


def test_estimate_happy_estimate_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/estimate/average-position-bid/keyword" in str(req.url)
        assert "nccKeywordId" in str(req.url)
        assert "position=3" in str(req.url)
        return httpx.Response(200, json={"estimate": [{"position": 3, "bid": 21500}]})

    with _client(httpx.MockTransport(handler)) as c:
        bid = average_position_bid(KW_ID, 3, client=c)
    assert bid == 21500


def test_estimate_alternate_wrapper_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keywordEstimatedBid": [{"bid": 9999}]})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, 1, client=c) == 9999


def test_estimate_empty_returns_none() -> None:
    """D3 (2026-05-27 review): empty/unparsable shape → None (sentinel = parse-failure).

    0 KRW는 Naver의 valid 응답값 → 0과 구별돼야 함.
    """

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"estimate": []})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, 5, client=c) is None


def test_estimate_zero_bid_preserved() -> None:
    """0 KRW는 valid — falsy `or` coalesce 제거 (P11)로 0이 그대로 반환돼야 함."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"estimate": [{"position": 1, "bid": 0}]})

    with _client(httpx.MockTransport(handler)) as c:
        assert average_position_bid(KW_ID, 1, client=c) == 0


def test_estimate_target_rank_bool_rejected() -> None:
    """P13: target_rank=True (== 1) 통과 silently 차단."""
    with pytest.raises(ValueError, match=r"must be a builtin int"):
        average_position_bid(KW_ID, True)  # type: ignore[arg-type]


def test_estimate_target_rank_below_1_raises() -> None:
    with pytest.raises(ValueError, match=r"target_rank must be in"):
        average_position_bid(KW_ID, 0)


def test_estimate_target_rank_above_10_raises() -> None:
    with pytest.raises(ValueError, match=r"target_rank must be in"):
        average_position_bid(KW_ID, 11)


def test_estimate_400_raises_invalid_request() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"title": "Invalid keyword id"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverInvalidRequest):
        average_position_bid(KW_ID, 2, client=c)
