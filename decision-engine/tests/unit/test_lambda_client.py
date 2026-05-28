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

    with _mock_client(handler) as c, pytest.raises(LambdaClientError, match="missing 'results'"):
        measure_keywords([{"id": "k", "term": "t"}], client=c)


def test_http_error_raises() -> None:
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectError("DNS fail")
    with pytest.raises(LambdaClientError, match="http error"):
        measure_keywords([{"id": "k", "term": "t"}], client=mock_client)


# Story 2.1 — chunk loop 자동 분할 (bulk import 후 cycle_full 다수 KW)


def test_chunk_loop_splits_large_list_preserves_order() -> None:
    """KW 25개 + chunk_size=10 → 3 chunks 호출 + results 순서 보존."""
    chunk_count = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        chunk_count["calls"] += 1
        body = req.read()
        import json

        payload = json.loads(body)
        # Echo back chunk KW ids as results.
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": kw["id"], "samples": [1, 1], "chosen_rank": 1}
                    for kw in payload["keywords"]
                ]
            },
        )

    keywords = [{"id": f"kw-{i:03}", "term": f"term-{i}"} for i in range(25)]
    with _mock_client(handler) as c:
        results = measure_keywords(keywords, samples_n=3, chunk_size=10, client=c)

    assert chunk_count["calls"] == 3, "25 KW with chunk=10 should produce 3 chunks (10+10+5)"
    assert len(results) == 25
    # 순서 보존 — chunk 1: 0..9, chunk 2: 10..19, chunk 3: 20..24.
    assert [r["id"] for r in results] == [f"kw-{i:03}" for i in range(25)]


def test_chunk_size_invalid_raises() -> None:
    with pytest.raises(ValueError, match="chunk_size must be >= 1"):
        measure_keywords([{"id": "k", "term": "t"}], chunk_size=0)


def test_chunk_loop_single_chunk_fast_path() -> None:
    """KW ≤ chunk_size → 단일 chunk 호출 (1번)."""
    chunk_count = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        chunk_count["calls"] += 1
        return httpx.Response(
            200,
            json={"results": [{"id": "k", "samples": [1, 1], "chosen_rank": 1}]},
        )

    with _mock_client(handler) as c:
        results = measure_keywords([{"id": "k", "term": "t"}], chunk_size=10, client=c)
    assert chunk_count["calls"] == 1
    assert len(results) == 1


def test_chunk_loop_failure_propagates() -> None:
    """첫 chunk 성공 + 둘째 chunk 500 → 전체 LambdaClientError raise."""
    chunk_count = {"calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        chunk_count["calls"] += 1
        if chunk_count["calls"] == 1:
            return httpx.Response(
                200,
                json={"results": [{"id": "k", "samples": [1, 1], "chosen_rank": 1}]},
            )
        return httpx.Response(500, text="boom on second chunk")

    keywords = [{"id": f"kw-{i}", "term": f"t-{i}"} for i in range(15)]
    with _mock_client(handler) as c, pytest.raises(LambdaClientError, match="non-200"):
        measure_keywords(keywords, chunk_size=10, client=c)
    assert chunk_count["calls"] == 2
