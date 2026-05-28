"""Story 1.10 — keywords.aliases column round-trip + validation.

DB migration 0009로 추가된 ``keywords.aliases`` TEXT(JSON) 컬럼이 Python
``list[str]``과 round-trip 되는지, validator가 빈 문자열/중복/초과 길이를 거부하는지
검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, KeywordUpdate, SiteCreate
from rank_bidder.db.repositories import keywords, sites


@pytest.fixture
def seeded_site(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
    return "s1"


def test_create_aliases_default_empty_list(seeded_site: str) -> None:
    """aliases 미지정 → []."""
    with write_transaction() as conn:
        kw = keywords.create(
            conn,
            KeywordCreate(
                id="kw-no-alias", site_id=seeded_site, term="t", target_rank=1, bid_cap=1000
            ),
        )
    assert kw.aliases == []
    with get_connection() as conn:
        round_trip = keywords.get(conn, "kw-no-alias")
    assert round_trip is not None and round_trip.aliases == []


def test_create_aliases_round_trip_korean(seeded_site: str) -> None:
    """한글 alias 다수 등록 → SELECT 시 동일 list 복원."""
    aliases = ["평택비스타동원", "브레인시티비스타동원", "평택브레인시티동원"]
    with write_transaction() as conn:
        keywords.create(
            conn,
            KeywordCreate(
                id="kw-rt",
                site_id=seeded_site,
                term="평택고덕동브레인시티비스타동원",
                target_rank=1,
                bid_cap=1000,
                aliases=aliases,
            ),
        )
    with get_connection() as conn:
        kw = keywords.get(conn, "kw-rt")
    assert kw is not None
    assert kw.aliases == aliases


def test_create_aliases_strips_whitespace(seeded_site: str) -> None:
    """alias 양끝 공백은 strip되어 저장."""
    with write_transaction() as conn:
        keywords.create(
            conn,
            KeywordCreate(
                id="kw-strip",
                site_id=seeded_site,
                term="t",
                target_rank=1,
                bid_cap=1000,
                aliases=["  hello  ", "world "],
            ),
        )
    with get_connection() as conn:
        kw = keywords.get(conn, "kw-strip")
    assert kw is not None and kw.aliases == ["hello", "world"]


def test_create_aliases_rejects_empty_string() -> None:
    """alias가 빈 문자열/공백뿐 → ValidationError."""
    with pytest.raises(ValidationError):
        KeywordCreate(
            id="kw-x",
            site_id="s1",
            term="t",
            target_rank=1,
            bid_cap=1000,
            aliases=["valid", "   "],
        )


def test_create_aliases_rejects_duplicates() -> None:
    """동일 alias 2회 → ValidationError."""
    with pytest.raises(ValidationError):
        KeywordCreate(
            id="kw-x",
            site_id="s1",
            term="t",
            target_rank=1,
            bid_cap=1000,
            aliases=["dup", "dup"],
        )


def test_create_aliases_rejects_over_20() -> None:
    """alias 21개 → ValidationError (Field max_length=20)."""
    with pytest.raises(ValidationError):
        KeywordCreate(
            id="kw-x",
            site_id="s1",
            term="t",
            target_rank=1,
            bid_cap=1000,
            aliases=[f"a{i}" for i in range(21)],
        )


def test_create_aliases_rejects_non_string_items() -> None:
    """alias 항목이 str이 아니면 → ValidationError."""
    with pytest.raises(ValidationError):
        KeywordCreate(
            id="kw-x",
            site_id="s1",
            term="t",
            target_rank=1,
            bid_cap=1000,
            aliases=["ok", 123],  # type: ignore[list-item]
        )


def test_update_aliases_replaces_existing(seeded_site: str) -> None:
    """KeywordUpdate(aliases=[...]) → 기존 aliases 교체 + version+1."""
    with write_transaction() as conn:
        keywords.create(
            conn,
            KeywordCreate(
                id="kw-up",
                site_id=seeded_site,
                term="t",
                target_rank=1,
                bid_cap=1000,
                aliases=["old1", "old2"],
            ),
        )
    with write_transaction() as conn:
        updated = keywords.update(
            conn,
            "kw-up",
            KeywordUpdate(aliases=["new1", "new2", "new3"]),
            expected_version=0,
        )
    assert updated.aliases == ["new1", "new2", "new3"]
    assert updated.version == 1


def test_update_aliases_none_preserves_existing(seeded_site: str) -> None:
    """KeywordUpdate(aliases=None, term="x") → aliases 보존, term만 갱신."""
    with write_transaction() as conn:
        keywords.create(
            conn,
            KeywordCreate(
                id="kw-pres",
                site_id=seeded_site,
                term="t",
                target_rank=1,
                bid_cap=1000,
                aliases=["keep1", "keep2"],
            ),
        )
    with write_transaction() as conn:
        updated = keywords.update(
            conn,
            "kw-pres",
            KeywordUpdate(term="changed", aliases=None),
            expected_version=0,
        )
    assert updated.term == "changed"
    assert updated.aliases == ["keep1", "keep2"]


def test_update_aliases_empty_list_clears(seeded_site: str) -> None:
    """KeywordUpdate(aliases=[]) → aliases 빈 list로 reset (None과 다른 의미)."""
    with write_transaction() as conn:
        keywords.create(
            conn,
            KeywordCreate(
                id="kw-clr",
                site_id=seeded_site,
                term="t",
                target_rank=1,
                bid_cap=1000,
                aliases=["a", "b"],
            ),
        )
    with write_transaction() as conn:
        updated = keywords.update(
            conn,
            "kw-clr",
            KeywordUpdate(aliases=[]),
            expected_version=0,
        )
    assert updated.aliases == []
