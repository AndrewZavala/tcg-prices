"""Pokémon TCG catalog API — demo search with Scryfall-style unique rollups."""

from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from tcgplayer_links import pokemon_buy_url

router = APIRouter(tags=["pokemon"])

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
}


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
    return (
        f"/media/cards/{card_id}/low.webp",
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


def _parse_search_query(
    q: str | None,
) -> dict[str, Any]:
    """Parse pkmncards-style query tokens (t:, is:, set:, e:, has:, etc.)."""
    result: dict[str, Any] = {
        "name_q": None,
        "tags": [],
        "oracle_tags": [],
        "generation": None,
        "pokemon_special": None,
        "species_groups": [],
        "has_ability": False,
        "category": None,
        "set_id": None,
        "series_id": None,
        "rarity": None,
        "card_type": None,
        "dex_id": None,
        "stage": None,
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
    type_names = {
        "grass": "Grass",
        "fire": "Fire",
        "water": "Water",
        "lightning": "Lightning",
        "psychic": "Psychic",
        "fighting": "Fighting",
        "darkness": "Darkness",
        "dark": "Darkness",
        "metal": "Metal",
        "fairy": "Fairy",
        "dragon": "Dragon",
        "colorless": "Colorless",
    }

    name_parts: list[str] = []
    for token in q.strip().split():
        if ":" not in token:
            name_parts.append(token)
            continue

        prefix, raw_val = token.split(":", 1)
        prefix = prefix.lower()
        val = raw_val.strip()
        val_lower = val.lower()
        if not val:
            continue

        if prefix == "t":
            if val_lower in category_aliases:
                result["category"] = category_aliases[val_lower]
            elif val_lower in trainer_subtype_aliases:
                result["tags"].append(trainer_subtype_aliases[val_lower])
            else:
                result["tags"].append(val_lower.replace("_", "-"))
        elif prefix == "is":
            if val_lower == "legendary":
                result["pokemon_special"] = "legendary"
            elif val_lower == "mythical":
                result["pokemon_special"] = "mythical"
            elif val_lower in ("notable", "legendary-mythical"):
                result["pokemon_special"] = "notable"
            elif val_lower.startswith("gen") and val_lower[3:].isdigit():
                result["generation"] = int(val_lower[3:])
            elif val_lower in SPECIES_GROUP_ALIASES:
                result["species_groups"].append(SPECIES_GROUP_ALIASES[val_lower])
            else:
                result["tags"].append(val_lower)
        elif prefix == "has":
            if val_lower == "ability":
                result["has_ability"] = True
            else:
                name_parts.append(token)
        elif prefix == "set":
            result["set_id"] = val_lower
        elif prefix in ("s", "series"):
            result["series_id"] = val_lower
        elif prefix == "r":
            result["rarity"] = rarity_aliases.get(val_lower, val)
        elif prefix in ("e", "type"):
            result["card_type"] = type_names.get(val_lower, val.title())
        elif prefix == "dex":
            if val.isdigit():
                result["dex_id"] = int(val)
        elif prefix == "stage":
            result["stage"] = stage_aliases.get(val_lower, val)
        elif prefix == "otag":
            slug = val_lower.replace("_", "-")
            if slug:
                result["oracle_tags"].append(slug)
        else:
            name_parts.append(token)

    result["name_q"] = " ".join(name_parts).strip() or None
    result["tags"] = list(dict.fromkeys(result["tags"]))
    result["oracle_tags"] = list(dict.fromkeys(result["oracle_tags"]))
    result["species_groups"] = list(dict.fromkeys(result["species_groups"]))
    return result


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
def pokemon_meta() -> PokemonMetaResponse:
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
                    SELECT slug, label
                    FROM oracle_tag_defs
                    WHERE active = TRUE
                    ORDER BY label, slug
                    """
                )
            ).mappings().all()
        except Exception:
            oracle_tag_defs = []
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
            "has": [
                {"id": "ability", "name": "Has Ability"},
            ],
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
    type: str | None = Query(None, description="Energy type, e.g. Grass"),
    stage: str | None = Query(None, description="Basic | Stage1 | Stage2"),
    tag: str | None = Query(None, description="Subtype slug, e.g. team-plasma"),
    otag: str | None = Query(None, description="Oracle tag slug(s), comma-separated, e.g. rain-dance"),
    generation: int | None = Query(None, ge=1, le=9, description="Pokémon generation, e.g. 5"),
    pokemon_special: str | None = Query(
        None,
        description="legendary | mythical | notable (legendary or mythical)",
    ),
    species_group: str | None = Query(
        None,
        description="Species group slug, e.g. starter | paradox | baby | regional",
    ),
    has: str | None = Query(None, description="ability — cards with an Ability"),
    unique: UniqueMode = Query("cards", description="pokemon | cards | prints | art"),
    sort: str = Query("name", description="name | set | dex | hp_desc"),
    limit: int = Query(48, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    assert _engine is not None
    order = SORT_SQL.get(sort, SORT_SQL["name"])

    filters = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    parsed = _parse_search_query(q)
    if parsed["name_q"]:
        filters.append("c.name ILIKE :q")
        params["q"] = f"%{parsed['name_q']}%"
    explicit_tags = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
    all_tags = list(dict.fromkeys(parsed["tags"] + explicit_tags))
    for idx, t in enumerate(all_tags):
        key = f"tag_{idx}"
        filters.append(f":{key} = ANY(c.tags)")
        params[key] = t

    explicit_otags = [t.strip().lower().replace("_", "-") for t in (otag or "").split(",") if t.strip()]
    all_otags = list(dict.fromkeys(parsed["oracle_tags"] + explicit_otags))
    for idx, slug in enumerate(all_otags):
        key = f"otag_{idx}"
        filters.append(
            f"""EXISTS (
                SELECT 1 FROM oracle_tags ot
                INNER JOIN oracle_tag_defs otd ON otd.slug = ot.tag_slug
                WHERE ot.oracle_id = c.oracle_id
                  AND ot.tag_slug = :{key}
                  AND otd.active = TRUE
            )"""
        )
        params[key] = slug

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

    has_vals = {(h.strip().lower()) for h in (has or "").split(",") if h.strip()}
    if parsed["has_ability"] or "ability" in has_vals:
        filters.append(
            "c.abilities IS NOT NULL AND jsonb_typeof(c.abilities) = 'array' "
            "AND jsonb_array_length(c.abilities) > 0"
        )

    eff_set = (set_id or parsed["set_id"] or "").strip().lower() or None
    eff_series = (series_id or parsed["series_id"] or "").strip().lower() or None
    if eff_set:
        filters.append("c.set_id = :set_id")
        params["set_id"] = eff_set
    elif eff_series:
        filters.append("s.series_id = :series_id")
        params["series_id"] = eff_series

    eff_dex = dex_id if dex_id is not None else parsed["dex_id"]
    if eff_dex is not None:
        filters.append(":dex_id = ANY(c.dex_ids)")
        params["dex_id"] = eff_dex

    eff_rarity = (rarity or parsed["rarity"] or "").strip() or None
    if eff_rarity:
        filters.append("c.rarity = :rarity")
        params["rarity"] = eff_rarity

    eff_category = (category or parsed["category"] or "").strip() or None
    if unique == "pokemon":
        # Dex rollup is Pokémon-only (trainers/energy excluded for now).
        filters.append("c.category = 'Pokemon'")
        filters.append("c.dex_ids IS NOT NULL AND cardinality(c.dex_ids) > 0")
    elif eff_category:
        filters.append("c.category = :category")
        params["category"] = eff_category

    eff_type = (type or parsed["card_type"] or "").strip() or None
    if eff_type:
        filters.append(":card_type = ANY(c.types)")
        params["card_type"] = eff_type

    eff_stage = (stage or parsed["stage"] or "").strip() or None
    if eff_stage:
        filters.append("c.stage = :stage")
        params["stage"] = eff_stage

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
            WHERE 1=1
        """
    elif unique == "cards":
        core_from = f"""
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
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
            WHERE 1=1
        """
    else:
        # prints (API only; not shown in Star Piece UI)
        core_from = f"""
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            LEFT JOIN pokemon_oracles o ON o.id = c.oracle_id
            WHERE {where_sql}
        """

    select_cols = """
        c.id, c.name, c.set_id, s.name AS set_name, c.local_id, c.category,
        c.rarity, c.hp, c.types, c.subtypes, c.tags, c.stage, c.evolve_from, c.dex_ids,
        c.illustrator, c.retreat, c.regulation_mark, c.legal_standard,
        c.legal_expanded, c.image_url, c.image_local, c.oracle_id, c.illustration_id,
        c.is_oracle_representative, c.attacks, c.abilities, c.tcgplayer_product_id,
        COALESCE(o.printing_count, 1) AS printing_count,
        COALESCE(o.art_variant_count, 1) AS art_variant_count
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
        cards = [_card_row(dict(r)) for r in rows]
        try:
            from spelltag_oracle_tags import fetch_oracle_tags_for_oracles

            oids = [c.get("oracle_id") for c in cards if c.get("oracle_id")]
            by_oid = fetch_oracle_tags_for_oracles(conn, oids)
            for card in cards:
                oid = card.get("oracle_id")
                card["oracle_tags"] = by_oid.get(oid, []) if oid else []
        except Exception:
            for card in cards:
                card["oracle_tags"] = card.get("oracle_tags") or []

    return {
        "unique": unique,
        "total": total,
        "limit": limit,
        "offset": offset,
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

    card = _card_row(dict(row))
    card["oracle_tags"] = oracle_tags
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
