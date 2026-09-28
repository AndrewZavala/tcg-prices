#!/usr/bin/env python3
"""Refresh latest TCGplayer USD prices for Spell Tag from tcgcsv.com (English Pokémon, category 3).

Runs monthly. ~1 groups request + 220 prices requests + 220 products requests.
Products are used to fill in missing pokemon_cards.tcgplayer_product_id by set + number + name.

Examples:
  python refresh_pokemon_prices.py
  python refresh_pokemon_prices.py --dry-run
  python refresh_pokemon_prices.py --no-match
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL

POKEMON_CATEGORY_ID = 3
TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
USER_AGENT = "SpellTag/1.0 (https://github.com/AndrewZavala/tcg-prices)"
REQUEST_DELAY_SEC = 0.15

# Refuse to replace prices when tcgcsv returns far less than a normal month.
MIN_PRICED_CARDS = 5000

# Spell Tag set id -> tcgcsv group ids, for sets whose names don't line up.
GROUP_ALIASES: dict[str, tuple[int, ...]] = {
    "swshp": (2545,),
    "smp": (1861,),
    "svp": (22872,),
    "xyp": (1451,),
    "bwp": (1407,),
    "dpp": (1421,),
    "hgssp": (1453,),
    "np": (1423,),
    "mep": (24451,),
    "sve": (24382,),
    "ru1": (1433,),
    "exu": (1398,),
    "g1": (1728, 1729),
    "bw11": (1409, 1465),
    "2021swsh": (2782,),
    "2022swsh": (3150,),
    "2023sv": (23306,),
    "2024sv": (24163,),
    "tk-ex-latia": (1543,),
    "tk-ex-latio": (1543,),
    "tk-ex-m": (1542,),
    "tk-ex-p": (1542,),
    "tk-dp-l": (1541,),
    "tk-dp-m": (1541,),
    "tk-hs-g": (1540,),
    "tk-hs-r": (1540,),
    "tk-bw-e": (1538,),
    "tk-bw-z": (1538,),
    "tk-xy-latia": (1536,),
    "tk-xy-latio": (1536,),
    "tk-xy-b": (1533,),
    "tk-xy-w": (1533,),
    "tk-xy-n": (1532,),
    "tk-xy-sy": (1532,),
    "tk-xy-p": (1796,),
    "tk-xy-su": (1796,),
    "tk-sm-l": (2069,),
    "tk-sm-r": (2069,),
}

_GROUP_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+(?:\s*:\s*TG)?\s*(?::|\s-)\s*")
_NUMBER_RE = re.compile(r"^([a-z]*)0*(\d+)([a-z]*)$")


@dataclass
class Product:
    product_id: str
    group_id: int
    name: str
    norm_name: str
    norm_number: str
    has_qualifier: bool


def _fold(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def norm_set_name(value: str) -> str:
    s = _fold(value).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]", "", s)


def group_name_keys(name: str) -> set[str]:
    keys = {norm_set_name(name)}
    stripped = _GROUP_PREFIX_RE.sub("", name or "", count=1)
    keys.add(norm_set_name(stripped))
    if stripped.lower().startswith("ex "):
        keys.add(norm_set_name(stripped[3:]))
    keys.discard("")
    return keys


def norm_card_name(value: str) -> str:
    s = _fold(value or "").replace("★", " star ").replace("δ", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\s+-\s+.*$", "", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_number(value: str) -> str:
    s = str(value or "").split("/")[0].strip().lower()
    m = _NUMBER_RE.match(s)
    if m:
        return f"{m.group(1)}{int(m.group(2))}{m.group(3)}"
    return re.sub(r"[^a-z0-9]", "", s)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _fetch_results(session: requests.Session, url: str) -> list[dict[str, Any]]:
    for attempt in range(3):
        resp = session.get(url, timeout=120)
        if resp.status_code == 404:
            return []
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        resp.raise_for_status()
        payload = resp.json()
        return list(payload.get("results") or []) if isinstance(payload, dict) else []
    return []


def _to_price(value: Any) -> float | None:
    try:
        return None if value is None else round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _product_from_json(item: dict[str, Any], group_id: int) -> Product | None:
    pid = item.get("productId")
    if not pid:
        return None
    number = ""
    for ext in item.get("extendedData") or []:
        if isinstance(ext, dict) and ext.get("name") == "Number":
            number = str(ext.get("value") or "")
            break
    if not number:
        return None
    name = str(item.get("name") or "")
    return Product(
        product_id=str(pid),
        group_id=group_id,
        name=name,
        norm_name=norm_card_name(name),
        norm_number=norm_number(number),
        has_qualifier="(" in name or " - " in name,
    )


def fetch_tcgcsv(*, with_products: bool) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, int],
    list[Product],
]:
    """Return (groups, prices by product id, product id -> group id, products)."""
    session = _session()
    groups = _fetch_results(session, f"{TCGCSV_BASE}/{POKEMON_CATEGORY_ID}/groups")
    if not groups:
        raise RuntimeError("tcgcsv returned no Pokémon groups")

    prices: dict[str, list[dict[str, Any]]] = defaultdict(list)
    product_group: dict[str, int] = {}
    products: list[Product] = []
    total = len(groups)
    for idx, group in enumerate(groups, start=1):
        gid = int(group["groupId"])
        for item in _fetch_results(session, f"{TCGCSV_BASE}/{POKEMON_CATEGORY_ID}/{gid}/prices"):
            pid = item.get("productId")
            if not pid:
                continue
            product_group[str(pid)] = gid
            prices[str(pid)].append(item)
        time.sleep(REQUEST_DELAY_SEC)
        if with_products:
            for item in _fetch_results(
                session, f"{TCGCSV_BASE}/{POKEMON_CATEGORY_ID}/{gid}/products"
            ):
                prod = _product_from_json(item, gid)
                if prod:
                    products.append(prod)
                    product_group.setdefault(prod.product_id, gid)
            time.sleep(REQUEST_DELAY_SEC)
        if idx % 25 == 0 or idx == total:
            print(f"  {idx}/{total} groups · {len(prices):,} priced products", flush=True)
    return groups, prices, product_group, products


def candidate_groups(
    set_id: str,
    set_name: str,
    *,
    learned: dict[str, Counter],
    group_keys: dict[int, set[str]],
) -> set[int]:
    out: set[int] = set(learned.get(set_id, Counter()).keys())
    out.update(GROUP_ALIASES.get(set_id, ()))
    key = norm_set_name(set_name)
    if key:
        out.update(gid for gid, keys in group_keys.items() if key in keys)
    return out


def match_card(
    card: dict[str, Any],
    groups: set[int],
    by_group_number: dict[tuple[int, str], list[Product]],
    taken: set[str],
) -> str | None:
    """Unique product for a card by number + name within its candidate groups."""
    num = norm_number(card.get("local_id") or "")
    name = norm_card_name(card.get("name") or "")
    if not num or not name:
        return None
    pool = [
        p
        for gid in groups
        for p in by_group_number.get((gid, num), [])
        if p.product_id not in taken
    ]
    exact = [p for p in pool if p.norm_name == name]
    if not exact:
        exact = [
            p for p in pool if p.norm_name.startswith(name) or name.startswith(p.norm_name)
        ]
    if len(exact) > 1:
        plain = [p for p in exact if not p.has_qualifier]
        if plain:
            exact = plain
    ids = {p.product_id for p in exact}
    return next(iter(ids)) if len(ids) == 1 else None


def fill_missing_product_ids(
    cards: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    product_group: dict[str, int],
    products: list[Product],
) -> dict[str, str]:
    """card_id -> matched product id for cards without one."""
    learned: dict[str, Counter] = defaultdict(Counter)
    taken: set[str] = set()
    for c in cards:
        pid = c.get("tcgplayer_product_id")
        if pid:
            taken.add(pid)
            gid = product_group.get(pid)
            if gid is not None:
                learned[c["set_id"]][gid] += 1

    group_keys = {int(g["groupId"]): group_name_keys(str(g.get("name") or "")) for g in groups}
    by_group_number: dict[tuple[int, str], list[Product]] = defaultdict(list)
    for p in products:
        by_group_number[(p.group_id, p.norm_number)].append(p)

    matched: dict[str, str] = {}
    for c in cards:
        if c.get("tcgplayer_product_id"):
            continue
        cand = candidate_groups(
            c["set_id"], c.get("set_name") or "", learned=learned, group_keys=group_keys
        )
        if not cand:
            continue
        pid = match_card(c, cand, by_group_number, taken)
        if pid:
            matched[c["id"]] = pid
            taken.add(pid)
    return matched


def build_price_rows(
    card_products: dict[str, str],
    prices: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card_id, pid in card_products.items():
        seen: set[str] = set()
        for item in prices.get(pid, []):
            variant = str(item.get("subTypeName") or "Normal").strip() or "Normal"
            if variant in seen:
                continue
            seen.add(variant)
            row = {
                "card_id": card_id,
                "variant": variant,
                "product_id": pid,
                "market_price": _to_price(item.get("marketPrice")),
                "low_price": _to_price(item.get("lowPrice")),
                "mid_price": _to_price(item.get("midPrice")),
                "high_price": _to_price(item.get("highPrice")),
                "direct_low_price": _to_price(item.get("directLowPrice")),
            }
            if any(row[k] is not None for k in ("market_price", "low_price", "mid_price")):
                rows.append(row)
    return rows


def write_prices(engine, matched: dict[str, str], rows: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        if matched:
            conn.execute(
                text(
                    """
                    UPDATE pokemon_cards
                    SET tcgplayer_product_id = :pid
                    WHERE id = :id AND tcgplayer_product_id IS NULL
                    """
                ),
                [{"id": cid, "pid": pid} for cid, pid in matched.items()],
            )
        conn.execute(text("DELETE FROM pokemon_card_prices"))
        conn.execute(
            text(
                """
                INSERT INTO pokemon_card_prices (
                    card_id, variant, product_id,
                    market_price, low_price, mid_price, high_price, direct_low_price,
                    updated_at
                ) VALUES (
                    :card_id, :variant, :product_id,
                    :market_price, :low_price, :mid_price, :high_price, :direct_low_price,
                    NOW()
                )
                """
            ),
            rows,
        )
        conn.execute(
            text(
                """
                UPDATE pokemon_cards c
                SET price_usd = agg.price_usd, price_updated_at = NOW()
                FROM (
                    SELECT card_id,
                           MIN(COALESCE(market_price, mid_price, low_price)) AS price_usd
                    FROM pokemon_card_prices
                    GROUP BY card_id
                ) agg
                WHERE c.id = agg.card_id
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE pokemon_cards c
                SET price_usd = NULL, price_updated_at = NOW()
                WHERE c.price_usd IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM pokemon_card_prices p WHERE p.card_id = c.id)
                """
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing")
    parser.add_argument(
        "--no-match",
        action="store_true",
        help="Skip products download / filling missing TCGplayer product ids",
    )
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        cards = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT c.id, c.set_id, s.name AS set_name, c.local_id, c.name,
                           NULLIF(c.tcgplayer_product_id, '') AS tcgplayer_product_id
                    FROM pokemon_cards c
                    INNER JOIN pokemon_sets s ON s.id = c.set_id
                    """
                )
            ).mappings()
        ]
    print(f"Spell Tag printings: {len(cards):,}")

    print("Fetching tcgcsv (TCGplayer category 3)…", flush=True)
    groups, prices, product_group, products = fetch_tcgcsv(with_products=not args.no_match)

    matched: dict[str, str] = {}
    if not args.no_match:
        matched = fill_missing_product_ids(cards, groups, product_group, products)
        missing = sum(1 for c in cards if not c.get("tcgplayer_product_id"))
        print(f"Filled {len(matched):,} of {missing:,} missing TCGplayer product ids")

    card_products = {
        c["id"]: c["tcgplayer_product_id"] for c in cards if c.get("tcgplayer_product_id")
    }
    card_products.update(matched)
    rows = build_price_rows(card_products, prices)
    priced_cards = len({r["card_id"] for r in rows})
    print(f"Price rows: {len(rows):,} across {priced_cards:,} printings")

    if priced_cards < MIN_PRICED_CARDS:
        print(
            f"Refusing to write: only {priced_cards:,} priced printings (< {MIN_PRICED_CARDS:,})",
            file=sys.stderr,
        )
        return 1
    if args.dry_run:
        print("Dry run — nothing written.")
        return 0

    write_prices(engine, matched, rows)
    print("Prices updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
