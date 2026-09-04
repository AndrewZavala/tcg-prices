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
from pokemon_card_corrections import apply_card_corrections

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
    s = s.replace("poké", "poke").replace("pokè", "poke")
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


_CARD_SELECT_SQL = """
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
"""


def _hydrate_card_row(row) -> dict[str, Any]:
    item = dict(row)
    for key in ("attacks", "abilities", "weaknesses", "resistances", "card_data"):
        val = item.get(key)
        if isinstance(val, str):
            item[key] = json.loads(val)
    apply_card_corrections(item)
    return item


def load_cards(
    conn,
    *,
    set_ids: list[str] | None = None,
    oracle_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if set_ids:
        clauses.append("c.set_id = ANY(:set_ids)")
        params["set_ids"] = [s.lower() for s in set_ids]
    if oracle_ids:
        clauses.append("c.oracle_id = ANY(:oracle_ids)")
        params["oracle_ids"] = oracle_ids
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        text(_CARD_SELECT_SQL + where + " ORDER BY c.id"),
        params,
    ).mappings()
    return [_hydrate_card_row(row) for row in rows]


def load_evolve_donor_cards(conn) -> list[dict[str, Any]]:
    """Printings with evolve_from — used to backfill side-set ingest rows."""
    rows = conn.execute(
        text(
            _CARD_SELECT_SQL
            + """
            WHERE c.category = 'Pokemon'
              AND c.evolve_from IS NOT NULL
              AND btrim(c.evolve_from) <> ''
            ORDER BY c.id
            """
        )
    ).mappings()
    return [_hydrate_card_row(row) for row in rows]


def _assign_card_fingerprints(cards: list[dict[str, Any]]) -> None:
    for card in cards:
        card["_oracle_fingerprint"] = oracle_fingerprint(card)
        card["_illustration_id"] = illustration_fingerprint(card)


def _oracle_row_payload(
    oracle_id: str,
    fp: str,
    rep: dict[str, Any],
    group: list[dict[str, Any]],
) -> dict[str, Any]:
    art_ids = {c["_illustration_id"] for c in group}
    releases = [c.get("release_date") for c in group if c.get("release_date")]
    first_release = min(releases) if releases else None
    return {
        "id": oracle_id,
        "fingerprint": fp,
        "name": rep.get("name"),
        "category": rep.get("category"),
        "representative_card_id": rep.get("id"),
        "gameplay": json.dumps(gameplay_payload(rep)),
        "printing_count": len(group),
        "art_variant_count": len(art_ids),
        "first_release_date": first_release,
    }


def _upsert_oracle(conn, payload: dict[str, Any]) -> None:
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
            ON CONFLICT (id) DO UPDATE SET
                fingerprint = EXCLUDED.fingerprint,
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                representative_card_id = EXCLUDED.representative_card_id,
                gameplay = EXCLUDED.gameplay,
                printing_count = EXCLUDED.printing_count,
                art_variant_count = EXCLUDED.art_variant_count,
                first_release_date = EXCLUDED.first_release_date
            """
        ),
        payload,
    )


def _link_cards_to_oracle(
    conn,
    *,
    oracle_id: str,
    group: list[dict[str, Any]],
    rep_id: str,
    only_ids: set[str] | None = None,
) -> int:
    linked = 0
    for card in group:
        cid = str(card.get("id") or "")
        if only_ids is not None and cid not in only_ids:
            continue
        is_rep = cid == rep_id
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
                "id": cid,
            },
        )
        linked += 1
    return linked


def _refresh_oracle_representative(conn, oracle_id: str, rep_id: str) -> None:
    conn.execute(
        text(
            """
            UPDATE pokemon_cards
            SET is_oracle_representative = (id = :rep_id)
            WHERE oracle_id = :oracle_id
            """
        ),
        {"oracle_id": oracle_id, "rep_id": rep_id},
    )


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


def persist_card_corrections(engine) -> int:
    """Apply narrow source fixes in their own short transaction (avoids rebuild deadlocks)."""
    from pokemon_card_corrections import (
        ABILITY_TYPE_BY_NAME,
        ATTACK_FIELD_BY_NAME,
        DROP_NAMELESS_ATTACKS,
        STAGE_BY_ID,
        apply_card_corrections,
    )

    ids = sorted(
        set(ABILITY_TYPE_BY_NAME)
        | set(ATTACK_FIELD_BY_NAME)
        | set(DROP_NAMELESS_ATTACKS)
        | set(STAGE_BY_ID)
    )
    if not ids:
        return 0

    fixed = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, abilities, attacks, stage
                FROM pokemon_cards
                WHERE id = ANY(:ids)
                """
            ),
            {"ids": ids},
        ).mappings().all()
        for row in rows:
            cid = str(row["id"])
            abilities = row.get("abilities")
            attacks = row.get("attacks")
            if isinstance(abilities, str):
                abilities = json.loads(abilities)
            if isinstance(attacks, str):
                attacks = json.loads(attacks)
            before = {
                "id": cid,
                "abilities": list(abilities or []),
                "attacks": list(attacks or []),
                "stage": row.get("stage"),
            }
            after = apply_card_corrections(dict(before))
            if (
                after.get("abilities") == before["abilities"]
                and after.get("attacks") == before["attacks"]
                and after.get("stage") == before["stage"]
            ):
                continue
            conn.execute(
                text(
                    """
                    UPDATE pokemon_cards
                    SET abilities = CAST(:abilities AS jsonb),
                        attacks = CAST(:attacks AS jsonb),
                        stage = :stage
                    WHERE id = :id
                    """
                ),
                {
                    "id": cid,
                    "abilities": json.dumps(after.get("abilities") or []),
                    "attacks": json.dumps(after.get("attacks") or []),
                    "stage": after.get("stage"),
                },
            )
            fixed += 1
    if fixed:
        print(f"Persisted {fixed} card correction(s).")
    return fixed


def persist_category_corrections(engine) -> int:
    """Reclassify Pokémon mislabeled Trainer/Energy (hp + stage/types/dex).

    Keep in sync with migrations/043_fix_mislabeled_pokemon_category.sql.
    """
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE pokemon_cards
                SET category = 'Pokemon',
                    card_data = CASE
                        WHEN card_data ? 'category'
                        THEN jsonb_set(card_data, '{category}', '"Pokemon"')
                        ELSE card_data
                    END
                WHERE category != 'Pokemon'
                  AND hp > 0
                  AND (
                    (stage IS NOT NULL AND stage <> '')
                    OR (types IS NOT NULL AND types <> '{}')
                    OR (dex_ids IS NOT NULL AND dex_ids <> '{}')
                  )
                """
            )
        )
        fixed = result.rowcount or 0
    if fixed:
        print(f"Reclassified {fixed} mislabeled Pokémon card(s).")
    return fixed


def build_oracles(engine) -> dict[str, int]:
    # Corrections first, committed separately — never share a lock with DELETE oracles.
    persist_category_corrections(engine)
    persist_card_corrections(engine)

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

        # Snapshot curated tags before DELETE (FK CASCADE would wipe them).
        # Keyed by card_id so merged fingerprint groups can union tags.
        tag_rows_by_card: dict[str, list[dict[str, Any]]] = {}
        try:
            for row in conn.execute(
                text(
                    """
                    SELECT c.id AS card_id, ot.tag_slug, ot.tagged_by, ot.tagged_at
                    FROM oracle_tags ot
                    INNER JOIN pokemon_cards c ON c.oracle_id = ot.oracle_id
                    """
                )
            ).mappings():
                tag_rows_by_card.setdefault(str(row["card_id"]), []).append(dict(row))
        except Exception:
            # oracle_tags may not exist yet on older DBs
            tag_rows_by_card = {}

        # Clear FKs first so DELETE oracles does not fight row locks via ON DELETE SET NULL.
        conn.execute(
            text(
                """
                UPDATE pokemon_cards
                SET oracle_id = NULL,
                    is_oracle_representative = FALSE
                """
            )
        )
        conn.execute(text("DELETE FROM pokemon_oracles"))

        oracle_count = 0
        tags_restored = 0
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

            # Union tags from every printing that previously carried them.
            by_slug: dict[str, dict[str, Any]] = {}
            for card in group:
                for t in tag_rows_by_card.get(str(card.get("id")), []):
                    slug = str(t.get("tag_slug") or "")
                    if not slug:
                        continue
                    prev = by_slug.get(slug)
                    if prev is None:
                        by_slug[slug] = t
                        continue
                    # Prefer earliest tagged_at when both present
                    ta = t.get("tagged_at")
                    pa = prev.get("tagged_at")
                    if ta is not None and (pa is None or ta < pa):
                        by_slug[slug] = t

            for slug, t in by_slug.items():
                conn.execute(
                    text(
                        """
                        INSERT INTO oracle_tags (oracle_id, tag_slug, tagged_by, tagged_at)
                        VALUES (
                            :oid,
                            :slug,
                            :uid,
                            COALESCE(CAST(:tagged_at AS timestamptz), NOW())
                        )
                        ON CONFLICT (oracle_id, tag_slug) DO NOTHING
                        """
                    ),
                    {
                        "oid": oracle_id,
                        "slug": slug,
                        "uid": t.get("tagged_by"),
                        "tagged_at": t.get("tagged_at"),
                    },
                )
                tags_restored += 1

        if tag_rows_by_card:
            print(
                f"Restored/unioned {tags_restored} oracle tag attachment(s) "
                f"across {oracle_count} oracle(s)."
            )

        return {
            "cards": len(cards),
            "oracles": oracle_count,
            "evolve_from_backfilled": len(evolve_updates),
            "oracle_tags_restored": tags_restored,
        }


def build_oracles_for_sets(engine, set_ids: list[str]) -> dict[str, int]:
    """Assign oracle groupings for printings in the given sets only.

    Does not wipe pokemon_oracles — merges into existing fingerprints when
    gameplay matches a card already in the catalog.
    """
    normalized = []
    seen: set[str] = set()
    for sid in set_ids:
        key = sid.lower()
        if key not in seen:
            seen.add(key)
            normalized.append(key)
    if not normalized:
        return {"cards": 0, "oracles": 0, "oracles_created": 0, "evolve_from_backfilled": 0}

    persist_category_corrections(engine)
    persist_card_corrections(engine)

    with engine.begin() as conn:
        batch = load_cards(conn, set_ids=normalized)
        if not batch:
            print(f"No pokemon_cards rows in set(s): {', '.join(normalized)}")
            return {"cards": 0, "oracles": 0, "oracles_created": 0, "evolve_from_backfilled": 0}

        batch_ids = {str(c["id"]) for c in batch}
        donors = load_evolve_donor_cards(conn)
        donor_ids = {str(c["id"]) for c in donors}
        combined = batch + [c for c in donors if str(c["id"]) not in batch_ids]
        evolve_updates = backfill_evolve_from(combined)
        evolve_updates = [(cid, evo) for cid, evo in evolve_updates if cid in batch_ids]
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

        _assign_card_fingerprints(batch)
        soft_remapped = merge_non_pokemon_name_fingerprints(batch)
        if soft_remapped:
            mode = (
                f"≥{int(SOFT_TEXT_SIM_THRESHOLD * 100)}% text"
                if USE_NON_POKEMON_TEXT_SIMILARITY
                else "same name"
            )
            print(f"Merged {soft_remapped} non-Pokémon printing(s) by {mode}.")

        by_fingerprint: dict[str, list[dict[str, Any]]] = {}
        for card in batch:
            by_fingerprint.setdefault(card["_oracle_fingerprint"], []).append(card)

        oracle_count = 0
        oracles_created = 0
        for fp, group in by_fingerprint.items():
            oracle_id = fp
            existing = conn.execute(
                text("SELECT id FROM pokemon_oracles WHERE id = :id"),
                {"id": oracle_id},
            ).first()
            if existing:
                linked = load_cards(conn, oracle_ids=[oracle_id])
                by_id = {str(c["id"]): c for c in linked}
                for card in group:
                    by_id[str(card["id"])] = card
                all_group = list(by_id.values())
                _assign_card_fingerprints(all_group)
            else:
                all_group = group
                oracles_created += 1

            rep = pick_representative(all_group)
            _upsert_oracle(conn, _oracle_row_payload(oracle_id, fp, rep, all_group))
            _link_cards_to_oracle(
                conn,
                oracle_id=oracle_id,
                group=group,
                rep_id=str(rep["id"]),
            )
            if existing:
                _refresh_oracle_representative(conn, oracle_id, str(rep["id"]))
            oracle_count += 1

        print(
            f"Incremental oracle — {len(batch)} printing(s) in {len(normalized)} set(s), "
            f"{oracle_count} oracle group(s) ({oracles_created} new)."
        )
        return {
            "cards": len(batch),
            "oracles": oracle_count,
            "oracles_created": oracles_created,
            "evolve_from_backfilled": len(evolve_updates),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Pokémon oracle groupings")
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument(
        "--set",
        action="append",
        dest="sets",
        metavar="ID",
        help="Limit to set(s); incremental merge (no full-table rebuild)",
    )
    args = parser.parse_args()

    set_ids: list[str] | None = None
    if args.sets:
        seen: set[str] = set()
        set_ids = []
        for sid in args.sets:
            key = sid.lower()
            if key not in seen:
                seen.add(key)
                set_ids.append(key)

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying pokemon oracle migration...")
        apply_migration(engine)

    if set_ids:
        stats = build_oracles_for_sets(engine, set_ids)
        print(
            f"Done — {stats['cards']} printings in {stats['oracles']} oracle group(s)"
            f" ({stats.get('oracles_created', 0)} new;"
            f" evolve_from backfilled: {stats.get('evolve_from_backfilled', 0)})."
        )
    else:
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
