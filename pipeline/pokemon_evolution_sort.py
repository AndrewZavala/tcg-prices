"""Evolution chain helpers for type-based Pokémon card sorting."""

from __future__ import annotations

from typing import Any

# TCG type order for search sort (Grass first, then Fire, Water, …).
TYPE_SORT_RANK: dict[str, int] = {
    "Grass": 1,
    "Fire": 2,
    "Water": 3,
    "Lightning": 4,
    "Psychic": 5,
    "Fighting": 6,
    "Darkness": 7,
    "Metal": 8,
    "Fairy": 9,
    "Dragon": 10,
    "Colorless": 11,
}

POKEAPI_TYPE_TO_TCG: dict[str, str] = {
    "grass": "Grass",
    "fire": "Fire",
    "water": "Water",
    "electric": "Lightning",
    "psychic": "Psychic",
    "fighting": "Fighting",
    "dark": "Darkness",
    "steel": "Metal",
    "fairy": "Fairy",
    "dragon": "Dragon",
    "normal": "Colorless",
    "flying": "Colorless",
    "poison": "Grass",
    "ground": "Fighting",
    "rock": "Fighting",
    "bug": "Grass",
    "ghost": "Psychic",
    "ice": "Water",
}


def tcg_type_rank(type_name: str | None) -> int:
    if not type_name:
        return 99
    return TYPE_SORT_RANK.get(str(type_name).strip(), 99)


def map_pokeapi_type(name: str | None) -> str | None:
    if not name:
        return None
    return POKEAPI_TYPE_TO_TCG.get(str(name).strip().lower())


def species_dex_from_url(url: str) -> int:
    return int(str(url).rstrip("/").split("/")[-1])


def paths_from_chain_node(node: dict[str, Any], prefix: list[int]) -> list[list[int]]:
    dex = species_dex_from_url(node["species"]["url"])
    path = prefix + [dex]
    children = node.get("evolves_to") or []
    if not children:
        return [path]
    out: list[list[int]] = []
    for child in children:
        out.extend(paths_from_chain_node(child, path))
    return out


def paths_from_evolution_chain(chain: dict[str, Any]) -> list[list[int]]:
    root = chain.get("chain") or {}
    if not root.get("species"):
        return []
    return paths_from_chain_node(root, [])


def assignments_for_paths(
    paths: list[list[int]],
    chain_id: int,
    leaf_types: dict[int, str | None],
) -> dict[int, dict[str, Any]]:
    """Build per-dex metadata from all root-to-leaf paths in one chain."""
    by_dex: dict[int, list[dict[str, Any]]] = {}

    for path in paths:
        if not path:
            continue
        leaf_dex = path[-1]
        leaf_type = leaf_types.get(leaf_dex)
        for depth, dex in enumerate(path):
            by_dex.setdefault(dex, []).append(
                {
                    "evolution_chain_id": chain_id,
                    "chain_root_dex_id": path[0],
                    "chain_stage_order": depth,
                    "chain_sort_type": leaf_type,
                    "path_len": len(path),
                    "leaf_dex": leaf_dex,
                    "type_rank": tcg_type_rank(leaf_type),
                }
            )

    chosen: dict[int, dict[str, Any]] = {}
    for dex, options in by_dex.items():
        best = max(
            options,
            key=lambda o: (o["path_len"], o["type_rank"], o["leaf_dex"]),
        )
        chosen[dex] = {
            "evolution_chain_id": best["evolution_chain_id"],
            "chain_root_dex_id": best["chain_root_dex_id"],
            "chain_stage_order": best["chain_stage_order"],
            "chain_sort_type": best["chain_sort_type"],
        }
    return chosen


def type_sort_order_sql(column_expr: str) -> str:
    """SQL CASE mapping a type column to sort rank."""
    parts = [f"WHEN {column_expr} = '{name}' THEN {rank}" for name, rank in TYPE_SORT_RANK.items()]
    return "CASE " + " ".join(parts) + f" ELSE 99 END"
