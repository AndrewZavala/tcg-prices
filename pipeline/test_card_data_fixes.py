"""Tests for card data corrections from docs/CARD_DATA_FIXES_PLAN.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from pokemon_card_corrections import (  # noqa: E402
    apply_card_corrections,
    compute_is_multicolor,
    correct_attacks,
    correct_types,
)


def test_umbreon_pursuit_darkness() -> None:
    fixed = correct_attacks(
        "neo2-32",
        [{"name": "Pursuit", "cost": ["Metal", "Colorless", "Colorless"], "damage": 30}],
    )
    assert fixed[0]["cost"] == ["Darkness", "Colorless", "Colorless"]


def test_hoppip_sleep_powder_merge() -> None:
    fixed = correct_attacks(
        "ecard1-112",
        [
            {
                "name": "Sleep Powder",
                "cost": ["Water", "Colorless", "Colorless"],
                "damage": "20x",
                "effect": "Flip a coin. If heads, the Defending Pokémon is now Asleep.",
            },
            {"cost": ["Grass"], "damage": 10},
        ],
    )
    assert len(fixed) == 1
    assert fixed[0]["name"] == "Sleep Powder"
    assert fixed[0]["cost"] == ["Grass"]
    assert fixed[0]["damage"] == 10


def test_type_corrections() -> None:
    assert correct_types("ex11-44", ["Fire"]) == ["Fighting"]
    assert correct_types("ex11-82", ["Water"]) == ["Fighting"]
    assert correct_types("ecard3-H19", ["Lightning"]) == ["Metal"]


def test_yanmega_pursue_colorless() -> None:
    fixed = correct_attacks(
        "dp6-17",
        [
            {
                "name": "Pursue and Turn",
                "cost": ["Grass", "Grass", "Metal", "Metal"],
                "damage": "60+",
            }
        ],
    )
    assert fixed[0]["cost"] == ["Grass", "Grass", "Colorless", "Colorless"]


def test_flavor_text_not_multicolor() -> None:
    assert not compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Lightning"],
            "attacks": [{"name": "Electric Ball", "cost": ["Lightning", "Colorless"]}],
            "description": (
                "It focuses psychic energy into its tail and rides it like it's surfing."
            ),
        }
    )
    assert not compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Water"],
            "attacks": [{"name": "Wave Splash", "cost": ["Water", "Colorless"]}],
            "description": "It fires the psychic energy from its mouth.",
        }
    )


def test_attack_effect_energy_still_multicolor() -> None:
    assert compute_is_multicolor(
        {
            "category": "Pokemon",
            "types": ["Water"],
            "attacks": [
                {
                    "name": "Burning Icicles",
                    "cost": ["Water", "Colorless"],
                    "effect": "If this Pokémon has any Fire Energy attached to it, …",
                }
            ],
            "description": "A legendary Pokémon.",
        }
    )


def test_apply_includes_types() -> None:
    card = apply_card_corrections(
        {"id": "ex10-44", "category": "Pokemon", "types": ["Fire"], "attacks": []}
    )
    assert card["types"] == ["Fighting"]
