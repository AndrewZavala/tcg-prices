#!/usr/bin/env python3
"""Flag Standard-legal cards that appear in Limitless TCG decklists (Spell Tag is:competitive).

Only Standard-legal oracles are checked (same rule as f:standard, migration 049).
Limitless shares decklists across reprints, so one card page is checked per oracle
(newest printing with a Limitless set code) and the result is copied to every printing.

Default run checks Standard oracles never checked or still marked "no decklists"
(they can gain decklists as tournaments happen). Progress is saved after every card,
so an interrupted run resumes where it stopped.

Examples:
  python refresh_limitless_decklists.py              # monthly
  python refresh_limitless_decklists.py --all        # also recheck cards marked "has decklists"
  python refresh_limitless_decklists.py --set sv01 --limit 20
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL

LIMITLESS_BASE = "https://limitlesstcg.com/cards"
USER_AGENT = "SpellTag/1.0 (https://spelltag.com)"
NO_DECKLISTS_MARKER = "does not appear in any decklist"
DECKLIST_LINK_MARKER = "/decks/list/"
MAX_PRINTINGS_TRIED = 3


def limitless_card_url(set_code: str, local_id: str) -> str | None:
    code = (set_code or "").strip().upper()
    number = (local_id or "").strip()
    if number.isdigit():
        number = str(int(number))
    if not code or not number:
        return None
    return f"{LIMITLESS_BASE}/{code}/{number}"


def decklist_status(html: str) -> bool | None:
    """True = has decklists, False = none, None = page didn't look like a card page."""
    if NO_DECKLISTS_MARKER in html:
        return False
    if DECKLIST_LINK_MARKER in html:
        return True
    return None


def fetch_status(session: requests.Session, url: str) -> bool | None:
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(10 * (attempt + 1))
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(30 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return None
        return decklist_status(resp.text)
    return None


def load_groups(engine, set_id: str | None) -> dict[str, list[dict[str, Any]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COALESCE(c.oracle_id, c.id) AS gkey, c.id, c.set_id, c.local_id,
                       s.tcg_online_code AS code, s.release_date,
                       c.limitless_decklists,
                       pokemon_printing_is_standard(
                           c.regulation_mark, c.category, c.name, c.card_data->>'energyType',
                           (SELECT spelltag_standard_min_mark())
                       ) AS is_standard
                FROM pokemon_cards c
                INNER JOIN pokemon_sets s ON s.id = c.set_id
                ORDER BY s.release_date DESC NULLS LAST, c.id
                """
            )
        ).mappings().all()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["gkey"]].append(dict(r))
    if set_id:
        groups = {k: v for k, v in groups.items() if any(p["set_id"] == set_id for p in v)}
    return groups


def needs_check(printings: list[dict[str, Any]], *, recheck_all: bool) -> bool:
    """Standard-legal oracles (any printing, reprint rule) not yet known to have decklists."""
    if not any(p["is_standard"] for p in printings):
        return False
    if recheck_all:
        return True
    return not all(p["limitless_decklists"] for p in printings)


def check_group(session: requests.Session, printings: list[dict[str, Any]], delay: float) -> bool | None:
    tried = 0
    for p in printings:
        url = limitless_card_url(p.get("code") or "", p.get("local_id") or "")
        if not url:
            continue
        status = fetch_status(session, url)
        time.sleep(delay)
        tried += 1
        if status is not None:
            return status
        if tried >= MAX_PRINTINGS_TRIED:
            break
    return None


def save_flag(engine, gkey: str, flag: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pokemon_cards
                SET limitless_decklists = :flag, limitless_checked_at = NOW()
                WHERE COALESCE(oracle_id, id) = :gkey
                """
            ),
            {"flag": flag, "gkey": gkey},
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--all", action="store_true", help="Recheck every card")
    parser.add_argument("--set", dest="set_id", help="Only cards with a printing in this set id")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N page checks")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)
    groups = load_groups(engine, args.set_id)

    todo: list[tuple[str, list[dict[str, Any]]]] = []
    propagated = 0
    for gkey, printings in groups.items():
        if not needs_check(printings, recheck_all=args.all):
            continue
        if not args.all and any(p["limitless_decklists"] for p in printings):
            save_flag(engine, gkey, True)
            propagated += 1
            continue
        if any(p.get("code") for p in printings):
            todo.append((gkey, printings))
    if args.limit:
        todo = todo[: args.limit]
    if propagated:
        print(f"Copied existing 'has decklists' to new printings of {propagated:,} cards")
    print(f"Checking {len(todo):,} cards on Limitless (~{len(todo) * args.delay / 60:.0f} min)")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    counts = {"yes": 0, "no": 0, "unknown": 0}
    for idx, (gkey, printings) in enumerate(todo, start=1):
        status = check_group(session, printings, args.delay)
        if status is None:
            counts["unknown"] += 1
        else:
            save_flag(engine, gkey, status)
            counts["yes" if status else "no"] += 1
        if idx % 100 == 0 or idx == len(todo):
            print(
                f"  {idx:,}/{len(todo):,} · {counts['yes']:,} with decklists · "
                f"{counts['no']:,} without · {counts['unknown']:,} unknown",
                flush=True,
            )

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
