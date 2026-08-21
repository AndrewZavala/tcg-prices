#!/usr/bin/env python3
"""Backfill pokemon_cards.tcgplayer_product_id from TCGdex pricing."""

from __future__ import annotations

import argparse
import sys
import time

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL
from refresh_tcgdex import TCGDEX_BASE, _get_json, _tcgplayer_product_id

REQUEST_DELAY_SEC = 0.05


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="sets", action="append", help="Limit to set id(s)")
    parser.add_argument("--force", action="store_true", help="Refresh rows that already have an id")
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)
    session = requests.Session()
    session.headers.update({"User-Agent": "StarPiece/1.0 (TCGdex backfill)"})

    where = "1=1"
    params: dict[str, object] = {}
    if args.sets:
        where = "set_id = ANY(:set_ids)"
        params["set_ids"] = args.sets
    if not args.force:
        where += " AND (tcgplayer_product_id IS NULL OR tcgplayer_product_id = '')"

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT id FROM pokemon_cards WHERE {where} ORDER BY id"),
            params,
        ).all()

    total = len(rows)
    if not total:
        print("No cards to backfill.")
        return 0

    updated = 0
    missing = 0
    for i, (card_id,) in enumerate(rows, 1):
        card = _get_json(session, f"{TCGDEX_BASE}/en/cards/{card_id}")
        pid = _tcgplayer_product_id(card.get("pricing"))
        if pid:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pokemon_cards
                        SET tcgplayer_product_id = :pid, synced_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"id": card_id, "pid": pid},
                )
            updated += 1
        else:
            missing += 1
        if i % 100 == 0 or i == total:
            print(f"  {i}/{total} processed · {updated} with product id · {missing} missing")
        time.sleep(REQUEST_DELAY_SEC)

    print(f"Done: {updated}/{total} cards got tcgplayer_product_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
