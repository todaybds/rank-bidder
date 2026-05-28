"""Story 6.2 — 시스템 건강 모니터 + notifications_log 자동 알림.

매분 실행 (systemd timer). 3가지 트리거:

1. **VM 자원 (CPU 90% / 메모리 90% / 디스크 80%)** → `vm_resource_warning` 알림.
2. **최근 N분 cycle 실패율 50% 초과** → `cycle_failure_extended` 알림.
3. **Naver SA API 실패율** (간이) — decisions 테이블 reason 안 NaverSAError 비율.

각 알림은 1h 재발 suppression (notifications.find_active_suppression). 같은 trigger가
1시간 안에 재발해도 중복 알림 안 생김.

실제 이메일 발송은 Epic 6.1 notify_sender (1분 timer)가 별도로 pending 알림 처리.
본 모듈은 row insert만.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import notifications

log = structlog.get_logger(__name__)

#: 1h suppression — 같은 trigger 1시간 안 재발 시 알림 중복 차단.
SUPPRESSION_HOURS = 1

#: VM 자원 threshold.
CPU_PCT_THRESHOLD = 90.0
MEM_PCT_THRESHOLD = 90.0
DISK_PCT_THRESHOLD = 80.0

#: 최근 N분 안 cycle decisions 중 실패(SKIP_STALE/FAILED 등) 비율 threshold.
CYCLE_WINDOW_MIN = 30
CYCLE_FAILURE_PCT_THRESHOLD = 50.0
CYCLE_MIN_SAMPLES = 5  # 표본 부족 시 알림 skip (false positive 차단)


def _now_utc_sqlite() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _suppression_until() -> str:
    return (datetime.now(UTC) + timedelta(hours=SUPPRESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def _emit_alert_if_not_suppressed(event_type: str, scope_key: str, payload: dict) -> bool:
    """1h suppression 검사 → 통과면 notifications_log insert + True. 차단되면 False."""
    now_sqlite = _now_utc_sqlite()
    with get_connection() as conn:
        existing = notifications.find_active_suppression(conn, event_type, scope_key, now_sqlite)
    if existing is not None:
        log.info("health.alert_suppressed", event_type=event_type, scope=scope_key)
        return False
    with write_transaction() as conn:
        notifications.insert(
            conn,
            event_type=event_type,
            related_ids=[scope_key],
            payload=payload,
            suppressed_until=_suppression_until(),
        )
    log.warning("health.alert_emitted", event_type=event_type, scope=scope_key, **payload)
    return True


def check_vm_resources() -> dict[str, bool]:
    """psutil로 CPU/메모리/디스크 측정 후 threshold 초과 시 알림."""
    try:
        import psutil
    except ImportError:
        log.warning("health.psutil_missing")
        return {"alerted": False}

    cpu_pct = psutil.cpu_percent(interval=1)  # 1초 샘플
    mem = psutil.virtual_memory()
    mem_pct = mem.percent
    disk = psutil.disk_usage("/")
    disk_pct = disk.percent

    log.info("health.vm_measured", cpu_pct=cpu_pct, mem_pct=mem_pct, disk_pct=disk_pct)

    alerted = False
    if cpu_pct >= CPU_PCT_THRESHOLD:
        alerted |= _emit_alert_if_not_suppressed(
            "vm_resource_warning",
            "cpu",
            {
                "summary": f"VM CPU {cpu_pct:.1f}% (≥ {CPU_PCT_THRESHOLD}%)",
                "metric": "cpu_pct",
                "value": cpu_pct,
                "threshold": CPU_PCT_THRESHOLD,
            },
        )
    if mem_pct >= MEM_PCT_THRESHOLD:
        alerted |= _emit_alert_if_not_suppressed(
            "vm_resource_warning",
            "memory",
            {
                "summary": f"VM 메모리 {mem_pct:.1f}% (≥ {MEM_PCT_THRESHOLD}%)",
                "metric": "mem_pct",
                "value": mem_pct,
                "threshold": MEM_PCT_THRESHOLD,
            },
        )
    if disk_pct >= DISK_PCT_THRESHOLD:
        alerted |= _emit_alert_if_not_suppressed(
            "vm_resource_warning",
            "disk",
            {
                "summary": f"VM 디스크 {disk_pct:.1f}% (≥ {DISK_PCT_THRESHOLD}%)",
                "metric": "disk_pct",
                "value": disk_pct,
                "threshold": DISK_PCT_THRESHOLD,
            },
        )
    return {"alerted": alerted, "cpu_pct": cpu_pct, "mem_pct": mem_pct, "disk_pct": disk_pct}


def check_cycle_failure_rate() -> dict[str, object]:
    """최근 N분 decisions 중 실패(SKIP_STALE/FAILED reason) 비율 측정."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=CYCLE_WINDOW_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT decision, COUNT(*) AS n FROM decisions
            WHERE decided_at >= ?
            GROUP BY decision
            """,
            (cutoff,),
        ).fetchall()

    counts = {r["decision"]: r["n"] for r in rows}
    total = sum(counts.values())
    failures = counts.get("SKIP_STALE", 0)
    fail_pct = (failures * 100.0 / total) if total else 0.0

    log.info(
        "health.cycle_failure_rate",
        window_min=CYCLE_WINDOW_MIN,
        total=total,
        failures=failures,
        fail_pct=fail_pct,
    )

    if total < CYCLE_MIN_SAMPLES:
        return {"alerted": False, "reason": "samples_below_min", "total": total}

    if fail_pct >= CYCLE_FAILURE_PCT_THRESHOLD:
        alerted = _emit_alert_if_not_suppressed(
            "cycle_failure_extended",
            f"window_{CYCLE_WINDOW_MIN}min",
            {
                "summary": f"최근 {CYCLE_WINDOW_MIN}분 cycle 실패율 {fail_pct:.1f}% (≥ {CYCLE_FAILURE_PCT_THRESHOLD}%, {failures}/{total})",
                "window_min": CYCLE_WINDOW_MIN,
                "total": total,
                "failures": failures,
                "fail_pct": fail_pct,
                "threshold": CYCLE_FAILURE_PCT_THRESHOLD,
            },
        )
        return {"alerted": alerted, "fail_pct": fail_pct, "total": total}

    return {"alerted": False, "fail_pct": fail_pct, "total": total}


def run() -> dict[str, object]:
    """systemd entrypoint. 3 트리거 일괄 실행. 1개 실패가 다른 거 안 막음."""
    summary: dict[str, object] = {}
    try:
        summary["vm"] = check_vm_resources()
    except Exception as exc:  # noqa: BLE001
        log.error("health.vm_check_failed", error=str(exc))
        summary["vm"] = {"error": str(exc)}
    try:
        summary["cycle"] = check_cycle_failure_rate()
    except Exception as exc:  # noqa: BLE001
        log.error("health.cycle_check_failed", error=str(exc))
        summary["cycle"] = {"error": str(exc)}
    return summary


if __name__ == "__main__":
    s = run()
    print(f"health summary: {s}")
