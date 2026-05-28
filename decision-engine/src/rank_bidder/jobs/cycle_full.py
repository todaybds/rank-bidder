"""Full cycle — 5분 cron entrypoint (Story 1.9, SM-1~3).

흐름 (cycle_id correlation, structlog contextvars):
    1. cycle_id 생성 (monotonic UUID v7, Story 1.7)
    2. enabled KW snapshot → cycle_entries PLANNED (Story 1.6 + 1.7)
    3. Lambda 측정 (lambda_client.measure_keywords) → measurements insert + MEASURED 전이
       - chosen_rank None / Lambda 실패 → SKIP_STALE → FAILED 전이
    4. bid_decision.decide → decisions insert + DECIDED 전이
       - HOLD/CAP_REACHED/SKIP_STALE → COMMITTED 직행 (PUT 생략)
    5. naver_sa.put_bid → PUT_SENT 전이 (BID_UP/BID_DOWN만)
    6. PUT 200 즉시 → COMMITTED (Story 1.3 측정 반영)
    7. recovery.reconcile_put_sent 호출 (응답 누락 잔존 행 정리)

각 KW 실패는 다른 KW 진행 막지 않음 (D15 a 키워드 단위 commit).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import (
    CycleEntryCreate,
    DecisionCreate,
    KeywordUpdate,
    MeasurementCreate,
)
from rank_bidder.db.repositories import (
    cycle_entries,
    decisions,
    keywords,
    measurements,
    notifications,
    runtime_config,
)
from rank_bidder.engine import bid_decision, cap_race, new_cycle_id, recovery, state_machine
from rank_bidder.engine.bid_decision_estimate import decide_by_estimate
from rank_bidder.engine.exceptions import FinalGuardFailedError
from rank_bidder.engine.policy_eval import effective_settings
from rank_bidder.lambda_client.serp import LambdaClientError, measure_keywords
from rank_bidder.naver_sa.bid import put_bid as sa_put_bid
from rank_bidder.naver_sa.estimate import average_position_bid
from rank_bidder.naver_sa.exceptions import NaverKeywordDeleted, NaverSAError

log = structlog.get_logger(__name__)

#: 2026-05-28 — Naver IP "검색 endpoint sticky 차단" 대응. estimate mode가 새 디폴트.
#: SERP 차단 풀리면 RANKBIDDER_CYCLE_MODE=serp로 되돌릴 수 있음. test 환경에선 기본 serp
#: (integration test가 measure_keywords mock 기반이라 호환).
CYCLE_MODE = os.environ.get("RANKBIDDER_CYCLE_MODE", "serp").strip().lower()


def run_cycle(samples_n: int = 3) -> dict[str, int]:
    """5분 풀 사이클 1회 실행. CLI/systemd 진입점.

    2026-05-28 박제: ``RANKBIDDER_CYCLE_MODE=estimate`` (Naver IP 차단 대응) 시
    estimate API 기반 분기로 위임. ``serp`` (기본) 시 기존 Lambda/VM-local fetch 흐름.

    Returns:
        요약 dict {scanned, committed, failed, skipped}.
    """
    if CYCLE_MODE == "estimate":
        return run_cycle_estimate()
    cycle_id = new_cycle_id()
    bind_contextvars(cycle_id=cycle_id, job="cycle_full")
    summary = {"scanned": 0, "committed": 0, "failed": 0, "skipped": 0}
    try:
        log.info("cycle_full.started")
        # 1+2. enabled KW snapshot → PLANNED
        with write_transaction() as conn:
            enabled_kws = keywords.list_keywords(conn, enabled=True)
            for kw in enabled_kws:
                cycle_entries.upsert(
                    conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="PLANNED")
                )
        summary["scanned"] = len(enabled_kws)
        log.info("cycle_full.snapshot", kw_count=summary["scanned"])

        if not enabled_kws:
            log.info("cycle_full.no_keywords")
            return summary

        # 3. Lambda 측정 (단발 batch)
        try:
            results = measure_keywords(
                [{"id": kw.id, "term": kw.term, "aliases": kw.aliases} for kw in enabled_kws],
                samples_n=samples_n,
            )
        except LambdaClientError as exc:
            log.error("cycle_full.lambda_failed", error=str(exc))
            # 모든 KW를 SKIP_STALE → FAILED
            with write_transaction() as conn:
                for kw in enabled_kws:
                    try:
                        state_machine.transition(conn, cycle_id, kw.id, "FAILED")
                        summary["failed"] += 1
                    except Exception as e2:  # noqa: BLE001
                        log.warning("cycle_full.fail_transition", kw_id=kw.id, error=str(e2))
            return summary

        results_by_id = {r["id"]: r for r in results}

        # 4+5+6. per-KW: MEASURED → DECIDED → PUT_SENT → COMMITTED
        deleted_kw_ids: list[str] = []  # Story 2.4 묶음 알림용
        for kw in enabled_kws:
            try:
                _process_keyword(cycle_id, kw, results_by_id.get(kw.id), summary, deleted_kw_ids)
            except Exception as exc:  # noqa: BLE001 — KW 단위 격리 (D15 a)
                log.error("cycle_full.kw_error", keyword_id=kw.id, error=str(exc))
                summary["failed"] += 1

        # Story 2.4: 같은 사이클에 404 발생 KW 여러 개 → 1 알림 row 묶음.
        if deleted_kw_ids:
            with write_transaction() as conn:
                notifications.insert(
                    conn,
                    event_type="naver_keyword_deleted",
                    related_ids=deleted_kw_ids,
                    payload={"cycle_id": cycle_id, "count": len(deleted_kw_ids)},
                )
            log.info("cycle_full.naver_deleted_batch", count=len(deleted_kw_ids))

        # Story 3.2 — cap_race + cap_reached_sustained (24h suppression). Email은 Epic 6.
        with write_transaction() as conn:
            race_summary = cap_race.evaluate_all_for_cycle(conn, datetime.now(UTC))
        if race_summary["sustained_fired"] or race_summary["race_fired"]:
            log.info("cycle_full.cap_alerts", **race_summary)

        log.info("cycle_full.completed", **summary)
        return summary
    finally:
        clear_contextvars()


def _process_keyword(
    cycle_id: str,
    kw,
    result: dict | None,
    summary: dict[str, int],
    deleted_kw_ids: list[str] | None = None,
) -> None:
    """단일 KW 처리 — MEASURED → DECIDED → PUT_SENT → COMMITTED 흐름.

    Story 2.4: NaverKeywordDeleted(404) catch → keywords.enabled=False + deleted_kw_ids 추가.
    """
    if result is None:
        with write_transaction() as conn:
            state_machine.transition(conn, cycle_id, kw.id, "FAILED")
        summary["failed"] += 1
        return

    samples = result.get("samples") or []
    chosen_rank = result.get("chosen_rank")
    current_bid = 0  # 첫 사이클 — 실제 값은 Naver GET 또는 keywords.bid_cap 사용 (v1 단순)
    # v1: current_bid는 마지막 decision.new_bid 또는 bid_cap의 80%로 시작
    with get_connection() as conn:
        last_dec = decisions.list_for_keyword(conn, kw.id, limit=1)
    current_bid = last_dec[0].new_bid if last_dec else max(kw.bid_cap // 2, 100)

    # MEASURED 전이 + measurement row insert
    with write_transaction() as conn:
        state_machine.transition(conn, cycle_id, kw.id, "MEASURED")
        measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id=kw.id,
                rank_samples=list(samples),
                rank_final=chosen_rank if isinstance(chosen_rank, int) else None,
                current_bid=current_bid,
            ),
        )

    # Story 3.1 — multi-time policy: KW → site → keyword default fallback.
    # D17 transition: 정책 전환으로 bid_cap이 바뀌면 decisions.bid_cap이 바뀜 → 다음
    # 사이클부터 cap streak 자동 break = Cap 도달 타이머 reset.
    now = datetime.now(UTC)
    with get_connection() as conn:
        eff = effective_settings(conn, kw, now)

    # decide → DECIDED 전이 + decisions row insert
    outcome = bid_decision.decide(
        current_rank=chosen_rank if isinstance(chosen_rank, int) else None,
        target_rank=eff.target_rank,
        current_bid=current_bid,
        bid_cap=eff.bid_cap,
    )

    # Story 4.5 — general_bid_paused True 시 일반 KW PUT skip.
    # 측정/결정 row insert는 계속 (운영자가 "지금 paused 상태에서 무슨 결정이 났을 것인가" 추적 가능).
    # BID_UP/BID_DOWN을 HOLD로 rewrite → 같은 PUT skip 경로 재사용.
    if outcome.decision in ("BID_UP", "BID_DOWN"):
        with get_connection() as conn:
            paused = runtime_config.is_general_bid_paused(conn)
        if paused:
            outcome = bid_decision.DecisionOutcome(
                decision="HOLD",
                new_bid=outcome.old_bid,
                old_bid=outcome.old_bid,
                reason=f"SYSTEM_PAUSED — would have {outcome.decision} to {outcome.new_bid}",
            )

    with write_transaction() as conn:
        state_machine.transition(conn, cycle_id, kw.id, "DECIDED")
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=kw.id,
                cycle_id=cycle_id,
                decision=outcome.decision,
                old_bid=outcome.old_bid,
                new_bid=outcome.new_bid,
                rank_observed=chosen_rank if isinstance(chosen_rank, int) else None,
                reason=outcome.reason,
                bid_cap=eff.bid_cap,
            ),
        )

    # PUT 필요한 경우만 (BID_UP/BID_DOWN), 그 외엔 COMMITTED 직행
    if outcome.decision not in ("BID_UP", "BID_DOWN"):
        with write_transaction() as conn:
            state_machine.transition(conn, cycle_id, kw.id, "COMMITTED")
        summary["committed"] += 1
        return

    # I6 final guard 포함 PUT_SENT 전이.
    # 2026-05-27 code-review CRITICAL C1 fix: FinalGuardFailedError가 raise되면
    # write_transaction이 rollback → FAILED 박제가 휘발. 별도 새 transaction에서
    # FAILED upsert 발생해야 spec AC2 "state=FAILED 박제" 충족.
    try:
        with write_transaction() as conn:
            state_machine.transition(conn, cycle_id, kw.id, "PUT_SENT")
    except FinalGuardFailedError as exc:
        log.warning("cycle_full.final_guard", keyword_id=kw.id, reason=exc.reason)
        with write_transaction() as conn:
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="FAILED")
            )
        summary["skipped"] += 1
        return

    # Naver PUT — Story 2.3: keywords.adgroup_id 컬럼 사용 (env 우회 폐기).
    # Story 2.1 import 시점에 nccAdgroupId 같이 저장 → cycle_full 호출 시 그대로 사용.
    try:
        if not kw.adgroup_id:
            raise NaverSAError(f"adgroup_id not set for KW {kw.id} — re-import required")
        sa_put_bid(kw.id, outcome.new_bid, adgroup_id=kw.adgroup_id)
    except NaverKeywordDeleted:
        # Story 2.4 D15 (n): KW 자동 OFF + reason=NAVER_DELETED + 묶음 알림 후보 추가.
        log.warning("cycle_full.naver_deleted", keyword_id=kw.id)
        with write_transaction() as conn:
            try:
                keywords.update(
                    conn, kw.id, KeywordUpdate(enabled=False), expected_version=kw.version
                )
            except Exception as eUp:  # noqa: BLE001
                log.warning("cycle_full.disable_failed", keyword_id=kw.id, error=str(eUp))
            state_machine.transition(conn, cycle_id, kw.id, "FAILED")
        if deleted_kw_ids is not None:
            deleted_kw_ids.append(kw.id)
        summary["failed"] += 1
        return
    except (NaverSAError, RuntimeError) as exc:
        log.warning("cycle_full.put_failed", keyword_id=kw.id, error=str(exc))
        with write_transaction() as conn:
            state_machine.transition(conn, cycle_id, kw.id, "FAILED")
        summary["failed"] += 1
        return

    # PUT 200 → 즉시 COMMITTED (D15 (i) calibrated Story 1.3)
    with write_transaction() as conn:
        state_machine.transition(conn, cycle_id, kw.id, "COMMITTED")
    summary["committed"] += 1


def run_cycle_estimate() -> dict[str, int]:
    """Estimate API 기반 cycle (2026-05-28, Naver SERP 차단 대응).

    SERP fetch 대신 ``naver_sa.estimate.average_position_bid`` 호출. KW별로 target_rank
    도달 추정 bid를 받고, 현재 bid와 비교해서 BID_UP/DOWN/HOLD 결정.

    Returns:
        요약 dict {scanned, committed, failed, skipped}.
    """
    cycle_id = new_cycle_id()
    bind_contextvars(cycle_id=cycle_id, job="cycle_full_estimate")
    summary = {"scanned": 0, "committed": 0, "failed": 0, "skipped": 0}
    try:
        log.info("cycle_estimate.started")
        with write_transaction() as conn:
            enabled_kws = keywords.list_keywords(conn, enabled=True)
            for kw in enabled_kws:
                cycle_entries.upsert(
                    conn,
                    CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="PLANNED"),
                )
        summary["scanned"] = len(enabled_kws)
        log.info("cycle_estimate.snapshot", kw_count=summary["scanned"])

        if not enabled_kws:
            log.info("cycle_estimate.no_keywords")
            return summary

        deleted_kw_ids: list[str] = []
        for kw in enabled_kws:
            try:
                _process_keyword_estimate(cycle_id, kw, summary, deleted_kw_ids)
            except Exception as exc:  # noqa: BLE001 — KW 단위 격리 (D15 a)
                log.error("cycle_estimate.kw_error", keyword_id=kw.id, error=str(exc))
                summary["failed"] += 1

        # Story 2.4 묶음 알림
        if deleted_kw_ids:
            with write_transaction() as conn:
                notifications.insert(
                    conn,
                    event_type="naver_keyword_deleted",
                    related_ids=deleted_kw_ids,
                    payload={"cycle_id": cycle_id, "count": len(deleted_kw_ids)},
                )
            log.info("cycle_estimate.naver_deleted_batch", count=len(deleted_kw_ids))

        # Story 3.2 cap_race / cap_reached_sustained 그대로 적용 (decisions 기반).
        with write_transaction() as conn:
            race_summary = cap_race.evaluate_all_for_cycle(conn, datetime.now(UTC))
        if race_summary["sustained_fired"] or race_summary["race_fired"]:
            log.info("cycle_estimate.cap_alerts", **race_summary)

        log.info("cycle_estimate.completed", **summary)
        return summary
    finally:
        clear_contextvars()


def _process_keyword_estimate(
    cycle_id: str,
    kw,
    summary: dict[str, int],
    deleted_kw_ids: list[str] | None = None,
) -> None:
    """단일 KW estimate 기반 처리 — MEASURED 단계 생략(SERP 없음) → DECIDED → 선택적 PUT.

    measurement row는 insert 안 함 (rank 측정 없음). state는 PLANNED → DECIDED →
    (BID_UP/DOWN시) PUT_SENT → COMMITTED. state_machine은 MEASURED 건너뛰는 transition
    지원 — 기존 state_machine.transition이 PLANNED→DECIDED를 허용하는지 확인 필요.
    안전 가드: 허용 안 하면 MEASURED upsert 후 DECIDED.
    """
    # 현재 bid 추정 (마지막 decision 또는 bid_cap의 절반)
    with get_connection() as conn:
        last_dec = decisions.list_for_keyword(conn, kw.id, limit=1)
    current_bid = last_dec[0].new_bid if last_dec else max(kw.bid_cap // 2, 100)

    # estimate API 호출 (Naver Public API, 차단 무관, 광고비 0)
    # 2026-05-28 POST fix: term + target_rank 박제 (Naver는 keyword 텍스트 기반).
    try:
        estimate_bid = average_position_bid(kw.id, kw.term, kw.target_rank)
    except NaverKeywordDeleted:
        log.warning("cycle_estimate.naver_deleted_on_estimate", keyword_id=kw.id)
        with write_transaction() as conn:
            try:
                keywords.update(
                    conn, kw.id, KeywordUpdate(enabled=False), expected_version=kw.version
                )
            except Exception as eUp:  # noqa: BLE001
                log.warning("cycle_estimate.disable_failed", keyword_id=kw.id, error=str(eUp))
            # state_machine 안 거치고 직접 FAILED upsert (estimate 단계 실패).
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="FAILED")
            )
        if deleted_kw_ids is not None:
            deleted_kw_ids.append(kw.id)
        summary["failed"] += 1
        return
    except NaverSAError as exc:
        log.warning("cycle_estimate.estimate_failed", keyword_id=kw.id, error=str(exc))
        with write_transaction() as conn:
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="FAILED")
            )
        summary["failed"] += 1
        return

    # 정책 평가 + 결정
    now = datetime.now(UTC)
    with get_connection() as conn:
        eff = effective_settings(conn, kw, now)

    outcome = decide_by_estimate(
        estimate_bid=estimate_bid,
        target_rank=eff.target_rank,
        current_bid=current_bid,
        bid_cap=eff.bid_cap,
    )

    # Story 4.5 general_bid_paused 가드 (기존 정책 그대로)
    if outcome.decision in ("BID_UP", "BID_DOWN"):
        with get_connection() as conn:
            paused = runtime_config.is_general_bid_paused(conn)
        if paused:
            outcome = bid_decision.DecisionOutcome(
                decision="HOLD",
                new_bid=outcome.old_bid,
                old_bid=outcome.old_bid,
                reason=f"SYSTEM_PAUSED — would have {outcome.decision} to {outcome.new_bid}",
            )

    # estimate mode는 MEASURED 단계 생략 → cycle_entries 직접 DECIDED upsert.
    with write_transaction() as conn:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="DECIDED")
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=kw.id,
                cycle_id=cycle_id,
                decision=outcome.decision,
                old_bid=outcome.old_bid,
                new_bid=outcome.new_bid,
                rank_observed=None,  # estimate mode: SERP rank 없음
                reason=f"[estimate:{estimate_bid}] {outcome.reason}",
                bid_cap=eff.bid_cap,
            ),
        )

    if outcome.decision not in ("BID_UP", "BID_DOWN"):
        with write_transaction() as conn:
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="COMMITTED")
            )
        summary["committed"] += 1
        return

    # PUT 직전 PUT_SENT
    with write_transaction() as conn:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="PUT_SENT")
        )

    try:
        if not kw.adgroup_id:
            raise NaverSAError(f"adgroup_id not set for KW {kw.id} — re-import required")
        sa_put_bid(kw.id, outcome.new_bid, adgroup_id=kw.adgroup_id)
    except NaverKeywordDeleted:
        log.warning("cycle_estimate.naver_deleted_on_put", keyword_id=kw.id)
        with write_transaction() as conn:
            try:
                keywords.update(
                    conn, kw.id, KeywordUpdate(enabled=False), expected_version=kw.version
                )
            except Exception as eUp:  # noqa: BLE001
                log.warning("cycle_estimate.disable_failed", keyword_id=kw.id, error=str(eUp))
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="FAILED")
            )
        if deleted_kw_ids is not None:
            deleted_kw_ids.append(kw.id)
        summary["failed"] += 1
        return
    except (NaverSAError, RuntimeError) as exc:
        log.warning("cycle_estimate.put_failed", keyword_id=kw.id, error=str(exc))
        with write_transaction() as conn:
            cycle_entries.upsert(
                conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="FAILED")
            )
        summary["failed"] += 1
        return

    with write_transaction() as conn:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=kw.id, state="COMMITTED")
        )
    summary["committed"] += 1


def reconcile_orphans(cycle_id: str | None = None) -> dict[str, int]:
    """주기적으로 호출 — PUT_SENT 잔존 행 정리 (응답 누락 케이스).

    cycle_id 미지정 시 전체 PUT_SENT 행 — list_active 결과 사이클 묶음.
    """
    if cycle_id is None:
        with get_connection() as conn:
            actives = cycle_entries.list_active(conn)
        cycle_ids = list({e.cycle_id for e in actives if e.state == "PUT_SENT"})
    else:
        cycle_ids = [cycle_id]

    total = {"scanned": 0, "committed": 0, "failed": 0}
    for cid in cycle_ids:
        from rank_bidder.naver_sa.client import call_with_retry

        def _get(kw_id: str) -> dict:
            _, body = call_with_retry("GET", f"/ncc/keywords/{kw_id}")
            return body

        with write_transaction() as conn:
            partial = recovery.reconcile_put_sent(conn, cid, _get)
        for k in ("scanned", "committed", "failed"):
            total[k] += partial.get(k, 0)
    return total


if __name__ == "__main__":
    import sys

    summary = run_cycle()
    print(f"cycle_full summary: {summary}")
    sys.exit(0 if summary["failed"] == 0 else 1)
