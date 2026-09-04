"""Tests for is:multicolor — multiple energy colors on a Pokémon."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from pokemon_api import (  # noqa: E402
    _apply_multicolor_filter,
    _parse_search_query,
    _sql_is_multicolor,
)
from pokemon_card_corrections import compute_is_multicolor  # noqa: E402


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


def test_sql_uses_cached_column() -> None:
    sql = _sql_is_multicolor()
    assert "is_multicolor" in sql
    assert "category = 'Pokemon'" in sql


def test_flavor_psychic_energy_ignored_by_compute() -> None:
    assert not compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Water"],
            "attacks": [{"cost": ["Water"], "name": "Splash"}],
            "description": "It fires the psychic energy from its mouth.",
        }
    )


def test_apply_multicolor_filter() -> None:
    filters: list[str] = []
    _apply_multicolor_filter(filters, multicolor=True)
    assert len(filters) == 1
    assert "is_multicolor" in filters[0]

    filters = []
    _apply_multicolor_filter(filters, multicolor=False)
    assert filters[0].startswith("NOT ")

    filters = []
    _apply_multicolor_filter(filters, multicolor=None)
    assert filters == []


def test_compute_hariyama_delta() -> None:
    assert compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Fire"],
            "attacks": [
                {"name": "Slap Push", "cost": ["Colorless", "Colorless"]},
                {"name": "Brick Smash", "cost": ["Fighting", "Fighting", "Colorless"]},
            ],
        }
    )


def test_compute_lugia_colorless_plus_psychic() -> None:
    assert compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Colorless"],
            "attacks": [
                {"name": "Silver Wing", "cost": ["Colorless"]},
                {
                    "name": "Psychic Destruction",
                    "cost": ["Psychic", "Colorless", "Colorless"],
                },
            ],
        }
    )


def test_compute_white_kyurem_fire_in_text() -> None:
    assert compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Water"],
            "attacks": [
                {
                    "name": "Burning Icicles",
                    "cost": ["Water", "Colorless"],
                    "effect": (
                        "If this Pokémon has any Fire Energy attached to it, "
                        "this attack does 20 damage to 2 of your opponent's Benched Pokémon."
                    ),
                }
            ],
        }
    )


def test_compute_mono_fire_not_multicolor() -> None:
    assert not compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Fire"],
            "attacks": [
                {"name": "Ember", "cost": ["Fire", "Colorless"]},
            ],
        }
    )
