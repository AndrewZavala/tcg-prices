"""Tests for tcgcsv product matching in refresh_pokemon_prices."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_pokemon_prices import (  # noqa: E402
    Product,
    build_price_rows,
    group_name_keys,
    match_card,
    norm_card_name,
    norm_number,
    norm_set_name,
)


def _product(pid: str, gid: int, name: str, number: str) -> Product:
    return Product(
        product_id=pid,
        group_id=gid,
        name=name,
        norm_name=norm_card_name(name),
        norm_number=norm_number(number),
        has_qualifier="(" in name or " - " in name,
    )


def _index(products: list[Product]) -> dict:
    out: dict = defaultdict(list)
    for p in products:
        out[(p.group_id, p.norm_number)].append(p)
    return out


def test_norm_number() -> None:
    assert norm_number("001/102") == "1"
    assert norm_number("SWSH001") == "swsh1"
    assert norm_number("TG05/TG30") == "tg5"
    assert norm_number("SV049") == "sv49"
    assert norm_number("046") == "46"


def test_norm_card_name() -> None:
    assert norm_card_name("Kingler (Delta Species)") == norm_card_name("Kingler δ")
    assert norm_card_name("Mew Star (Delta Species)") == norm_card_name("Mew ★ δ")
    assert norm_card_name("Volcanion - XY185") == "volcanion"
    assert norm_card_name("Pokemon Catcher") == norm_card_name("Pokémon Catcher")


def test_group_name_keys_strip_prefixes() -> None:
    assert norm_set_name("Crown Zenith Galarian Gallery") in group_name_keys(
        "SWSH: Crown Zenith: Galarian Gallery"
    )
    assert norm_set_name("Dragon Frontiers") in group_name_keys("EX Dragon Frontiers")
    assert norm_set_name("Black & White") in group_name_keys("Black and White")
    assert norm_set_name("Astral Radiance Trainer Gallery") in group_name_keys(
        "SWSH10: Astral Radiance Trainer Gallery"
    )


def test_match_card_by_number_and_name() -> None:
    idx = _index(
        [
            _product("1", 10, "Kingler (Delta Species)", "22/100"),
            _product("2", 10, "Krabby", "23/100"),
        ]
    )
    card = {"name": "Kingler δ", "local_id": "22"}
    assert match_card(card, {10}, idx, set()) == "1"


def test_match_card_prefers_plain_name_when_ambiguous() -> None:
    idx = _index(
        [
            _product("1", 10, "Pikachu", "58/102"),
            _product("2", 10, "Pikachu (Prerelease)", "58/102"),
        ]
    )
    assert match_card({"name": "Pikachu", "local_id": "58"}, {10}, idx, set()) == "1"


def test_match_card_skips_ambiguous_and_taken() -> None:
    idx = _index(
        [
            _product("1", 10, "Darkness Energy (#28)", "28"),
            _product("2", 10, "Darkness Energy (#28)", "28"),
        ]
    )
    assert match_card({"name": "Darkness Energy", "local_id": "28"}, {10}, idx, set()) is None
    assert match_card({"name": "Darkness Energy", "local_id": "28"}, {10}, idx, {"2"}) == "1"


def test_build_price_rows_keeps_variants() -> None:
    rows = build_price_rows(
        {"base1-4": "42382"},
        {
            "42382": [
                {"subTypeName": "Holofoil", "marketPrice": 400.126, "lowPrice": 350},
                {"subTypeName": "Holofoil", "marketPrice": 999},
                {"subTypeName": "Normal"},
            ]
        },
    )
    assert len(rows) == 1
    assert rows[0]["variant"] == "Holofoil"
    assert rows[0]["market_price"] == 400.13
