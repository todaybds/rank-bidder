"""SERP HTML parser — 파워링크 영역 + ``li[data-index]`` 기반 rank 추출.

**중요한 금지 사항 (Research §Mobile SERP):**
``sds-comps-*``, ``sc-*``, 6자 hash-based 자동 생성 클래스 직접 매칭 금지 —
Naver는 수개월마다 클래스명을 로테이션한다. 본 파서는 다음 두 신호에만 의존한다:

1. **텍스트 앵커** — 페이지에 "파워링크" 단어 존재 (광고 영역 표식).
2. **``data-*`` 속성** — ``<li data-index="N">`` 항목 (광고 슬롯).

v1은 단일 전략 + 빈결과율 알림(Epic 6 별도 story). v2에서 multi-strategy fallback 도입 예정.
"""

from __future__ import annotations

import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger(__name__)

#: 광고 영역 식별 텍스트 앵커.
_AD_SECTION_TEXT_ANCHOR = "파워링크"


def extract_rank(html: str | None, term: str) -> int | None:
    """SERP HTML에서 ``term`` 일치 광고의 1-based rank 추출.

    Args:
        html: SERP HTML 전체 (``http_client.fetch_serp_html`` 출력).
        term: 검색 키워드. 광고 항목 텍스트에 부분 매치되는 첫 항목을 채택.

    Returns:
        매치 항목의 1-based 순위(파워링크 영역 내 ``data-index`` 정렬 기준).
        다음 경우 None:
          - ``html`` 이 None 또는 빈 문자열
          - ``term`` 이 빈 문자열
          - 페이지에 "파워링크" 텍스트 없음
          - ``li[data-index]`` 항목 없음
          - 어떤 항목 텍스트에도 ``term`` 부분 매치 없음
    """
    if not html or not term:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # 광고 영역 표식 — 페이지 전체 텍스트에 "파워링크" 단어가 있어야.
    if _AD_SECTION_TEXT_ANCHOR not in soup.get_text():
        log.info("parser.no_ad_section_anchor", term=term)
        return None

    # data-index 속성이 있는 모든 <li> — 광고 슬롯 후보.
    ad_items = soup.find_all("li", attrs={"data-index": True})
    if not ad_items:
        log.info("parser.no_data_index_items", term=term)
        return None

    # data-index 정수 정렬 (HTML 순서 = data-index 순서가 보장 안 될 수 있음).
    def _index_key(li_tag: object) -> int:
        try:
            return int(li_tag.get("data-index"))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            return 10_000

    sorted_items = sorted(ad_items, key=_index_key)

    for rank_one_based, li_tag in enumerate(sorted_items, start=1):
        text = li_tag.get_text(separator=" ", strip=True)
        if term in text:
            log.info(
                "parser.match_found",
                term=term,
                rank=rank_one_based,
                data_index=li_tag.get("data-index"),
            )
            return rank_one_based

    log.info("parser.no_match", term=term, candidates=len(sorted_items))
    return None
