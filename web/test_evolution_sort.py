"""Tests for evolution-line type sort helpers."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from pokemon_evolution_sort import (  # noqa: E402
    assignments_for_paths,
    paths_from_evolution_chain,
    tcg_type_rank,
)


def _chain(*paths: list[int]) -> dict:
    """Minimal PokeAPI-like chain from root-to-leaf dex paths."""

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
    return {"id": 1, "chain": root}


class EvolutionSortTests(unittest.TestCase):
    def test_branching_line_uses_highest_stage_leaf_type(self):
        # Oddish(43) → Gloom(44) → Vileplume(45) or Bellossom(182)
        chain = _chain([43, 44, 45], [43, 44, 182])
        paths = paths_from_evolution_chain(chain)
        leaf_types = {45: "Psychic", 182: "Grass", 43: "Grass", 44: "Grass"}
        meta = assignments_for_paths(paths, 1, leaf_types)

        self.assertEqual(meta[43]["chain_sort_type"], "Psychic")
        self.assertEqual(meta[44]["chain_sort_type"], "Psychic")
        self.assertEqual(meta[45]["chain_sort_type"], "Psychic")
        self.assertEqual(meta[182]["chain_sort_type"], "Grass")
        self.assertEqual(meta[43]["chain_stage_order"], 0)
        self.assertEqual(meta[44]["chain_stage_order"], 1)
        self.assertEqual(meta[45]["chain_stage_order"], 2)

    def test_linear_line_keeps_stage_order(self):
        chain = _chain([69, 70, 71])  # Bellsprout line
        paths = paths_from_evolution_chain(chain)
        leaf_types = {71: "Grass", 70: "Grass", 69: "Grass"}
        meta = assignments_for_paths(paths, 2, leaf_types)

        self.assertEqual(meta[69]["chain_root_dex_id"], 69)
        self.assertEqual(meta[70]["chain_stage_order"], 1)
        self.assertEqual(meta[71]["chain_stage_order"], 2)
        self.assertEqual(meta[69]["chain_sort_type"], "Grass")

    def test_type_rank_order(self):
        self.assertLess(tcg_type_rank("Grass"), tcg_type_rank("Fire"))
        self.assertLess(tcg_type_rank("Fire"), tcg_type_rank("Psychic"))


if __name__ == "__main__":
    unittest.main()
