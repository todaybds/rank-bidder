"""Event-type별 이메일 본문 — Story 6.1.

각 함수는 (subject, body_text) tuple 반환. plain text (ASCII + 한글) — HTML 미사용 (NFR-8).
"""

from __future__ import annotations

from collections.abc import Callable

from rank_bidder.db.repositories.notifications import Notification


def _fmt_naver_keyword_deleted(n: Notification) -> tuple[str, str]:
    p = n.payload
    count = p.get("count", len(n.related_ids))
    cycle_id = p.get("cycle_id", "?")
    body = (
        f"[Rank Bidder] Naver 키워드 자동 OFF — {count}건\n"
        f"\n"
        f"cycle_id : {cycle_id}\n"
        f"발생 시각 : {n.created_at} (UTC)\n"
        f"영향 KW  : {', '.join(n.related_ids)}\n"
        f"\n"
        f"권장 액션 — Naver SA 콘솔에서 KW 상태 확인 + 필요 시 재등록.\n"
    )
    return f"[Rank Bidder] Naver KW 삭제 {count}건", body


def _fmt_cap_race(n: Notification) -> tuple[str, str]:
    p = n.payload
    body = (
        f"[Rank Bidder] 옥션 과열 가능성 — site={p.get('site_id')}\n"
        f"\n"
        f"1h 윈도우 내 Cap 도달 KW : {p.get('count')}개\n"
        f"keyword_ids             : {', '.join(p.get('keyword_ids', []))}\n"
        f"발생 시각               : {n.created_at} (UTC)\n"
        f"\n"
        f"권장 액션 — 정책의 bid_cap 또는 target_rank 검토. 동일 site에서 24h 내 재발화 차단.\n"
    )
    return f"[Rank Bidder] 옥션 과열 — {p.get('site_id')}", body


def _fmt_cap_reached_sustained(n: Notification) -> tuple[str, str]:
    p = n.payload
    duration_h = round((p.get("duration_seconds", 0)) / 3600, 1)
    body = (
        f"[Rank Bidder] Cap 도달 {duration_h}h 지속 — {p.get('keyword_id')}\n"
        f"\n"
        f"site_id    : {p.get('site_id')}\n"
        f"bid_cap    : ₩{p.get('bid_cap', 0):,}\n"
        f"streak start : {p.get('started_at')}\n"
        f"\n"
        f"권장 액션 — 목표 순위 미달이 1h 이상 지속. 정책 bid_cap 상향 또는 target_rank 완화 검토.\n"
    )
    return f"[Rank Bidder] Cap 지속 — {p.get('keyword_id')}", body


def _fmt_generic(n: Notification) -> tuple[str, str]:
    body = (
        f"[Rank Bidder] {n.event_type}\n"
        f"\n"
        f"발생 시각  : {n.created_at} (UTC)\n"
        f"related_ids: {', '.join(n.related_ids)}\n"
        f"payload    : {n.payload}\n"
    )
    return f"[Rank Bidder] {n.event_type}", body


_RENDERERS: dict[str, Callable[[Notification], tuple[str, str]]] = {
    "naver_keyword_deleted": _fmt_naver_keyword_deleted,
    "cap_race": _fmt_cap_race,
    "cap_reached_sustained": _fmt_cap_reached_sustained,
}


def render(n: Notification) -> tuple[str, str]:
    """Event-type 매핑 → subject + body. 미등록 event_type 은 generic fallback."""
    return _RENDERERS.get(n.event_type, _fmt_generic)(n)
