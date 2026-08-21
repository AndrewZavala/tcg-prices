#!/usr/bin/env python3
"""Enrich pokemon_cards.subtypes from pokemontcg.io (free API key at dev.pokemontcg.io).

Examples:
  python enrich_pokemon_subtypes.py
  python enrich_pokemon_subtypes.py --set bw8
  python enrich_pokemon_subtypes.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR, POKEMONTCG_API_KEY, POKEMONTCG_BASE

USER_AGENT = "TCGPokemonCatalog/1.0"
REQUEST_DELAY_SEC = 0.2
# pokemontcg.io / Cloudflare often 500/502 on large pageSize without an API key
PAGE_SIZE = 25

# TCGdex set ids differ from pokemontcg.io (me01 vs me1, sv01 vs sv1, me02.5 vs me2pt5).
POKEMONTCG_SET_ALIASES: dict[str, str] = {
    "me01": "me1",
    "me02": "me2",
    "me02.5": "me2pt5",
    "me03": "me3",
    "me04": "me4",
    "me05": "me5",
    # Scarlet & Violet block
    "sv01": "sv1",
    "sv02": "sv2",
    "sv03": "sv3",
    "sv03.5": "sv3pt5",
    "sv04": "sv4",
    "sv04.5": "sv4pt5",
    "sv05": "sv5",
    "sv06": "sv6",
    "sv06.5": "sv6pt5",
    "sv07": "sv7",
    "sv08": "sv8",
    "sv08.5": "sv8pt5",
    "sv09": "sv9",
    "sv10": "sv10",
    "sv10.5b": "zsv10pt5",  # Black Bolt
    "sv10.5w": "rsv10pt5",  # White Flare
    # Sun & Moon block (dot-ids → compact pokemontcg.io ids)
    "sm3.5": "sm35",
    "sm7.5": "sm75",
}


def pokemontcg_set_id(tcgdex_set_id: str) -> str:
    return POKEMONTCG_SET_ALIASES.get(tcgdex_set_id.lower(), tcgdex_set_id.lower())


def pokemontcg_card_id(tcgdex_card_id: str) -> str:
    """Map TCGdex card id to pokemontcg.io id (me01-081 -> me1-81)."""
    card_id = tcgdex_card_id.strip()
    if "-" not in card_id:
        return card_id.lower()
    set_part, local = card_id.split("-", 1)
    api_set = pokemontcg_set_id(set_part)
    if local.isdigit():
        local = str(int(local))
    return f"{api_set}-{local}".lower()


def _session() -> requests.Session:
    s = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if POKEMONTCG_API_KEY:
        headers["X-Api-Key"] = POKEMONTCG_API_KEY
    s.headers.update(headers)
    return s


def _get_json(session: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> Any:
    last_exc: Exception | None = None
    for attempt in range(8):
        resp = session.get(url, params=params, timeout=90)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5"))
            time.sleep(max(retry_after, 2 ** attempt))
            continue
        if resp.status_code >= 500:
            last_exc = requests.HTTPError(f"{resp.status_code} from pokemontcg.io", response=resp)
            time.sleep(min(2 ** attempt, 20))
            continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            last_exc = exc
            raise
        return resp.json()
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url}")


def slugify_tag(label: str) -> str:
    """Team Plasma -> team-plasma; Stage 1 -> stage-1."""
    normalized = unicodedata.normalize("NFKD", label)
    ascii_label = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower().strip())
    return slug.strip("-")


def subtypes_to_tags(subtypes: list[str] | None) -> list[str]:
    if not subtypes:
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for raw in subtypes:
        tag = slugify_tag(raw)
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def apply_migration(engine) -> None:
    mig = MIGRATIONS_DIR / "027_pokemon_subtypes.sql"
    if not mig.exists():
        raise FileNotFoundError(mig)
    with engine.begin() as conn:
        conn.execute(text(mig.read_text(encoding="utf-8")))


def list_loaded_sets(conn, only: list[str] | None) -> list[str]:
    if only:
        return [s.lower() for s in only]
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT set_id
            FROM pokemon_cards
            ORDER BY set_id
            """
        )
    ).scalars()
    return list(rows)


def fetch_set_cards(session: requests.Session, tcgdex_set_id: str) -> list[dict[str, Any]]:
    """Paginate a set; restart the whole set a few times on mid-pagination failures."""
    api_set_id = pokemontcg_set_id(tcgdex_set_id)
    last_exc: Exception | None = None
    for attempt in range(5):
        page = 1
        cards: list[dict[str, Any]] = []
        try:
            while True:
                payload = _get_json(
                    session,
                    f"{POKEMONTCG_BASE}/cards",
                    params={"q": f"set.id:{api_set_id}", "pageSize": PAGE_SIZE, "page": page},
                )
                batch = payload.get("data") or []
                cards.extend(batch)
                total = int(payload.get("totalCount") or len(cards))
                if not batch or page * PAGE_SIZE >= total:
                    return cards
                page += 1
                time.sleep(REQUEST_DELAY_SEC)
        except Exception as exc:
            last_exc = exc
            time.sleep(min(2 ** attempt, 15))
    if last_exc:
        raise last_exc
    return []


def fetch_card_by_id(session: requests.Session, card_id: str) -> dict[str, Any] | None:
    try:
        payload = _get_json(session, f"{POKEMONTCG_BASE}/cards/{card_id.lower()}")
    except (requests.HTTPError, RuntimeError):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def enrich_set(
    conn,
    session: requests.Session,
    set_id: str,
    *,
    dry_run: bool,
) -> dict[str, int]:
    db_ids = conn.execute(
        text("SELECT id FROM pokemon_cards WHERE set_id = :set_id ORDER BY id"),
        {"set_id": set_id},
    ).scalars().all()

    try:
        api_cards = fetch_set_cards(session, set_id)
    except Exception as exc:
        print(
            f"  {set_id}: set fetch failed after retries ({exc}); skipping set",
            file=sys.stderr,
        )
        return {
            "api_cards": 0,
            "db_cards": len(db_ids),
            "matched": 0,
            "updated": 0,
            "missing_api": len(db_ids),
        }

    by_id = {pokemontcg_card_id(str(c["id"])): c for c in api_cards if c.get("id")}

    matched = 0
    updated = 0
    missing_api = 0

    upsert_sql = text(
        """
        UPDATE pokemon_cards
        SET subtypes = :subtypes,
            tags = :tags
        WHERE id = :id
        """
    )

    for card_id in db_ids:
        lookup_id = pokemontcg_card_id(card_id)
        api_card = by_id.get(lookup_id)
        if not api_card:
            # Only probe single cards for small gaps (odd promo numbers).
            if len(api_cards) > 0 and (missing_api + matched) < 40:
                api_card = fetch_card_by_id(session, lookup_id)
                time.sleep(REQUEST_DELAY_SEC)
            if not api_card:
                missing_api += 1
                continue

        subtypes = api_card.get("subtypes") or []
        if not isinstance(subtypes, list):
            subtypes = []
        subtypes = [str(s) for s in subtypes if s]
        tags = subtypes_to_tags(subtypes)

        matched += 1
        if dry_run:
            if subtypes:
                updated += 1
            continue

        conn.execute(
            upsert_sql,
            {"id": card_id, "subtypes": subtypes or None, "tags": tags or None},
        )
        if subtypes:
            updated += 1

    return {
        "api_cards": len(api_cards),
        "db_cards": len(db_ids),
        "matched": matched,
        "updated": updated,
        "missing_api": missing_api,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich Pokémon subtypes from pokemontcg.io")
    parser.add_argument("--set", action="append", dest="sets", metavar="ID", help="Limit to set id(s)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing")
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip applying 027_pokemon_subtypes.sql",
    )
    args = parser.parse_args()

    if not POKEMONTCG_API_KEY:
        print(
            "Warning: POKEMONTCG_API_KEY not set — unauthenticated requests are heavily rate-limited.",
            file=sys.stderr,
        )

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying pokemon subtypes migration...")
        apply_migration(engine)

    session = _session()

    with engine.connect() as conn:
        set_ids = list_loaded_sets(conn, args.sets)
    if not set_ids:
        print("No pokemon_cards rows found.")
        return 0

    totals = {"api_cards": 0, "db_cards": 0, "matched": 0, "updated": 0, "missing_api": 0}
    print(f"Enriching {len(set_ids)} set(s): {', '.join(set_ids)}")
    for set_id in set_ids:
        try:
            # Commit per set so later failures do not roll back earlier work.
            with engine.begin() as conn:
                stats = enrich_set(conn, session, set_id, dry_run=args.dry_run)
        except Exception as exc:
            print(f"  {set_id}: ERROR {exc}", file=sys.stderr)
            continue
        for key in totals:
            totals[key] += stats[key]
        print(
            f"  {set_id}: api={stats['api_cards']} db={stats['db_cards']} "
            f"matched={stats['matched']} with_subtypes={stats['updated']} "
            f"missing={stats['missing_api']}"
        )
        time.sleep(REQUEST_DELAY_SEC)

    mode = "dry-run" if args.dry_run else "done"
    print(
        f"{mode.capitalize()} — matched {totals['matched']}/{totals['db_cards']} cards, "
        f"{totals['updated']} with subtypes, {totals['missing_api']} not found on pokemontcg.io."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
