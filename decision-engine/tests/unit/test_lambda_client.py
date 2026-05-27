"""Story 1.9 — lambda_client.serp.measure_keywords."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import httpx
import pytest
from rank_bidder.lambda_client.serp import LambdaClientError, measure_keywords


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RANKBIDDER_LAMBDA_FUNCTION_URL", "https://fake.lambda-url/")
    monkeypatch.setenv("RANKBIDDER_LAMBDA_AUTH_TOKEN", "test-token")
    yield


def _mock_client(handler):  # type: ignore[no-untyped-def]
    """httpx.Client with MockTransport — test에서 직접 주입."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_happy_path_returns_results() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-Auth-Token"] == "test-token"
        return httpx.Response(
            200,
            json={"results": [{"id": "kw1", "samples": [1, 1], "chosen_rank": 1}]},
        )

    with _mock_client(handler) as c:
        results = measure_keywords([{"id": "kw1", "term": "수자인"}], samples_n=3, client=c)
    assert len(results) == 1
    assert results[0]["chosen_rank"] == 1


def test_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RANKBIDDER_LAMBDA_FUNCTION_URL", raising=False)
    with pytest.raises(LambdaClientError, match="env missing"):
        measure_keywords([{"id": "k", "term": "t"}])


def test_non_200_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _mock_client(handler) as c, pytest.raises(LambdaClientError, match="non-200"):
        measure_keywords([{"id": "k", "term": "t"}], client=c)


def test_missing_results_key_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": []})

    with _mock_client(handler) as c:
        with pytest.raises(LambdaClientError, match="missing 'results'"):
            measure_keywords([{"id": "k", "term": "t"}], client=c)


def test_http_error_raises() -> None:
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectError("DNS fail")
    with pytest.raises(LambdaClientError, match="http error"):
        measure_keywords([{"id": "k", "term": "t"}], client=mock_client)
