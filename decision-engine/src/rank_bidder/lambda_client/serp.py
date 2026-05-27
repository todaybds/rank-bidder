"""SERP Lambda Function URL client (Story 1.9).

Story 1.4 Lambda(`rank-bidder-serp-measurer` on ap-northeast-2)에 단발 POST.
``X-Auth-Token`` 헤더 + 단발 httpx Client + 10초 timeout.

응답 contract (Story 1.4 D13):
    {"results":[{"id","samples","chosen_rank","latency_ms","mode_count","dispersion","unique_count","errors?"}]}
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


class LambdaClientError(Exception):
    """Lambda 호출 실패 — 상위에서 measurement_failure 처리."""


def measure_keywords(
    keywords: list[dict[str, str]],
    *,
    samples_n: int = 3,
    timeout_s: float = 15.0,
    function_url: str | None = None,
    auth_token: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Lambda Function URL 호출 → results 리스트 반환.

    Args:
        keywords: ``[{"id": "...", "term": "..."}, ...]`` (최대 50개, Story 1.4 D13).
        samples_n: 3-5.
        timeout_s: HTTP timeout.
        function_url: override (None이면 env ``RANKBIDDER_LAMBDA_FUNCTION_URL``).
        auth_token: override (None이면 env ``RANKBIDDER_LAMBDA_AUTH_TOKEN``).

    Returns:
        Story 1.4 응답 ``results`` 리스트.

    Raises:
        LambdaClientError: env 누락 / 비-200 / 응답 파싱 실패.
    """
    url = function_url or os.environ.get("RANKBIDDER_LAMBDA_FUNCTION_URL", "")
    token = auth_token or os.environ.get("RANKBIDDER_LAMBDA_AUTH_TOKEN", "")
    if not url or not token:
        raise LambdaClientError(
            "RANKBIDDER_LAMBDA_FUNCTION_URL / RANKBIDDER_LAMBDA_AUTH_TOKEN env missing"
        )

    payload = {"keywords": keywords, "samples_n": samples_n}
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    try:
        if client is not None:
            response = client.post(url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=timeout_s) as c:
                response = c.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("lambda.http_error", error=str(exc))
        raise LambdaClientError(f"http error: {exc}") from exc

    if response.status_code != 200:
        log.warning("lambda.non_200", status=response.status_code, body=response.text[:200])
        raise LambdaClientError(f"non-200: {response.status_code} {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise LambdaClientError(f"non-JSON response: {exc}") from exc

    results = body.get("results")
    if not isinstance(results, list):
        raise LambdaClientError(f"missing 'results' list in response: {body}")
    return results
