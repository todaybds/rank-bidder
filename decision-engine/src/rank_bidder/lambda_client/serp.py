"""SERP measurement — VM-local fetch+parse (Story 2.1 hot-fix 2026-05-28).

**아키텍처 전환 박제 (2026-05-28)**: 본 모듈은 원래 AWS Lambda(ap-northeast-2 Seoul)에
HTTP POST하던 클라이언트였으나, Naver가 Lambda Seoul IP에 대해 ``power_link_body`` 광고
영역을 비워서 SERP를 반환하는 것이 확정 (VM Oregon IP는 정상 광고 5개 노출, Lambda 응답
0개). cycle_full 측정 성공률 0/40 = 0% 누적.

**전환 결정**: SERP fetch를 VM(GCP us-west1 Oregon)에서 직접 수행. ``serp-measurer`` 패키지
``sampler.sample_keyword`` 재사용 (parser는 동일 코드, VM-fetch만 신규).

**시그니처 동일 유지** → cycle_full/cycle_hot/integration 테스트 변경 0. Lambda chunk_size,
function_url, auth_token 옵션은 호환 위해 받기만 하고 무시 (deprecated, 추후 cleanup epic).

**모듈명 'lambda_client'는 더 이상 Lambda를 호출하지 않음** — rename은 cleanup epic
(Phase B). LambdaClientError는 이번엔 거의 발생 안 함 (fetch 실패는 sample_keyword 안에서
None 처리, measurement_failure 응답으로 자연 흐름).
"""

from __future__ import annotations

from typing import Any

import structlog
from measurer.sampler import sample_keyword

log = structlog.get_logger(__name__)


class LambdaClientError(Exception):
    """SERP 측정 실패 — 상위에서 모든 KW SKIP_STALE 처리.

    VM-local 전환 후엔 거의 발생 안 함 (개별 KW fetch 실패는 sample_keyword가 None
    samples로 흡수, valid<2면 measurement_failure 응답). 본 예외는 호출 측 호환 위해
    유지 — 향후 cleanup epic에서 rename + 폐기.
    """


def measure_keywords(
    keywords: list[dict[str, Any]],
    *,
    samples_n: int = 3,
    timeout_s: float = 60.0,  # noqa: ARG001 — Lambda HTTP timeout이었음, 무시
    chunk_size: int = 5,  # noqa: ARG001 — Lambda chunk였음, 무시
    function_url: str | None = None,  # noqa: ARG001 — Lambda URL, 무시
    auth_token: str | None = None,  # noqa: ARG001 — Lambda 토큰, 무시
    client: object | None = None,  # noqa: ARG001 — httpx.Client, 무시
) -> list[dict[str, Any]]:
    """VM-local SERP fetch+parse — KW list 측정 후 results 리스트 반환.

    Args:
        keywords: ``[{"id": "...", "term": "...", "aliases": [...optional...]}, ...]``.
        samples_n: 3-5 (Story 1.4 D13).
        timeout_s/chunk_size/function_url/auth_token/client: Lambda 시절 옵션,
            backward-compat 위해 받기만 함. 무시.

    Returns:
        Lambda 응답 contract 동일 (Story 1.4 D13):
            ``[{"id", "samples", "chosen_rank", "latency_ms", "mode_count",
              "dispersion", "unique_count", "errors?"}, ...]``
        순서는 입력 keywords 순서 보존.

    Raises:
        LambdaClientError: 거의 발생 안 함. 시그니처 호환 위해 보존.
    """
    results: list[dict[str, Any]] = []
    for kw in keywords:
        kw_id = kw.get("id")
        term = kw.get("term", "")
        aliases = kw.get("aliases") or None
        if not kw_id or not term:
            log.warning("serp_local.invalid_kw", kw=kw)
            results.append(
                {
                    "id": kw_id or "",
                    "samples": [],
                    "chosen_rank": None,
                    "latency_ms": 0,
                    "errors": [{"code": "INVALID_KEYWORD", "message": "id/term missing"}],
                }
            )
            continue
        sample_result = sample_keyword(term, samples_n, aliases=aliases)
        sample_result["id"] = kw_id
        results.append(sample_result)
    return results
