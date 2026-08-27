"""Unit tests for o: oracle text search parsing and SQL helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_api import (  # noqa: E402
    _apply_oracle_text_filters,
    _parse_oracle_text_value,
    _parse_search_query,
    _tokenize_search_query,
)


def test_tokenize_quoted_phrase() -> None:
    assert _tokenize_search_query('o:"active spot" t:pokemon') == [
        'o:"active spot"',
        "t:pokemon",
    ]


def test_parse_oracle_word() -> None:
    parsed = _parse_search_query("o:active t:pokemon")
    assert parsed["oracle_text"] == [{"mode": "word", "pattern": "active"}]
    assert parsed["category"] == "Pokemon"


def test_parse_oracle_quoted_phrase() -> None:
    parsed = _parse_search_query('o:"active spot"')
    assert parsed["oracle_text"] == [{"mode": "phrase", "pattern": "active spot"}]


def test_parse_oracle_regex() -> None:
    parsed = _parse_search_query(r"o:/active\s+spot/i")
    assert parsed["oracle_text"] == [{"mode": "regex", "pattern": r"active\s+spot"}]


def test_parse_oracle_negation() -> None:
    parsed = _parse_search_query("o:active -o:bench")
    assert parsed["oracle_text"] == [{"mode": "word", "pattern": "active"}]
    assert parsed["exclude_oracle_text"] == [{"mode": "word", "pattern": "bench"}]


def test_parse_quoted_name() -> None:
    parsed = _parse_search_query('"dark gyarados" t:pokemon')
    assert parsed["name_q"] == "dark gyarados"


def test_apply_oracle_text_filters_word_and_phrase() -> None:
    filters: list[str] = []
    params: dict = {}
    _apply_oracle_text_filters(
        filters,
        params,
        oracle_text=[
            {"mode": "word", "pattern": "active"},
            {"mode": "phrase", "pattern": "active spot"},
        ],
        exclude_oracle_text=[],
    )
    assert len(filters) == 2
    assert "~*" in filters[0]
    assert "ILIKE" in filters[1]
    assert params["otext_0"] == r"\yactive\y"
    assert params["otext_1"] == "%active spot%"


def test_invalid_regex_ignored() -> None:
    assert _parse_oracle_text_value("/(/") is None


if __name__ == "__main__":
    test_tokenize_quoted_phrase()
    test_parse_oracle_word()
    test_parse_oracle_quoted_phrase()
    test_parse_oracle_regex()
    test_parse_oracle_negation()
    test_parse_quoted_name()
    test_apply_oracle_text_filters_word_and_phrase()
    test_invalid_regex_ignored()
    print("ok")
