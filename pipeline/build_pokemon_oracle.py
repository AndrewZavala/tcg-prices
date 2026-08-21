#!/usr/bin/env python3
"""Assign oracle (functional) and illustration groups to pokemon_cards.

Scryfall-style rollups:
  - unique=cards  → one row per oracle_id (representative printing)
  - unique=prints → every pokemon_cards row
  - unique=art    → one row per illustration_id

Oracle identity requires a gameplay match (HP, attacks, abilities, retreat,
weaknesses, resistances, etc.) — NOT just name. Card name is an exact hard key.
Soft rules-text matching (case, Pokémon spelling, optional \"up to\") applies to
rules text under that name. Non-Pokémon cards (Trainers / Energy) with the same
name share one oracle regardless of wording. Optional SequenceMatcher text
similarity remains available via USE_NON_POKEMON_TEXT_SIMILARITY (off by default).
Pokémon stay exact gameplay match. Structural differences still split Pokémon oracles.
Near-matches (e.g. same card minus 1 retreat) are future "similar cards" suggestions.
Example: bw7-63 and bw10-104 Dusknoir share an oracle; bw10-49 vs bw10-50 Machamp do not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR

SECRET_RARITY_MARKERS = ("secret",)

# Set-level promo buckets — release_date is the series start, not each promo.
PROMO_SET_IDS = frozenset({"bwp", "smp", "svp", "mep", "xyp", "hgssp", "dpp"})

# Non-Pokémon (Trainer / Energy): same exact name → one oracle.
# Set True to also require ≥SOFT_TEXT_SIM_THRESHOLD SequenceMatcher overlap
# (kept for a possible future tightening — currently unused).
USE_NON_POKEMON_TEXT_SIMILARITY = False
SOFT_TEXT_SIM_THRESHOLD = 0.80

# Typography variants that do not change gameplay (TCGdex / promo printings differ).
_TEXT_REPLACEMENTS = (
    ("\u2019", "'"),  # ’
    ("\u2018", "'"),  # ‘
    ("\u201c", '"'),  # “
    ("\u201d", '"'),  # ”
    ("\u2013", "-"),  # –
    ("\u2014", "-"),  # —
    ("\u00d7", "x"),  # × in “×2” weakness etc.
)

# Optional "up to N" vs bare "N" — same selection range in practice for oracle rollup
# (e.g. Energy Retrieval: "Put 2" vs "Put up to 2").
_UP_TO_RE = re.compile(r"\bup to\s+(\d+)\b", re.IGNORECASE)


def _norm_name(value: str | None) -> str:
    """Exact card name for oracle identity — never soft-matched across names."""
    if not value:
        return ""
    return " ".join(str(value).split())


def _norm_card_text(value: str | None) -> str:
    """Soft-normalize rules text for oracle fingerprinting.

    Only safe because gameplay_payload always pairs this with an exact card name:
    soft text never merges differently named cards. Soft rules:
      - case (basic vs Basic)
      - Pokémon spelling (Pokémon / Pokemon)
      - optional \"up to\" before a quantity
    Typography (quotes, dashes, ×) is also collapsed.
    """
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    for old, new in _TEXT_REPLACEMENTS:
        s = s.replace(old, new)
    s = s.casefold()
    s = s.replace("pokémon", "pokemon").replace("pokèmon", "pokemon")
    s = _UP_TO_RE.sub(r"\1", s)
    return " ".join(s.split())


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _norm_attacks(attacks: list[dict] | None) -> list[dict]:
    rows = []
    for atk in attacks or []:
        if not isinstance(atk, dict):
            continue
        rows.append(
            {
                "name": atk.get("name"),
                "cost": list(atk.get("cost") or []),
                "damage": atk.get("damage"),
                "effect": _norm_card_text(atk.get("effect")),
            }
        )
    rows.sort(key=lambda r: (r.get("name") or "", _stable_json(r)))
    return rows


def _norm_abilities(abilities: list[dict] | None) -> list[dict]:
    rows = []
    for ab in abilities or []:
        if not isinstance(ab, dict):
            continue
        rows.append(
            {
                "type": ab.get("type"),
                "name": ab.get("name"),
                "effect": _norm_card_text(ab.get("effect")),
            }
        )
    rows.sort(key=lambda r: (r.get("name") or "", _stable_json(r)))
    return rows


def _norm_weak_res(rows: list[dict] | None) -> list[dict]:
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append({"type": row.get("type"), "value": _norm_card_text(row.get("value"))})
    out.sort(key=lambda r: _stable_json(r))
    return out


def gameplay_payload(card: dict[str, Any], *, include_evolve_from: bool = True) -> dict[str, Any]:
    """Fields that define functional identity on the card.

    ``name`` is exact (hard gate). Soft text normalization only applies to rules
    text fields under that name.
    """
    category = card.get("category") or "Unknown"
    payload: dict[str, Any] = {
        "category": category,
        "name": _norm_name(card.get("name")),
    }
    if category == "Pokemon":
        payload.update(
            {
                "stage": card.get("stage"),
                "hp": card.get("hp"),
                "types": list(card.get("types") or []),
                "abilities": _norm_abilities(card.get("abilities")),
                "attacks": _norm_attacks(card.get("attacks")),
                "weaknesses": _norm_weak_res(card.get("weaknesses")),
                "resistances": _norm_weak_res(card.get("resistances")),
                "retreat": card.get("retreat"),
            }
        )
        if include_evolve_from:
            payload["evolve_from"] = card.get("evolve_from")
    else:
        # Trainers / energy: prefer card_data.effect, fall back to description column
        data = card.get("card_data") or {}
        if isinstance(data, str):
            data = json.loads(data)
        effect = data.get("effect") or card.get("description")
        payload.update(
            {
                "trainer_type": data.get("trainerType"),
                "energy_type": data.get("energyType"),
                "effect": _norm_card_text(effect),
                "abilities": _norm_abilities(data.get("abilities")),
                "attacks": _norm_attacks(data.get("attacks")),
            }
        )
    return payload


def oracle_fingerprint(card: dict[str, Any]) -> str:
    payload = gameplay_payload(card)
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return digest[:32]


def evolve_line_fingerprint(card: dict[str, Any]) -> str:
    """Gameplay identity ignoring evolve_from — used to backfill missing lines."""
    payload = gameplay_payload(card, include_evolve_from=False)
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return digest[:32]


def _card_data(card: dict[str, Any]) -> dict[str, Any]:
    data = card.get("card_data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _is_non_pokemon_name_merge_eligible(card: dict[str, Any]) -> bool:
    """Trainers and Energy — never Pokémon."""
    return (card.get("category") or "") != "Pokemon"


def _effect_text_for_similarity(card: dict[str, Any]) -> str:
    """Normalized effect text — used only when USE_NON_POKEMON_TEXT_SIMILARITY."""
    data = _card_data(card)
    return _norm_card_text(data.get("effect") or card.get("description"))


def _non_pokemon_merge_bucket_key(card: dict[str, Any]) -> tuple[str, ...]:
    """Same-name gate (plus category so Trainer ≠ Energy if names collide)."""
    return (
        _norm_name(card.get("name")),
        str(card.get("category") or ""),
    )


def _text_similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio — back-pocket helper for optional text gating."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def merge_non_pokemon_name_fingerprints(cards: list[dict[str, Any]]) -> int:
    """Merge Trainer/Energy fingerprints that share the same card name.

    By default merges all same-name non-Pokémon printings. When
    ``USE_NON_POKEMON_TEXT_SIMILARITY`` is True, only merges pairs whose
    normalized effect text is ≥ ``SOFT_TEXT_SIM_THRESHOLD`` similar.

    Mutates each eligible card's ``_oracle_fingerprint``. Returns remapped count.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for card in cards:
        if not _is_non_pokemon_name_merge_eligible(card):
            continue
        buckets.setdefault(_non_pokemon_merge_bucket_key(card), []).append(card)

    for group in buckets.values():
        exemplars: dict[str, str] = {}
        for card in group:
            fp = card["_oracle_fingerprint"]
            parent.setdefault(fp, fp)
            if fp not in exemplars:
                exemplars[fp] = _effect_text_for_similarity(card)

        fps = list(exemplars.keys())
        for i, fp_a in enumerate(fps):
            for fp_b in fps[i + 1 :]:
                if USE_NON_POKEMON_TEXT_SIMILARITY:
                    if _text_similarity(exemplars[fp_a], exemplars[fp_b]) < SOFT_TEXT_SIM_THRESHOLD:
                        continue
                union(fp_a, fp_b)

    remapped = 0
    for card in cards:
        if not _is_non_pokemon_name_merge_eligible(card):
            continue
        old = card["_oracle_fingerprint"]
        new = find(old)
        if new != old:
            card["_oracle_fingerprint"] = new
            remapped += 1
    return remapped


def backfill_evolve_from(cards: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Fill null evolve_from from other printings with the same gameplay (ex-evolve).

    Returns list of (card_id, evolve_from) updates applied in memory.
    """
    donors: dict[str, set[str]] = {}
    for card in cards:
        if (card.get("category") or "") != "Pokemon":
            continue
        evo = (card.get("evolve_from") or "").strip()
        if not evo:
            continue
        key = evolve_line_fingerprint(card)
        donors.setdefault(key, set()).add(evo)

    # Only use a donor value when every matching printing agrees.
    resolved: dict[str, str] = {}
    for key, values in donors.items():
        if len(values) == 1:
            resolved[key] = next(iter(values))

    updates: list[tuple[str, str]] = []
    for card in cards:
        if (card.get("category") or "") != "Pokemon":
            continue
        if (card.get("evolve_from") or "").strip():
            continue
        key = evolve_line_fingerprint(card)
        evo = resolved.get(key)
        if not evo:
            continue
        card["evolve_from"] = evo
        updates.append((str(card["id"]), evo))
    return updates


def illustration_fingerprint(card: dict[str, Any]) -> str:
    """Unique art — image URL distinguishes reprints with new artwork."""
    image = (card.get("image_url") or "").strip()
    artist = (card.get("illustrator") or "").strip().lower()
    basis = f"{artist}|{image}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _set_penalty(set_id: str | None) -> int:
    sid = (set_id or "").lower()
    if sid in PROMO_SET_IDS:
        return 150
    return 0


def _rarity_penalty(rarity: str | None) -> int:
    r = (rarity or "").lower()
    if any(marker in r for marker in SECRET_RARITY_MARKERS):
        return 100
    if "ultra" in r or "hyper" in r:
        return 50
    if "rare" in r:
        return 10
    return 0


def apply_migration(engine) -> None:
    mig = MIGRATIONS_DIR / "026_pokemon_oracle.sql"
    if not mig.exists():
        raise FileNotFoundError(mig)
    with engine.begin() as conn:
        conn.execute(text(mig.read_text(encoding="utf-8")))


def load_cards(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
                c.id,
                c.set_id,
                c.name,
                c.category,
                c.hp,
                c.types,
                c.stage,
                c.evolve_from,
                c.rarity,
                c.illustrator,
                c.image_url,
                c.retreat,
                c.attacks,
                c.abilities,
                c.weaknesses,
                c.resistances,
                c.description,
                c.card_data,
                s.release_date
            FROM pokemon_cards c
            LEFT JOIN pokemon_sets s ON s.id = c.set_id
            ORDER BY c.id
            """
        )
    ).mappings()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("attacks", "abilities", "weaknesses", "resistances", "card_data"):
            val = item.get(key)
            if isinstance(val, str):
                item[key] = json.loads(val)
        out.append(item)
    return out


def pick_representative(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Default printing for unique=cards — earliest release, prefer non-secret."""

    def sort_key(card: dict[str, Any]) -> tuple:
        release = card.get("release_date")
        release_ord = release.toordinal() if release else 99999999
        return (
            _set_penalty(card.get("set_id")),
            release_ord,
            _rarity_penalty(card.get("rarity")),
            str(card.get("id") or ""),
        )

    return sorted(cards, key=sort_key)[0]


def build_oracles(engine) -> dict[str, int]:
    with engine.begin() as conn:
        cards = load_cards(conn)
        if not cards:
            print("No pokemon_cards rows found.")
            return {"cards": 0, "oracles": 0, "evolve_from_backfilled": 0}

        evolve_updates = backfill_evolve_from(cards)
        if evolve_updates:
            upd = text(
                """
                UPDATE pokemon_cards
                SET evolve_from = :evolve_from
                WHERE id = :id
                  AND (evolve_from IS NULL OR btrim(evolve_from) = '')
                """
            )
            for card_id, evo in evolve_updates:
                conn.execute(upd, {"id": card_id, "evolve_from": evo})
            print(f"Backfilled evolve_from on {len(evolve_updates)} printing(s).")

        by_fingerprint: dict[str, list[dict[str, Any]]] = {}
        for card in cards:
            fp = oracle_fingerprint(card)
            card["_oracle_fingerprint"] = fp
            card["_illustration_id"] = illustration_fingerprint(card)

        soft_remapped = merge_non_pokemon_name_fingerprints(cards)
        if soft_remapped:
            mode = (
                f"≥{int(SOFT_TEXT_SIM_THRESHOLD * 100)}% text"
                if USE_NON_POKEMON_TEXT_SIMILARITY
                else "same name"
            )
            print(
                f"Merged {soft_remapped} non-Pokémon printing(s) by {mode}."
            )

        for card in cards:
            by_fingerprint.setdefault(card["_oracle_fingerprint"], []).append(card)

        conn.execute(text("UPDATE pokemon_cards SET is_oracle_representative = FALSE"))
        conn.execute(text("DELETE FROM pokemon_oracles"))

        oracle_count = 0
        for fp, group in by_fingerprint.items():
            rep = pick_representative(group)
            art_ids = {c["_illustration_id"] for c in group}
            releases = [c.get("release_date") for c in group if c.get("release_date")]
            first_release = min(releases) if releases else None
            oracle_id = fp
            gameplay = gameplay_payload(rep)

            conn.execute(
                text(
                    """
                    INSERT INTO pokemon_oracles (
                        id, fingerprint, name, category, representative_card_id,
                        gameplay, printing_count, art_variant_count, first_release_date
                    ) VALUES (
                        :id, :fingerprint, :name, :category, :representative_card_id,
                        CAST(:gameplay AS jsonb), :printing_count, :art_variant_count,
                        :first_release_date
                    )
                    """
                ),
                {
                    "id": oracle_id,
                    "fingerprint": fp,
                    "name": rep.get("name"),
                    "category": rep.get("category"),
                    "representative_card_id": rep.get("id"),
                    "gameplay": json.dumps(gameplay),
                    "printing_count": len(group),
                    "art_variant_count": len(art_ids),
                    "first_release_date": first_release,
                },
            )
            oracle_count += 1

            for card in group:
                is_rep = card.get("id") == rep.get("id")
                conn.execute(
                    text(
                        """
                        UPDATE pokemon_cards
                        SET oracle_id = :oracle_id,
                            illustration_id = :illustration_id,
                            illustration_artist = :illustration_artist,
                            is_oracle_representative = :is_rep
                        WHERE id = :id
                        """
                    ),
                    {
                        "oracle_id": oracle_id,
                        "illustration_id": card["_illustration_id"],
                        "illustration_artist": card.get("illustrator"),
                        "is_rep": is_rep,
                        "id": card.get("id"),
                    },
                )

        return {
            "cards": len(cards),
            "oracles": oracle_count,
            "evolve_from_backfilled": len(evolve_updates),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Pokémon oracle groupings")
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying pokemon oracle migration...")
        apply_migration(engine)

    stats = build_oracles(engine)
    print(
        f"Done — {stats['cards']} printings → {stats['oracles']} oracles"
        f" (evolve_from backfilled: {stats.get('evolve_from_backfilled', 0)})."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
