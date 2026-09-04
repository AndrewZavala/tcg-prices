"""Pokémon TCG catalog API — demo search with Scryfall-style unique rollups."""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text

META_CACHE_CONTROL = "public, max-age=3600"

from tcgplayer_links import pokemon_buy_url
from pokemon_type_sort_sql import SEARCH_SPECIES_JOINS, build_card_type_sort_sql

router = APIRouter(tags=["pokemon"])

# Fold Latin accents for name search (Pokémon ↔ Pokemon, Flabébé ↔ Flabebe, …).
# Must stay 1:1 for PostgreSQL translate(); keep in sync with fold_accents().
_ACCENT_FROM = (
    "àáâãäåāăąèéêëēĕėęěìíîïīĭįıòóôõöøōŏőùúûüūŭůűųýÿñç"
)
_ACCENT_TO = "aaaaaaaaaeeeeeeeeeeiiiiiiiiiooooooooouuuuuuuuuuyync"


def fold_accents(text: str) -> str:
    """Strip combining marks so accented and plain spellings match."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _sql_accent_fold(expr: str) -> str:
    """SQL expression: lower + latin accent fold (mirrors fold_accents for TCG names)."""
    return f"translate(lower({expr}), '{_ACCENT_FROM}', '{_ACCENT_TO}')"

_TCG_NAME_SUFFIX_RE = re.compile(
    r"""
    \s+
    (?:
        ex|v|vmax|vstar|gx|break|prime|legend|lv\.?x|
        \u03b4|  # δ
        radiant
    )
    $
    """,
    re.I | re.VERBOSE,
)
_REGIONAL_PREFIX_RE = re.compile(
    r"^(Alolan|Galarian|Hisuian|Paldean)\s+",
    re.I,
)


def limitless_collector_number(local_id: str | None) -> str | None:
    """Limitless uses unpadded collector numbers (82 not 082)."""
    raw = (local_id or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return str(int(raw))
    return raw


def limitless_card_url(*, set_code: str | None, local_id: str | None) -> str | None:
    """Card stats page on Limitless, e.g. https://limitlesstcg.com/cards/PAL/189."""
    code = (set_code or "").strip().upper()
    number = limitless_collector_number(local_id)
    if not code or not number:
        return None
    return f"https://limitlesstcg.com/cards/{code}/{number}"


# Kept for possible future deck-search links (name query).
def limitless_decks_url(query: str | None) -> str | None:
    """Limitless deck search for a species / card name."""
    q = (query or "").strip()
    if not q:
        return None
    return f"https://limitlesstcg.com/decks?{urlencode({'q': q})}"


def limitless_query_for_card(
    *,
    name: str | None,
    species_name: str | None,
    is_regional: bool,
    category: str | None,
) -> str | None:
    """Prefer species for Pokémon; keep regional form prefix from the card name."""
    raw_name = (name or "").strip()
    cleaned = _TCG_NAME_SUFFIX_RE.sub("", raw_name).strip() or raw_name

    if (category or "").lower() == "pokemon":
        if is_regional and cleaned:
            return cleaned
        if species_name and str(species_name).strip():
            return str(species_name).strip()
        if cleaned:
            return _REGIONAL_PREFIX_RE.sub("", cleaned).strip() or cleaned
        return None

    return cleaned or None

_engine = None

UniqueMode = Literal["pokemon", "cards", "prints", "art"]

# Species-group tokens for is: (regional is card-name based).
SPECIES_GROUP_ALIASES: dict[str, str] = {
    "baby": "baby",
    "starter": "starter",
    "fossil": "fossil",
    "pseudo": "pseudo-legendary",
    "pseudo-legendary": "pseudo-legendary",
    "ultrabeast": "ultra-beast",
    "ultra-beast": "ultra-beast",
    "ub": "ultra-beast",
    "paradox": "paradox",
    "eevee": "eeveelution",
    "eeveelution": "eeveelution",
    "regional": "regional",
}

SPECIES_GROUP_LABELS: dict[str, str] = {
    "baby": "Baby",
    "starter": "Starter",
    "fossil": "Fossil",
    "pseudo-legendary": "Pseudo-Legendary",
    "ultra-beast": "Ultra Beast",
    "paradox": "Paradox",
    "eeveelution": "Eeveelution",
    "regional": "Regional form",
}

REGIONAL_NAME_SQL = (
    "c.name ~* '(^|[[:space:]])(Alolan|Galarian|Hisuian|Paldean)[[:space:]]'"
)

# Pokémon energy colors for c: / color: (letters match cost-symbol abbreviations).
COLOR_NAMES: dict[str, str] = {
    "grass": "Grass",
    "g": "Grass",
    "fire": "Fire",
    "r": "Fire",
    "water": "Water",
    "w": "Water",
    "lightning": "Lightning",
    "l": "Lightning",
    "psychic": "Psychic",
    "p": "Psychic",
    "fighting": "Fighting",
    "f": "Fighting",
    "darkness": "Darkness",
    "dark": "Darkness",
    "d": "Darkness",
    "metal": "Metal",
    "m": "Metal",
    "fairy": "Fairy",
    "y": "Fairy",
    "dragon": "Dragon",
    "n": "Dragon",
    "colorless": "Colorless",
    "c": "Colorless",
}


def normalize_color_name(raw: str | None) -> str | None:
    """Map c:r / Fire / fire → canonical type string, or None if unknown."""
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return COLOR_NAMES.get(key) or (raw.strip().title() if raw.strip() else None)


def _norm_ability_type_key(label: str) -> str:
    """Collapse ability type labels for matching (Poké-POWER ≈ poke-power)."""
    return re.sub(r"[^a-z0-9]+", "", fold_accents(label or "").lower())


# has: filters — aliases → canonical slug; slug → normalized type keys (empty = any).
ABILITY_HAS_ALIASES: dict[str, str] = {
    "ability-any": "ability-any",
    "ability_any": "ability-any",
    "any-ability": "ability-any",
    "abilityany": "ability-any",
    "ability": "ability",
    "poke-power": "poke-power",
    "pokepower": "poke-power",
    "poke_power": "poke-power",
    "poke-body": "poke-body",
    "pokebody": "poke-body",
    "poke_body": "poke-body",
    "pokemon-power": "pokemon-power",
    "pokemonpower": "pokemon-power",
    "pokemon_power": "pokemon-power",
    # TCGdex: Ancient Trait; Ω prints often say Omega Trait.
    "ancient-trait": "omega-trait",
    "omega-trait": "omega-trait",
    "ancienttrait": "omega-trait",
    "omegatrait": "omega-trait",
    "ancient": "omega-trait",
    "omega": "omega-trait",
}

ABILITY_HAS_NORMS: dict[str, tuple[str, ...]] = {
    "ability-any": (),
    "ability": ("ability",),
    "poke-power": ("pokepower",),
    "poke-body": ("pokebody",),
    "pokemon-power": ("pokemonpower",),
    "omega-trait": ("ancienttrait", "omegatrait"),
}

ABILITY_HAS_FACETS: list[dict[str, str]] = [
    {"id": "ability-any", "name": "Any ability-like"},
    {"id": "ability", "name": "Ability"},
    {"id": "poke-power", "name": "Poké-Power"},
    {"id": "poke-body", "name": "Poké-Body"},
    {"id": "pokemon-power", "name": "Pokémon Power"},
    {"id": "omega-trait", "name": "Omega / Ancient Trait"},
]


def _sql_has_ability_kind(param_key: str) -> str:
    """Match abilities[].type against normalized keys in :param_key (text[])."""
    folded = _sql_accent_fold("COALESCE(elem->>'type', '')")
    return f"""EXISTS (
      SELECT 1
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(c.abilities) = 'array' THEN c.abilities ELSE '[]'::jsonb END
      ) AS elem
      WHERE regexp_replace({folded}, '[^a-z0-9]', '', 'g')
            = ANY(CAST(:{param_key} AS text[]))
    )"""


def _sql_has_any_ability() -> str:
    return (
        "c.abilities IS NOT NULL AND jsonb_typeof(c.abilities) = 'array' "
        "AND jsonb_array_length(c.abilities) > 0"
    )


def _resolve_has_ability_kind(raw: str) -> str | None:
    """Return canonical has-kind slug, or None if unknown."""
    key = (raw or "").strip().lower().replace("_", "-")
    if key in ABILITY_HAS_ALIASES:
        return ABILITY_HAS_ALIASES[key]
    collapsed = re.sub(r"[^a-z0-9]+", "", key)
    return ABILITY_HAS_ALIASES.get(collapsed)


def _apply_has_ability_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    kinds: list[str],
    exclude_kinds: list[str],
) -> None:
    """AND together has:/−has: ability-kind filters."""
    for idx, kind in enumerate(kinds):
        if kind not in ABILITY_HAS_NORMS:
            continue
        norms = ABILITY_HAS_NORMS[kind]
        if not norms:
            filters.append(_sql_has_any_ability())
            continue
        key = f"has_ab_{idx}"
        params[key] = list(norms)
        filters.append(_sql_has_ability_kind(key))
    for idx, kind in enumerate(exclude_kinds):
        if kind not in ABILITY_HAS_NORMS:
            continue
        norms = ABILITY_HAS_NORMS[kind]
        if not norms:
            filters.append(f"NOT ({_sql_has_any_ability()})")
            continue
        key = f"xhas_ab_{idx}"
        params[key] = list(norms)
        filters.append(f"NOT ({_sql_has_ability_kind(key)})")


SORT_SQL = {
    "name": "c.name ASC, s.release_date ASC NULLS LAST, c.local_id",
    # local_id is often "SM142" / "TG01" / "RC1" — never cast the whole string to int
    "set": (
        "s.release_date ASC NULLS LAST, c.set_id, "
        "NULLIF(regexp_replace(c.local_id, '[^0-9]', '', 'g'), '')::int NULLS LAST, "
        "c.local_id ASC NULLS LAST"
    ),
    "dex": "c.dex_ids[1] ASC NULLS LAST, c.name ASC",
    "hp_desc": "c.hp DESC NULLS LAST, c.name ASC",
    # Seeded via :shuffle_seed so pagination stays stable within a shuffle session.
    "shuffle": "md5(c.id || CAST(:shuffle_seed AS text)) ASC, c.id ASC",
}

SORT_SQL["type"] = build_card_type_sort_sql("c", include_category_bucket=True)

SPECIES_SORT_JOINS = SEARCH_SPECIES_JOINS


class PokemonMetaResponse(BaseModel):
    set_count: int
    printing_count: int
    oracle_count: int
    sets: list[dict[str, Any]]
    facets: dict[str, Any]


def init_pokemon_api(engine) -> None:
    global _engine
    _engine = engine


# Fallback when TCGdex left image_url empty — pokemontcg.io CDN paths.
# Keep in sync with pipeline/enrich_pokemon_subtypes.POKEMONTCG_SET_ALIASES.
_POKEMONTCG_SET_ALIASES: dict[str, str] = {
    "me01": "me1",
    "me02": "me2",
    "me02.5": "me2pt5",
    "me03": "me3",
    "me04": "me4",
    "me05": "me5",
    "sv01": "sv1",
    "sv02": "sv2",
    "sv03": "sv3",
    "sv03.5": "sv3pt5",
    "sv04": "sv4",
    "sv04.5": "sv4pt5",
    "sv05": "sv5",
    "sv06": "sv6",
    "sv06.5": "sv6pt5",
    "sv07": "sv7",
    "sv08": "sv8",
    "sv08.5": "sv8pt5",
    "sv09": "sv9",
    "sv10": "sv10",
    "sv10.5b": "zsv10pt5",
    "sv10.5w": "rsv10pt5",
    "sm3.5": "sm35",
    "sm7.5": "sm75",
    "swsh3.5": "swsh35",
    "swsh4.5": "swsh45",
    "swsh4.5sv": "swsh45sv",
    "swsh9.5tg": "swsh9tg",
    "swsh10.5": "pgo",
    "swsh10.5tg": "swsh10tg",
    "swsh11.5tg": "swsh11tg",
    "swsh12.5": "swsh12pt5",
    "swsh12.5tg": "swsh12tg",
    "swsh12.5gg": "swsh12pt5gg",
    "cel25cc": "cel25c",
}


def _pokemontcg_image_fallback(card_id: str | None, local_id: str | None = None) -> str | None:
    """Best-effort CDN URL when TCGdex has no art. May 404 for very new promos."""
    if not card_id or "-" not in card_id:
        return None
    set_part, local = card_id.split("-", 1)
    if local_id:
        local = str(local_id)
    api_set = _POKEMONTCG_SET_ALIASES.get(set_part.lower(), set_part.lower())
    num = local
    if local.isdigit():
        num = str(int(local))
    elif local.upper().startswith("CC") and local[2:].isdigit():
        num = f"{int(local[2:])}_A"
    return f"https://images.pokemontcg.io/{api_set}/{num}_hires.png"


def _remote_image_url(
    base: str | None,
    *,
    card_id: str | None = None,
    local_id: str | None = None,
    size: str = "high",
) -> str | None:
    """Build a remote CDN URL (ingest provenance / mid-backfill fallback)."""
    if base:
        if base.endswith((".webp", ".png", ".jpg", ".jpeg")):
            return base
        suffix = "low.webp" if size == "low" else "high.webp"
        return f"{base}/{suffix}"
    return _pokemontcg_image_fallback(card_id, local_id)


def _local_image_urls(card_id: str) -> tuple[str, str]:
    # grid.webp = ~512px search tile; high.webp = full art for modal.
    return (
        f"/media/cards/{card_id}/grid.webp",
        f"/media/cards/{card_id}/high.webp",
    )


def _image_url(
    base: str | None,
    *,
    card_id: str | None = None,
    local_id: str | None = None,
    image_local: bool = False,
    size: str = "low",
) -> str | None:
    """Public image URL: local /media when mirrored, else remote CDN."""
    if image_local and card_id:
        low, high = _local_image_urls(str(card_id))
        return low if size == "low" else high
    return _remote_image_url(base, card_id=card_id, local_id=local_id, size=size)


def _attach_card_images(row: dict[str, Any], raw: dict[str, Any]) -> None:
    local = bool(raw.get("image_local"))
    card_id = raw.get("id")
    base = raw.get("image_url")
    local_id = raw.get("local_id")
    row["image_local"] = local
    row["image_url"] = _image_url(
        base, card_id=card_id, local_id=local_id, image_local=local, size="low"
    )
    row["image_url_high"] = _image_url(
        base, card_id=card_id, local_id=local_id, image_local=local, size="high"
    )


def _tokenize_search_query(q: str) -> list[str]:
    """Split a search string on whitespace, keeping quoted segments intact."""
    tokens: list[str] = []
    i = 0
    n = len(q)
    while i < n:
        while i < n and q[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n:
            if q[i] == '"':
                i += 1
                while i < n and q[i] != '"':
                    if q[i] == "\\" and i + 1 < n:
                        i += 2
                    else:
                        i += 1
                if i < n:
                    i += 1
            elif q[i].isspace():
                break
            else:
                i += 1
        tokens.append(q[start:i])
    return tokens


def _parse_oracle_text_value(raw: str) -> dict[str, str] | None:
    """Parse o: value — word, quoted phrase, /regex/, or {L}-style energy symbol."""
    val = raw.strip()
    if not val:
        return None
    if val.startswith("/") and val.count("/") >= 2:
        end = val.rfind("/")
        if end > 0:
            pattern = val[1:end]
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                return None
            return {"mode": "regex", "pattern": pattern}
    if val.startswith('"') and val.endswith('"') and len(val) >= 2:
        inner = val[1:-1].replace('\\"', '"')
        energy = _energy_symbol_regex(inner)
        if energy:
            return {"mode": "regex", "pattern": energy}
        return {"mode": "phrase", "pattern": inner}
    energy = _energy_symbol_regex(val)
    if energy:
        return {"mode": "regex", "pattern": energy}
    return {"mode": "word", "pattern": val}


# Energy symbols in rules text (TCGdex): {L}, {Fire}, etc. — not attack cost / type / W/R.
_ENERGY_SYMBOL_LETTER_TO_NAME: dict[str, str] = {
    "G": "Grass",
    "R": "Fire",
    "W": "Water",
    "L": "Lightning",
    "P": "Psychic",
    "F": "Fighting",
    "D": "Darkness",
    "M": "Metal",
    "Y": "Fairy",
    "N": "Dragon",
    "C": "Colorless",
}
_ENERGY_SYMBOL_NAME_TO_LETTER: dict[str, str] = {
    name.upper(): letter for letter, name in _ENERGY_SYMBOL_LETTER_TO_NAME.items()
}
_ENERGY_SYMBOL_RE = re.compile(r"^\{([A-Za-z]+)\}$")


def _energy_symbol_regex(pattern: str) -> str | None:
    """If pattern is {L} / {Lightning}, return regex matching letter or full-name form."""
    m = _ENERGY_SYMBOL_RE.match((pattern or "").strip())
    if not m:
        return None
    token = m.group(1)
    upper = token.upper()
    if len(token) == 1 and upper in _ENERGY_SYMBOL_LETTER_TO_NAME:
        letter = upper
        name = _ENERGY_SYMBOL_LETTER_TO_NAME[upper]
    elif upper in _ENERGY_SYMBOL_NAME_TO_LETTER:
        letter = _ENERGY_SYMBOL_NAME_TO_LETTER[upper]
        name = _ENERGY_SYMBOL_LETTER_TO_NAME[letter]
    else:
        return None
    return rf"\{{(?:{re.escape(letter)}|{re.escape(name)})\}}"


def _oracle_searchable_text_sql() -> str:
    """Rules text for o: search — effects only (not costs, types, weakness/resistance)."""
    abilities_effects = """COALESCE((
        SELECT string_agg(COALESCE(elem->>'effect', ''), ' ')
        FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(c.abilities) = 'array' THEN c.abilities ELSE '[]'::jsonb END
        ) AS elem
      ), '')"""
    attacks_effects = """COALESCE((
        SELECT string_agg(COALESCE(elem->>'effect', ''), ' ')
        FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(c.attacks) = 'array' THEN c.attacks ELSE '[]'::jsonb END
        ) AS elem
      ), '')"""
    return f"""(
        trim(
          COALESCE(c.description, '') || ' ' ||
          COALESCE(c.card_data->>'effect', '') || ' ' ||
          {abilities_effects} || ' ' ||
          {attacks_effects}
        )
    )"""


def _parse_search_query(
    q: str | None,
) -> dict[str, Any]:
    """Parse pkmncards-style query tokens (t:, is:, set:, e:, has:, etc.).

    Leading ``-`` negates a token (Scryfall-style), e.g. ``t:trainer -t:stadium``.
    """
    result: dict[str, Any] = {
        "name_q": None,
        "tags": [],
        "exclude_tags": [],
        "oracle_text": [],
        "exclude_oracle_text": [],
        "oracle_tags": [],
        "exclude_oracle_tags": [],
        "art_tags": [],
        "exclude_art_tags": [],
        "generation": None,
        "exclude_generation": None,
        "pokemon_special": None,
        "exclude_pokemon_special": None,
        "species_groups": [],
        "exclude_species_groups": [],
        "has_ability_kinds": [],
        "exclude_has_ability_kinds": [],
        "category": None,
        "exclude_categories": [],
        "set_id": None,
        "exclude_set_ids": [],
        "series_id": None,
        "exclude_series_ids": [],
        "rarity": None,
        "exclude_rarities": [],
        "card_type": None,
        "exclude_card_types": [],
        "dex_id": None,
        "exclude_dex_ids": [],
        "stage": None,
        "exclude_stages": [],
        "prizes": [],
        "exclude_prizes": [],
        "weaknesses": [],
        "exclude_weaknesses": [],
        "resistances": [],
        "exclude_resistances": [],
        "retreats": [],
        "exclude_retreats": [],
    }
    if not q or not q.strip():
        return result

    category_aliases = {
        "pokemon": "Pokemon",
        "trainer": "Trainer",
        "energy": "Energy",
    }
    trainer_subtype_aliases = {
        "supporter": "supporter",
        "item": "item",
        "stadium": "stadium",
        "tool": "pokemon-tool",
        "pokemon-tool": "pokemon-tool",
    }
    rarity_aliases = {
        "common": "Common",
        "uncommon": "Uncommon",
        "rare": "Rare",
        "ultra": "Ultra Rare",
        "secret": "Secret Rare",
    }
    stage_aliases = {
        "basic": "Basic",
        "stage1": "Stage1",
        "stage-1": "Stage1",
        "stage2": "Stage2",
        "stage-2": "Stage2",
        "restored": "RESTORED",
    }
    type_names = COLOR_NAMES

    name_parts: list[str] = []
    for token in _tokenize_search_query(q.strip()):
        if ":" not in token:
            if token.startswith('"') and token.endswith('"') and len(token) >= 2:
                name_parts.append(token[1:-1].replace('\\"', '"'))
            else:
                name_parts.append(token)
            continue

        prefix, raw_val = token.split(":", 1)
        prefix = prefix.lower()
        negated = False
        if prefix.startswith("-"):
            negated = True
            prefix = prefix[1:]
        val = raw_val.strip()
        val_lower = val.lower()
        if not val or not prefix:
            continue

        if prefix == "t":
            if val_lower in category_aliases:
                cat = category_aliases[val_lower]
                if negated:
                    result["exclude_categories"].append(cat)
                else:
                    result["category"] = cat
            else:
                tag = trainer_subtype_aliases.get(
                    val_lower, val_lower.replace("_", "-")
                )
                if negated:
                    result["exclude_tags"].append(tag)
                else:
                    result["tags"].append(tag)
        elif prefix == "is":
            if val_lower == "legendary":
                if negated:
                    result["exclude_pokemon_special"] = "legendary"
                else:
                    result["pokemon_special"] = "legendary"
            elif val_lower == "mythical":
                if negated:
                    result["exclude_pokemon_special"] = "mythical"
                else:
                    result["pokemon_special"] = "mythical"
            elif val_lower in ("notable", "legendary-mythical"):
                if negated:
                    result["exclude_pokemon_special"] = "notable"
                else:
                    result["pokemon_special"] = "notable"
            elif val_lower.startswith("gen") and val_lower[3:].isdigit():
                gen = int(val_lower[3:])
                if negated:
                    result["exclude_generation"] = gen
                else:
                    result["generation"] = gen
            elif val_lower in SPECIES_GROUP_ALIASES:
                group = SPECIES_GROUP_ALIASES[val_lower]
                if negated:
                    result["exclude_species_groups"].append(group)
                else:
                    result["species_groups"].append(group)
            else:
                tag = val_lower
                if negated:
                    result["exclude_tags"].append(tag)
                else:
                    result["tags"].append(tag)
        elif prefix == "has":
            kind = _resolve_has_ability_kind(val_lower)
            if kind:
                if negated:
                    result["exclude_has_ability_kinds"].append(kind)
                else:
                    result["has_ability_kinds"].append(kind)
            else:
                name_parts.append(token)
        elif prefix == "set":
            if negated:
                result["exclude_set_ids"].append(val_lower)
            else:
                result["set_id"] = val_lower
        elif prefix in ("s", "series"):
            if negated:
                result["exclude_series_ids"].append(val_lower)
            else:
                result["series_id"] = val_lower
        elif prefix == "r":
            rarity = rarity_aliases.get(val_lower, val)
            if negated:
                result["exclude_rarities"].append(rarity)
            else:
                result["rarity"] = rarity
        elif prefix in ("c", "color"):
            # Pokémon energy color (Magic-style c:r). Letters: g r w l p f d m y n c
            ctype = type_names.get(val_lower)
            if ctype:
                if negated:
                    result["exclude_card_types"].append(ctype)
                else:
                    result["card_type"] = ctype
        elif prefix == "dex":
            if val.isdigit():
                dex = int(val)
                if negated:
                    result["exclude_dex_ids"].append(dex)
                else:
                    result["dex_id"] = dex
        elif prefix == "stage":
            stage = stage_aliases.get(val_lower, val)
            if negated:
                result["exclude_stages"].append(stage)
            else:
                result["stage"] = stage
        elif prefix == "otag":
            slug = val_lower.replace("_", "-")
            if slug:
                if negated:
                    result["exclude_oracle_tags"].append(slug)
                else:
                    result["oracle_tags"].append(slug)
        elif prefix == "art":
            slug = val_lower.replace("_", "-")
            if slug:
                if negated:
                    result["exclude_art_tags"].append(slug)
                else:
                    result["art_tags"].append(slug)
        elif prefix == "prize":
            if val_lower in ("1", "2", "3"):
                n = int(val_lower)
                if negated:
                    result["exclude_prizes"].append(n)
                else:
                    result["prizes"].append(n)
        elif prefix in ("weakness", "weak"):
            wtype = type_names.get(val_lower)
            if wtype:
                if negated:
                    result["exclude_weaknesses"].append(wtype)
                else:
                    result["weaknesses"].append(wtype)
        elif prefix in ("resistance", "resist", "res"):
            rtype = type_names.get(val_lower)
            if rtype:
                if negated:
                    result["exclude_resistances"].append(rtype)
                else:
                    result["resistances"].append(rtype)
        elif prefix == "retreat":
            if val_lower.isdigit():
                n = int(val_lower)
                if negated:
                    result["exclude_retreats"].append(n)
                else:
                    result["retreats"].append(n)
        elif prefix == "o":
            spec = _parse_oracle_text_value(val)
            if spec:
                if negated:
                    result["exclude_oracle_text"].append(spec)
                else:
                    result["oracle_text"].append(spec)
        else:
            name_parts.append(token)

    result["name_q"] = " ".join(name_parts).strip() or None
    for key in (
        "tags",
        "exclude_tags",
        "oracle_tags",
        "exclude_oracle_tags",
        "art_tags",
        "exclude_art_tags",
        "species_groups",
        "exclude_species_groups",
        "exclude_categories",
        "exclude_set_ids",
        "exclude_series_ids",
        "exclude_rarities",
        "exclude_card_types",
        "exclude_dex_ids",
        "exclude_stages",
        "prizes",
        "exclude_prizes",
        "weaknesses",
        "exclude_weaknesses",
        "resistances",
        "exclude_resistances",
        "retreats",
        "exclude_retreats",
        "has_ability_kinds",
        "exclude_has_ability_kinds",
    ):
        result[key] = list(dict.fromkeys(result[key]))
    return result


# Prize cards taken when Knocked Out — derived from subtypes (not a stored column).
# Radiant Pokémon are 1 prize. Modern Mega Pokémon ex (Mega Evolution block me*) are 3.
PRIZE_3_TAGS = ("tag-team", "v-union")
PRIZE_2_TAGS = ("ex", "gx", "v", "vmax", "vstar", "break", "legend")


def _sql_prize_three() -> str:
    """TAG TEAM / V-UNION, or Mega Pokémon ex from the Mega Evolution block onward."""
    return """(
      c.category = 'Pokemon'
      AND (
        COALESCE(c.tags, ARRAY[]::text[]) && CAST(:prize_3_tags AS text[])
        OR (
          'ex' = ANY(COALESCE(c.tags, ARRAY[]::text[]))
          AND (
            'mega' = ANY(COALESCE(c.tags, ARRAY[]::text[]))
            OR c.name ILIKE 'Mega %'
          )
          AND (s.series_id LIKE 'me%' OR c.set_id LIKE 'me%')
        )
      )
    )"""


def _sql_prize_two() -> str:
    """Rule-box 2-prize Pokémon (ex/V/GX/…), excluding 3-prize cards. Radiant is not included."""
    return f"""(
      c.category = 'Pokemon'
      AND NOT {_sql_prize_three()}
      AND COALESCE(c.tags, ARRAY[]::text[]) && CAST(:prize_2_tags AS text[])
    )"""


def _sql_prize_one() -> str:
    """Pokémon that give 1 prize (including Radiant; excluding 2-/3-prize subtypes)."""
    return f"""(
      c.category = 'Pokemon'
      AND NOT {_sql_prize_three()}
      AND NOT (
        COALESCE(c.tags, ARRAY[]::text[]) && CAST(:prize_2_tags AS text[])
      )
    )"""


def _sql_prize_count(n: int) -> str:
    if n == 1:
        return _sql_prize_one()
    if n == 2:
        return _sql_prize_two()
    if n == 3:
        return _sql_prize_three()
    raise ValueError(f"unsupported prize count: {n}")


def _apply_oracle_text_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    oracle_text: list[dict[str, str]],
    exclude_oracle_text: list[dict[str, str]],
) -> None:
    text_sql = _oracle_searchable_text_sql()
    for idx, spec in enumerate(oracle_text):
        key = f"otext_{idx}"
        mode = spec["mode"]
        pattern = spec["pattern"]
        if mode == "regex":
            params[key] = pattern
            filters.append(f"{text_sql} ~* CAST(:{key} AS text)")
        elif mode == "phrase":
            params[key] = f"%{pattern}%"
            filters.append(f"{text_sql} ILIKE :{key}")
        else:
            params[key] = rf"\y{re.escape(pattern)}\y"
            filters.append(f"{text_sql} ~* CAST(:{key} AS text)")
    for idx, spec in enumerate(exclude_oracle_text):
        key = f"xotext_{idx}"
        mode = spec["mode"]
        pattern = spec["pattern"]
        if mode == "regex":
            params[key] = pattern
            filters.append(f"NOT ({text_sql} ~* CAST(:{key} AS text))")
        elif mode == "phrase":
            params[key] = f"%{pattern}%"
            filters.append(f"NOT ({text_sql} ILIKE :{key})")
        else:
            params[key] = rf"\y{re.escape(pattern)}\y"
            filters.append(f"NOT ({text_sql} ~* CAST(:{key} AS text))")


def _apply_prize_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    prizes: list[int],
    exclude_prizes: list[int],
) -> None:
    if not prizes and not exclude_prizes:
        return
    params["prize_2_tags"] = list(PRIZE_2_TAGS)
    params["prize_3_tags"] = list(PRIZE_3_TAGS)
    if prizes:
        filters.append("(" + " OR ".join(_sql_prize_count(n) for n in prizes) + ")")
    for n in exclude_prizes:
        filters.append(f"NOT {_sql_prize_count(n)}")


def _sql_jsonb_has_type(column: str, param_key: str) -> str:
    """Match a type string inside weaknesses/resistances JSONB array of {type, value}."""
    return f"""EXISTS (
      SELECT 1
      FROM jsonb_array_elements(COALESCE(c.{column}, '[]'::jsonb)) AS elem
      WHERE elem->>'type' = :{param_key}
    )"""


def _apply_weak_res_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    weaknesses: list[str],
    exclude_weaknesses: list[str],
    resistances: list[str],
    exclude_resistances: list[str],
) -> None:
    for idx, wtype in enumerate(weaknesses):
        key = f"weak_{idx}"
        filters.append(_sql_jsonb_has_type("weaknesses", key))
        params[key] = wtype
    for idx, wtype in enumerate(exclude_weaknesses):
        key = f"xweak_{idx}"
        filters.append(f"NOT {_sql_jsonb_has_type('weaknesses', key)}")
        params[key] = wtype
    for idx, rtype in enumerate(resistances):
        key = f"resist_{idx}"
        filters.append(_sql_jsonb_has_type("resistances", key))
        params[key] = rtype
    for idx, rtype in enumerate(exclude_resistances):
        key = f"xresist_{idx}"
        filters.append(f"NOT {_sql_jsonb_has_type('resistances', key)}")
        params[key] = rtype


def _sql_retreat_eq(param_key: str) -> str:
    """Retreat cost match — NULL treated as 0; Pokémon only."""
    return f"(c.category = 'Pokemon' AND COALESCE(c.retreat, 0) = :{param_key})"


def _apply_retreat_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    retreats: list[int],
    exclude_retreats: list[int],
) -> None:
    if retreats:
        parts = []
        for idx, n in enumerate(retreats):
            key = f"retreat_{idx}"
            parts.append(_sql_retreat_eq(key))
            params[key] = n
        filters.append("(" + " OR ".join(parts) + ")")
    for idx, n in enumerate(exclude_retreats):
        key = f"xretreat_{idx}"
        filters.append(f"NOT {_sql_retreat_eq(key)}")
        params[key] = n


def _apply_species_filters(
    filters: list[str],
    params: dict[str, Any],
    *,
    generation: int | None,
    pokemon_special: str | None,
    species_groups: list[str] | None = None,
) -> None:
    groups = [g for g in (species_groups or []) if g and g != "regional"]
    want_regional = bool(species_groups and "regional" in species_groups)
    if generation is None and not pokemon_special and not groups and not want_regional:
        return

    if want_regional:
        filters.append(REGIONAL_NAME_SQL)

    if generation is None and not pokemon_special and not groups:
        return

    filters.append("c.dex_ids IS NOT NULL AND cardinality(c.dex_ids) > 0")
    clauses = ["ps.dex_id = c.dex_ids[1]"]
    if generation is not None:
        clauses.append("ps.generation_id = :generation")
        params["generation"] = generation
    if pokemon_special == "legendary":
        clauses.append("ps.is_legendary = TRUE")
    elif pokemon_special == "mythical":
        clauses.append("ps.is_mythical = TRUE")
    elif pokemon_special == "notable":
        clauses.append("(ps.is_legendary = TRUE OR ps.is_mythical = TRUE)")
    for idx, group in enumerate(groups):
        if group == "baby":
            clauses.append("ps.is_baby = TRUE")
            continue
        key = f"species_group_{idx}"
        clauses.append(f":{key} = ANY(ps.species_groups)")
        params[key] = group
    filters.append(
        f"EXISTS (SELECT 1 FROM pokemon_species ps WHERE {' AND '.join(clauses)})"
    )


def _card_text(raw: dict[str, Any]) -> str | None:
    """Rules text for trainers/energy (effect) or flavor text for Pokémon."""
    desc = raw.get("description")
    if desc and str(desc).strip():
        return str(desc).strip()
    data = raw.get("card_data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict):
        effect = data.get("effect")
        if effect and str(effect).strip():
            return str(effect).strip()
    return None


def _attach_tcg_urls(card: dict[str, Any]) -> None:
    card["tcgplayer_product_id"] = card.get("tcgplayer_product_id") or None
    card["tcg_url"] = pokemon_buy_url(
        product_id=card.get("tcgplayer_product_id"),
        name=card.get("name") or "",
        set_name=card.get("set_name") or "",
        local_id=str(card.get("local_id") or ""),
    ) or None


def _grid_card_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Minimal fields for search grid (detail modal loads /cards/{id})."""
    card_id = raw.get("id")
    return {
        "id": raw["id"],
        "name": raw["name"],
        "set_name": raw["set_name"],
        "local_id": raw["local_id"],
        "image_url": _image_url(
            raw.get("image_url"),
            card_id=card_id,
            local_id=raw.get("local_id"),
            image_local=bool(raw.get("image_local")),
            size="low",
        ),
    }


def _card_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": raw["id"],
        "name": raw["name"],
        "set_id": raw["set_id"],
        "set_name": raw["set_name"],
        "local_id": raw["local_id"],
        "category": raw["category"],
        "rarity": raw["rarity"],
        "hp": raw["hp"],
        "types": raw["types"] or [],
        "subtypes": raw.get("subtypes") or [],
        "tags": raw.get("tags") or [],
        "stage": raw["stage"],
        "evolve_from": raw["evolve_from"],
        "dex_ids": raw["dex_ids"] or [],
        "illustrator": raw["illustrator"],
        "retreat": raw["retreat"],
        "regulation_mark": raw["regulation_mark"],
        "legal_standard": raw["legal_standard"],
        "legal_expanded": raw["legal_expanded"],
        "oracle_id": raw.get("oracle_id"),
        "illustration_id": raw.get("illustration_id"),
        "is_oracle_representative": bool(raw.get("is_oracle_representative")),
        "printing_count": raw.get("printing_count") or 1,
        "art_variant_count": raw.get("art_variant_count") or 1,
        "attacks": raw.get("attacks") or [],
        "abilities": raw.get("abilities") or [],
        "tcgplayer_product_id": raw.get("tcgplayer_product_id"),
        "oracle_tags": raw.get("oracle_tags") or [],
    }
    _attach_card_images(row, raw)
    _attach_tcg_urls(row)
    return row


@router.get("/api/pokemon/meta", response_model=PokemonMetaResponse)
def pokemon_meta(response: Response) -> PokemonMetaResponse:
    response.headers["Cache-Control"] = META_CACHE_CONTROL
    assert _engine is not None
    with _engine.connect() as conn:
        sets = conn.execute(
            text(
                """
                SELECT
                    s.id,
                    s.name,
                    s.series_id,
                    s.series_name,
                    s.release_date::text AS release_date,
                    s.card_count_total,
                    COUNT(c.id)::int AS loaded_cards
                FROM pokemon_sets s
                LEFT JOIN pokemon_cards c ON c.set_id = s.id
                GROUP BY s.id, s.name, s.series_id, s.series_name, s.release_date, s.card_count_total
                ORDER BY s.release_date ASC NULLS LAST, s.name
                """
            )
        ).mappings().all()
        stats = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM pokemon_sets)::int AS set_count,
                    (SELECT COUNT(*) FROM pokemon_cards)::int AS printing_count,
                    (SELECT COUNT(*) FROM pokemon_oracles)::int AS oracle_count
                """
            )
        ).mappings().one()
        series = conn.execute(
            text(
                """
                SELECT
                    series_id AS id,
                    MAX(series_name) AS name,
                    COUNT(*)::int AS set_count
                FROM pokemon_sets
                WHERE series_id IS NOT NULL
                GROUP BY series_id
                ORDER BY MIN(release_date) ASC NULLS LAST, series_id
                """
            )
        ).mappings().all()
        rarities = conn.execute(
            text(
                """
                SELECT DISTINCT rarity
                FROM pokemon_cards
                WHERE rarity IS NOT NULL
                ORDER BY rarity
                """
            )
        ).scalars().all()
        types = conn.execute(
            text(
                """
                SELECT DISTINCT unnest(types) AS type
                FROM pokemon_cards
                WHERE types IS NOT NULL
                ORDER BY type
                """
            )
        ).scalars().all()
        categories = conn.execute(
            text(
                """
                SELECT DISTINCT category
                FROM pokemon_cards
                ORDER BY category
                """
            )
        ).scalars().all()
        stages = conn.execute(
            text(
                """
                SELECT DISTINCT stage
                FROM pokemon_cards
                WHERE stage IS NOT NULL
                ORDER BY stage
                """
            )
        ).scalars().all()
        tags = conn.execute(
            text(
                """
                SELECT DISTINCT unnest(tags) AS tag
                FROM pokemon_cards
                WHERE tags IS NOT NULL
                ORDER BY tag
                """
            )
        ).scalars().all()
        try:
            oracle_tag_defs = conn.execute(
                text(
                    """
                    SELECT slug, label, parent_slug
                    FROM oracle_tag_defs
                    WHERE active = TRUE
                    ORDER BY label, slug
                    """
                )
            ).mappings().all()
        except Exception:
            oracle_tag_defs = []
        try:
            art_tag_defs = conn.execute(
                text(
                    """
                    SELECT slug, label, parent_slug
                    FROM art_tag_defs
                    WHERE active = TRUE
                    ORDER BY label, slug
                    """
                )
            ).mappings().all()
        except Exception:
            art_tag_defs = []
        generations = conn.execute(
            text(
                """
                SELECT
                    ps.generation_id AS id,
                    ps.generation_name AS name,
                    COUNT(DISTINCT c.id)::int AS card_count
                FROM pokemon_cards c
                INNER JOIN pokemon_species ps ON ps.dex_id = c.dex_ids[1]
                WHERE c.category = 'Pokemon'
                GROUP BY ps.generation_id, ps.generation_name
                ORDER BY ps.generation_id
                """
            )
        ).mappings().all()
    return PokemonMetaResponse(
        set_count=stats["set_count"],
        printing_count=stats["printing_count"],
        oracle_count=stats["oracle_count"],
        sets=[dict(row) for row in sets],
        facets={
            "series": [dict(row) for row in series],
            "rarities": list(rarities),
            "types": list(types),
            "categories": list(categories),
            "stages": list(stages),
            "tags": list(tags),
            "oracle_tags": [dict(r) for r in oracle_tag_defs],
            "art_tags": [dict(r) for r in art_tag_defs],
            "generations": [dict(row) for row in generations],
            "pokemon_special": [
                {"id": "legendary", "name": "Legendary"},
                {"id": "mythical", "name": "Mythical"},
                {"id": "notable", "name": "Legendary or Mythical"},
            ],
            "species_groups": [
                {"id": gid, "name": label}
                for gid, label in SPECIES_GROUP_LABELS.items()
            ],
            "has": list(ABILITY_HAS_FACETS),
        },
    )


@router.get("/api/pokemon/cards")
def search_pokemon_cards(
    q: str | None = Query(None, description="Card name search"),
    set_id: str | None = Query(None, description="TCGdex set id, e.g. bw10"),
    series_id: str | None = Query(None, description="TCGdex series/block id, e.g. bw"),
    dex_id: int | None = Query(None, description="National Pokédex number"),
    rarity: str | None = Query(None, description="Exact rarity match"),
    category: str | None = Query(None, description="Pokemon | Trainer | Energy"),
    color: str | None = Query(None, description="Energy color, e.g. Grass or Fire"),
    type: str | None = Query(
        None,
        description="Deprecated alias for color",
        deprecated=True,
    ),
    stage: str | None = Query(None, description="Basic | Stage1 | Stage2"),
    tag: str | None = Query(None, description="Subtype slug, e.g. team-plasma"),
    otag: str | None = Query(None, description="Oracle tag slug(s), comma-separated, e.g. rain-dance"),
    art: str | None = Query(None, description="Art tag slug(s), comma-separated, e.g. night"),
    generation: int | None = Query(None, ge=1, le=9, description="Pokémon generation, e.g. 5"),
    pokemon_special: str | None = Query(
        None,
        description="legendary | mythical | notable (legendary or mythical)",
    ),
    species_group: str | None = Query(
        None,
        description="Species group slug, e.g. starter | paradox | baby | regional",
    ),
    has: str | None = Query(
        None,
        description="ability | ability-any | poke-power | poke-body | pokemon-power | omega-trait",
    ),
    unique: UniqueMode = Query("cards", description="pokemon | cards | prints | art"),
    sort: str = Query("name", description="name | set | dex | hp_desc | type | shuffle"),
    seed: str | None = Query(
        None,
        description="Shuffle seed (stable pagination when sort=shuffle)",
        max_length=64,
    ),
    limit: int = Query(48, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    assert _engine is not None
    sort_key = (sort or "name").strip().lower()
    if sort_key == "random":
        sort_key = "shuffle"

    filters = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    shuffle_seed: str | None = None
    if sort_key == "shuffle":
        shuffle_seed = (seed or "").strip() or secrets.token_hex(8)
        params["shuffle_seed"] = shuffle_seed
        order = SORT_SQL["shuffle"]
    else:
        order = SORT_SQL.get(sort_key, SORT_SQL["name"])
    parsed = _parse_search_query(q)
    if parsed["name_q"]:
        # Accent-insensitive: "pokemon" matches "Pokémon", etc.
        filters.append(f"{_sql_accent_fold('c.name')} LIKE :q")
        params["q"] = f"%{fold_accents(parsed['name_q']).lower()}%"
    explicit_tags = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
    all_tags = list(dict.fromkeys(parsed["tags"] + explicit_tags))
    for idx, t in enumerate(all_tags):
        key = f"tag_{idx}"
        filters.append(f":{key} = ANY(c.tags)")
        params[key] = t
    for idx, t in enumerate(parsed.get("exclude_tags") or []):
        key = f"xtag_{idx}"
        filters.append(f"NOT (:{key} = ANY(COALESCE(c.tags, ARRAY[]::text[])))")
        params[key] = t

    explicit_otags = [t.strip().lower().replace("_", "-") for t in (otag or "").split(",") if t.strip()]
    all_otags = list(dict.fromkeys(parsed["oracle_tags"] + explicit_otags))
    # Each requested tag is AND'd; within a tag, parent matches any descendant (OR).
    for idx, slug in enumerate(all_otags):
        expanded = [slug]
        try:
            from spelltag_oracle_tags import expand_oracle_search_slugs

            with _engine.connect() as _c:
                expanded = expand_oracle_search_slugs(_c, [slug])
        except Exception:
            pass
        key = f"otags_{idx}"
        filters.append(
            f"""EXISTS (
                SELECT 1 FROM oracle_tags ot
                INNER JOIN oracle_tag_defs otd ON otd.slug = ot.tag_slug
                WHERE ot.oracle_id = c.oracle_id
                  AND ot.tag_slug = ANY(:{key})
                  AND otd.active = TRUE
            )"""
        )
        params[key] = expanded
    for idx, slug in enumerate(parsed.get("exclude_oracle_tags") or []):
        expanded = [slug]
        try:
            from spelltag_oracle_tags import expand_oracle_search_slugs

            with _engine.connect() as _c:
                expanded = expand_oracle_search_slugs(_c, [slug])
        except Exception:
            pass
        key = f"xotags_{idx}"
        filters.append(
            f"""NOT EXISTS (
                SELECT 1 FROM oracle_tags ot
                INNER JOIN oracle_tag_defs otd ON otd.slug = ot.tag_slug
                WHERE ot.oracle_id = c.oracle_id
                  AND ot.tag_slug = ANY(:{key})
                  AND otd.active = TRUE
            )"""
        )
        params[key] = expanded

    explicit_artags = [t.strip().lower().replace("_", "-") for t in (art or "").split(",") if t.strip()]
    all_artags = list(dict.fromkeys(parsed["art_tags"] + explicit_artags))
    for idx, slug in enumerate(all_artags):
        expanded = [slug]
        try:
            from spelltag_art_tags import expand_art_search_slugs

            with _engine.connect() as _c:
                expanded = expand_art_search_slugs(_c, [slug])
        except Exception:
            pass
        key = f"artags_{idx}"
        filters.append(
            f"""EXISTS (
                SELECT 1 FROM art_tags at
                INNER JOIN art_tag_defs atd ON atd.slug = at.tag_slug
                WHERE at.illustration_id = c.illustration_id
                  AND at.tag_slug = ANY(:{key})
                  AND atd.active = TRUE
            )"""
        )
        params[key] = expanded
    for idx, slug in enumerate(parsed.get("exclude_art_tags") or []):
        expanded = [slug]
        try:
            from spelltag_art_tags import expand_art_search_slugs

            with _engine.connect() as _c:
                expanded = expand_art_search_slugs(_c, [slug])
        except Exception:
            pass
        key = f"xartags_{idx}"
        filters.append(
            f"""NOT EXISTS (
                SELECT 1 FROM art_tags at
                INNER JOIN art_tag_defs atd ON atd.slug = at.tag_slug
                WHERE at.illustration_id = c.illustration_id
                  AND at.tag_slug = ANY(:{key})
                  AND atd.active = TRUE
            )"""
        )
        params[key] = expanded

    gen = generation if generation is not None else parsed["generation"]
    special = (pokemon_special or "").strip().lower() or parsed["pokemon_special"]
    if special and special not in ("legendary", "mythical", "notable"):
        special = None
    group_vals = list(parsed["species_groups"])
    for raw in (species_group or "").split(","):
        g = SPECIES_GROUP_ALIASES.get(raw.strip().lower())
        if g:
            group_vals.append(g)
    group_vals = list(dict.fromkeys(group_vals))
    _apply_species_filters(
        filters,
        params,
        generation=gen,
        pokemon_special=special,
        species_groups=group_vals,
    )
    # Negated species filters (simple NOT EXISTS / NOT conditions)
    excl_gen = parsed.get("exclude_generation")
    excl_special = parsed.get("exclude_pokemon_special")
    excl_groups = list(parsed.get("exclude_species_groups") or [])
    if excl_gen is not None or excl_special or excl_groups:
        excl_clauses = ["ps.dex_id = c.dex_ids[1]"]
        if excl_gen is not None:
            excl_clauses.append("ps.generation_id = :xgeneration")
            params["xgeneration"] = excl_gen
        if excl_special == "legendary":
            excl_clauses.append("ps.is_legendary = TRUE")
        elif excl_special == "mythical":
            excl_clauses.append("ps.is_mythical = TRUE")
        elif excl_special == "notable":
            excl_clauses.append("(ps.is_legendary = TRUE OR ps.is_mythical = TRUE)")
        for idx, group in enumerate(excl_groups):
            if group == "regional":
                filters.append(f"NOT ({REGIONAL_NAME_SQL})")
                continue
            if group == "baby":
                excl_clauses.append("ps.is_baby = TRUE")
                continue
            key = f"xspecies_group_{idx}"
            excl_clauses.append(f":{key} = ANY(ps.species_groups)")
            params[key] = group
        # Only add species EXISTS-not if we still have species table predicates
        species_preds = [c for c in excl_clauses if c != "ps.dex_id = c.dex_ids[1]"]
        if species_preds:
            filters.append(
                "NOT (c.dex_ids IS NOT NULL AND cardinality(c.dex_ids) > 0 AND EXISTS ("
                f"SELECT 1 FROM pokemon_species ps WHERE {' AND '.join(excl_clauses)}))"
            )

    has_vals = {(h.strip().lower()) for h in (has or "").split(",") if h.strip()}
    has_kinds: list[str] = list(parsed.get("has_ability_kinds") or [])
    exclude_kinds: list[str] = list(parsed.get("exclude_has_ability_kinds") or [])
    for raw in has_vals:
        kind = _resolve_has_ability_kind(raw)
        if kind:
            has_kinds.append(kind)
    has_kinds = list(dict.fromkeys(has_kinds))
    exclude_kinds = list(dict.fromkeys(exclude_kinds))
    _apply_has_ability_filters(
        filters,
        params,
        kinds=has_kinds,
        exclude_kinds=exclude_kinds,
    )

    _apply_oracle_text_filters(
        filters,
        params,
        oracle_text=list(parsed.get("oracle_text") or []),
        exclude_oracle_text=list(parsed.get("exclude_oracle_text") or []),
    )

    eff_set = (set_id or parsed["set_id"] or "").strip().lower() or None
    eff_series = (series_id or parsed["series_id"] or "").strip().lower() or None
    if eff_set:
        filters.append("c.set_id = :set_id")
        params["set_id"] = eff_set
    elif eff_series:
        filters.append("s.series_id = :series_id")
        params["series_id"] = eff_series
    for idx, sid in enumerate(parsed.get("exclude_set_ids") or []):
        key = f"xset_{idx}"
        filters.append(f"c.set_id <> :{key}")
        params[key] = sid
    for idx, sid in enumerate(parsed.get("exclude_series_ids") or []):
        key = f"xseries_{idx}"
        filters.append(f"s.series_id IS DISTINCT FROM :{key}")
        params[key] = sid

    eff_dex = dex_id if dex_id is not None else parsed["dex_id"]
    if eff_dex is not None:
        filters.append(":dex_id = ANY(c.dex_ids)")
        params["dex_id"] = eff_dex
    for idx, dex in enumerate(parsed.get("exclude_dex_ids") or []):
        key = f"xdex_{idx}"
        filters.append(f"NOT (:{key} = ANY(COALESCE(c.dex_ids, ARRAY[]::int[])))")
        params[key] = dex

    eff_rarity = (rarity or parsed["rarity"] or "").strip() or None
    if eff_rarity:
        filters.append("c.rarity = :rarity")
        params["rarity"] = eff_rarity
    for idx, rar in enumerate(parsed.get("exclude_rarities") or []):
        key = f"xrarity_{idx}"
        filters.append(f"c.rarity IS DISTINCT FROM :{key}")
        params[key] = rar

    eff_category = (category or parsed["category"] or "").strip() or None
    if unique == "pokemon":
        # Dex rollup is Pokémon-only (trainers/energy excluded for now).
        filters.append("c.category = 'Pokemon'")
        filters.append("c.dex_ids IS NOT NULL AND cardinality(c.dex_ids) > 0")
    elif eff_category:
        filters.append("c.category = :category")
        params["category"] = eff_category
    for idx, cat in enumerate(parsed.get("exclude_categories") or []):
        key = f"xcat_{idx}"
        filters.append(f"c.category IS DISTINCT FROM :{key}")
        params[key] = cat

    eff_type = normalize_color_name(color or type or parsed["card_type"])
    if eff_type:
        filters.append(":card_type = ANY(c.types)")
        params["card_type"] = eff_type
    for idx, ctype in enumerate(parsed.get("exclude_card_types") or []):
        key = f"xtype_{idx}"
        filters.append(f"NOT (:{key} = ANY(COALESCE(c.types, ARRAY[]::text[])))")
        params[key] = ctype

    eff_stage = (stage or parsed["stage"] or "").strip() or None
    if eff_stage:
        filters.append("c.stage = :stage")
        params["stage"] = eff_stage
    for idx, stg in enumerate(parsed.get("exclude_stages") or []):
        key = f"xstage_{idx}"
        filters.append(f"c.stage IS DISTINCT FROM :{key}")
        params[key] = stg

    _apply_prize_filters(
        filters,
        params,
        prizes=list(parsed.get("prizes") or []),
        exclude_prizes=list(parsed.get("exclude_prizes") or []),
    )
    _apply_weak_res_filters(
        filters,
        params,
        weaknesses=list(parsed.get("weaknesses") or []),
        exclude_weaknesses=list(parsed.get("exclude_weaknesses") or []),
        resistances=list(parsed.get("resistances") or []),
        exclude_resistances=list(parsed.get("exclude_resistances") or []),
    )
    _apply_retreat_filters(
        filters,
        params,
        retreats=list(parsed.get("retreats") or []),
        exclude_retreats=list(parsed.get("exclude_retreats") or []),
    )

    where_sql = " AND ".join(filters)

    if unique == "pokemon":
        core_from = f"""
            FROM (
                SELECT DISTINCT ON (c.dex_ids[1])
                    c.*,
                    o.printing_count,
                    o.art_variant_count
                FROM pokemon_cards c
                INNER JOIN pokemon_sets s ON s.id = c.set_id
                LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
                WHERE {where_sql}
                ORDER BY c.dex_ids[1],
                         c.is_oracle_representative DESC,
                         s.release_date ASC NULLS LAST,
                         c.id
            ) c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
            {SPECIES_SORT_JOINS}
            WHERE 1=1
        """
    elif unique == "cards":
        core_from = f"""
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
            {SPECIES_SORT_JOINS}
            WHERE {where_sql}
              AND c.is_oracle_representative = TRUE
        """
    elif unique == "art":
        core_from = f"""
            FROM (
                SELECT DISTINCT ON (c.illustration_id)
                    c.*,
                    o.printing_count,
                    o.art_variant_count
                FROM pokemon_cards c
                INNER JOIN pokemon_sets s ON s.id = c.set_id
                LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
                WHERE {where_sql}
                ORDER BY c.illustration_id, c.is_oracle_representative DESC,
                         s.release_date ASC NULLS LAST, c.id
            ) c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
            {SPECIES_SORT_JOINS}
            WHERE 1=1
        """
    else:
        # prints (API only; not shown in Star Piece UI)
        core_from = f"""
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
            {SPECIES_SORT_JOINS}
            WHERE {where_sql}
        """

    select_cols = """
        c.id, c.name, s.name AS set_name, c.local_id, c.image_url, c.image_local
    """

    count_sql = f"SELECT COUNT(*) {core_from}"
    data_sql = f"""
        SELECT {select_cols}
        {core_from}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """

    with _engine.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        rows = conn.execute(text(data_sql), params).mappings().all()
        cards = [_grid_card_row(dict(r)) for r in rows]

    return {
        "unique": unique,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort_key if sort_key in SORT_SQL else "name",
        "seed": shuffle_seed,
        "cards": cards,
    }


@router.get("/api/pokemon/cards/{card_id}")
def get_pokemon_card(card_id: str) -> dict[str, Any]:
    assert _engine is not None
    lookup_id = card_id.strip()
    if not lookup_id:
        raise HTTPException(status_code=404, detail="Card not found")
    with _engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    c.*,
                    s.name AS set_name,
                    s.release_date::text AS release_date,
                    s.series_name,
                    s.tcg_online_code,
                    o.printing_count,
                    o.art_variant_count,
                    o.representative_card_id,
                    ps.name AS species_name,
                    ps.generation_id,
                    ps.generation_name,
                    ps.is_legendary,
                    ps.is_mythical,
                    ps.is_baby,
                    ps.species_groups
                FROM pokemon_cards c
                INNER JOIN pokemon_sets s ON s.id = c.set_id
                LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
                LEFT JOIN pokemon_species ps ON ps.dex_id = c.dex_ids[1]
                WHERE lower(c.id) = lower(:id)
                """
            ),
            {"id": lookup_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Card not found")

        siblings: list[dict[str, Any]] = []
        if row.get("oracle_id"):
            sib_rows = conn.execute(
                text(
                    """
                    SELECT
                        c.id, c.name, c.set_id, s.name AS set_name, c.local_id,
                        c.rarity, c.illustrator, c.image_url, c.image_local, c.retreat,
                        c.is_oracle_representative, c.illustration_id,
                        c.tcgplayer_product_id,
                        s.release_date::text AS release_date
                    FROM pokemon_cards c
                    INNER JOIN pokemon_sets s ON s.id = c.set_id
                    WHERE c.oracle_id = :oracle_id
                    ORDER BY s.release_date ASC NULLS LAST, c.id
                    """
                ),
                {"oracle_id": row["oracle_id"]},
            ).mappings().all()
            siblings = [dict(r) for r in sib_rows]

        species_printings: list[dict[str, Any]] = []
        primary_dex = (row.get("dex_ids") or [None])[0]
        if primary_dex is not None and (row.get("category") or "") == "Pokemon":
            sp_rows = conn.execute(
                text(
                    """
                    SELECT
                        c.id, c.name, c.set_id, s.name AS set_name, c.local_id,
                        c.rarity, c.illustrator, c.image_url, c.image_local, c.retreat,
                        c.is_oracle_representative, c.illustration_id,
                        c.tcgplayer_product_id, c.oracle_id,
                        s.release_date::text AS release_date
                    FROM pokemon_cards c
                    INNER JOIN pokemon_sets s ON s.id = c.set_id
                    WHERE c.category = 'Pokemon'
                      AND c.dex_ids[1] = :dex_id
                    ORDER BY s.release_date ASC NULLS LAST, c.name, c.id
                    """
                ),
                {"dex_id": int(primary_dex)},
            ).mappings().all()
            species_printings = [dict(r) for r in sp_rows]

        try:
            from spelltag_oracle_tags import fetch_oracle_tags_for_oracles

            oid = row.get("oracle_id")
            oracle_tags = (
                fetch_oracle_tags_for_oracles(conn, [str(oid)]).get(str(oid), [])
                if oid
                else []
            )
        except Exception:
            oracle_tags = []

        try:
            from spelltag_art_tags import fetch_art_tags_for_illustrations

            iid = row.get("illustration_id")
            art_tags = (
                fetch_art_tags_for_illustrations(conn, [str(iid)]).get(str(iid), [])
                if iid
                else []
            )
        except Exception:
            art_tags = []

    card = _card_row(dict(row))
    card["oracle_tags"] = oracle_tags
    card["art_tags"] = art_tags
    card["release_date"] = row.get("release_date")
    card["series_name"] = row.get("series_name")
    card["description"] = _card_text(dict(row))
    card["weaknesses"] = row.get("weaknesses") or []
    card["resistances"] = row.get("resistances") or []
    card["variants"] = row.get("variants") or {}
    card["representative_card_id"] = row.get("representative_card_id")
    if row.get("dex_ids"):
        groups = list(row.get("species_groups") or [])
        card["pokemon"] = {
            "dex_id": (row.get("dex_ids") or [None])[0],
            "species_name": row.get("species_name"),
            "generation_id": row.get("generation_id"),
            "generation_name": row.get("generation_name"),
            "is_legendary": bool(row.get("is_legendary")),
            "is_mythical": bool(row.get("is_mythical")),
            "is_baby": bool(row.get("is_baby")),
            "species_groups": groups,
            "printing_count": len(species_printings) or None,
        }
    name = card.get("name") or ""
    card["is_regional"] = bool(
        re.search(r"(^|\s)(Alolan|Galarian|Hisuian|Paldean)\s", name, re.I)
    )
    card["has_ability"] = bool(card.get("abilities"))
    species_name = (card.get("pokemon") or {}).get("species_name")
    card["limitless_query"] = limitless_query_for_card(
        name=name,
        species_name=species_name,
        is_regional=card["is_regional"],
        category=card.get("category"),
    )
    card["limitless_set_code"] = (row.get("tcg_online_code") or "").strip().upper() or None
    card["limitless_url"] = limitless_card_url(
        set_code=row.get("tcg_online_code"),
        local_id=str(card.get("local_id") or ""),
    )

    def _related_row(s: dict[str, Any]) -> dict[str, Any]:
        out = {**s}
        local = bool(s.get("image_local"))
        out["image_local"] = local
        out["image_url"] = _image_url(
            s.get("image_url"),
            card_id=s.get("id"),
            local_id=s.get("local_id"),
            image_local=local,
            size="low",
        )
        out["image_url_high"] = _image_url(
            s.get("image_url"),
            card_id=s.get("id"),
            local_id=s.get("local_id"),
            image_local=local,
            size="high",
        )
        out["tcg_url"] = (
            pokemon_buy_url(
                product_id=s.get("tcgplayer_product_id"),
                name=s.get("name") or card.get("name") or "",
                set_name=s.get("set_name") or "",
                local_id=str(s.get("local_id") or ""),
            )
            or None
        )
        return out

    card["sibling_printings"] = [_related_row(s) for s in siblings]
    card["species_printings"] = [_related_row(s) for s in species_printings]
    return card
