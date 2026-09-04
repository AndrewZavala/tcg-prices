"""Per-card source data fixes (TCGdex / upstream mislabels).

Poké-Power ≠ Pokémon Power: only remap within Wizards-era sets where upstream
often mislabels Pokémon Powers as Poké-POWER / Poké-BODY.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Wizards of the Coast era (before Expedition / e-Card). Ability text is
# "Pokémon Power" only — TCGdex often mislabels these as Poké-POWER.
# User list: BS, JU, FO, B2, RO, G1, G2, N1–N4.
# Keep in sync with web/pokemon_api.py PRE_EXPEDITION_POKEMON_POWER_SETS.
PRE_EXPEDITION_POKEMON_POWER_SETS: frozenset[str] = frozenset(
    {
        "base1",  # Base Set (BS)
        "base2",  # Jungle (JU)
        "base3",  # Fossil (FO)
        "base4",  # Base Set 2 (B2)
        "base5",  # Team Rocket (RO)
        "gym1",   # Gym Heroes (G1)
        "gym2",   # Gym Challenge (G2)
        "neo1",   # Neo Genesis (N1)
        "neo2",   # Neo Discovery (N2)
        "neo3",   # Neo Revelation (N3)
        "neo4",   # Neo Destiny (N4)
    }
)

# Backward-compatible alias
WIZARDS_POKEMON_POWER_SETS = PRE_EXPEDITION_POKEMON_POWER_SETS


def _set_id_from_card_id(card_id: str) -> str | None:
    cid = (card_id or "").strip()
    if "-" not in cid:
        return None
    return cid.rsplit("-", 1)[0] or None


def _norm_ability_type_token(label: str) -> str:
    folded = (label or "").replace("é", "e").replace("É", "E").lower()
    return re.sub(r"[^a-z0-9]+", "", folded)


def is_pre_expedition_pokemon_power_set(set_id: str | None) -> bool:
    return bool(set_id) and set_id.strip() in PRE_EXPEDITION_POKEMON_POWER_SETS


def remap_pre_expedition_ability_type(set_id: str | None, type_label: str | None) -> str | None:
    """Poké-Power/Body on pre-Expedition sets → Pokemon Power."""
    if type_label is None:
        return None
    if not is_pre_expedition_pokemon_power_set(set_id):
        return type_label
    token = _norm_ability_type_token(type_label)
    if token in ("pokepower", "pokebody"):
        return "Pokemon Power"
    return type_label


# card_id → ability name → corrected type label (as stored in jsonb)
ABILITY_TYPE_BY_NAME: dict[str, dict[str, str]] = {}

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
    # TCGdex mislabeled Sonicboom as Grass×2 + Colorless×2 / 40; card is Colorless×2 / 20.
    "base5-11": {
        "Sonicboom": {
            "cost": ["Colorless", "Colorless"],
            "damage": 20,
        },
    },
    # Neo Discovery Umbreon — Pursuit cost was Metal; card is Darkness.
    "neo2-32": {
        "Pursuit": {
            "cost": ["Darkness", "Colorless", "Colorless"],
        },
    },
    # Emerald Volbeat — Double-edge cost was Lightning; card is Grass.
    "ex9-42": {
        "Double-edge": {
            "cost": ["Grass", "Colorless"],
        },
    },
    # Delta Species Magnemite — Magnetic Blast cost was Grass; card is Lightning.
    "ex11-74": {
        "Magnetic Blast": {
            "cost": ["Lightning", "Colorless"],
        },
    },
    # Legends Awakened Yanmega — Pursue and Turn was Metal×2; card is Colorless×2.
    "dp6-17": {
        "Pursue and Turn": {
            "cost": ["Grass", "Grass", "Colorless", "Colorless"],
        },
    },
}

# card_id → full attacks array replacement (when rows are merged/split wrongly)
ATTACKS_BY_ID: dict[str, list[dict[str, Any]]] = {
    # Expedition Hoppip — Sleep Powder garbled into Water/20x + nameless Grass/10.
    "ecard1-112": [
        {
            "cost": ["Grass"],
            "name": "Sleep Powder",
            "damage": 10,
            "effect": (
                "Flip a coin. If heads, the Defending Pokémon is now Asleep."
            ),
        },
    ],
}

# card_id → corrected printed types
TYPES_BY_ID: dict[str, list[str]] = {
    "ex10-44": ["Fighting"],  # Quagsire Unseen Forces (was Fire)
    "ex11-44": ["Fighting"],  # Hariyama δ (was Fire)
    "ex11-82": ["Fighting"],  # Sandshrew δ (was Water)
    "ecard3-H19": ["Metal"],  # Skyridge Magneton holo (was Lightning; matches ecard3-20)
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


def correct_abilities(
    card_id: str,
    abilities: list[Any] | None,
    *,
    set_id: str | None = None,
) -> list[Any]:
    """Return abilities with card-specific and pre-Expedition type fixes applied."""
    rows = _patch_named_rows(abilities, ABILITY_TYPE_BY_NAME.get(card_id) or {})
    sid = (set_id or "").strip() or _set_id_from_card_id(card_id)
    if not is_pre_expedition_pokemon_power_set(sid) or not rows:
        return list(rows or [])

    out: list[Any] = []
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        want = remap_pre_expedition_ability_type(sid, str(row.get("type") or "") or None)
        if want and row.get("type") != want:
            patched = copy.deepcopy(row)
            patched["type"] = want
            out.append(patched)
            changed = True
        else:
            out.append(row)
    return out if changed else list(rows)


def correct_attacks(card_id: str, attacks: list[Any] | None) -> list[Any]:
    """Return attacks with card-specific field fixes applied."""
    if card_id in ATTACKS_BY_ID:
        return copy.deepcopy(ATTACKS_BY_ID[card_id])
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


def correct_types(card_id: str, types: list[Any] | None) -> list[str] | None:
    """Return corrected printed types when known, else unchanged list (or None)."""
    fixed = TYPES_BY_ID.get(card_id)
    if fixed is not None:
        return list(fixed)
    if types is None:
        return None
    return [str(t) for t in types if t]


def correct_category(card: dict[str, Any]) -> str:
    """Fix Pokémon mislabeled Trainer when hp/stage/types/dex are present."""
    category = str(card.get("category") or "Unknown")
    if category == "Pokemon":
        return category
    hp = card.get("hp")
    if hp is None or (isinstance(hp, (int, float)) and hp <= 0):
        return category
    stage = str(card.get("stage") or "").strip()
    types = card.get("types") or []
    dex = card.get("dexId") or card.get("dex_ids") or []
    if stage or types or dex:
        return "Pokemon"
    return category


# Colored energies for is:multicolor (Colorless handled specially).
MULTICOLOR_ENERGY_TYPES: tuple[tuple[str, str], ...] = (
    ("Grass", "G"),
    ("Fire", "R"),
    ("Water", "W"),
    ("Lightning", "L"),
    ("Psychic", "P"),
    ("Fighting", "F"),
    ("Darkness", "D"),
    ("Metal", "M"),
    ("Fairy", "Y"),
    ("Dragon", "N"),
)


def _multicolor_rules_text(card: dict[str, Any]) -> str:
    """Attack/ability effects only — not Pokédex flavor (description)."""
    parts: list[str] = []
    data = card.get("card_data")
    if isinstance(data, dict):
        parts.append(str(data.get("effect") or ""))
    for key in ("attacks", "abilities"):
        rows = card.get(key) or []
        if isinstance(rows, str):
            parts.append(rows)
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                parts.append(str(row.get("effect") or ""))
            else:
                parts.append(str(row))
    return " ".join(parts)


def compute_is_multicolor(card: dict[str, Any]) -> bool:
    """True when a Pokémon shows 2+ energy colors (type, attack cost, energy-in-text).

    Colorless is ignored unless the card's printed type includes Colorless.
    """
    if str(card.get("category") or "") != "Pokemon":
        # After correct_category, ingest may pass pre-correct category; still
        # compute from fields when it looks like a Pokémon.
        if str(correct_category(card)) != "Pokemon":
            return False

    types = [str(t) for t in (card.get("types") or []) if t]
    colors: set[str] = set(types)
    colorless_type = "Colorless" in colors

    for atk in card.get("attacks") or []:
        if not isinstance(atk, dict):
            continue
        for cost in atk.get("cost") or []:
            c = str(cost or "")
            if not c:
                continue
            if c == "Colorless":
                if colorless_type:
                    colors.add(c)
            else:
                colors.add(c)

    if len(colors) >= 2:
        return True

    text = _multicolor_rules_text(card)
    if not text.strip():
        return False
    text_lower = text.lower()
    for name, letter in MULTICOLOR_ENERGY_TYPES:
        if name in colors:
            continue
        if (
            f"{name.lower()} energy" in text_lower
            or f"{{{letter}}}" in text
            or f"{{{letter.lower()}}}" in text_lower
            or f"{{{name}}}" in text
            or f"{{{name.lower()}}}" in text_lower
        ):
            colors.add(name)
            if len(colors) >= 2:
                return True
    return len(colors) >= 2


def apply_card_corrections(card: dict[str, Any]) -> dict[str, Any]:
    """Mutate and return a card dict with known corrections applied."""
    card_id = str(card.get("id") or "")
    if not card_id:
        return card

    if "category" in card:
        card["category"] = correct_category(card)

    if "types" in card or card_id in TYPES_BY_ID:
        fixed_types = correct_types(card_id, card.get("types"))
        if fixed_types is not None:
            card["types"] = fixed_types

    if "abilities" in card:
        set_id = card.get("set_id")
        if not set_id and isinstance(card.get("set"), dict):
            set_id = card["set"].get("id")
        card["abilities"] = correct_abilities(
            card_id, card.get("abilities"), set_id=set_id if isinstance(set_id, str) else None
        )
    if "attacks" in card or card_id in ATTACKS_BY_ID:
        card["attacks"] = correct_attacks(card_id, card.get("attacks"))

    stage_fix = STAGE_BY_ID.get(card_id)
    if stage_fix and not (card.get("stage") or "").strip():
        card["stage"] = stage_fix

    data = card.get("card_data")
    if isinstance(data, dict):
        if "category" in data:
            data["category"] = correct_category({**card, **data})
        if "types" in data or card_id in TYPES_BY_ID:
            fixed_types = correct_types(card_id, data.get("types") or card.get("types"))
            if fixed_types is not None:
                data["types"] = fixed_types
        if "abilities" in data:
            set_id = card.get("set_id")
            if not set_id and isinstance(card.get("set"), dict):
                set_id = card["set"].get("id")
            data["abilities"] = correct_abilities(
                card_id,
                data.get("abilities"),
                set_id=set_id if isinstance(set_id, str) else None,
            )
        if "attacks" in data or card_id in ATTACKS_BY_ID:
            data["attacks"] = correct_attacks(card_id, data.get("attacks"))
        if stage_fix and not (data.get("stage") or "").strip():
            data["stage"] = stage_fix
    return card
