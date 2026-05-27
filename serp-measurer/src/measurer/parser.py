"""SERP HTML parser — 파워링크 영역 + ``li[data-index]`` 기반 rank 추출.

**중요한 금지 사항 (Research §Mobile SERP):**
``sds-comps-*``, ``sc-*``, 6자 hash-based 자동 생성 클래스 직접 매칭 금지 —
Naver는 수개월마다 클래스명을 로테이션한다. 본 파서는 다음 두 신호에만 의존한다:

1. **텍스트 앵커** — 페이지에 "파워링크" 단어 존재 + ``li[data-index]`` 의 ancestor section/ul 안에도 동일 앵커 (P1 section-scoped, 2026-05-27 review).
2. **``data-*`` 속성** — ``<li data-index="N">`` 항목 (광고 슬롯).

v1은 단일 전략 + 빈결과율 알림(Epic 6 별도 story). v2에서 multi-strategy fallback 도입 예정.
"""

from __future__ import annotations

import re
import unicodedata

import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger(__name__)

#: 광고 영역 식별 텍스트 앵커.
_AD_SECTION_TEXT_ANCHOR = "파워링크"

#: 한글/영숫자 단어경계 (P0 review 2026-05-27 — 한글 false positive 차단).
#: term이 한글/영숫자 글자 사이에 끼어 있으면 매치 거부.
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


def _is_in_ad_section(li_tag: object) -> bool:
    """``li`` 의 가까운 ancestor(section/ul/div)에 '파워링크' 앵커가 있는지 확인.

    P1 review (2026-05-27): page-global anchor만 보면 푸터/도움말의 '파워링크 안내'
    텍스트로도 통과해 false positive 발생. ancestor 범위를 좁혀 광고 영역에서
    발견된 ``data-index`` li만 채택.
    """
    for ancestor in li_tag.parents:  # type: ignore[attr-defined]
        name = getattr(ancestor, "name", None)
        if name in (None, "html", "body"):
            return False
        if name not in ("section", "ul", "div"):
            continue
        ancestor_text = ancestor.get_text(" ", strip=True)
        if _AD_SECTION_TEXT_ANCHOR in ancestor_text:
            return True
    return False


def extract_rank(html: str | None, term: str) -> int | None:
    """SERP HTML에서 ``term`` 일치 광고의 1-based rank 추출.

    Args:
        html: SERP HTML 전체 (``http_client.fetch_serp_html`` 출력).
        term: 검색 키워드. 광고 항목 텍스트에 단어경계 안에서 매치되는 첫 항목 채택.

    Returns:
        매치 항목의 1-based 순위(파워링크 영역 내 ``data-index`` 정렬 기준).
        다음 경우 None:
          - ``html`` 이 None 또는 빈 문자열
          - ``term`` 이 빈 문자열 / 공백뿐
          - 페이지에 "파워링크" 텍스트 없음
          - 광고 영역에 ``li[data-index]`` 항목 없음
          - 어떤 광고 항목 텍스트에도 ``term`` 단어경계 매치 없음
    """
    if not html or not term or not term.strip():
        return None

    term_normalized = _normalize(term)
    if not term_normalized:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # 광고 영역 page-global 앵커 (1차 가드).
    if _AD_SECTION_TEXT_ANCHOR not in soup.get_text():
        log.info("parser.no_ad_section_anchor", term=term_normalized)
        return None

    # data-index 있는 모든 li 후보.
    candidate_items = soup.find_all("li", attrs={"data-index": True})
    if not candidate_items:
        log.info("parser.no_data_index_items", term=term_normalized)
        return None

    # P1: section-scoped 가드 (ancestor section/ul/div에 파워링크 앵커 있는 것만).
    ad_items = [li for li in candidate_items if _is_in_ad_section(li)]
    if not ad_items:
        log.info(
            "parser.no_ad_section_scoped_items",
            term=term_normalized,
            page_candidates=len(candidate_items),
        )
        return None

    # P1: 비숫자 data-index는 drop + warn (sentinel 10_000 silent corruption 차단).
    items_with_keys: list[tuple[int, object]] = []
    dropped = 0
    for li in ad_items:
        raw = li.get("data-index")  # type: ignore[union-attr]
        try:
            key = int(raw)
        except (TypeError, ValueError):
            dropped += 1
            continue
        items_with_keys.append((key, li))

    if dropped:
        log.warning("parser.dropped_invalid_data_index", term=term_normalized, dropped=dropped)

    if not items_with_keys:
        log.info("parser.no_int_data_index_items", term=term_normalized)
        return None

    items_with_keys.sort(key=lambda t: t[0])

    for rank_one_based, (_key, li_tag) in enumerate(items_with_keys, start=1):
        text = _normalize(li_tag.get_text(separator=" ", strip=True))  # type: ignore[attr-defined]
        if _term_in_text(term_normalized, text):
            log.info(
                "parser.match_found",
                term=term_normalized,
                rank=rank_one_based,
                data_index=li_tag.get("data-index"),  # type: ignore[attr-defined]
            )
            return rank_one_based

    log.info("parser.no_match", term=term_normalized, candidates=len(items_with_keys))
    return None
