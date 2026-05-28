"""Unit tests — parser v2 (``ul#power_link_body`` + onclick ``r=N`` cross-check).

Fixtures:
- ``serp_rank1.html`` — "수자인" 광고가 r=1.
- ``serp_rank3.html`` — "수자인" 광고가 r=3.
- ``serp_empty.html`` — ``power_link_body`` 부재 (광고 영역 없음).
- ``serp_2026_05_28_sujain.html`` — production 캡처 (2026-05-28, "수자인" → r=?).
"""

from __future__ import annotations

from pathlib import Path

from measurer.parser import extract_rank
from structlog.testing import capture_logs

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_rank1_fixture_returns_1() -> None:
    html = _load_fixture("serp_rank1.html")
    assert extract_rank(html, "수자인") == 1


def test_rank3_fixture_returns_3() -> None:
    html = _load_fixture("serp_rank3.html")
    assert extract_rank(html, "수자인") == 3


def test_empty_fixture_no_ad_section_returns_none() -> None:
    html = _load_fixture("serp_empty.html")
    assert extract_rank(html, "수자인") is None


def test_term_not_in_any_ad_returns_none() -> None:
    """광고 영역은 있지만 term 매치 없음."""
    html = _load_fixture("serp_rank1.html")
    assert extract_rank(html, "전혀다른키워드") is None


def test_partial_match_in_ad_title_returns_rank() -> None:
    """광고 텍스트에 term이 부분 포함되어도 매치 인정 (FR-8 spec)."""
    html = _load_fixture("serp_rank1.html")
    # serp_rank1 첫 광고: "수자인 더 좋은 아파트" — "더 좋은"으로도 매치.
    assert extract_rank(html, "더 좋은") == 1


def test_none_html_returns_none() -> None:
    assert extract_rank(None, "수자인") is None


def test_empty_html_returns_none() -> None:
    assert extract_rank("", "수자인") is None


def test_empty_term_returns_none() -> None:
    html = _load_fixture("serp_rank1.html")
    assert extract_rank(html, "") is None


def test_malformed_html_returns_none_gracefully() -> None:
    """파싱 실패해도 예외 없이 None."""
    assert extract_rank("<not-real-html<<>>", "수자인") is None


def test_onclick_rank_preferred_over_dom_order() -> None:
    """광고 영역 안 li가 DOM-reorder된 경우, onclick ``r=`` 값을 채택."""
    # DOM 순서로는 첫 번째지만 onclick은 r=3 — onclick 채택 + warn.
    html = """
    <html><body>
      <ul id="power_link_body">
        <li class="bx">
          <a href="#" onclick='return goOtherCR(this,"a=pwl.tit&amp;r=3&amp;i=nad-x-1&amp;d=")'>
            <span>수자인 광고</span>
          </a>
        </li>
        <li class="bx">
          <a href="#" onclick='return goOtherCR(this,"a=pwl.tit&amp;r=1&amp;i=nad-x-2&amp;d=")'>
            <span>다른 광고</span>
          </a>
        </li>
      </ul>
    </body></html>
    """
    assert extract_rank(html, "수자인") == 3


def test_onclick_rank_mismatch_emits_warning_log() -> None:
    """AC3 review patch — DOM-order ≠ onclick r= 시 parser.rank_mismatch warning 박제 검증.

    회귀 방어: structlog warn 콜이 silent drop되면 production drift 진단 신호 끊김.
    """
    html = """
    <html><body>
      <ul id="power_link_body">
        <li class="bx">
          <a href="#" onclick='return goOtherCR(this,"a=pwl.tit&amp;r=5&amp;i=nad-x-1&amp;d=")'>
            <span>수자인 광고</span>
          </a>
        </li>
      </ul>
    </body></html>
    """
    with capture_logs() as cap:
        result = extract_rank(html, "수자인")
    assert result == 5
    warnings = [e for e in cap if e.get("event") == "parser.rank_mismatch"]
    assert len(warnings) == 1, f"expected 1 parser.rank_mismatch event, got: {cap}"
    w = warnings[0]
    assert w["dom_index"] == 1
    assert w["onclick_rank"] == 5
    assert w["nad_id"] == "nad-x-1"


def test_onclick_missing_falls_back_to_dom_order() -> None:
    """onclick anchor 없으면 DOM 순서를 rank로 사용."""
    html = """
    <html><body>
      <ul id="power_link_body">
        <li class="bx"><span>다른 광고</span></li>
        <li class="bx"><span>수자인 광고</span></li>
      </ul>
    </body></html>
    """
    assert extract_rank(html, "수자인") == 2


def test_word_boundary_rejects_substring_match() -> None:
    """``수자인`` 이 ``수자인플러스`` 등 한글 내부 substring 매치는 거부."""
    html = """
    <html><body>
      <ul id="power_link_body">
        <li class="bx">
          <a href="#" onclick='return goOtherCR(this,"a=pwl.tit&amp;r=1&amp;i=nad-x-1&amp;d=")'>
            <span>수자인플러스 분양</span>
          </a>
        </li>
      </ul>
    </body></html>
    """
    assert extract_rank(html, "수자인") is None


def test_production_fixture_sujain_returns_one() -> None:
    """Production capture (2026-05-28) — "수자인" 광고 5개 중 매치 첫 슬롯."""
    html = _load_fixture("serp_2026_05_28_sujain.html")
    # production에서 r=1~5 광고 모두 "수자인" 단어경계 매치 가능 — 첫 슬롯 채택.
    assert extract_rank(html, "수자인") == 1


# ---------------------------------------------------------------------------
# Story 1.10 — aliases 매칭 (long-tail KW unlock)
# ---------------------------------------------------------------------------


def test_aliases_match_when_term_does_not(_caplog=None) -> None:
    """term 자체는 광고 텍스트에 부재하지만 alias가 단어경계 매치 시 rank 반환.

    sentinel 케이스 mirror: term="평택고덕동브레인시티비스타동원" + aliases=["수자인"]
    (광고 텍스트에는 "수자인" 만 등장 가정) → rank 반환.
    """
    html = _load_fixture("serp_rank3.html")
    # serp_rank3 광고 3슬롯에 "수자인" 단어 등장. term="없는키워드긴거" + alias "수자인" 매치.
    assert extract_rank(html, "없는키워드긴거", aliases=["수자인"]) == 3


def test_aliases_none_keeps_v1_behavior() -> None:
    """aliases 부재(None) → term-only 동작. v1.4b backward-compat."""
    html = _load_fixture("serp_rank1.html")
    # term-only로 v1과 동일 결과.
    assert extract_rank(html, "수자인") == 1
    assert extract_rank(html, "수자인", aliases=None) == 1
    assert extract_rank(html, "수자인", aliases=[]) == 1


def test_aliases_term_takes_precedence_when_both_match() -> None:
    """term + alias 둘 다 매치 가능한 광고에서, term이 candidate 리스트 첫째라 우선 매치."""
    html = _load_fixture("serp_rank1.html")
    # serp_rank1: rank=1 광고 텍스트 "수자인 더 좋은 아파트", rank=2 "아파트 분양 정보".
    # term "아파트" + aliases ["수자인"]. rank=1 광고는 둘 다 매치 가능.
    # candidate order = [term, alias1] → "아파트" 먼저 매치되지만, rank=1 광고에선
    # 둘 다 가능하니 어느 쪽이 첫째인지로 rank 결정. rank=1.
    assert extract_rank(html, "아파트", aliases=["수자인"]) == 1


def test_aliases_only_first_matching_li_returns() -> None:
    """alias가 rank=3 광고에만 있고 term이 어디에도 없으면 → rank=3."""
    html = _load_fixture("serp_rank3.html")
    assert extract_rank(html, "이런키워드없음", aliases=["수자인"]) == 3
    # 단어경계 — 한글 substring 매치 거부 보존.
    assert extract_rank(html, "이런키워드없음", aliases=["수자인플러스"]) is None


def test_aliases_empty_after_normalize_returns_none() -> None:
    """term 빈 + aliases가 normalize 후 모두 빈 → None (어떤 광고도 매치할 수 없음)."""
    html = _load_fixture("serp_rank1.html")
    assert extract_rank(html, "", aliases=["", "  "]) is None


def test_aliases_dedupe_against_term() -> None:
    """alias가 term과 동일하면 dedupe (중복 매칭 안 함). 결과는 term 매치와 동일."""
    html = _load_fixture("serp_rank1.html")
    assert extract_rank(html, "수자인", aliases=["수자인"]) == 1


def test_aliases_non_string_items_ignored_silently() -> None:
    """alias list에 non-str item(잘못된 payload) 섞여있으면 그 항목만 무시, str alias는 매치."""
    html = _load_fixture("serp_rank3.html")
    # 첫 alias=None (무시), 둘째 "수자인" 매치 → rank=3.
    assert extract_rank(html, "없는단어", aliases=[None, "수자인"]) == 3  # type: ignore[list-item]
