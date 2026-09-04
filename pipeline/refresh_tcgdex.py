#!/usr/bin/env python3
"""Ingest Pokémon TCG catalog data from TCGdex into Postgres.

Examples:
  python refresh_tcgdex.py --set bw10
  python refresh_tcgdex.py --series bw
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR
from pokemon_card_corrections import correct_abilities, correct_attacks, apply_card_corrections, compute_is_multicolor

TCGDEX_BASE = "https://api.tcgdex.net/v2"
USER_AGENT = "TCGPokemonCatalog/1.0"
REQUEST_DELAY_SEC = 0.05

# Black & White through Legendary Treasures (+ Dragon Vault, promos, Radiant Collection)
BW_SET_IDS = (
    "bw1",   # Black & White
    "bwp",   # BW Black Star Promos
    "bw2",   # Emerging Powers
    "bw3",   # Noble Victories
    "bw4",   # Next Destinies
    "bw5",   # Dark Explorers
    "bw6",   # Dragons Exalted
    "dv1",   # Dragon Vault
    "bw7",   # Boundaries Crossed
    "bw8",   # Plasma Storm
    "bw9",   # Plasma Freeze
    "bw10",  # Plasma Blast
    "bw11",  # Legendary Treasures (+ Radiant Collection as RC## cards)
)

# Mega Evolution block — me01 (Mega Evolution) through me05 (Pitch Black)
ME_BLOCK_SET_IDS = (
    "me01",   # Mega Evolution
    "mep",    # MEP Black Star Promos
    "me02",   # Phantasmal Flames
    "me02.5", # Ascended Heroes
    "me03",   # Perfect Order
    "me04",   # Chaos Rising
    "me05",   # Pitch Black
)

# Scarlet & Violet era (TCGdex series sv — includes promos, energy, Black Bolt / White Flare)
SV_BLOCK_SET_IDS = (
    "sv01",    # Scarlet & Violet
    "sve",     # Scarlet & Violet Energy
    "svp",     # SVP Black Star Promos
    "sv02",    # Paldea Evolved
    "sv03",    # Obsidian Flames
    "sv03.5",  # 151
    "mfb",     # My First Battle
    "sv04",    # Paradox Rift
    "sv04.5",  # Paldean Fates
    "sv05",    # Temporal Forces
    "sv06",    # Twilight Masquerade
    "sv06.5",  # Shrouded Fable
    "sv07",    # Stellar Crown
    "sv08",    # Surging Sparks
    "sv08.5",  # Prismatic Evolutions
    "sv09",    # Journey Together
    "sv10",    # Destined Rivals
    "sv10.5b", # Black Bolt
    "sv10.5w", # White Flare
)

# Sun & Moon era (TCGdex series sm — ~18 sets / ~2.9k printings)
SM_BLOCK_SET_IDS = (
    "sm1",    # Sun & Moon
    "smp",    # SM Black Star Promos
    "sm2",    # Guardians Rising
    "sm3",    # Burning Shadows
    "sm3.5",  # Shining Legends
    "sm4",    # Crimson Invasion
    "sm5",    # Ultra Prism
    "sm6",    # Forbidden Light
    "sm7",    # Celestial Storm
    "sm7.5",  # Dragon Majesty
    "sm8",    # Lost Thunder
    "sm9",    # Team Up
    "det1",   # Detective Pikachu
    "sm10",   # Unbroken Bonds
    "sm11",   # Unified Minds
    "sm115",  # Hidden Fates
    "sma",    # Hidden Fates Shiny Vault
    "sm12",   # Cosmic Eclipse
)

# XY era (TCGdex series xy — includes Kalos Starter, Double Crisis, Generations)
XY_BLOCK_SET_IDS = (
    "xyp",   # XY Black Star Promos
    "xy0",   # Kalos Starter Set
    "xy1",   # XY
    "xya",   # Yellow A Alternate
    "xy2",   # Flashfire
    "xy3",   # Furious Fists
    "xy4",   # Phantom Forces
    "xy5",   # Primal Clash
    "dc1",   # Double Crisis
    "xy6",   # Roaring Skies
    "xy7",   # Ancient Origins
    "xy8",   # BREAKthrough
    "xy9",   # BREAKpoint
    "g1",    # Generations
    "xy10",  # Fates Collide
    "xy11",  # Steam Siege
    "xy12",  # Evolutions
)

# HeartGold & SoulSilver era (+ Call of Legends)
HGSS_BLOCK_SET_IDS = (
    "hgss1",  # HeartGold SoulSilver
    "hgssp",  # HGSS Black Star Promos
    "hgss2",  # Unleashed
    "hgss3",  # Undaunted
    "hgss4",  # Triumphant
    "col1",   # Call of Legends
)

# Diamond & Pearl through Platinum (Arceus + Pokémon Rumble)
DP_BLOCK_SET_IDS = (
    "dp1",   # Diamond & Pearl
    "dpp",   # DP Black Star Promos
    "dp2",   # Mysterious Treasures
    "dp3",   # Secret Wonders
    "dp4",   # Great Encounters
    "dp5",   # Majestic Dawn
    "dp6",   # Legends Awakened
    "dp7",   # Stormfront
    "pl1",   # Platinum
    "pl2",   # Rising Rivals
    "pl3",   # Supreme Victors
    "pl4",   # Arceus
    "ru1",   # Pokémon Rumble
)

# EX era — Ruby & Sapphire through Power Keepers
EX_BLOCK_SET_IDS = (
    "ex1",    # Ruby & Sapphire
    "ex2",    # Sandstorm
    "ex3",    # Dragon
    "ex4",    # Team Magma vs Team Aqua
    "ex5",    # Hidden Legends
    "ex5.5",  # Poké Card Creator Pack
    "ex6",    # FireRed & LeafGreen
    "ex7",    # Team Rocket Returns
    "ex8",    # Deoxys
    "ex9",    # Emerald
    "exu",    # Unseen Forces Unown Collection
    "ex10",   # Unseen Forces
    "ex11",   # Delta Species
    "ex12",   # Legend Maker
    "ex13",   # Holon Phantoms
    "ex14",   # Crystal Guardians
    "ex15",   # Dragon Frontiers
    "ex16",   # Power Keepers
)

# Wizards of the Coast era — Base Set through Skyridge
WOTC_BLOCK_SET_IDS = (
    "base1",   # Base Set
    "base2",   # Jungle
    "basep",   # Wizards Black Star Promos
    "wp",      # W Promotional
    "base3",   # Fossil
    "base4",   # Base Set 2
    "base5",   # Team Rocket
    "gym1",    # Gym Heroes
    "gym2",    # Gym Challenge
    "neo1",    # Neo Genesis
    "neo2",    # Neo Discovery
    "si1",     # Southern Islands
    "neo3",    # Neo Revelation
    "neo4",    # Neo Destiny
    "lc",      # Legendary Collection
    "ecard1",  # Expedition Base Set
    "bog",     # Best of Game
    "ecard2",  # Aquapolis
    "ecard3",  # Skyridge
)

# Sword & Shield era (TCGdex series swsh)
SWSH_BLOCK_SET_IDS = (
    "swshp",      # SWSH Black Star Promos
    "swsh1",      # Sword & Shield
    "swsh2",      # Rebel Clash
    "swsh3",      # Darkness Ablaze
    "fut2020",    # Pokémon Futsal 2020
    "swsh3.5",    # Champion's Path
    "swsh4",      # Vivid Voltage
    "swsh4.5",    # Shining Fates
    "swsh4.5sv",  # Shining Fates Shiny Vault
    "swsh5",      # Battle Styles
    "swsh6",      # Chilling Reign
    "swsh7",      # Evolving Skies
    "cel25",      # Celebrations
    "cel25cc",    # Celebrations Classic Collection
    "swsh8",      # Fusion Strike
    "swsh9",      # Brilliant Stars
    "swsh9.5tg",  # Brilliant Stars Trainer Gallery
    "swsh10",     # Astral Radiance
    "swsh10.5tg", # Astral Radiance Trainer Gallery
    "swsh10.5",   # Pokémon GO
    "swsh11",     # Lost Origin
    "swsh11.5tg", # Lost Origin Trainer Gallery
    "swsh12",     # Silver Tempest
    "swsh12.5tg", # Silver Tempest Trainer Gallery
    "swsh12.5",   # Crown Zenith
    "swsh12.5gg", # Crown Zenith Galarian Gallery
)

# POP Series 1–9
POP_BLOCK_SET_IDS = (
    "pop1",
    "pop2",
    "pop3",
    "pop4",
    "pop5",
    "pop6",
    "pop7",
    "pop8",
    "pop9",
)

# Nintendo Black Star Promos
NP_BLOCK_SET_IDS = (
    "np",
)

# McDonald's Collections
MCD_BLOCK_SET_IDS = (
    "2011bw",    # McDonald's Collection 2011
    "2012bw",    # McDonald's Collection 2012
    "2014xy",    # McDonald's Collection 2014
    "2015xy",    # McDonald's Collection 2015
    "2016xy",    # McDonald's Collection 2016
    "2017sm",    # McDonald's Collection 2017
    "2018sm",    # McDonald's Collection 2018
    "2019sm",    # McDonald's Collection 2019
    "2021swsh",  # McDonald's Collection 2021
    "2022swsh",  # McDonald's Collection 2022
    "2023sv",    # McDonald's Collection 2023
    "2024sv",    # McDonald's Collection 2024
)

# Official Trainer Kits (EX through SM)
TK_BLOCK_SET_IDS = (
    "tk-ex-latia",  # EX trainer Kit (Latias)
    "tk-ex-latio",  # EX trainer Kit (Latios)
    "tk-ex-m",      # EX trainer Kit 2 (Minun)
    "tk-ex-p",      # EX trainer Kit 2 (Plusle)
    "tk-dp-l",      # DP trainer Kit (Lucario)
    "tk-dp-m",      # DP trainer Kit (Manaphy)
    "tk-hs-g",      # HS trainer Kit (Gyarados)
    "tk-hs-r",      # HS trainer Kit (Raichu)
    "tk-bw-e",      # BW trainer Kit (Excadrill)
    "tk-bw-z",      # BW trainer Kit (Zoroark)
    "tk-xy-b",      # XY trainer Kit (Bisharp)
    "tk-xy-latia",  # XY trainer Kit (Latias)
    "tk-xy-latio",  # XY trainer Kit (Latios)
    "tk-xy-n",      # XY trainer Kit (Noivern)
    "tk-xy-p",      # XY trainer Kit (Pikachu Libre)
    "tk-xy-su",     # XY trainer Kit (Suicune)
    "tk-xy-sy",     # XY trainer Kit (Sylveon)
    "tk-xy-w",      # XY trainer Kit (Wigglytuff)
    "tk-sm-l",      # SM trainer Kit (Lycanroc)
    "tk-sm-r",      # SM trainer Kit (Alolan Raichu)
)

# Combined side products (POP + Nintendo promos + McDonald's + Trainer Kits)
SIDE_BLOCK_SET_IDS = (
    *POP_BLOCK_SET_IDS,
    *NP_BLOCK_SET_IDS,
    *MCD_BLOCK_SET_IDS,
    *TK_BLOCK_SET_IDS,
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get_json(session: requests.Session, url: str) -> Any:
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _tcgplayer_product_id(pricing: dict[str, Any] | None) -> str | None:
    """Best TCGplayer product id from TCGdex pricing block."""
    tp = (pricing or {}).get("tcgplayer") or {}
    if not isinstance(tp, dict):
        return None
    for key in (
        "normal",
        "holofoil",
        "reverse-holofoil",
        "1st-edition",
        "1st-edition-holofoil",
        "unlimited",
        "unlimited-holofoil",
    ):
        block = tp.get(key)
        if isinstance(block, dict) and block.get("productId"):
            return str(block["productId"])
    return None


def _strip_pricing(card: dict[str, Any]) -> dict[str, Any]:
    """Drop price fields; catalog-only ingest for now."""
    out = dict(card)
    out.pop("pricing", None)
    detailed = out.get("variants_detailed")
    if isinstance(detailed, list):
        cleaned = []
        for item in detailed:
            if not isinstance(item, dict):
                cleaned.append(item)
                continue
            row = dict(item)
            row.pop("pricing", None)
            cleaned.append(row)
        out["variants_detailed"] = cleaned
    return out


def apply_migration(engine) -> None:
    mig = MIGRATIONS_DIR / "025_pokemon_catalog.sql"
    if not mig.exists():
        raise FileNotFoundError(mig)
    with engine.begin() as conn:
        conn.execute(text(mig.read_text(encoding="utf-8")))


def list_set_card_ids(session: requests.Session, lang: str, set_id: str) -> list[str]:
    """List card ids for one set. Uses strict eq filter so bw1 does not match bw10/bw11."""
    page = 1
    per_page = 250
    ids: list[str] = []
    while True:
        url = (
            f"{TCGDEX_BASE}/{lang}/cards"
            f"?set.id=eq:{set_id}&pagination:page={page}&pagination:itemsPerPage={per_page}"
        )
        rows = _get_json(session, url)
        if not isinstance(rows, list):
            raise ValueError(f"Unexpected card list response for set {set_id}")
        if not rows:
            break
        ids.extend(str(row["id"]) for row in rows if row.get("id"))
        if len(rows) < per_page:
            break
        page += 1
    return ids


def fetch_set(session: requests.Session, lang: str, set_id: str) -> dict[str, Any]:
    return _get_json(session, f"{TCGDEX_BASE}/{lang}/sets/{set_id}")


def fetch_card(session: requests.Session, lang: str, card_id: str) -> dict[str, Any]:
    # Some list payloads pre-encode localIds (e.g. exu-%3F for "?"). Encode the
    # path segment so "%" / "?" / "!" reach TCGdex as the intended card id.
    encoded = quote(str(card_id), safe="-_.")
    return _get_json(session, f"{TCGDEX_BASE}/{lang}/cards/{encoded}")


def upsert_set(conn, set_obj: dict[str, Any]) -> None:
    serie = set_obj.get("serie") or {}
    legal = set_obj.get("legal") or {}
    counts = set_obj.get("cardCount") or {}
    tcg_online = set_obj.get("tcgOnline")
    if tcg_online is None and isinstance(set_obj.get("abbreviation"), dict):
        tcg_online = set_obj["abbreviation"].get("official")

    conn.execute(
        text(
            """
            INSERT INTO pokemon_sets (
                id, name, series_id, series_name, release_date,
                logo_url, symbol_url, card_count_official, card_count_total,
                legal_standard, legal_expanded, tcg_online_code,
                source_updated_at, synced_at
            ) VALUES (
                :id, :name, :series_id, :series_name, :release_date,
                :logo_url, :symbol_url, :card_count_official, :card_count_total,
                :legal_standard, :legal_expanded, :tcg_online_code,
                :source_updated_at, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                series_id = EXCLUDED.series_id,
                series_name = EXCLUDED.series_name,
                release_date = EXCLUDED.release_date,
                logo_url = EXCLUDED.logo_url,
                symbol_url = EXCLUDED.symbol_url,
                card_count_official = EXCLUDED.card_count_official,
                card_count_total = EXCLUDED.card_count_total,
                legal_standard = EXCLUDED.legal_standard,
                legal_expanded = EXCLUDED.legal_expanded,
                tcg_online_code = EXCLUDED.tcg_online_code,
                source_updated_at = EXCLUDED.source_updated_at,
                synced_at = NOW()
            """
        ),
        {
            "id": set_obj["id"],
            "name": set_obj.get("name"),
            "series_id": serie.get("id"),
            "series_name": serie.get("name"),
            "release_date": _parse_date(set_obj.get("releaseDate")),
            "logo_url": set_obj.get("logo"),
            "symbol_url": set_obj.get("symbol"),
            "card_count_official": counts.get("official"),
            "card_count_total": counts.get("total"),
            "legal_standard": bool(legal.get("standard")),
            "legal_expanded": bool(legal.get("expanded")),
            "tcg_online_code": tcg_online,
            "source_updated_at": _parse_ts(set_obj.get("updated")),
        },
    )


def upsert_card(conn, card: dict[str, Any]) -> None:
    legal = card.get("legal") or {}
    cleaned = _strip_pricing(card)
    card_id = str(card.get("id") or "")
    set_obj = card.get("set") if isinstance(card.get("set"), dict) else {}
    set_id = str(set_obj.get("id") or "") or None
    abilities = correct_abilities(card_id, card.get("abilities") or [], set_id=set_id)
    attacks = correct_attacks(card_id, card.get("attacks") or [])
    stage = card.get("stage")
    patched = apply_card_corrections(
        {
            "id": card_id,
            "set_id": set_id,
            "set": set_obj,
            "category": card.get("category"),
            "hp": card.get("hp"),
            "types": card.get("types"),
            "dexId": card.get("dexId"),
            "abilities": abilities,
            "attacks": attacks,
            "stage": stage,
            "card_data": cleaned if isinstance(cleaned, dict) else {},
        }
    )
    abilities = patched.get("abilities") or []
    attacks = patched.get("attacks") or []
    stage = patched.get("stage")
    if isinstance(cleaned, dict):
        cleaned = patched.get("card_data") or cleaned
    category = patched.get("category") or card.get("category") or "Unknown"
    is_multicolor = compute_is_multicolor(
        {
            "id": card_id,
            "category": category,
            "types": card.get("types"),
            "attacks": attacks,
            "abilities": patched.get("abilities") or abilities,
            "description": card.get("description") or card.get("effect"),
            "card_data": cleaned if isinstance(cleaned, dict) else {},
        }
    )
    conn.execute(
        text(
            """
            INSERT INTO pokemon_cards (
                id, set_id, local_id, name, category, hp, types, stage,
                evolve_from, dex_ids, description, rarity, illustrator,
                regulation_mark, legal_standard, legal_expanded, image_url,
                retreat, attacks, abilities, weaknesses, resistances, variants,
                tcgplayer_product_id, card_data, is_multicolor, source_updated_at, synced_at
            ) VALUES (
                :id, :set_id, :local_id, :name, :category, :hp, :types, :stage,
                :evolve_from, :dex_ids, :description, :rarity, :illustrator,
                :regulation_mark, :legal_standard, :legal_expanded, :image_url,
                :retreat, CAST(:attacks AS jsonb), CAST(:abilities AS jsonb),
                CAST(:weaknesses AS jsonb), CAST(:resistances AS jsonb),
                CAST(:variants AS jsonb), :tcgplayer_product_id,
                CAST(:card_data AS jsonb), :is_multicolor, :source_updated_at, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                set_id = EXCLUDED.set_id,
                local_id = EXCLUDED.local_id,
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                hp = EXCLUDED.hp,
                types = EXCLUDED.types,
                stage = EXCLUDED.stage,
                evolve_from = EXCLUDED.evolve_from,
                dex_ids = EXCLUDED.dex_ids,
                description = EXCLUDED.description,
                rarity = EXCLUDED.rarity,
                illustrator = EXCLUDED.illustrator,
                regulation_mark = EXCLUDED.regulation_mark,
                legal_standard = EXCLUDED.legal_standard,
                legal_expanded = EXCLUDED.legal_expanded,
                image_url = EXCLUDED.image_url,
                retreat = EXCLUDED.retreat,
                attacks = EXCLUDED.attacks,
                abilities = EXCLUDED.abilities,
                weaknesses = EXCLUDED.weaknesses,
                resistances = EXCLUDED.resistances,
                variants = EXCLUDED.variants,
                tcgplayer_product_id = EXCLUDED.tcgplayer_product_id,
                card_data = EXCLUDED.card_data,
                is_multicolor = EXCLUDED.is_multicolor,
                source_updated_at = EXCLUDED.source_updated_at,
                synced_at = NOW()
            """
        ),
        {
            "id": card["id"],
            "set_id": (card.get("set") or {}).get("id") or card["id"].split("-", 1)[0],
            "local_id": unquote(str(card.get("localId", "") or "")),
            "name": card.get("name"),
            "category": category,
            "hp": card.get("hp"),
            "types": card.get("types"),
            "stage": stage,
            "evolve_from": card.get("evolveFrom"),
            "dex_ids": card.get("dexId"),
            "description": card.get("description") or card.get("effect"),
            "rarity": card.get("rarity"),
            "illustrator": card.get("illustrator"),
            "regulation_mark": card.get("regulationMark"),
            "legal_standard": legal.get("standard"),
            "legal_expanded": legal.get("expanded"),
            "image_url": card.get("image"),
            "retreat": card.get("retreat"),
            "attacks": json.dumps(attacks),
            "abilities": json.dumps(abilities),
            "weaknesses": json.dumps(card.get("weaknesses") or []),
            "resistances": json.dumps(card.get("resistances") or []),
            "variants": json.dumps(card.get("variants") or {}),
            "tcgplayer_product_id": _tcgplayer_product_id(card.get("pricing")),
            "card_data": json.dumps(cleaned),
            "is_multicolor": is_multicolor,
            "source_updated_at": _parse_ts(card.get("updated")),
        },
    )


def ingest_set(engine, lang: str, set_id: str) -> int:
    session = _session()
    print(f"Fetching set {set_id} ({lang})...")
    set_obj = fetch_set(session, lang, set_id)
    card_ids = list_set_card_ids(session, lang, set_id)
    if not card_ids:
        print(f"  skipped — no cards listed for {set_id}")
        return 0

    print(f"Found {len(card_ids)} cards; fetching full details...")
    cards: list[dict[str, Any]] = []
    for i, card_id in enumerate(card_ids, start=1):
        cards.append(fetch_card(session, lang, card_id))
        if i % 25 == 0 or i == len(card_ids):
            print(f"  fetched {i}/{len(card_ids)}")
        time.sleep(REQUEST_DELAY_SEC)

    with engine.begin() as conn:
        upsert_set(conn, set_obj)
        for card in cards:
            upsert_card(conn, card)
        conn.execute(
            text(
                """
                INSERT INTO pokemon_sync_log (set_id, cards_upserted)
                VALUES (:set_id, :cards_upserted)
                """
            ),
            {"set_id": set_id, "cards_upserted": len(cards)},
        )

    return len(cards)


def fetch_series_sets(session: requests.Session, lang: str, series_id: str) -> list[str]:
    data = _get_json(session, f"{TCGDEX_BASE}/{lang}/series/{series_id}")
    sets = data.get("sets") or []
    return [str(s["id"]) for s in sets if s.get("id")]


def ingest_sets(engine, lang: str, set_ids: list[str]) -> int:
    total = 0
    for set_id in set_ids:
        total += ingest_set(engine, lang, set_id)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Pokémon cards from TCGdex")
    parser.add_argument(
        "--set",
        action="append",
        dest="sets",
        metavar="ID",
        help="TCGdex set id (repeatable), e.g. bw10",
    )
    parser.add_argument(
        "--series",
        help="Ingest all sets in a TCGdex series, e.g. bw",
    )
    parser.add_argument("--lang", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip applying 025_pokemon_catalog.sql",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Run post-ingest enrichment (subtypes, species, oracle) for ingested set(s)",
    )
    args = parser.parse_args()

    set_ids: list[str] = []
    if args.series:
        if args.series.lower() == "bw":
            set_ids = list(BW_SET_IDS)
        elif args.series.lower() == "me":
            set_ids = list(ME_BLOCK_SET_IDS)
        elif args.series.lower() == "sv":
            set_ids = list(SV_BLOCK_SET_IDS)
        elif args.series.lower() == "sm":
            set_ids = list(SM_BLOCK_SET_IDS)
        elif args.series.lower() == "xy":
            set_ids = list(XY_BLOCK_SET_IDS)
        elif args.series.lower() == "hgss":
            set_ids = list(HGSS_BLOCK_SET_IDS)
        elif args.series.lower() == "dp":
            set_ids = list(DP_BLOCK_SET_IDS)
        elif args.series.lower() == "ex":
            set_ids = list(EX_BLOCK_SET_IDS)
        elif args.series.lower() in ("wotc", "wizards"):
            set_ids = list(WOTC_BLOCK_SET_IDS)
        elif args.series.lower() == "swsh":
            set_ids = list(SWSH_BLOCK_SET_IDS)
        elif args.series.lower() in ("side", "extras"):
            set_ids = list(SIDE_BLOCK_SET_IDS)
        elif args.series.lower() == "pop":
            set_ids = list(POP_BLOCK_SET_IDS)
        elif args.series.lower() in ("np", "nintendo"):
            set_ids = list(NP_BLOCK_SET_IDS)
        elif args.series.lower() in ("mcd", "mcdonalds", "mcdonald"):
            set_ids = list(MCD_BLOCK_SET_IDS)
        elif args.series.lower() in ("tk", "trainer-kits", "trainers"):
            set_ids = list(TK_BLOCK_SET_IDS)
        else:
            session = _session()
            set_ids = fetch_series_sets(session, args.lang, args.series.lower())
    if args.sets:
        set_ids.extend(args.sets)
    if not set_ids:
        set_ids = ["bw10"]

    # Stable order, dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for sid in set_ids:
        key = sid.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying pokemon catalog migration...")
        apply_migration(engine)

    print(f"Ingesting {len(ordered)} set(s): {', '.join(ordered)}")
    total = ingest_sets(engine, args.lang, ordered)
    print(f"Done — upserted {total} cards across {len(ordered)} set(s).")

    if args.enrich:
        import subprocess

        side_set_ids = frozenset(s.lower() for s in SIDE_BLOCK_SET_IDS)
        skip_oracle = all(sid in side_set_ids for sid in ordered)

        enrich_cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "enrich_pokemon.py"),
            "--skip-migration",
            *[arg for sid in ordered for arg in ("--set", sid)],
        ]
        if skip_oracle:
            enrich_cmd.append("--skip-oracle")
            print("\nRunning post-ingest enrichment (incremental oracle for side sets)...")
        else:
            print("\nRunning post-ingest enrichment...")
        subprocess.run(enrich_cmd, check=True)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
