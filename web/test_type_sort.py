"""Tests for type-sort rank helpers (mirrors pokemon_type_sort_sql logic)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from pokemon_evolution_sort import assignments_for_paths, paths_from_evolution_chain  # noqa: E402


def _chain(*paths: list[int]) -> dict:
    def insert(node: dict, path: list[int], idx: int = 0) -> None:
        dex = path[idx]
        if node.get("species", {}).get("url") != f"/api/v2/pokemon-species/{dex}/":
            node["species"] = {"url": f"/api/v2/pokemon-species/{dex}/"}
        if idx == len(path) - 1:
            node["evolves_to"] = []
            return
        next_dex = path[idx + 1]
        children = node.setdefault("evolves_to", [])
        child = next((c for c in children if c["species"]["url"].endswith(f"/{next_dex}/")), None)
        if child is None:
            child = {}
            children.append(child)
        insert(child, path, idx + 1)

    root: dict = {}
    for path in paths:
        insert(root, path)
    return {"id": 20, "chain": root}


def line_sort_key(
    *,
    dex_id: int,
    stage: str | None,
    chain_root_dex_id: int | None,
    chain_stage_order: int | None,
) -> tuple:
    group = chain_root_dex_id if chain_root_dex_id is not None else dex_id
    if chain_root_dex_id is not None:
        order = chain_stage_order if chain_stage_order is not None else 99
    else:
        stage_map = {"Basic": 0, "Stage1": 1, "Stage2": 2}
        order = stage_map.get(stage or "", 99)
    return (group, order, dex_id)


class RaltsLineSortTests(unittest.TestCase):
    def test_ralts_line_orders_by_stage_even_without_chain_metadata(self):
        keys = [
            line_sort_key(dex_id=282, stage="Stage2", chain_root_dex_id=None, chain_stage_order=0),
            line_sort_key(dex_id=280, stage="Basic", chain_root_dex_id=None, chain_stage_order=0),
            line_sort_key(dex_id=281, stage="Stage1", chain_root_dex_id=None, chain_stage_order=0),
        ]
        names = ["Gardevoir ex", "Ralts", "Kirlia"]
        ordered = [name for _, name in sorted(zip(keys, names), key=lambda row: row[0])]
        self.assertEqual(ordered, ["Ralts", "Kirlia", "Gardevoir ex"])

    def test_ralts_line_with_evolution_metadata(self):
        chain = _chain([280, 281, 282])
        paths = paths_from_evolution_chain(chain)
        leaf_types = {280: "Psychic", 281: "Psychic", 282: "Psychic"}
        meta = assignments_for_paths(paths, 20, leaf_types)
        keys = [
            line_sort_key(
                dex_id=280,
                stage="Basic",
                chain_root_dex_id=meta[280]["chain_root_dex_id"],
                chain_stage_order=meta[280]["chain_stage_order"],
            ),
            line_sort_key(
                dex_id=281,
                stage="Stage1",
                chain_root_dex_id=meta[281]["chain_root_dex_id"],
                chain_stage_order=meta[281]["chain_stage_order"],
            ),
            line_sort_key(
                dex_id=282,
                stage="Stage2",
                chain_root_dex_id=meta[282]["chain_root_dex_id"],
                chain_stage_order=meta[282]["chain_stage_order"],
            ),
        ]
        ordered = [dex for dex, _ in sorted(zip([280, 281, 282], keys), key=lambda row: row[1])]
        self.assertEqual(ordered, [280, 281, 282])


if __name__ == "__main__":
    unittest.main()
