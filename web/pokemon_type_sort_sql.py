"""Shared SQL fragments for sort-by-type (Pokemon, Trainer, Energy)."""

# δ / delta-species prints use alternate TCG types (e.g. Fire Gardevoir ex δ) — ignore for sort.
_DELTA_NAME_RE = r"[δΔ]| delta"


def inferred_chain_root_dex(alias: str, ps_alias: str = "ps") -> str:
    """Best-effort evolution-line root when chain metadata is missing."""
    a = alias
    p = ps_alias
    return f"""COALESCE(
  {p}.chain_root_dex_id,
  CASE {a}.stage
    WHEN 'Stage1' THEN {a}.dex_ids[1] - 1
    WHEN 'Stage2' THEN {a}.dex_ids[1] - 2
    ELSE {a}.dex_ids[1]
  END
)"""


def line_print_type_subquery(alias: str, root_expr: str) -> str:
    """Representative non-δ print type for a line root (usually Basic)."""
    return f"""(SELECT bp.types[1]
  FROM pokemon_cards bp
  WHERE bp.category = 'Pokemon'
    AND bp.dex_ids IS NOT NULL
    AND cardinality(bp.dex_ids) > 0
    AND bp.dex_ids[1] = ({root_expr})
    AND bp.types IS NOT NULL
    AND cardinality(bp.types) > 0
    AND bp.name !~* '{_DELTA_NAME_RE}'
  ORDER BY
    CASE bp.stage WHEN 'Basic' THEN 0 WHEN 'Stage1' THEN 1 WHEN 'Stage2' THEN 2 ELSE 3 END,
    bp.id
  LIMIT 1)"""


def pokemon_line_type_expr(alias: str) -> str:
    """Line-level TCG type: evolution metadata, then root print, not δ card type."""
    a = alias
    root = inferred_chain_root_dex(a)
    sub = line_print_type_subquery(a, root)
    return f"""COALESCE(ps_root.chain_sort_type, ps.chain_sort_type, {sub}, {a}.types[1], 'Colorless')"""


def build_species_sort_joins(card_alias: str) -> str:
    root = inferred_chain_root_dex(card_alias)
    return f"""
LEFT JOIN pokemon_species ps ON ps.dex_id = {card_alias}.dex_ids[1]
LEFT JOIN pokemon_species ps_root ON ps_root.dex_id = ({root})"""


def build_card_type_sort_sql(alias: str = "c", *, include_category_bucket: bool = True) -> str:
    a = alias
    line_type = pokemon_line_type_expr(a)
    type_rank = f"""CASE {line_type}
  WHEN 'Grass' THEN 1 WHEN 'Fire' THEN 2 WHEN 'Water' THEN 3 WHEN 'Lightning' THEN 4
  WHEN 'Psychic' THEN 5 WHEN 'Fighting' THEN 6 WHEN 'Darkness' THEN 7 WHEN 'Metal' THEN 8
  WHEN 'Fairy' THEN 9 WHEN 'Dragon' THEN 10 WHEN 'Colorless' THEN 11 ELSE 99 END"""

    tcg_type_rank = f"""CASE COALESCE({a}.types[1], 'Colorless')
  WHEN 'Grass' THEN 1 WHEN 'Fire' THEN 2 WHEN 'Water' THEN 3 WHEN 'Lightning' THEN 4
  WHEN 'Psychic' THEN 5 WHEN 'Fighting' THEN 6 WHEN 'Darkness' THEN 7 WHEN 'Metal' THEN 8
  WHEN 'Fairy' THEN 9 WHEN 'Dragon' THEN 10 WHEN 'Colorless' THEN 11 ELSE 99 END"""

    trainer_rank = f"""CASE
  WHEN 'supporter' = ANY(COALESCE({a}.tags, ARRAY[]::text[])) THEN 1
  WHEN 'item' = ANY(COALESCE({a}.tags, ARRAY[]::text[])) THEN 2
  WHEN 'pokemon-tool' = ANY(COALESCE({a}.tags, ARRAY[]::text[])) THEN 3
  WHEN 'stadium' = ANY(COALESCE({a}.tags, ARRAY[]::text[])) THEN 4
  ELSE 99 END"""

    energy_rank = f"""CASE
  WHEN 'special' = ANY(COALESCE({a}.tags, ARRAY[]::text[])) THEN 2
  ELSE 1 END"""

    primary_rank = f"""CASE {a}.category
  WHEN 'Pokemon' THEN ({type_rank})
  WHEN 'Trainer' THEN ({trainer_rank})
  WHEN 'Energy' THEN ({energy_rank})
  ELSE 99 END"""

    root = inferred_chain_root_dex(a)
    line_group = f"""CASE WHEN {a}.category = 'Pokemon'
  THEN COALESCE(({root}), {a}.dex_ids[1], 999999)
  ELSE 0 END"""

    line_stage = f"""CASE WHEN {a}.category = 'Pokemon' THEN COALESCE(
  CASE WHEN ps.chain_root_dex_id IS NOT NULL THEN ps.chain_stage_order END,
  CASE {a}.stage
    WHEN 'Basic' THEN 0
    WHEN 'Stage1' THEN 1
    WHEN 'Stage2' THEN 2
    ELSE NULL
  END,
  99
) ELSE 0 END"""

    lines: list[str] = []
    if include_category_bucket:
        lines.append(f"CASE {a}.category WHEN 'Pokemon' THEN 0 WHEN 'Trainer' THEN 1 ELSE 2 END")
    lines.append(primary_rank)
    lines.append(
        f"CASE WHEN {a}.category = 'Energy' "
        f"AND NOT ('special' = ANY(COALESCE({a}.tags, ARRAY[]::text[]))) "
        f"THEN ({tcg_type_rank}) ELSE 0 END"
    )
    lines.append(line_group)
    lines.append(line_stage)
    lines.append(f"{a}.dex_ids[1] ASC NULLS LAST")
    lines.append(f"{a}.name ASC")
    lines.append("s.release_date ASC NULLS LAST")
    lines.append(f"{a}.id ASC NULLS LAST")
    return ",\n                ".join(lines)


COLLECTION_SPECIES_JOINS = build_species_sort_joins("pc")

SEARCH_SPECIES_JOINS = build_species_sort_joins("c")
