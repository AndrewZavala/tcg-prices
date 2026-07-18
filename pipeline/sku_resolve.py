"""Resolve Scryfall / TCGplayer IDs from CK SKU when scryfall_id collides across printings."""

from __future__ import annotations

import re

import pandas as pd

_SKU_RE = re.compile(r"^([A-Za-z0-9]+)-(.+)$")
_SKIP_SKU = {"", "api", "nan", "none"}


def parse_ck_sku(sku) -> tuple[str, str] | None:
    text = str(sku or "").strip()
    if not text or text.lower() in _SKIP_SKU:
        return None
    match = _SKU_RE.match(text)
    if not match:
        return None
    return match.group(1).upper(), match.group(2).strip()


def _collector_base(value) -> str:
    return re.sub(r"[★*☆]+", "", str(value or "")).strip().lstrip("0") or str(value or "").strip()


def _collector_norm(value) -> str:
    """Numeric collector for same-set collision checks (84 == 0084)."""
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.lstrip("0") or digits


def _prefix_set_code_candidates(prefix: str, valid_codes: set[str], *, _variant_fallback: bool = True) -> list[str]:
    """Map CK SKU prefix to Scryfall set codes (try exact, foil F-, promo SF-)."""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(code: str) -> None:
        code = code.lower()
        if code and code in valid_codes and code not in seen:
            seen.add(code)
            ordered.append(code)

    p = prefix.upper()
    add(p)
    if p.startswith("F") and len(p) > 1:
        add(p[1:])
    if p.startswith("SF") and len(p) > 2:
        add(p[2:])

    # CK promo-pack SKUs use set prefix + collector ending in P (e.g. NEO-082P → pneo).
    for code in list(ordered):
        add(f"p{code}")

    # Variant prefixes CK uses for alternate printings (e.g. RFBLC-0096 → blc).
    if not ordered and _variant_fallback:
        if p.startswith("RF") and len(p) > 2:
            ordered = _prefix_set_code_candidates(
                p[2:], valid_codes, _variant_fallback=False
            )
        elif p.startswith("R") and len(p) > 1:
            ordered = _prefix_set_code_candidates(
                p[1:], valid_codes, _variant_fallback=False
            )

    return ordered


def _collector_match_keys(collector: str, finish: str) -> list[str]:
    raw = collector.strip()
    keys = [raw, raw.lstrip("0") or raw, _collector_base(raw)]
    finish_l = str(finish or "normal").lower()
    if finish_l in {"foil", "etched"}:
        for base in list(keys):
            keys.extend([f"{base}★", f"{base}*", f"{base}☆"])
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
        lower = key.lower()
        if lower and lower not in seen:
            seen.add(lower)
            out.append(lower)
    return out


def _build_set_collector_index(subset: pd.DataFrame) -> dict[str, pd.Series]:
    """Map collector match keys to Scryfall rows for fast SKU lookup."""
    index: dict[str, pd.Series] = {}
    if subset.empty:
        return index
    for _, row in subset.iterrows():
        cn = str(row["collector_number"])
        for finish in ("normal", "foil", "etched"):
            for key in _collector_match_keys(cn, finish):
                index[key] = row
    return index


def _build_set_base_index(subset: pd.DataFrame) -> dict[str, list[pd.Series]]:
    """Group Scryfall rows by normalized collector number for fallback lookup."""
    base: dict[str, list[pd.Series]] = {}
    if subset.empty:
        return base
    for _, row in subset.iterrows():
        key = _collector_base(row["collector_number"]).lower()
        base.setdefault(key, []).append(row)
    return base


def _match_from_base_index(
    base_index: dict[str, list[pd.Series]],
    collector: str,
    finish: str,
) -> pd.Series | None:
    candidates = base_index.get(_collector_base(collector).lower())
    if not candidates:
        return None
    foilish = str(finish or "normal").lower() in {"foil", "etched"}
    if foilish:
        for row in candidates:
            cn = str(row["collector_number"])
            if any(mark in cn for mark in ("★", "*", "☆")):
                return row
    if len(candidates) == 1:
        return candidates[0]
    return candidates[0]


def _match_card_in_set(
    set_indexes: dict[str, dict[str, pd.Series]],
    base_indexes: dict[str, dict[str, list[pd.Series]]],
    set_code: str,
    collector: str,
    finish: str,
) -> pd.Series | None:
    code = set_code.lower()
    subset_index = set_indexes.get(code, {})
    for key in _collector_match_keys(collector, finish):
        hit = subset_index.get(key)
        if hit is not None:
            return hit
    return _match_from_base_index(base_indexes.get(code, {}), collector, finish)


def _build_prefix_to_first_set(
    valid_codes: set[str],
    prefixes: set[str] | None = None,
) -> dict[str, str]:
    """Map CK SKU prefix to the first Scryfall set code _prefix_set_code_candidates would try."""
    if prefixes is None:
        prefixes = {c.upper() for c in valid_codes}
        prefixes |= {f"F{c.upper()}" for c in valid_codes}
        prefixes |= {f"SF{c.upper()}" for c in valid_codes}
    out: dict[str, str] = {}
    for prefix in prefixes:
        cands = _prefix_set_code_candidates(prefix, valid_codes)
        if cands:
            out[prefix.upper()] = cands[0]
    return out


def resolve_card_from_sku(
    sku,
    finish: str,
    set_indexes: dict[str, dict[str, pd.Series]],
    base_indexes: dict[str, dict[str, list[pd.Series]]],
    valid_codes: set[str],
    *,
    prefix_to_set: dict[str, str] | None = None,
) -> pd.Series | None:
    parsed = parse_ck_sku(sku)
    if not parsed:
        return None
    prefix, collector = parsed
    if prefix_to_set is not None:
        set_code = prefix_to_set.get(prefix.upper())
        if set_code:
            return _match_card_in_set(set_indexes, base_indexes, set_code, collector, finish)
        return None
    for set_code in _prefix_set_code_candidates(prefix, valid_codes):
        card = _match_card_in_set(set_indexes, base_indexes, set_code, collector, finish)
        if card is not None:
            return card
    return None


def _clean_pid(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(".0", "")
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        return str(int(float(text)))
    except (ValueError, TypeError):
        return text


def _resolve_sku_pairs(
    pairs: pd.DataFrame,
    set_indexes: dict[str, dict[str, pd.Series]],
    base_indexes: dict[str, dict[str, list[pd.Series]]],
    valid_codes: set[str],
) -> pd.DataFrame:
    if pairs.empty:
        return pd.DataFrame(
            columns=[
                "sku",
                "finish",
                "sku_tcgplayer_id",
                "sku_scryfall_id",
                "sku_set_code",
                "sku_pid",
            ]
        )

    work = pairs.copy()
    work["sku"] = work["sku"].astype(str).str.strip()
    work["finish"] = (
        work["finish"]
        .astype(str)
        .str.lower()
        .replace({"nonfoil": "normal", "": "normal", "nan": "normal"})
    )
    extracted = work["sku"].str.extract(_SKU_RE)
    work["prefix"] = extracted[0].str.upper()
    work["collector"] = extracted[1].str.strip()
    work = work[work["prefix"].notna() & work["collector"].notna()]
    if work.empty:
        return pd.DataFrame(
            columns=[
                "sku",
                "finish",
                "sku_tcgplayer_id",
                "sku_scryfall_id",
                "sku_set_code",
                "sku_pid",
            ]
        )

    prefix_to_set = _build_prefix_to_first_set(valid_codes, set(work["prefix"].unique()))
    work["set_code"] = work["prefix"].map(prefix_to_set)
    work = work[work["set_code"].notna()]
    if work.empty:
        return pd.DataFrame(
            columns=[
                "sku",
                "finish",
                "sku_tcgplayer_id",
                "sku_scryfall_id",
                "sku_set_code",
                "sku_pid",
            ]
        )

    rows: list[dict] = []
    for prefix, collector, finish, sku, set_code in work[
        ["prefix", "collector", "finish", "sku", "set_code"]
    ].itertuples(index=False, name=None):
        card = _match_card_in_set(set_indexes, base_indexes, set_code, collector, finish)
        if card is None:
            continue
        sku_pid = _clean_pid(card.get("tcgplayer_id"))
        if not sku_pid:
            continue
        rows.append(
            {
                "sku": sku,
                "finish": finish,
                "sku_tcgplayer_id": card["tcgplayer_id"],
                "sku_scryfall_id": card["scryfall_id"],
                "sku_set_code": str(card["set_code"]).lower(),
                "sku_collector_norm": _collector_norm(collector),
                "sku_pid": sku_pid,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "sku",
                "finish",
                "sku_tcgplayer_id",
                "sku_scryfall_id",
                "sku_set_code",
                "sku_pid",
            ]
        )
    return pd.DataFrame(rows)


def apply_sku_tcgplayer_resolution(
    df: pd.DataFrame,
    scryfall_cards: pd.DataFrame,
) -> pd.DataFrame:
    """Prefer SKU-derived tcgplayer_id when CK scryfall_id maps to a different printing."""
    if "sku" not in df.columns:
        return df

    out = df.copy()
    cards = scryfall_cards.copy()
    cards["set_code"] = cards["set_code"].astype(str).str.lower()
    cards["scryfall_id"] = cards["scryfall_id"].astype(str)
    valid_codes = set(cards["set_code"].dropna().unique())
    cards_by_set = {code: grp for code, grp in cards.groupby("set_code", sort=False)}
    set_indexes = {
        code: _build_set_collector_index(grp) for code, grp in cards_by_set.items()
    }
    base_indexes = {
        code: _build_set_base_index(grp) for code, grp in cards_by_set.items()
    }
    id_meta = cards.drop_duplicates(subset=["scryfall_id"]).set_index("scryfall_id")
    id_set_code = id_meta["set_code"]
    id_collector_norm = id_meta["collector_number"].map(_collector_norm)

    out["finish"] = out["finish"].astype(str).str.lower()
    sku_text = out["sku"].astype(str).str.strip()
    sku_mask = sku_text.ne("") & ~sku_text.str.lower().isin(_SKIP_SKU)
    if not sku_mask.any():
        return out

    pairs = (
        out.loc[sku_mask, ["sku", "finish"]]
        .assign(sku=sku_text.loc[sku_mask].values)
        .drop_duplicates()
    )
    resolved = _resolve_sku_pairs(pairs, set_indexes, base_indexes, valid_codes)
    if resolved.empty:
        return out

    merged = out.merge(resolved, on=["sku", "finish"], how="left")
    current_pid = merged["tcgplayer_id"].map(_clean_pid)
    id_set = merged["scryfall_id"].map(
        lambda sid: str(id_set_code.get(str(sid), "")).lower()
        if pd.notna(sid) and str(sid).lower() not in {"nan", "none"}
        else ""
    )
    sku_set = merged["sku_set_code"].fillna("").astype(str).str.lower()
    id_collector = merged["scryfall_id"].map(
        lambda sid: id_collector_norm.get(str(sid), "")
        if pd.notna(sid) and str(sid).lower() not in {"nan", "none"}
        else ""
    )
    sku_collector = merged.get("sku_collector_norm", pd.Series("", index=merged.index)).fillna("").astype(str)
    numeric_collector_clash = (
        sku_collector.ne("")
        & id_collector.ne("")
        & sku_collector.str.match(r"^\d+$", na=False)
        & id_collector.str.match(r"^\d+$", na=False)
        & (sku_collector != id_collector)
    )

    scryfall_id_text = merged["scryfall_id"].astype(str).str.strip().str.lower()
    sku_scryfall_id_text = (
        merged["sku_scryfall_id"].astype(str).str.strip().str.lower()
        if "sku_scryfall_id" in merged.columns
        else pd.Series("", index=merged.index)
    )
    _invalid_sid = {"", "nan", "none", "<na>"}
    has_ck_identity = (
        merged["scryfall_id"].notna()
        & ~scryfall_id_text.isin(_invalid_sid)
        & current_pid.notna()
    )
    scryfall_id_mismatch = (
        ~sku_scryfall_id_text.isin(_invalid_sid)
        & ~scryfall_id_text.isin(_invalid_sid)
        & (sku_scryfall_id_text != scryfall_id_text)
    )
    override = (
        merged["sku_pid"].notna()
        & (merged["sku_pid"] != current_pid)
        & (
            ~has_ck_identity
            | ((id_set == sku_set) & numeric_collector_clash)
            | (scryfall_id_mismatch & numeric_collector_clash)
        )
    )
    if not override.any():
        return out

    out.loc[override, "tcgplayer_id"] = merged.loc[override, "sku_tcgplayer_id"].values
    out.loc[override, "scryfall_id"] = merged.loc[override, "sku_scryfall_id"].values
    if "set_code" in out.columns:
        out.loc[override, "set_code"] = merged.loc[override, "sku_set_code"].values
    return out
