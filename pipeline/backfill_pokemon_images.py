#!/usr/bin/env python3
"""Fill missing pokemon_cards.image_url from pokemontcg.io CDN / API.

TCGdex often omits promo and subset-gallery art. pokemontcg.io usually hosts
hi-res PNGs at https://images.pokemontcg.io/{set}/{number}_hires.png.

Examples:
  python backfill_pokemon_images.py
  python backfill_pokemon_images.py --set smp
  python backfill_pokemon_images.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL
from enrich_pokemon_subtypes import (
    REQUEST_DELAY_SEC,
    fetch_set_cards,
    pokemontcg_card_id,
    pokemontcg_set_id,
    _session,
)

USER_AGENT = "TCGPokemonCatalog/1.0"


def _number_candidates(local_id: str) -> list[str]:
    raw = (local_id or "").strip()
    if not raw:
        return []
    out: list[str] = [raw]
    if raw.isdigit():
        out.append(str(int(raw)))
    elif raw.lstrip("0").isdigit() and raw.lstrip("0"):
        out.append(str(int(raw)))
    # Celebrations Classic: CC002 → 2_A (pokemontcg.io cel25c)
    if raw.upper().startswith("CC") and raw[2:].isdigit():
        out.append(f"{int(raw[2:])}_A")
    # Prefer unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def _cdn_candidates(tcgdex_set_id: str, local_id: str) -> list[str]:
    api_set = pokemontcg_set_id(tcgdex_set_id)
    urls: list[str] = []
    for num in _number_candidates(local_id):
        urls.append(f"https://images.pokemontcg.io/{api_set}/{num}_hires.png")
        urls.append(f"https://images.pokemontcg.io/{api_set}/{num}.png")
    return urls


def _head_ok(session: requests.Session, url: str) -> bool:
    try:
        resp = session.head(url, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            return True
        # Some CDNs dislike HEAD — try a tiny GET range
        if resp.status_code in (403, 405):
            get = session.get(url, timeout=20, stream=True)
            ok = get.status_code == 200
            get.close()
            return ok
    except requests.RequestException:
        return False
    return False


def _image_from_api_card(api_card: dict[str, Any] | None) -> str | None:
    if not api_card:
        return None
    images = api_card.get("images") or {}
    large = images.get("large") or images.get("small")
    return str(large) if large else None


def backfill_set(
    conn,
    session: requests.Session,
    set_id: str,
    *,
    dry_run: bool,
    cdn_only: bool = False,
) -> dict[str, int]:
    rows = conn.execute(
        text(
            """
            SELECT id, local_id, name
            FROM pokemon_cards
            WHERE set_id = :set_id
              AND (image_url IS NULL OR BTRIM(image_url) = '')
            ORDER BY id
            """
        ),
        {"set_id": set_id},
    ).mappings().all()

    if not rows:
        return {"missing": 0, "filled": 0, "unresolved": 0}

    api_by_id: dict[str, dict[str, Any]] = {}
    api_by_name: dict[str, dict[str, Any]] = {}
    if not cdn_only:
        try:
            api_cards = fetch_set_cards(session, set_id)
            for card in api_cards:
                cid = str(card.get("id") or "").lower()
                if cid:
                    api_by_id[cid] = card
                    api_by_id[pokemontcg_card_id(cid)] = card
                name = str(card.get("name") or "").strip().lower()
                if name and name not in api_by_name:
                    api_by_name[name] = card
        except Exception as exc:
            print(f"  {set_id}: API set fetch failed ({exc}); CDN-only", file=sys.stderr)

    filled = 0
    unresolved = 0
    update_sql = text(
        """
        UPDATE pokemon_cards
        SET image_url = :image_url
        WHERE id = :id
          AND (image_url IS NULL OR BTRIM(image_url) = '')
        """
    )

    for row in rows:
        card_id = str(row["id"])
        local_id = str(row["local_id"] or "")
        name = str(row["name"] or "").strip().lower()

        image: str | None = None

        # 1) HEAD-check constructed CDN URLs (no API quota)
        for url in _cdn_candidates(set_id, local_id):
            if _head_ok(session, url):
                image = url
                break
            time.sleep(0.03)

        # 2) Match pokemontcg card from set listing / name
        if not image and not cdn_only:
            lookup = pokemontcg_card_id(card_id)
            api_card = api_by_id.get(lookup) or api_by_id.get(card_id.lower())
            if not api_card and name:
                api_card = api_by_name.get(name)
            image = _image_from_api_card(api_card)

        if not image:
            unresolved += 1
            continue

        filled += 1
        if dry_run:
            print(f"  would set {card_id} → {image}")
            continue

        conn.execute(update_sql, {"id": card_id, "image_url": image})

    return {"missing": len(rows), "filled": filled, "unresolved": unresolved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", action="append", dest="sets", help="Limit to TCGdex set id(s)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-sets", type=int, default=0, help="Process at most N sets")
    parser.add_argument(
        "--cdn-only",
        action="store_true",
        help="Skip pokemontcg.io API set fetches; only probe CDN URLs",
    )
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL, future=True)
    session = _session()
    session.headers.setdefault("User-Agent", USER_AGENT)

    with engine.begin() as conn:
        if args.sets:
            set_ids = [s.lower() for s in args.sets]
        else:
            set_ids = list(
                conn.execute(
                    text(
                        """
                        SELECT set_id
                        FROM pokemon_cards
                        WHERE image_url IS NULL OR BTRIM(image_url) = ''
                        GROUP BY set_id
                        ORDER BY COUNT(*) DESC, set_id
                        """
                    )
                ).scalars().all()
            )

        if args.limit_sets and args.limit_sets > 0:
            set_ids = set_ids[: args.limit_sets]

        print(f"Backfilling images for {len(set_ids)} set(s)...")
        total_missing = total_filled = total_unresolved = 0
        for set_id in set_ids:
            stats = backfill_set(
                conn,
                session,
                set_id,
                dry_run=args.dry_run,
                cdn_only=args.cdn_only,
            )
            total_missing += stats["missing"]
            total_filled += stats["filled"]
            total_unresolved += stats["unresolved"]
            print(
                f"  {set_id}: missing={stats['missing']} "
                f"filled={stats['filled']} unresolved={stats['unresolved']}"
            )
            time.sleep(REQUEST_DELAY_SEC)

        print(
            f"Done — missing={total_missing} filled={total_filled} "
            f"unresolved={total_unresolved}"
            + (" (dry-run)" if args.dry_run else "")
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
