"""Tests for same-name Trainer/Energy oracle merging."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from build_pokemon_oracle import (  # noqa: E402
    merge_non_pokemon_name_fingerprints,
    oracle_fingerprint,
)


def _energy(card_id: str, energy_type: str, effect: str | None = None,
            name: str = "Darkness Energy") -> dict:
    card = {
        "id": card_id,
        "name": name,
        "category": "Energy",
        "card_data": {"energyType": energy_type, "effect": effect},
    }
    card["_oracle_fingerprint"] = oracle_fingerprint(card)
    return card


def test_special_darkness_energy_not_merged_with_basic() -> None:
    cards = [
        _energy("sv1-1", "Normal"),
        _energy("xy1-138", "Normal"),
        _energy("ex1-93", "Special", "If the Pokémon Darkness Energy is attached to attacks..."),
        _energy("dp5-93", "Special", "If the Pokemon Darkness Energy is attached to attacks, ..."),
    ]
    merge_non_pokemon_name_fingerprints(cards)
    basic = {c["_oracle_fingerprint"] for c in cards if c["card_data"]["energyType"] == "Normal"}
    special = {c["_oracle_fingerprint"] for c in cards if c["card_data"]["energyType"] == "Special"}
    assert len(basic) == 1
    assert len(special) == 1
    assert basic != special


def test_mislabeled_special_energy_reprint_still_merges() -> None:
    cards = [
        _energy("bw4-93", "Special", "This card provides Colorless Energy.", name="Prism Energy"),
        _energy("me02-1", "Normal", "As long as this card is attached...", name="Prism Energy"),
    ]
    merge_non_pokemon_name_fingerprints(cards)
    assert cards[0]["_oracle_fingerprint"] == cards[1]["_oracle_fingerprint"]


def test_same_name_trainers_still_merge() -> None:
    cards = []
    for cid, effect in (("a", "Search your deck for a Basic Pokémon."), ("b", "Totally different wording.")):
        card = {"id": cid, "name": "Nest Ball", "category": "Trainer", "card_data": {"effect": effect}}
        card["_oracle_fingerprint"] = oracle_fingerprint(card)
        cards.append(card)
    assert cards[0]["_oracle_fingerprint"] != cards[1]["_oracle_fingerprint"]
    merge_non_pokemon_name_fingerprints(cards)
    assert cards[0]["_oracle_fingerprint"] == cards[1]["_oracle_fingerprint"]
