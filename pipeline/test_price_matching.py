"""Tests for tcgcsv product matching in refresh_pokemon_prices."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_pokemon_prices import (  # noqa: E402
    Product,
    apply_product_id_corrections,
    build_price_rows,
    missing_image_urls,
    group_name_keys,
    match_card,
    norm_card_name,
    norm_number,
    norm_set_name,
    qualifier_count,
)


def _product(pid: str, gid: int, name: str, number: str) -> Product:
    return Product(
        product_id=pid,
        group_id=gid,
        name=name,
        norm_name=norm_card_name(name),
        norm_number=norm_number(number),
        qualifiers=qualifier_count(name),
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
    assert norm_card_name("Basic Lightning Energy - 012") == norm_card_name("Lightning Energy")
    assert norm_card_name("Drapion E4") == norm_card_name("Drapion 4")
    assert norm_card_name("Team Aqua Technical Machine 01") == norm_card_name(
        "Team Aqua's Technical Machine 01"
    )
    assert norm_card_name("Unit Energy GRW") == norm_card_name("Unit Energy GrassFireWater")
    assert norm_card_name("Blend Energy WLFM") == norm_card_name(
        "Blend Energy Water Lightning Fighting Metal"
    )
    assert norm_card_name(
        "Professor's Research [Professor Willow] - SWSH178"
    ) == norm_card_name("Professor's Research")


def test_qualifier_count_ignores_number_suffix() -> None:
    assert qualifier_count("Delphox - 074") == 0
    assert qualifier_count("Delphox - 074 [Staff]") == 1
    assert qualifier_count("Baxcalibur - 019 (Prerelease) [Staff]") == 2
    assert qualifier_count("Pikachu - Worlds") == 1


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


def test_match_card_prefers_fewest_variant_labels() -> None:
    idx = _index(
        [
            _product("1", 24451, "Delphox - 074", "074"),
            _product("2", 24451, "Delphox - 074 [Staff]", "074"),
            _product("3", 22872, "Baxcalibur - 019 (Prerelease)", "019"),
            _product("4", 22872, "Baxcalibur - 019 (Prerelease) [Staff]", "019"),
            _product("5", 22872, "Scraggy - BW25 (Cosmos Holo)", "BW25"),
            _product("6", 22872, "Scraggy - BW25 (Cracked Ice Holo)", "BW25"),
        ]
    )
    assert match_card({"name": "Delphox", "local_id": "074"}, {24451}, idx, set()) == "1"
    assert match_card({"name": "Baxcalibur", "local_id": "019"}, {22872}, idx, set()) == "3"
    # Equal labels are a real tie — leave unmatched.
    assert match_card({"name": "Scraggy", "local_id": "BW25"}, {22872}, idx, set()) is None


def test_match_card_skips_ambiguous_and_taken() -> None:
    idx = _index(
        [
            _product("1", 10, "Darkness Energy (#28)", "28"),
            _product("2", 10, "Darkness Energy (#28)", "28"),
        ]
    )
    assert match_card({"name": "Darkness Energy", "local_id": "28"}, {10}, idx, set()) is None
    assert match_card({"name": "Darkness Energy", "local_id": "28"}, {10}, idx, {"2"}) == "1"


def test_match_card_name_only_ignores_reprint_numbers() -> None:
    products = [
        _product("1", 24837, "Charizard", "4/102"),
        _product("2", 24837, "Pikachu & Zekrom GX", "33/181"),
        _product("3", 24837, "Metagross (Delta Species)", "11/113"),
    ]
    by_group = {24837: products}
    idx = _index(products)
    assert match_card({"name": "Charizard", "local_id": "001"}, {24837}, idx, set(), by_group=by_group) == "1"
    assert match_card({"name": "Metagross", "local_id": "003"}, {24837}, idx, set(), by_group=by_group) == "3"
    # Name-only never falls back to prefix matches.
    assert match_card({"name": "Pikachu", "local_id": "009"}, {24837}, idx, set(), by_group=by_group) is None
    assert match_card({"name": "Charizard", "local_id": "001"}, {24837}, idx, set()) is None


def test_missing_image_urls_skips_cards_with_art_and_promo_sets() -> None:
    cards = [
        {"id": "30th-c-001", "set_id": "30th-c", "image_url": None, "image_local": False},
        {"id": "30th-001", "set_id": "30th", "image_url": "https://assets/x", "image_local": False},
        {"id": "mep-001", "set_id": "mep", "image_url": None, "image_local": False},
        {"id": "exu-1", "set_id": "exu", "image_url": None, "image_local": True},
    ]
    products = {c["id"]: "714372" for c in cards}
    assert missing_image_urls(cards, products) == {
        "30th-c-001": "https://tcgplayer-cdn.tcgplayer.com/product/714372_in_1000x1000.jpg"
    }


def test_cel25cc_product_ids_are_corrected() -> None:
    cards = [
        {"id": "cel25cc-CC002", "tcgplayer_product_id": None},
        {"id": "cel25cc-CC020", "tcgplayer_product_id": "250301"},
        {"id": "cel25-2", "tcgplayer_product_id": "250301"},
    ]
    corrected = apply_product_id_corrections(cards)
    assert corrected == {"cel25cc-CC002": "250320", "cel25cc-CC020": "250337"}
    assert cards[2]["tcgplayer_product_id"] == "250301"


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
