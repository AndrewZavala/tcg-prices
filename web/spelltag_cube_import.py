"""Parse CubeKoga / Tabletop Simulator cube JSON and match cards in Spell Tag."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import unquote

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Keep in sync with pipeline/enrich_pokemon_subtypes.POKEMONTCG_SET_ALIASES
POKEMONTCG_SET_ALIASES: dict[str, str] = {
    "me01": "me1",
    "me02": "me2",
    "me02.5": "me2pt5",
    "me03": "me3",
    "me04": "me4",
    "me05": "me5",
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
    "sv10.5b": "zsv10pt5",
    "sv10.5w": "rsv10pt5",
    "sm3.5": "sm35",
    "sm7.5": "sm75",
    "swsh3.5": "swsh35",
    "swsh4.5": "swsh45",
    "swsh4.5sv": "swsh45sv",
    "swsh9.5tg": "swsh9tg",
    "swsh10.5": "pgo",
    "swsh10.5tg": "swsh10tg",
    "swsh11.5tg": "swsh11tg",
    "swsh12.5": "swsh12pt5",
    "swsh12.5tg": "swsh12tg",
    "swsh12.5gg": "swsh12pt5gg",
    "cel25cc": "cel25c",
}

_PTCGIO_FACE_RE = re.compile(
    r"images\.pokemontcg\.io/([^/]+)/(\d+)(?:_[a-z]+)?\.(?:png|jpg|jpeg|webp)",
    re.I,
)
_PKMNCARDS_FACE_RE = re.compile(
    r"pkmncards\.com/wp-content/uploads/([a-z0-9]+)_en_(\d+)_",
    re.I,
)
_NAME_NOISE_RE = re.compile(r"\s+I['']$|['']$", re.I)


def _reverse_set_aliases() -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for tcgdex, api in POKEMONTCG_SET_ALIASES.items():
        rev.setdefault(api.lower(), []).append(tcgdex.lower())
    return rev


_REVERSE_SET_ALIASES = _reverse_set_aliases()


def _tcgdex_set_candidates(api_set: str) -> list[str]:
    api = api_set.lower()
    out = [api]
    out.extend(_REVERSE_SET_ALIASES.get(api, []))
    return list(dict.fromkeys(out))


def _local_id_variants(num: str) -> list[str]:
    raw = unquote(str(num or "").strip())
    if not raw:
        return []
    variants = [raw]
    if raw.isdigit():
        n = int(raw)
        variants.extend([str(n), f"{n:02d}", f"{n:03d}"])
    elif raw.upper().startswith("CC") and raw[2:].isdigit():
        n = int(raw[2:])
        variants.extend([raw.upper(), f"CC{n:02d}", f"CC{n:03d}"])
    return list(dict.fromkeys(variants))


def _normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _NAME_NOISE_RE.sub("", s.strip())
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def parse_face_url(face_url: str) -> tuple[str, str] | None:
    """Return (api_set, card_number) from a cube card face image URL."""
    url = unquote(face_url or "")
    m = _PTCGIO_FACE_RE.search(url)
    if m:
        return m.group(1).lower(), m.group(2)
    m = _PKMNCARDS_FACE_RE.search(url)
    if m:
        return m.group(1).lower(), m.group(2)
    return None


def extract_cube_entries(cube_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull card rows from a TTS / CubeKoga ObjectStates export."""
    entries: list[dict[str, Any]] = []
    for state in cube_json.get("ObjectStates") or []:
        if not isinstance(state, dict):
            continue
        custom = state.get("CustomDeck") or {}
        for obj in state.get("ContainedObjects") or []:
            if not isinstance(obj, dict) or obj.get("Name") != "Card":
                continue
            card_id_num = obj.get("CardID")
            if card_id_num is None:
                continue
            try:
                deck_key = str(int(card_id_num) // 100)
            except (TypeError, ValueError):
                continue
            deck_info = custom.get(deck_key) if isinstance(custom, dict) else None
            face_url = ""
            if isinstance(deck_info, dict):
                face_url = str(deck_info.get("FaceURL") or "")
            entries.append(
                {
                    "nickname": str(obj.get("Nickname") or "").strip(),
                    "memo": str(obj.get("Memo") or "").strip(),
                    "face_url": face_url,
                }
            )
    return entries


def _candidate_card_ids(api_set: str, num: str) -> list[str]:
    locals_ = _local_id_variants(num)
    sets_ = _tcgdex_set_candidates(api_set)
    ids: list[str] = []
    for set_id in sets_:
        for local in locals_:
            ids.append(f"{set_id}-{local}")
    # Some catalog ids match pokemontcg.io set codes directly.
    for local in locals_:
        ids.append(f"{api_set.lower()}-{local}")
    return list(dict.fromkeys(ids))


def _load_cards_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.set_id, c.local_id, s.name AS set_name
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            WHERE c.id = ANY(:ids)
            """
        ),
        {"ids": ids},
    ).mappings().all()
    return {str(r["id"]): dict(r) for r in rows}


def _load_cards_by_set_local(
    conn: Connection, set_ids: list[str], local_ids: list[str]
) -> list[dict[str, Any]]:
    if not set_ids or not local_ids:
        return []
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.set_id, c.local_id, s.name AS set_name
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            WHERE c.set_id = ANY(:set_ids)
              AND c.local_id = ANY(:local_ids)
            """
        ),
        {"set_ids": set_ids, "local_ids": local_ids},
    ).mappings().all()
    return [dict(r) for r in rows]


def _load_cards_by_name_in_sets(
    conn: Connection, name: str, set_ids: list[str]
) -> list[dict[str, Any]]:
    norm = _normalize_name(name)
    if not norm or not set_ids:
        return []
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.set_id, c.local_id, s.name AS set_name
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            WHERE c.set_id = ANY(:set_ids)
              AND lower(c.name) = :name
            """
        ),
        {"set_ids": set_ids, "name": norm},
    ).mappings().all()
    if rows:
        return [dict(r) for r in rows]
    like = f"%{norm}%"
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.set_id, c.local_id, s.name AS set_name
            FROM pokemon_cards c
            INNER JOIN pokemon_sets s ON s.id = c.set_id
            WHERE c.set_id = ANY(:set_ids)
              AND c.name ILIKE :like
            ORDER BY length(c.name) ASC
            LIMIT 5
            """
        ),
        {"set_ids": set_ids, "like": like},
    ).mappings().all()
    return [dict(r) for r in rows]


def match_cube_entries(conn: Connection, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Match cube rows to catalog cards. Returns preview payload."""
    # Precompute all candidate ids for one bulk lookup.
    row_candidates: list[list[str]] = []
    row_meta: list[dict[str, Any]] = []
    all_ids: list[str] = []

    for entry in entries:
        parsed = parse_face_url(entry.get("face_url") or "")
        cids: list[str] = []
        api_set = ""
        num = ""
        if parsed:
            api_set, num = parsed
            cids = _candidate_card_ids(api_set, num)
            all_ids.extend(cids)
        row_candidates.append(cids)
        row_meta.append({"entry": entry, "api_set": api_set, "num": num, "parsed": bool(parsed)})

    by_id = _load_cards_by_ids(conn, list(dict.fromkeys(all_ids)))

    results: list[dict[str, Any]] = []
    matched_ids: list[str] = []

    for meta, cids in zip(row_meta, row_candidates):
        entry = meta["entry"]
        nickname = entry.get("nickname") or ""
        face_url = entry.get("face_url") or ""
        card_row: dict[str, Any] | None = None
        method = ""

        for cid in cids:
            if cid in by_id:
                card_row = by_id[cid]
                method = "id"
                break

        if not card_row and meta["parsed"]:
            set_ids = _tcgdex_set_candidates(meta["api_set"])
            locals_ = _local_id_variants(meta["num"])
            hits = _load_cards_by_set_local(conn, set_ids, locals_)
            if len(hits) == 1:
                card_row = hits[0]
                method = "set_local"
            elif len(hits) > 1 and nickname:
                norm = _normalize_name(nickname)
                named = [h for h in hits if _normalize_name(h["name"]) == norm]
                if len(named) == 1:
                    card_row = named[0]
                    method = "set_local_name"

        if not card_row and meta["parsed"] and nickname:
            set_ids = _tcgdex_set_candidates(meta["api_set"])
            named = _load_cards_by_name_in_sets(conn, nickname, set_ids)
            if len(named) == 1:
                card_row = named[0]
                method = "name"

        if card_row:
            matched_ids.append(str(card_row["id"]))
            results.append(
                {
                    "status": "matched",
                    "method": method,
                    "nickname": nickname,
                    "face_url": face_url,
                    "card_id": card_row["id"],
                    "name": card_row["name"],
                    "set_id": card_row["set_id"],
                    "set_name": card_row["set_name"],
                    "local_id": card_row["local_id"],
                }
            )
        else:
            results.append(
                {
                    "status": "unmatched",
                    "nickname": nickname,
                    "face_url": face_url,
                    "memo": entry.get("memo") or "",
                    "hint": (
                        f"{meta['api_set']}-{meta['num']}" if meta["parsed"] else None
                    ),
                }
            )

    unique_matched = list(dict.fromkeys(matched_ids))
    duplicate_slots = len(matched_ids) - len(unique_matched)

    return {
        "total": len(entries),
        "matched": len(matched_ids),
        "unique_matched": len(unique_matched),
        "unmatched": len(entries) - len(matched_ids),
        "duplicate_slots": duplicate_slots,
        "card_ids": unique_matched,
        "items": results,
    }
