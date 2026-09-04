"""Accent-insensitive name search helpers."""

import unittest

from pokemon_api import fold_accents, _sql_accent_fold


class AccentFoldTests(unittest.TestCase):
    def test_pokemon_accent_folds(self):
        self.assertEqual(fold_accents("Pokémon").lower(), "pokemon")
        self.assertEqual(fold_accents("Pokemon").lower(), "pokemon")
        self.assertEqual(fold_accents("POKÉMON").lower(), "pokemon")

    def test_other_accented_names(self):
        self.assertEqual(fold_accents("Flabébé").lower(), "flabebe")
        self.assertEqual(fold_accents("Nidoran♀"), "Nidoran♀")

    def test_sql_helper_uses_translate(self):
        sql = _sql_accent_fold("c.name")
        self.assertIn("translate(lower(c.name)", sql)
        self.assertIn("é", sql)
        from pokemon_api import _ACCENT_FROM, _ACCENT_TO

        self.assertEqual(len(_ACCENT_FROM), len(_ACCENT_TO))


if __name__ == "__main__":
    unittest.main()
