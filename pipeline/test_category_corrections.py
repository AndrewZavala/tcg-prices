"""Tests for Pokémon mislabeled as Trainer/Energy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from pokemon_card_corrections import apply_card_corrections, correct_category  # noqa: E402


def test_glameow_trainer_becomes_pokemon() -> None:
    """Majestic Dawn Glameow was stored as Trainer despite Pokemon fields."""
    card = {
        "id": "dp5-65",
        "category": "Trainer",
        "hp": 60,
        "stage": "Basic",
        "types": ["Colorless"],
        "dexId": [431],
    }
    assert correct_category(card) == "Pokemon"
    assert apply_card_corrections(card)["category"] == "Pokemon"


def test_fossil_trainer_with_hp_stays_trainer() -> None:
    """Old Amber / fossils have HP but no stage/types/dex — remain Trainer."""
    card = {
        "id": "dp5-84",
        "category": "Trainer",
        "hp": 50,
        "stage": None,
        "types": [],
        "dexId": [],
    }
    assert correct_category(card) == "Trainer"


def test_trainer_without_hp_unchanged() -> None:
    card = {
        "id": "swshp-SWSH146",
        "category": "Trainer",
        "hp": None,
        "types": ["Lightning"],
    }
    assert correct_category(card) == "Trainer"


def test_already_pokemon_unchanged() -> None:
    card = {
        "id": "swsh1-123",
        "category": "Pokemon",
        "hp": 70,
        "stage": "Basic",
        "types": ["Darkness"],
    }
    assert correct_category(card) == "Pokemon"
