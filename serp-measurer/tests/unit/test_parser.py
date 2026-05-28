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
