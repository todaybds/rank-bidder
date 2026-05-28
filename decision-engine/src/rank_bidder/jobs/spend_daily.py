"""Story 4.4 — 매일 00:30 KST에 어제 spend 수집.

흐름:
1. enabled keywords에서 distinct (site_id, adgroup_id) 수집.
2. 각 adgroup_id로 Naver /stats 호출 (어제 summary).
3. site+adgroup 단위로 spend_daily UPSERT.
4. 3일 연속 모두 실패 시 'spend_collection_failed' 알림.

수동 실행: ``python -m rank_bidder.jobs.spend_daily``.
systemd timer: 매일 00:30 KST (UTC 15:30).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import structlog

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import notifications, spend_daily
from rank_bidder.naver_sa.exceptions import NaverSAError
from rank_bidder.naver_sa.stats import fetch_yesterday_summary

log = structlog.get_logger(__name__)

KST = timezone(timedelta(hours=9))


def _yesterday_kst_date() -> str:
    """어제 날짜 (KST, YYYY-MM-DD)."""
    return (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")


def collect_yesterday() -> dict[str, int]:
    """진입점. 어제 spend 수집 + upsert.

    Returns:
        ``{"collected": int, "failed": int, "scanned_adgroups": int}``
    """
    summary = {"collected": 0, "failed": 0, "scanned_adgroups": 0}
    date_kst = _yesterday_kst_date()

    # 1. distinct (site, adgroup) — enabled KW에서.
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT site_id, adgroup_id FROM keywords
            WHERE enabled = 1 AND adgroup_id IS NOT NULL AND adgroup_id != ''
            """
        ).fetchall()
    pairs = [(r["site_id"], r["adgroup_id"]) for r in rows]
    summary["scanned_adgroups"] = len(pairs)
    log.info("spend.scan_started", date=date_kst, adgroup_count=len(pairs))

    if not pairs:
        log.info("spend.no_adgroups")
        return summary

    # 2. 각 adgroup마다 stats 호출 + upsert
    failed_ids: list[str] = []
    for site_id, adgroup_id in pairs:
        try:
            stat = fetch_yesterday_summary(adgroup_id)
        except NaverSAError as exc:
            log.warning("spend.fetch_failed", adgroup_id=adgroup_id, error=str(exc))
            failed_ids.append(adgroup_id)
            summary["failed"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 — KW 단위 격리
            log.warning("spend.fetch_error", adgroup_id=adgroup_id, error=str(exc))
            failed_ids.append(adgroup_id)
            summary["failed"] += 1
            continue

        if stat is None:
            log.info("spend.no_data", adgroup_id=adgroup_id, date=date_kst)
            # 데이터 없음 = 광고비 0으로 박제 (당일 광고 미운영 가능성)
            stat = {}

        spend = int(stat.get("salesAmt", 0))
        clicks = int(stat.get("clkCnt", 0))
        imps = int(stat.get("impCnt", 0))

        try:
            with write_transaction() as conn:
                spend_daily.upsert(
                    conn,
                    date=date_kst,
                    site_id=site_id,
                    campaign_id=adgroup_id,
                    spend_amount=spend,
                    click_count=clicks,
                    impression_count=imps,
                )
            summary["collected"] += 1
            log.info(
                "spend.upserted",
                date=date_kst,
                site=site_id,
                adgroup=adgroup_id,
                spend=spend,
                clicks=clicks,
                imps=imps,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("spend.upsert_failed", adgroup_id=adgroup_id, error=str(exc))
            summary["failed"] += 1

    # 3. 모든 fetch 실패 → 즉시 알림 (3일 연속 검사는 다음 호출에서)
    if summary["scanned_adgroups"] > 0 and summary["collected"] == 0:
        try:
            with write_transaction() as conn:
                notifications.insert(
                    conn,
                    event_type="spend_collection_failed",
                    related_ids=failed_ids,
                    payload={
                        "summary": f"광고비 수집 실패 ({summary['failed']}/{summary['scanned_adgroups']})",
                        "date": date_kst,
                        "failed": summary["failed"],
                        "scanned": summary["scanned_adgroups"],
                    },
                    suppressed_until=(datetime.now(UTC) + timedelta(hours=24)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("spend.notify_failed", error=str(exc))

    log.info("spend.completed", **summary)
    return summary


if __name__ == "__main__":
    s = collect_yesterday()
    print(f"spend_daily summary: {s}")
