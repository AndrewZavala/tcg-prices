"""Tests for type-sort rank helpers (mirrors pokemon_api SQL logic)."""

import unittest


def trainer_subtype_rank(tags: list[str] | None) -> int:
    tags = tags or []
    if "supporter" in tags:
        return 1
    if "item" in tags:
        return 2
    if "pokemon-tool" in tags:
        return 3
    if "stadium" in tags:
        return 4
    return 99


def energy_kind_rank(tags: list[str] | None) -> int:
    tags = tags or []
    return 2 if "special" in tags else 1


class TypeSortRankTests(unittest.TestCase):
    def test_trainer_subtype_order(self):
        self.assertLess(trainer_subtype_rank(["supporter"]), trainer_subtype_rank(["item"]))
        self.assertLess(trainer_subtype_rank(["item"]), trainer_subtype_rank(["pokemon-tool"]))
        self.assertLess(trainer_subtype_rank(["pokemon-tool"]), trainer_subtype_rank(["stadium"]))

    def test_energy_basic_before_special(self):
        self.assertLess(energy_kind_rank(["basic"]), energy_kind_rank(["special"]))
        self.assertEqual(energy_kind_rank([]), 1)


if __name__ == "__main__":
    unittest.main()
