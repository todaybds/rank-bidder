"""다회 샘플링 + mode/median_low chosen_rank 결정 (FR-10).

전략:
- ``samples_n`` 회 ``fetch_serp_html`` + ``extract_rank`` 반복.
- 각 호출 결과는 rank 정수 또는 None(파싱 실패/빈결과/HTTP fail).
- ``samples`` 배열에 raw 시퀀스(None 포함) 그대로 노출.
- 유효 샘플(non-null) ≥ 2 → ``chosen_rank`` = ``statistics.multimode()``.
  단일 mode → 그 값. 동점 → ``statistics.median_low()`` (결정적 정수 보장).
- 유효 샘플 < 2 → ``chosen_rank: None`` + ``errors=[MEASUREMENT_FAILURE]``.

재시도 없음 — 단일 sample fetch 실패는 다음 sample이 자연 재시도 (FR-10 §빈결과 흡수).

Story 2.1 patch (2026-05-28): inter-sample sleep 도입. Naver가 Lambda IP에 대해
짧은 시간 내 다수 fetch를 rate-limit한다 (검증: VM IP는 200 OK, Lambda IP는 즉시
fail 0.157s). sample 사이 ``SAMPLE_DELAY_S`` 휴식으로 fetch 부담 분산. 환경변수
``RANKBIDDER_SAMPLE_DELAY_S``로 override 가능 (운영 측정 기반 조정).
"""

from __future__ import annotations

import os
import random
import statistics
import time
from typing import Any

import structlog

from measurer.http_client import fetch_serp_html
from measurer.parser import extract_rank

log = structlog.get_logger(__name__)

#: Story 2.1 (2026-05-28) — Naver IP rate-limit 회피용 sample 간 휴식 (median).
#: 1.5s 보수적 채택. 운영 후 측정 기반 조정 위해 env override 허용.
SAMPLE_DELAY_S = float(os.environ.get("RANKBIDDER_SAMPLE_DELAY_S", "1.5"))

#: 봇 회피 강화 (2026-05-28 후속): 고정 delay 대신 ±range 랜덤. 동일 cadence가
#: 봇 시그너처가 되는 거 회피. 0이면 비활성 (legacy 동작).
SAMPLE_DELAY_JITTER_S = float(os.environ.get("RANKBIDDER_SAMPLE_DELAY_JITTER_S", "0.8"))


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
        # Story 2.1 + 2026-05-28 hot-fix: 첫 sample 후부터 inter-sample delay.
        # 봇 회피 강화 — 고정 delay 대신 SAMPLE_DELAY_S ± JITTER 랜덤. 일정한 cadence
        # 가 봇 시그너처가 되는 패턴 회피.
        if sample_idx > 0 and SAMPLE_DELAY_S > 0:
            jitter = random.uniform(-SAMPLE_DELAY_JITTER_S, SAMPLE_DELAY_JITTER_S)
            sleep_s = max(0.1, SAMPLE_DELAY_S + jitter)
            time.sleep(sleep_s)
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
