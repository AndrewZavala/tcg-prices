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

# card_id → attack name → field → corrected value
ATTACK_FIELD_BY_NAME: dict[str, dict[str, dict[str, Any]]] = {
    # Base Set 2 uses later template wording; functionally identical to Base Set.
    "base4-2": {
        "Hydro Pump": {
            "effect": (
                "Does 40 damage plus 10 more damage for each attached Water Energy "
                "attached to Blastoise but not used to pay for this attack's Energy cost. "
                "Extra Water Energy after the 2nd doesn't count."
            ),
        },
    },
}

# card_id → corrected stage (when source omits Basic on Pokémon-EX / TAG TEAM reprints)
STAGE_BY_ID: dict[str, str] = {
    # XY Venusaur-EX promos omit stage; set printings are Basic.
    "xyp-XY28": "Basic",
    "xyp-XY123": "Basic",
    # Cosmic Eclipse Venusaur & Snivy-GX — only the secret art has stage filled.
    "sm12-1": "Basic",
    "sm12-210": "Basic",
    "smp-SM229": "Basic",
}

# Drop attack rows that have a cost but no name (TCGdex stubs).
DROP_NAMELESS_ATTACKS: frozenset[str] = frozenset({"sm12-210"})


def _patch_named_rows(
    rows: list[Any] | None,
    fixes: dict[str, Any],
    *,
    field_map: bool = False,
) -> list[Any]:
    """Apply name-keyed fixes to ability/attack dict rows."""
    if not fixes or not rows:
        return list(rows or [])

    out: list[Any] = []
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        name = str(row.get("name") or "")
        want = fixes.get(name)
        if not want:
            out.append(row)
            continue
        if field_map:
            # want is {field: value}
            patched = None
            for field, value in want.items():
                if row.get(field) != value:
                    if patched is None:
                        patched = copy.deepcopy(row)
                    patched[field] = value
                    changed = True
            out.append(patched if patched is not None else row)
        else:
            # want is a single type string (abilities)
            if row.get("type") != want:
                patched = copy.deepcopy(row)
                patched["type"] = want
                out.append(patched)
                changed = True
            else:
                out.append(row)
    return out if changed else list(rows)


def correct_abilities(card_id: str, abilities: list[Any] | None) -> list[Any]:
    """Return abilities with card-specific type fixes applied."""
    return _patch_named_rows(abilities, ABILITY_TYPE_BY_NAME.get(card_id) or {})


def correct_attacks(card_id: str, attacks: list[Any] | None) -> list[Any]:
    """Return attacks with card-specific field fixes applied."""
    rows = _patch_named_rows(
        attacks,
        ATTACK_FIELD_BY_NAME.get(card_id) or {},
        field_map=True,
    )
    if card_id in DROP_NAMELESS_ATTACKS:
        filtered = [
            row
            for row in rows
            if not isinstance(row, dict) or str(row.get("name") or "").strip()
        ]
        if len(filtered) != len(rows):
            return filtered
    return rows


def apply_card_corrections(card: dict[str, Any]) -> dict[str, Any]:
    """Mutate and return a card dict with known corrections applied."""
    card_id = str(card.get("id") or "")
    if not card_id:
        return card

    if "abilities" in card:
        card["abilities"] = correct_abilities(card_id, card.get("abilities"))
    if "attacks" in card:
        card["attacks"] = correct_attacks(card_id, card.get("attacks"))

    stage_fix = STAGE_BY_ID.get(card_id)
    if stage_fix and not (card.get("stage") or "").strip():
        card["stage"] = stage_fix

    data = card.get("card_data")
    if isinstance(data, dict):
        if "abilities" in data:
            data["abilities"] = correct_abilities(card_id, data.get("abilities"))
        if "attacks" in data:
            data["attacks"] = correct_attacks(card_id, data.get("attacks"))
        if stage_fix and not (data.get("stage") or "").strip():
            data["stage"] = stage_fix
    return card
