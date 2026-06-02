"""Normalize Card Kingdom set/edition strings to Scryfall set names."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import CK_SET_ALIASES, SCRYFALL_SET_LOOKUP

UNIVERSES_BEYOND_PREFIX = re.compile(r"^Universes Beyond:\s*", re.I)

# After stripping UB prefix, map product name to Scryfall set name.
UB_OVERRIDES: dict[str, str] = {
    "Warhammer 40,000": "Warhammer 40,000 Commander",
}


def _squish_set(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    s = s.str.replace(r"[\r\n]+", " ", regex=True)
    s = s.str.replace(r"\s+FOIL\b", "", regex=True, case=False)
    s = s.str.replace(r" FOIL$", "", regex=True, case=False)
    s = s.str.replace(r" \([A-Z]+\)$", "", regex=True)
    s = s.str.replace(r" JPN Planeswalkers$", "", regex=True)
    s = s.str.replace(r" Variants$", "", regex=True)
    s = s.str.replace(r" Commander Decks$", " Commander", regex=True)
    return s.str.strip()


def _apply_ub_rules(name: str) -> str:
    name = UNIVERSES_BEYOND_PREFIX.sub("", name).strip()
    return UB_OVERRIDES.get(name, name)


def _commander_candidates(clean: str) -> list[str]:
    if not clean.endswith(" Commander"):
        return []
    out = [clean]
    if clean.startswith("Adventures in the "):
        out.append(clean.removeprefix("Adventures in the ").strip())
    if ": " in clean:
        out.append(clean.split(": ", 1)[1].strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def load_alias_map() -> dict[str, str]:
    if not CK_SET_ALIASES.exists():
        return {}
    aliases = pd.read_csv(CK_SET_ALIASES)
    mapping: dict[str, str] = {}
    for _, row in aliases.iterrows():
        ck = str(row["ck_name"]).strip()
        sf = row.get("scryfall_set_name")
        if pd.isna(sf) or not str(sf).strip():
            continue
        mapping[ck] = str(sf).strip()
    return mapping


def base_clean_set(series: pd.Series) -> pd.Series:
    s = _squish_set(series)
    s = s.map(_apply_ub_rules)
    return s


def resolve_scryfall_set_name(clean: str, alias_map: dict[str, str]) -> str | None:
    if not clean or clean.lower() in ("nan", "none"):
        return None

    if clean in alias_map:
        return alias_map[clean]

    if clean == "Mystery Booster/The List":
        return "The List"

    ub = _apply_ub_rules(clean)
    if ub != clean and ub in alias_map:
        return alias_map[ub]
    if ub != clean:
        clean = ub

    for candidate in _commander_candidates(clean):
        if candidate in alias_map:
            return alias_map[candidate]

    return clean


def attach_set_codes(
    df: pd.DataFrame,
    sets_lookup: pd.DataFrame,
    alias_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Add clean_set and set_code columns."""
    alias_map = alias_map or load_alias_map()
    name_to_code = {
        str(row["name"]).strip(): str(row["code"]).strip().lower()
        for _, row in sets_lookup.iterrows()
    }

    out = df.copy()
    out["clean_set"] = base_clean_set(out["set"])

    scryfall_names: list[str | None] = []
    set_codes: list[str | None] = []

    for clean in out["clean_set"]:
        resolved = resolve_scryfall_set_name(clean, alias_map)
        code = None
        if resolved:
            code = name_to_code.get(resolved)
            if not code:
                for candidate in _commander_candidates(resolved):
                    code = name_to_code.get(candidate)
                    if code:
                        resolved = candidate
                        break
                if not code and resolved == clean:
                    code = name_to_code.get(clean)
        scryfall_names.append(resolved)
        set_codes.append(code)

    out["scryfall_set_name"] = scryfall_names
    out["set_code"] = set_codes
    return out


def load_sets_lookup() -> pd.DataFrame:
    return pd.read_csv(SCRYFALL_SET_LOOKUP)
