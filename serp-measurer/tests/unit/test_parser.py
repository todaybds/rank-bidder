"""Unit tests — parser.extract_rank.

3개 fixture HTML 기반:
- ``serp_rank1.html`` — "수자인" 광고가 첫 슬롯 (rank=1)
- ``serp_rank3.html`` — "수자인" 광고가 셋째 슬롯 (rank=3)
- ``serp_empty.html`` — 파워링크 영역 없음 (rank=None)
"""

from __future__ import annotations

from pathlib import Path

import pytest
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
    """광고 제목에 term이 부분 포함되어도 매치 인정 (FR-8 spec)."""
    html = _load_fixture("serp_rank1.html")
    # serp_rank1 첫 광고: "수자인 더 좋은 아파트 분양정보" — "더 좋은"으로도 매치.
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


def test_data_index_sort_handles_out_of_order(tmp_path: pytest.TempPathFactory) -> None:
    """HTML 순서와 data-index 정수 순서가 다른 경우 — data-index 순서로 정렬."""
    html = """
    <html><body><section>
      <p>파워링크</p>
      <ul>
        <li data-index="2"><span>일반 광고</span></li>
        <li data-index="0"><span>수자인 광고</span></li>
        <li data-index="1"><span>다른 광고</span></li>
      </ul>
    </section></body></html>
    """
    # data-index=0이 첫 슬롯 → 수자인 = rank 1.
    assert extract_rank(html, "수자인") == 1
