"""Tests for CubeKoga / TTS cube import parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spelltag_cube_import import (  # noqa: E402
    extract_cube_entries,
    parse_face_url,
    _candidate_card_ids,
    _normalize_name,
)


def test_parse_pokemontcg_face_url() -> None:
    url = "https://images.pokemontcg.io/pop4/5_hires.png?c=0"
    assert parse_face_url(url) == ("pop4", "5")


def test_parse_pkmncards_face_url() -> None:
    url = "https://pkmncards.com/wp-content/uploads/sv10_en_181_std.jpg?c=312"
    assert parse_face_url(url) == ("sv10", "181")


def test_candidate_ids_include_tcgdex_alias() -> None:
    ids = _candidate_card_ids("sv1", "3")
    assert "sv1-3" in ids
    assert "sv01-3" in ids


def test_normalize_name_strips_noise() -> None:
    assert _normalize_name("Grovyle I'") == "grovyle"
    assert _normalize_name("Snorlax I'") == "snorlax"


def test_extract_entries_from_fixture() -> None:
    fixture = {
        "ObjectStates": [
            {
                "CustomDeck": {
                    "1": {
                        "FaceURL": "https://images.pokemontcg.io/ex14/19_hires.png",
                    }
                },
                "ContainedObjects": [
                    {
                        "Name": "Card",
                        "Nickname": "Grovyle I'",
                        "CardID": 100,
                        "Memo": "019",
                    }
                ],
            }
        ]
    }
    rows = extract_cube_entries(fixture)
    assert len(rows) == 1
    assert rows[0]["nickname"] == "Grovyle I'"
    assert "ex14/19" in rows[0]["face_url"]


if __name__ == "__main__":
    test_parse_pokemontcg_face_url()
    test_parse_pkmncards_face_url()
    test_candidate_ids_include_tcgdex_alias()
    test_normalize_name_strips_noise()
    test_extract_entries_from_fixture()
    print("ok")
