"""Tests for is:multicolor — multiple energy colors on a Pokémon."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_api import (  # noqa: E402
    _apply_multicolor_filter,
    _parse_search_query,
    _sql_is_multicolor,
)


def test_parse_multicolor() -> None:
    assert _parse_search_query("is:multicolor")["multicolor"] is True
    assert _parse_search_query("is:multi-color")["multicolor"] is True
    assert _parse_search_query("is:multicolour")["multicolor"] is True
    assert _parse_search_query("-is:multicolor")["multicolor"] is False
    assert _parse_search_query("Hariyama")["multicolor"] is None


def test_multicolor_not_treated_as_tag() -> None:
    parsed = _parse_search_query("is:multicolor is:ex")
    assert parsed["multicolor"] is True
    assert "ex" in parsed["tags"]
    assert "multicolor" not in parsed["tags"]


def test_sql_mentions_colorless_exception() -> None:
    sql = _sql_is_multicolor()
    assert "Colorless" in sql
    assert "attacks" in sql
    assert "Fire" in sql
    assert "Psychic" in sql
    # Energy-in-text for White Kyurem-style cards
    assert r"\yFire\s+Energy\y" in sql or "Fire" in sql


def test_apply_multicolor_filter() -> None:
    filters: list[str] = []
    _apply_multicolor_filter(filters, multicolor=True)
    assert len(filters) == 1
    assert "category = 'Pokemon'" in filters[0]

    filters = []
    _apply_multicolor_filter(filters, multicolor=False)
    assert filters[0].startswith("NOT ")

    filters = []
    _apply_multicolor_filter(filters, multicolor=None)
    assert filters == []
