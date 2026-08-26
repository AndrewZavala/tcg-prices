"""Unit tests for prize: search parsing and SQL helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_api import (  # noqa: E402
    PRIZE_2_TAGS,
    PRIZE_3_TAGS,
    _apply_prize_filters,
    _parse_search_query,
    _sql_prize_count,
)


def test_parse_prize_tokens() -> None:
    parsed = _parse_search_query("charizard prize:2 -prize:3")
    assert parsed["name_q"] == "charizard"
    assert parsed["prizes"] == [2]
    assert parsed["exclude_prizes"] == [3]


def test_parse_prize_or_list() -> None:
    parsed = _parse_search_query("prize:1 prize:3")
    assert parsed["prizes"] == [1, 3]


def test_radiant_not_in_two_prize_tags() -> None:
    assert "radiant" not in PRIZE_2_TAGS
    assert "radiant" not in PRIZE_3_TAGS


def test_sql_three_includes_mega_block() -> None:
    sql = _sql_prize_count(3)
    assert "me%" in sql
    assert "Mega %" in sql
    assert "tag-team" not in sql  # bound via param, not literal
    assert ":prize_3_tags" in sql


def test_apply_prize_filters_binds_params() -> None:
    filters: list[str] = []
    params: dict = {}
    _apply_prize_filters(filters, params, prizes=[2], exclude_prizes=[1])
    assert params["prize_2_tags"] == list(PRIZE_2_TAGS)
    assert params["prize_3_tags"] == list(PRIZE_3_TAGS)
    assert len(filters) == 2
    assert filters[0].startswith("(")
    assert filters[1].startswith("NOT ")


if __name__ == "__main__":
    test_parse_prize_tokens()
    test_parse_prize_or_list()
    test_radiant_not_in_two_prize_tags()
    test_sql_three_includes_mega_block()
    test_apply_prize_filters_binds_params()
    print("ok")
