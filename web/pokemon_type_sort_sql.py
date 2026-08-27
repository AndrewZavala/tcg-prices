"""Shared SQL fragments for sort-by-type (Pokemon, Trainer, Energy)."""


def build_card_type_sort_sql(alias: str = "c", *, include_category_bucket: bool = True) -> str:
    a = alias
    type_rank = f"""CASE COALESCE(
  CASE WHEN {a}.category = 'Pokemon' THEN ps.chain_sort_type ELSE NULL END,
  {a}.types[1],
  'Colorless'
)
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

    lines: list[str] = []
    if include_category_bucket:
        lines.append(f"CASE {a}.category WHEN 'Pokemon' THEN 0 WHEN 'Trainer' THEN 1 ELSE 2 END")
    lines.append(primary_rank)
    lines.append(
        f"CASE WHEN {a}.category = 'Energy' "
        f"AND NOT ('special' = ANY(COALESCE({a}.tags, ARRAY[]::text[]))) "
        f"THEN ({tcg_type_rank}) ELSE 0 END"
    )
    lines.append(
        f"CASE WHEN {a}.category = 'Pokemon' "
        f"THEN COALESCE(ps_root.name, ps.name, {a}.name) ELSE '' END"
    )
    lines.append(
        f"CASE WHEN {a}.category = 'Pokemon' THEN COALESCE(ps.chain_stage_order, 99) ELSE 0 END"
    )
    lines.append(f"{a}.name ASC")
    lines.append("s.release_date ASC NULLS LAST")
    lines.append(f"{a}.id ASC")
    return ",\n                ".join(lines)


COLLECTION_SPECIES_JOINS = """
            LEFT JOIN pokemon_species ps ON ps.dex_id = pc.dex_ids[1]
            LEFT JOIN pokemon_species ps_root ON ps_root.dex_id = ps.chain_root_dex_id
"""
