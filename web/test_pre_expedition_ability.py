"""Tests for pre-Expedition Poké-Power → Pokémon Power remapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "web"))

from pokemon_api import (  # noqa: E402
    _sql_ability_type_norm_expr,
    remap_pre_expedition_abilities,
)
from pokemon_card_corrections import (  # noqa: E402
    correct_abilities,
    remap_pre_expedition_ability_type,
)


def test_remap_pre_expedition_labels() -> None:
    assert remap_pre_expedition_ability_type("base4", "Poke-POWER") == "Pokemon Power"
    assert remap_pre_expedition_ability_type("base1", "Poké-POWER") == "Pokemon Power"
    assert remap_pre_expedition_ability_type("neo4", "Poke-BODY") == "Pokemon Power"
    assert remap_pre_expedition_ability_type("base1", "Pokemon Power") == "Pokemon Power"
    # Expedition+ stays Poké-Power
    assert remap_pre_expedition_ability_type("ecard1", "Poke-POWER") == "Poke-POWER"
    assert remap_pre_expedition_ability_type("ex16", "Poke-POWER") == "Poke-POWER"


def test_correct_abilities_set_scoped() -> None:
    rows = [{"type": "Poke-POWER", "name": "Damage Swap", "effect": "…"}]
    fixed = correct_abilities("base4-1", rows, set_id="base4")
    assert fixed[0]["type"] == "Pokemon Power"
    untouched = correct_abilities("ecard1-1", rows, set_id="ecard1")
    assert untouched[0]["type"] == "Poke-POWER"


def test_api_remap_abilities() -> None:
    abs = remap_pre_expedition_abilities(
        "lc", [{"type": "Poke-POWER", "name": "X"}]
    )
    # Legendary Collection is not in the curated pre-Expedition list
    assert abs[0]["type"] == "Poke-POWER"
    base = remap_pre_expedition_abilities(
        "base4", [{"type": "Poke-POWER", "name": "X"}]
    )
    assert base[0]["type"] == "Pokemon Power"


def test_sql_norm_rewrites_pre_expedition() -> None:
    sql = _sql_ability_type_norm_expr()
    assert "base4" in sql
    assert "pokepower" in sql
    assert "pokemonpower" in sql
    assert "ecard1" not in sql


if __name__ == "__main__":
    test_remap_pre_expedition_labels()
    test_correct_abilities_set_scoped()
    test_api_remap_abilities()
    test_sql_norm_rewrites_pre_expedition()
    print("ok")
