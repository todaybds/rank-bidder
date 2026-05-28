"""SERP Lambda Function URL client (Story 1.9).

Story 1.4 Lambda(`rank-bidder-serp-measurer` on ap-northeast-2)에 단발 POST.
``X-Auth-Token`` 헤더 + 단발 httpx Client + 60초 timeout.

응답 contract (Story 1.4 D13):
    {"results":[{"id","samples","chosen_rank","latency_ms","mode_count","dispersion","unique_count","errors?"}]}

Story 2.1 bulk import patch (2026-05-28): KW 다수(>chunk_size) 호출 시 자동 chunk +
sequential 호출. Lambda Timeout(30s)을 KW × samples_n × ~2s SERP latency가 초과하지
않도록 chunk_size=10 보수적 채택. 단일 chunk 내 1 KW fail → 그 KW만 measurement_failure
응답(handler isolation), chunk 전체 fail → all-chunk fallback.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

#: Story 2.1 — chunk size cap. Lambda Timeout 30s + KW당 ~6s 처리(3 sample × 2s).
#: 10 KW × 6s = 60s — Lambda timeout 30s 초과하나, sampler 측 KW 단위 isolation으로
#: 부분 응답 가능. 보수적 안전선: 10 KW면 1-2 KW만 timeout cut + 나머지 정상 측정.
DEFAULT_CHUNK_SIZE = 10


class LambdaClientError(Exception):
    """Lambda 호출 실패 — 상위에서 measurement_failure 처리."""


def _post_single_chunk(
    keywords: list[dict[str, Any]],
    *,
    samples_n: int,
    timeout_s: float,
    url: str,
    token: str,
    client: httpx.Client | None,
) -> list[dict[str, Any]]:
    """단일 Lambda 호출. results list 반환. 호출 측 keyword payload는 그대로 통과."""
    payload = {"keywords": keywords, "samples_n": samples_n}
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    try:
        if client is not None:
            response = client.post(url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=timeout_s) as c:
                response = c.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("lambda.http_error", error=str(exc), chunk_size=len(keywords))
        raise LambdaClientError(f"http error: {exc}") from exc

    if response.status_code != 200:
        log.warning(
            "lambda.non_200",
            status=response.status_code,
            body=response.text[:200],
            chunk_size=len(keywords),
        )
        raise LambdaClientError(f"non-200: {response.status_code} {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise LambdaClientError(f"non-JSON response: {exc}") from exc

    results = body.get("results")
    if not isinstance(results, list):
        raise LambdaClientError(f"missing 'results' list in response: {body}")
    return results


def measure_keywords(
    keywords: list[dict[str, Any]],
    *,
    samples_n: int = 3,
    timeout_s: float = 60.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    function_url: str | None = None,
    auth_token: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Lambda Function URL 호출 → results 리스트 반환. KW가 ``chunk_size`` 초과 시 자동 분할.

    Args:
        keywords: ``[{"id": "...", "term": "...", "aliases": [...optional...]}, ...]``
            (최대 50개/chunk — Story 1.4 D13 Lambda max). chunk loop으로 큰 list도 처리.
        samples_n: 3-5.
        timeout_s: HTTP timeout per chunk (default 60s — Lambda 30s 처리 + 클라이언트
            버퍼 30s).
        chunk_size: Lambda 호출 1회 당 KW 개수 cap (default 10).
        function_url: override (None이면 env ``RANKBIDDER_LAMBDA_FUNCTION_URL``).
        auth_token: override (None이면 env ``RANKBIDDER_LAMBDA_AUTH_TOKEN``).

    Returns:
        Story 1.4 응답 ``results`` 리스트 — 모든 chunk results 순서 보존하여 concat.

    Raises:
        LambdaClientError: env 누락 / 어떤 chunk라도 비-200 / 응답 파싱 실패.
            단일 chunk 실패는 전체 raise (상위 cycle_full이 모든 KW를 SKIP_STALE 처리).
    """
    url = function_url or os.environ.get("RANKBIDDER_LAMBDA_FUNCTION_URL", "")
    token = auth_token or os.environ.get("RANKBIDDER_LAMBDA_AUTH_TOKEN", "")
    if not url or not token:
        raise LambdaClientError(
            "RANKBIDDER_LAMBDA_FUNCTION_URL / RANKBIDDER_LAMBDA_AUTH_TOKEN env missing"
        )
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")

    # Single-chunk fast path
    if len(keywords) <= chunk_size:
        return _post_single_chunk(
            keywords,
            samples_n=samples_n,
            timeout_s=timeout_s,
            url=url,
            token=token,
            client=client,
        )

    # Multi-chunk loop. 순서 보존.
    all_results: list[dict[str, Any]] = []
    total_chunks = (len(keywords) + chunk_size - 1) // chunk_size
    for idx in range(0, len(keywords), chunk_size):
        chunk = keywords[idx : idx + chunk_size]
        chunk_idx = idx // chunk_size + 1
        log.info(
            "lambda.chunk_start",
            chunk_idx=chunk_idx,
            total_chunks=total_chunks,
            chunk_size=len(chunk),
        )
        chunk_results = _post_single_chunk(
            chunk,
            samples_n=samples_n,
            timeout_s=timeout_s,
            url=url,
            token=token,
            client=client,
        )
        all_results.extend(chunk_results)
    return all_results
