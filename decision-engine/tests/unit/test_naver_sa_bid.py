"""Unit tests — naver_sa.bid.put_bid (Story 1.5).

httpx.MockTransport로 Naver SA 응답 시뮬레이션. 실제 API 호출 없음.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from rank_bidder.naver_sa.bid import put_bid
from rank_bidder.naver_sa.exceptions import (
    NaverAuthError,
    NaverInvalidRequest,
    NaverKeywordDeleted,
    NaverSANtpDrift,
    NaverSAUnavailable,
)

KW_ID = "nkw-test-123"
AG_ID = "grp-test-456"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_API_KEY", "test-key")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "9999999")
    # tenacity 백오프 sleep 제거 → test 빠르게
    monkeypatch.setattr("rank_bidder.naver_sa.client.time.sleep", lambda *_a, **_k: None)
    # rate limiter no-op (rate-limit 검증은 별도 test에서)
    monkeypatch.setattr("rank_bidder.naver_sa.client._acquire_rate_limit", lambda *a, **k: None)
    yield


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="https://api.searchad.naver.com")


def test_put_bid_happy_path_200() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT"
        assert f"/ncc/keywords/{KW_ID}" in str(req.url)
        body = req.read()
        assert b'"nccAdgroupId"' in body
        assert b'"useGroupBidAmt":false' in body
        return httpx.Response(
            200, json={"nccKeywordId": KW_ID, "bidAmt": 500, "useGroupBidAmt": False}
        )

    with _client(httpx.MockTransport(handler)) as c:
        result = put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)
    assert result["bidAmt"] == 500
    assert result["useGroupBidAmt"] is False


def test_put_bid_below_min_raises() -> None:
    with pytest.raises(ValueError, match=r"bid_amt must be in"):
        put_bid(KW_ID, 50, adgroup_id=AG_ID)


def test_put_bid_above_max_raises() -> None:
    with pytest.raises(ValueError, match=r"bid_amt must be in"):
        put_bid(KW_ID, 200_000, adgroup_id=AG_ID)


def test_put_bid_empty_kw_raises() -> None:
    with pytest.raises(ValueError, match=r"keyword_id must match"):
        put_bid("", 500, adgroup_id=AG_ID)


def test_put_bid_keyword_id_with_whitespace_rejected() -> None:
    """P26: leading/trailing whitespace → HMAC vs URL 불일치 위험 차단."""
    with pytest.raises(ValueError, match=r"keyword_id must match"):
        put_bid("nkw-test-123\n", 500, adgroup_id=AG_ID)


def test_put_bid_bool_amt_rejected() -> None:
    """P12: True == 1 통과 silently 차단."""
    with pytest.raises(ValueError, match=r"must be a builtin int"):
        put_bid(KW_ID, True, adgroup_id=AG_ID)  # type: ignore[arg-type]


def test_put_bid_float_amt_rejected() -> None:
    """P12: 100.7 silent truncation 차단."""
    with pytest.raises(ValueError, match=r"must be a builtin int"):
        put_bid(KW_ID, 100.7, adgroup_id=AG_ID)  # type: ignore[arg-type]


def test_put_bid_400_raises_invalid_request() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 3705, "title": "Invalid ad group number"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverInvalidRequest):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)


def test_put_bid_404_raises_keyword_deleted() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": 2003, "title": "Not Found"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverKeywordDeleted):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)


def test_put_bid_429_retries_then_raises_unavailable() -> None:
    counter = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(429, json={"code": 1016, "title": "Too many connections"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverSAUnavailable):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)
    # tenacity 4 attempts (1 + 3 retries)
    assert counter["n"] == 4


def test_put_bid_5xx_retries_then_raises_unavailable() -> None:
    counter = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(503, json={"title": "Service Unavailable"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverSAUnavailable):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)
    assert counter["n"] == 4


def test_put_bid_429_then_success_on_retry() -> None:
    seq = iter(
        [
            httpx.Response(429, json={"code": 1016}),
            httpx.Response(429, json={"code": 1016}),
            httpx.Response(200, json={"nccKeywordId": KW_ID, "bidAmt": 500}),
        ]
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return next(seq)

    with _client(httpx.MockTransport(handler)) as c:
        result = put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)
    assert result["bidAmt"] == 500


def test_put_bid_403_resync_then_persists_raises_ntp_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    # ntp.resync_ntp을 no-op으로 패치 → 403이 계속 나면 NaverSANtpDrift
    monkeypatch.setattr("rank_bidder.naver_sa.client.resync_ntp", lambda: False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"type": "urn:naver:api:problem:invalid-timestamp"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverSANtpDrift):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)


def test_put_bid_403_non_timestamp_raises_auth_error() -> None:
    """P9: 키 해지/IP 차단 등 non-timestamp 403은 NTP path 진입 안 함 → NaverAuthError 즉시."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": 1001, "title": "Permission denied"})

    with _client(httpx.MockTransport(handler)) as c, pytest.raises(NaverAuthError):
        put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)


def test_put_bid_403_resync_then_success_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rank_bidder.naver_sa.client.resync_ntp", lambda: True)
    seq = iter(
        [
            httpx.Response(403, json={"type": "urn:naver:api:problem:invalid-timestamp"}),
            httpx.Response(200, json={"nccKeywordId": KW_ID, "bidAmt": 500}),
        ]
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return next(seq)

    with _client(httpx.MockTransport(handler)) as c:
        result = put_bid(KW_ID, 500, adgroup_id=AG_ID, client=c)
    assert result["bidAmt"] == 500


def test_put_bid_missing_env_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """P19: env state leak 차단 — monkeypatch.delenv로 자동 restore."""
    for k in (
        "RANKBIDDER_NAVER_SA_API_KEY",
        "RANKBIDDER_NAVER_SA_SECRET_KEY",
        "RANKBIDDER_NAVER_SA_CUSTOMER_ID",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match=r"credentials missing"):
        put_bid(KW_ID, 500, adgroup_id=AG_ID)


def test_put_bid_whitespace_env_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """P22: 공백만 자격증명 → strip 후 empty 검출."""
    monkeypatch.setenv("RANKBIDDER_NAVER_SA_API_KEY", "  ")
    with pytest.raises(RuntimeError, match=r"credentials missing"):
        put_bid(KW_ID, 500, adgroup_id=AG_ID)
