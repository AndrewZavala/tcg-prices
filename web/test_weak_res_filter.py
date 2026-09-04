"""Tests for weakness:/resistance: search parsing and SQL helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_api import (  # noqa: E402
    _apply_weak_res_filters,
    _parse_search_query,
    _sql_jsonb_has_type,
)


def test_parse_weakness_abbrev_and_name() -> None:
    parsed = _parse_search_query("weakness:l weakness:fighting")
    assert parsed["weaknesses"] == ["Lightning", "Fighting"]


def test_parse_resistance_abbrev() -> None:
    parsed = _parse_search_query("resistance:f -resistance:psychic")
    assert parsed["resistances"] == ["Fighting"]
    assert parsed["exclude_resistances"] == ["Psychic"]


def test_parse_weak_resist_aliases() -> None:
    parsed = _parse_search_query("weak:fire resist:metal res:y")
    assert parsed["weaknesses"] == ["Fire"]
    assert parsed["resistances"] == ["Metal", "Fairy"]


def test_energy_color_abbrev() -> None:
    parsed = _parse_search_query("c:l -c:f")
    assert parsed["card_type"] == "Lightning"
    assert parsed["exclude_card_types"] == ["Fighting"]


def test_energy_color_full_name() -> None:
    parsed = _parse_search_query("c:fire color:water")
    assert parsed["card_type"] == "Water"  # last wins
    assert _parse_search_query("c:r")["card_type"] == "Fire"


def test_legacy_e_type_prefixes_ignored() -> None:
    # Replaced by c: / color:
    parsed = _parse_search_query("e:l type:f")
    assert parsed["card_type"] is None
    assert parsed["exclude_card_types"] == []


def test_sql_jsonb_helper() -> None:
    sql = _sql_jsonb_has_type("weaknesses", "weak_0")
    assert "jsonb_array_elements" in sql
    assert "elem->>'type' = :weak_0" in sql


def test_apply_weak_res_filters() -> None:
    filters: list[str] = []
    params: dict = {}
    _apply_weak_res_filters(
        filters,
        params,
        weaknesses=["Lightning"],
        exclude_weaknesses=["Fire"],
        resistances=["Fighting"],
        exclude_resistances=[],
    )
    assert len(filters) == 3
    assert params["weak_0"] == "Lightning"
    assert params["xweak_0"] == "Fire"
    assert params["resist_0"] == "Fighting"
    assert any("NOT" in f for f in filters)


def test_parse_retreat() -> None:
    from pokemon_api import _apply_retreat_filters, _sql_retreat_eq

    parsed = _parse_search_query("retreat:0 retreat:2 -retreat:1")
    assert parsed["retreats"] == [0, 2]
    assert parsed["exclude_retreats"] == [1]
    assert "COALESCE(c.retreat, 0)" in _sql_retreat_eq("retreat_0")

    filters: list[str] = []
    params: dict = {}
    _apply_retreat_filters(
        filters, params, retreats=[0, 2], exclude_retreats=[1]
    )
    assert len(filters) == 2
    assert params["retreat_0"] == 0
    assert params["retreat_1"] == 2
    assert params["xretreat_0"] == 1


if __name__ == "__main__":
    test_parse_weakness_abbrev_and_name()
    test_parse_resistance_abbrev()
    test_parse_weak_resist_aliases()
    test_energy_color_abbrev()
    test_energy_color_full_name()
    test_legacy_e_type_prefixes_ignored()
    test_sql_jsonb_helper()
    test_apply_weak_res_filters()
    test_parse_retreat()
    print("ok")
