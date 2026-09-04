"""Tests for has:ability / has:poke-power style filters."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_api import (  # noqa: E402
    _apply_has_ability_filters,
    _norm_ability_type_key,
    _parse_search_query,
    _resolve_has_ability_kind,
    _sql_has_ability_kind,
    _sql_has_any_ability,
)


def test_norm_ability_type_key() -> None:
    assert _norm_ability_type_key("Poké-POWER") == "pokepower"
    assert _norm_ability_type_key("Pokemon Power") == "pokemonpower"
    assert _norm_ability_type_key("Ability") == "ability"
    assert _norm_ability_type_key("Ancient Trait") == "ancienttrait"


def test_resolve_has_kinds() -> None:
    assert _resolve_has_ability_kind("ability") == "ability"
    assert _resolve_has_ability_kind("ability-any") == "ability-any"
    assert _resolve_has_ability_kind("poke-power") == "poke-power"
    assert _resolve_has_ability_kind("pokepower") == "poke-power"
    assert _resolve_has_ability_kind("omega-trait") == "omega-trait"
    assert _resolve_has_ability_kind("nope") is None


def test_parse_has_ability_specific() -> None:
    parsed = _parse_search_query("has:ability -has:poke-body")
    assert parsed["has_ability_kinds"] == ["ability"]
    assert parsed["exclude_has_ability_kinds"] == ["poke-body"]


def test_parse_has_ability_any() -> None:
    parsed = _parse_search_query("has:ability-any has:pokemon-power")
    assert parsed["has_ability_kinds"] == ["ability-any", "pokemon-power"]


def test_apply_has_ability_filters_sql() -> None:
    filters: list[str] = []
    params: dict = {}
    _apply_has_ability_filters(
        filters,
        params,
        kinds=["ability-any", "ability", "poke-power"],
        exclude_kinds=["omega-trait"],
    )
    assert any(_sql_has_any_ability() in f for f in filters)
    assert any("EXISTS" in f for f in filters)
    assert params["has_ab_1"] == ["ability"]
    assert params["has_ab_2"] == ["pokepower"]
    assert params["xhas_ab_0"] == ["ancienttrait", "omegatrait"]
    assert "CAST(:has_ab_1 AS text[])" in _sql_has_ability_kind("has_ab_1")


if __name__ == "__main__":
    test_norm_ability_type_key()
    test_resolve_has_kinds()
    test_parse_has_ability_specific()
    test_parse_has_ability_any()
    test_apply_has_ability_filters_sql()
    print("ok")
