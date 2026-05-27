"""Hot cycle — 1분 cron entrypoint (Story 1.9).

측정만 — 입찰 변경 없음. measurements row insert만, cycle_entries 미생성.
용도: 5분 풀 사이클 사이의 SERP 변동 모니터링 (D26 metric MAD/dispersion 추세).
"""

from __future__ import annotations

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from rank_bidder.db.connection import write_transaction
from rank_bidder.db.models import MeasurementCreate
from rank_bidder.db.repositories import decisions, keywords, measurements
from rank_bidder.lambda_client.serp import LambdaClientError, measure_keywords

log = structlog.get_logger(__name__)


def run_hot_cycle(samples_n: int = 3) -> dict[str, int]:
    """1분 hot 사이클 — measurement only."""
    bind_contextvars(job="cycle_hot")
    summary = {"scanned": 0, "measured": 0, "failed": 0}
    try:
        log.info("cycle_hot.started")
        with write_transaction() as conn:
            enabled_kws = keywords.list_keywords(conn, enabled=True)
        summary["scanned"] = len(enabled_kws)
        if not enabled_kws:
            return summary

        try:
            results = measure_keywords(
                [{"id": kw.id, "term": kw.term} for kw in enabled_kws],
                samples_n=samples_n,
            )
        except LambdaClientError as exc:
            log.error("cycle_hot.lambda_failed", error=str(exc))
            summary["failed"] = summary["scanned"]
            return summary

        results_by_id = {r["id"]: r for r in results}
        for kw in enabled_kws:
            result = results_by_id.get(kw.id)
            if result is None:
                summary["failed"] += 1
                continue
            with write_transaction() as conn:
                last_dec = decisions.list_for_keyword(conn, kw.id, limit=1)
                current_bid = last_dec[0].new_bid if last_dec else max(kw.bid_cap // 2, 100)
                chosen = result.get("chosen_rank")
                measurements.insert(
                    conn,
                    MeasurementCreate(
                        keyword_id=kw.id,
                        rank_samples=list(result.get("samples") or []),
                        rank_final=chosen if isinstance(chosen, int) else None,
                        current_bid=current_bid,
                    ),
                )
                summary["measured"] += 1
        log.info("cycle_hot.completed", **summary)
        return summary
    finally:
        clear_contextvars()


if __name__ == "__main__":
    import sys

    summary = run_hot_cycle()
    print(f"cycle_hot summary: {summary}")
    # Exit 1 only when there was work AND all of it failed. scanned==0 (KW seed 전
    # 또는 모두 disabled) 은 "할 일 없음" 이지 failure 아님 — exit 0. 기존 식
    # `failed < scanned` 는 scanned=0 일 때 `0 < 0 = False` 로 잘못 exit 1 됨
    # (2026-05-28 GCP deploy 실측에서 매분 FAILURE 로그 박힘 확인).
    sys.exit(1 if summary["scanned"] > 0 and summary["failed"] >= summary["scanned"] else 0)
