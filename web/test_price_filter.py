"""Tests for usd>/usd< price search tokens, price sorts, is:competitive, and f: formats."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from pokemon_api import (  # noqa: E402
    _apply_competitive_filter,
    _apply_format_filters,
    _apply_price_filters,
    _parse_search_query,
    resolve_sort,
    sort_order_sql,
)


def test_parse_price_tokens() -> None:
    parsed = _parse_search_query("charizard usd>10 usd<=250.50")
    assert parsed["prices"] == [(">", 10.0), ("<=", 250.5)]
    assert parsed["name_q"] == "charizard"


def test_parse_price_aliases_and_negation() -> None:
    parsed = _parse_search_query("price>=$5 -usd>100 usd=1")
    assert parsed["prices"] == [(">=", 5.0), ("=", 1.0)]
    assert parsed["exclude_prices"] == [(">", 100.0)]


def test_malformed_price_is_name_text() -> None:
    parsed = _parse_search_query("usd>abc")
    assert parsed["prices"] == []
    assert parsed["name_q"] == "usd>abc"


def test_apply_price_filters() -> None:
    filters: list[str] = []
    params: dict = {}
    _apply_price_filters(
        filters,
        params,
        prices=[(">", 10.0), (":", 2.0)],
        exclude_prices=[("<", 1.0)],
    )
    assert filters[0] == "c.price_usd > :usd_0"
    assert filters[1] == "c.price_usd = :usd_1"
    assert "c.price_usd IS NOT NULL" in filters[2]
    assert "NOT (c.price_usd < :xusd_0)" in filters[2]
    assert params == {"usd_0": 10.0, "usd_1": 2.0, "xusd_0": 1.0}


def test_price_sorts_put_unpriced_last() -> None:
    assert "price_usd DESC NULLS LAST" in sort_order_sql("price", "desc")
    assert "price_usd ASC NULLS LAST" in sort_order_sql("price", "asc")


def test_resolve_sort_defaults_and_legacy_keys() -> None:
    assert resolve_sort(None, None) == ("name", "asc")
    assert resolve_sort("price", None) == ("price", "desc")
    assert resolve_sort("hp", "asc") == ("hp", "asc")
    assert resolve_sort("set", "desc") == ("set", "desc")
    assert resolve_sort("price_asc", None) == ("price", "asc")
    assert resolve_sort("price_desc", None) == ("price", "desc")
    assert resolve_sort("hp_desc", None) == ("hp", "desc")
    assert resolve_sort("price_desc", "asc") == ("price", "asc")
    assert resolve_sort("random", None)[0] == "shuffle"
    assert resolve_sort("bogus", "sideways") == ("name", "asc")


def test_sort_direction_flips_primary_columns() -> None:
    assert sort_order_sql("set", "desc").startswith("s.release_date DESC NULLS LAST, c.set_id DESC")
    assert sort_order_sql("name", "desc").startswith("c.name DESC")
    assert "DESC" not in sort_order_sql("type", "asc").split(",")[0]
    assert sort_order_sql("type", "desc").split(",")[0].endswith("END DESC")


def test_supertype_sort() -> None:
    assert resolve_sort("supertype", None) == ("supertype", "asc")
    asc = sort_order_sql("supertype", "asc")
    desc = sort_order_sql("supertype", "desc")
    assert "END ASC, c.name ASC" in asc
    assert "END DESC, c.name ASC" in desc
    tool = asc.index("'pokemon-tool'")
    assert tool < asc.index("'supporter'") < asc.index("'item' =")


def test_competitive_filter() -> None:
    assert _parse_search_query("is:competitive")["competitive"] is True
    assert _parse_search_query("-is:competitive")["competitive"] is False
    assert "competitive" not in _parse_search_query("is:competitive")["tags"]

    filters: list[str] = []
    _apply_competitive_filter(filters, competitive=True)
    _apply_competitive_filter(filters, competitive=False)
    _apply_competitive_filter(filters, competitive=None)
    assert filters == ["c.limitless_decklists = TRUE", "c.limitless_decklists IS NOT TRUE"]


def test_parse_formats() -> None:
    parsed = _parse_search_query("f:standard format:exp -legal:expanded f:std f:modern")
    assert parsed["formats"] == ["standard", "expanded"]
    assert parsed["exclude_formats"] == ["expanded"]


def test_format_filters_use_reprint_rule() -> None:
    filters: list[str] = []
    _apply_format_filters(filters, formats=["standard"], exclude_formats=["expanded"])
    assert "pokemon_printing_is_standard(c.regulation_mark" in filters[0]
    assert "spelltag_standard_min_mark()" in filters[0]
    assert "c.oracle_id IN (SELECT fo.oracle_id FROM pokemon_cards fo" in filters[0]
    assert filters[1].startswith("NOT (COALESCE(c.legal_expanded, FALSE) OR")
