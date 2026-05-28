"""다회 샘플링 + mode/median_low chosen_rank 결정 (FR-10).

전략:
- ``samples_n`` 회 ``fetch_serp_html`` + ``extract_rank`` 반복.
- 각 호출 결과는 rank 정수 또는 None(파싱 실패/빈결과/HTTP fail).
- ``samples`` 배열에 raw 시퀀스(None 포함) 그대로 노출.
- 유효 샘플(non-null) ≥ 2 → ``chosen_rank`` = ``statistics.multimode()``.
  단일 mode → 그 값. 동점 → ``statistics.median_low()`` (결정적 정수 보장).
- 유효 샘플 < 2 → ``chosen_rank: None`` + ``errors=[MEASUREMENT_FAILURE]``.

재시도 없음 — 단일 sample fetch 실패는 다음 sample이 자연 재시도 (FR-10 §빈결과 흡수).
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import structlog

from measurer.http_client import fetch_serp_html
from measurer.parser import extract_rank

log = structlog.get_logger(__name__)


def sample_keyword(
    term: str,
    samples_n: int,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    """키워드 1개를 ``samples_n`` 회 fetch + 다회 샘플링 채택.

    Args:
        term: 검색 키워드.
        samples_n: 샘플 횟수. AC1 검증된 범위 3-5.
        aliases: Story 1.10 KW alias 후보 (광고 텍스트 변형 표현). None → term-only.

    Returns:
        dict 구조:
          - ``samples`` (list[int | None]): raw 시퀀스
          - ``chosen_rank`` (int | None): 최빈값 / 동점 시 median_low / 유효<2면 None
          - ``latency_ms`` (int): wall-clock total
          - ``errors`` (list[dict] | None): MEASUREMENT_FAILURE 박스 (성공 시 키 없음)
    """
    start = time.perf_counter()
    samples: list[int | None] = []

    for sample_idx in range(samples_n):
        html, status = fetch_serp_html(term)
        rank = extract_rank(html, term, aliases=aliases) if html else None
        samples.append(rank)
        log.info(
            "serp.fetched",
            term=term,
            sample_idx=sample_idx,
            rank=rank,
            status=status,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)
    valid = [r for r in samples if r is not None]

    result: dict[str, Any] = {
        "samples": samples,
        "latency_ms": latency_ms,
    }

    if len(valid) < 2:
        result["chosen_rank"] = None
        result["errors"] = [
            {
                "code": "MEASUREMENT_FAILURE",
                "message": "valid samples < 2",
                "valid_count": len(valid),
            }
        ]
        log.warning(
            "sampler.measurement_failure",
            term=term,
            valid_count=len(valid),
            samples_n=samples_n,
        )
        return result

    # 단일 mode → 그 값. 동점 → median_low로 결정적 정수 보장 (median은 .5 반환 가능).
    modes = statistics.multimode(valid)
    chosen = modes[0] if len(modes) == 1 else statistics.median_low(valid)

    # P2 (review 2026-05-27): chosen_rank 신뢰도 정보 동봉.
    #   mode_count=1 → 명확한 최빈값 (높은 신뢰), >1 → 동점 / 분산
    #   dispersion = max-min → 0이면 모든 샘플 일치, 큰 값이면 SERP 변동 큼
    #   Story 1.8 입찰 결정에서 dispersion 큰 케이스는 HOLD 고려 가능.
    unique_ranks = sorted(set(valid))
    dispersion = max(valid) - min(valid)
    result["chosen_rank"] = chosen
    result["mode_count"] = len(modes)
    result["dispersion"] = dispersion
    result["unique_count"] = len(unique_ranks)
    log.info(
        "sampler.chosen_rank",
        term=term,
        chosen_rank=chosen,
        valid_count=len(valid),
        modes=modes,
        dispersion=dispersion,
    )
    return result
