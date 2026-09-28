"""Tests for usd>/usd< price search tokens and price sorts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from pokemon_api import SORT_SQL, _apply_price_filters, _parse_search_query  # noqa: E402


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
    assert "price_usd DESC NULLS LAST" in SORT_SQL["price_desc"]
    assert "price_usd ASC NULLS LAST" in SORT_SQL["price_asc"]
