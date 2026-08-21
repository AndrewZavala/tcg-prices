"""Per-card source data fixes (TCGdex / upstream mislabels).

Keep these narrow — do not normalize era terms globally (Poké-Power ≠ Pokémon Power).
"""

from __future__ import annotations

import copy
from typing import Any

# card_id → ability name → corrected type label (as stored in jsonb)
ABILITY_TYPE_BY_NAME: dict[str, dict[str, str]] = {
    # Base Set 2 Blastoise — Rain Dance is a Pokémon Power (same as Base Set),
    # but some sources mislabel it as Poké-Power.
    "base4-2": {"Rain Dance": "Pokemon Power"},
}


def correct_abilities(card_id: str, abilities: list[Any] | None) -> list[Any]:
    """Return abilities with card-specific type fixes applied (copy when changed)."""
    fixes = ABILITY_TYPE_BY_NAME.get(card_id)
    if not fixes or not abilities:
        return list(abilities or [])

    out: list[Any] = []
    changed = False
    for ab in abilities:
        if not isinstance(ab, dict):
            out.append(ab)
            continue
        name = str(ab.get("name") or "")
        want = fixes.get(name)
        if want and ab.get("type") != want:
            row = copy.deepcopy(ab)
            row["type"] = want
            out.append(row)
            changed = True
        else:
            out.append(ab)
    return out if changed else list(abilities)


def apply_card_corrections(card: dict[str, Any]) -> dict[str, Any]:
    """Mutate and return a card dict with known corrections applied."""
    card_id = str(card.get("id") or "")
    if not card_id:
        return card
    if "abilities" in card:
        card["abilities"] = correct_abilities(card_id, card.get("abilities"))
    data = card.get("card_data")
    if isinstance(data, dict) and "abilities" in data:
        data["abilities"] = correct_abilities(card_id, data.get("abilities"))
    return card
