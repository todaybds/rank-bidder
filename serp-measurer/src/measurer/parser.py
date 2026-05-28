"""SERP HTML parser v2 — ``<ul id="power_link_body">`` + onclick ``r=N`` 기반 rank 추출.

**v1 폐기 (2026-05-28)**: v1은 "파워링크" 텍스트 앵커 + ``<li data-index>`` 두 신호에
의존했으나, 2026-05-28 production 검증 시 m.search.naver.com SERP 응답에 두 신호
모두 부재 (광고 5개 노출 상태에서 "파워링크" 0회 / ``data-index`` 0회). cycle_full
3회 연속 measurement 100% null. 즉 Naver가 광고 영역 마크업을 교체.

**v2 신호 (2026-05-28 production 검증)**:

1. **광고 컨테이너 ID** — ``<ul id="power_link_body" class="lst_total">`` (전체 페이지에
   정확히 1회 등장). 이 element가 파워링크 광고 list의 root.
2. **광고 단위** — 위 ``ul`` 의 direct ``<li>`` children. li class 는
   ``["bx", ...]`` 패턴 (``bx`` 가 공통 접두 class, 나머지는 광고 layout variant).
3. **순위 cross-check** — 각 li 안의 ``<a onclick="...">`` 에 다음 패턴 박힘:
   ``a=pwl.tit&r=<RANK>&i=nad-<ad_id>``. DOM-order 순서(1-based)와 onclick ``r=`` 값이
   일치해야 신뢰. 불일치 시 onclick ``r=`` 값을 채택하고 warn (Naver 영역 마크업이
   re-ordering 됐을 가능성).

**term 매칭**: v1과 동일하게 단어경계(``re`` lookahead/lookbehind) 안에서만. 한글
글자 사이 끼인 substring 매치 거부 (P0 review 2026-05-27 패턴 유지).

**v3 (future) — multi-strategy fallback**: ``power_link_body`` 부재 시 ``a=pwl.tit&r=``
onclick 전수 스캔 후 ancestor ``<li>`` reverse-lookup 등의 보조 전략. 현재 v2는
단일 전략 + 빈결과율 알림(Epic 6 별도 story).
"""

from __future__ import annotations

import re
import unicodedata

import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger(__name__)

#: 광고 list root element ID — production 안정 anchor (2026-05-28 검증).
_AD_SECTION_ID = "power_link_body"

#: onclick attribute 안 rank 박제 패턴 — ``a=pwl.tit&r=<rank>&i=nad-<id>``.
_ONCLICK_RANK_RE = re.compile(r"a=pwl\.tit&r=(\d+)&i=(nad-[A-Za-z0-9_-]+)")

#: 한글/영숫자 단어경계 (P0 review 2026-05-27 — 한글 false positive 차단).
_WORD_CHAR = r"[A-Za-z0-9가-힣]"


def _normalize(text: str) -> str:
    """Unicode 정규화 + whitespace 컬랩스.

    - NFC 정규화 (조합형 한글 → 완성형)
    - U+00A0(non-breaking space) 등 모든 Unicode whitespace를 일반 공백으로 통일.
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def _term_in_text(term: str, text: str) -> bool:
    """단어경계 안에서만 ``term`` 매치.

    예) ``term="수자인"`` 일 때 ``"수자인플러스 분양"`` 에는 매치 안 됨
    (``수자인`` 뒤에 한글 ㅍ → 단어 내부 substring 매치).
    ``"수자인 더 좋은"`` 또는 ``"분양 수자인 분양"`` 은 매치.
    """
    pattern = rf"(?<!{_WORD_CHAR}){re.escape(term)}(?!{_WORD_CHAR})"
    return re.search(pattern, text) is not None


def _resolve_rank(li_tag: object, dom_index: int, term: str) -> int:
    """DOM 순서(1-based)와 onclick ``r=`` 값을 cross-check 후 채택 rank 반환.

    둘이 일치하면 그 값, 불일치하면 onclick ``r=`` 값을 채택(광고 영역 내 명시적
    rank 신호가 DOM 순서보다 강하다)하고 warn 로그. onclick 신호 없으면 DOM 순서.
    """
    onclick_anchor = li_tag.find("a", onclick=True)  # type: ignore[attr-defined]
    if onclick_anchor is None:
        return dom_index
    match = _ONCLICK_RANK_RE.search(onclick_anchor.get("onclick", ""))
    if match is None:
        return dom_index
    onclick_rank = int(match.group(1))
    if onclick_rank != dom_index:
        log.warning(
            "parser.rank_mismatch",
            term=term,
            dom_index=dom_index,
            onclick_rank=onclick_rank,
            nad_id=match.group(2),
        )
    return onclick_rank


def _build_candidate_terms(term: str, aliases: list[str] | None) -> list[tuple[str, str]]:
    """Story 1.10: term + aliases를 normalize + dedupe해서 (label, normalized) 리스트로 반환.

    label = ``"term"`` (KW 본 term) 또는 ``"alias"``. match_found 로그에 ``matched_via`` 박제용.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    term_norm = _normalize(term)
    if term_norm:
        out.append(("term", term_norm))
        seen.add(term_norm)
    if aliases:
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            norm = _normalize(alias)
            if not norm or norm in seen:
                continue
            out.append(("alias", norm))
            seen.add(norm)
    return out


def extract_rank(
    html: str | None,
    term: str,
    aliases: list[str] | None = None,
) -> int | None:
    """SERP HTML에서 ``term`` 또는 ``aliases`` 일치 광고의 1-based rank 추출 (v2.1).

    Story 1.10: ``aliases`` optional 도입. term + aliases 중 하나라도 단어경계 매치
    시 인정. 한 광고에 여러 후보가 매치돼도 첫 광고만 채택.

    Args:
        html: SERP HTML 전체 (``http_client.fetch_serp_html`` 출력).
        term: 검색 키워드.
        aliases: KW alias 후보 list (광고 텍스트 변형 표현). None/빈 list → v1.4b 호환
            (term-only 매칭).

    Returns:
        매치 광고의 1-based 순위 — onclick ``r=`` 값 우선, 부재 시 DOM 순서.
        다음 경우 None:
          - ``html`` 이 None 또는 빈 문자열
          - ``term`` 이 빈 문자열 / 공백뿐 AND aliases도 비어있음
          - ``<ul id="power_link_body">`` 부재
          - 광고 영역에 ``<li>`` direct child 없음
          - 어떤 광고에도 term/aliases 매치 없음
    """
    if not html:
        return None

    candidates = _build_candidate_terms(term, aliases)
    if not candidates:
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 — malformed HTML 안전 가드
        log.warning("parser.bs4_parse_failed", term=term)
        return None

    ad_section = soup.find("ul", id=_AD_SECTION_ID)
    if ad_section is None:
        log.info("parser.no_ad_section", term=term)
        return None

    ad_items = ad_section.find_all("li", recursive=False)
    if not ad_items:
        log.info("parser.no_ad_items", term=term)
        return None

    for dom_index, li_tag in enumerate(ad_items, start=1):
        text = _normalize(li_tag.get_text(separator=" ", strip=True))
        for label, candidate in candidates:
            if _term_in_text(candidate, text):
                rank = _resolve_rank(li_tag, dom_index, candidate)
                log.info(
                    "parser.match_found",
                    term=term,
                    matched_via=label,
                    matched_value=candidate,
                    rank=rank,
                    dom_index=dom_index,
                )
                return rank

    log.info(
        "parser.no_match",
        term=term,
        candidates=len(ad_items),
        candidate_term_count=len(candidates),
    )
    return None
