#!/usr/bin/env python3
"""Enrich CK buylist: normalize CK set names, API-first Scryfall IDs, USD/TCG metadata."""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from config import (
    BUYLIST_ENRICHED_DIR,
    BUYLIST_MASTER_DIR,
    SCRYFALL_CARDS_LOOKUP,
    ensure_dirs,
)
from set_normalize import attach_set_codes, load_alias_map, load_sets_lookup


def _latest_master_path():
    files = sorted(BUYLIST_MASTER_DIR.glob("cardkingdom_buylist_master_*.csv"))
    if not files:
        raise FileNotFoundError(f"No master files in {BUYLIST_MASTER_DIR}")
    return files[-1]


def _normalize_finish(df: pd.DataFrame) -> pd.DataFrame:
    name = df["name"].astype(str)
    set_col = df["set"].astype(str)
    out = df.copy()
    out["finish"] = "normal"
    out.loc[name.str.contains("Foil Etched", case=False, na=False), "finish"] = "etched"
    out.loc[set_col.str.contains(r"\bFOIL\b", case=False, na=False), "finish"] = "foil"
    return out


def _coalesce_scryfall_id(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "scryfall_id_api" in out.columns:
        api_id = out["scryfall_id_api"].astype(str).replace({"": pd.NA, "nan": pd.NA})
        if "scryfall_id" in out.columns:
            out["scryfall_id"] = out["scryfall_id"].fillna(api_id)
        else:
            out["scryfall_id"] = api_id
        out = out.drop(columns=["scryfall_id_api"], errors="ignore")
    out["scryfall_id"] = out.get("scryfall_id", pd.Series(dtype=object)).astype(str)
    out.loc[out["scryfall_id"].isin(["", "nan", "None", "<NA>"]), "scryfall_id"] = pd.NA
    return out


def _plst_collector_fallback(df: pd.DataFrame, sets_lookup: pd.DataFrame) -> pd.DataFrame:
    """For plst rows missing scryfall_id, build collector key from card name suffix."""
    out = df.copy()
    missing = out["scryfall_id"].isna() & (out["set_code"] == "plst")
    if not missing.any():
        out["scryfall_collector_number"] = out["collector_number"].astype(str)
        return out

    suffix_map = sets_lookup.rename(columns={"name": "suffix_hint", "code": "suffix_set_code"})
    suffix_map["suffix_set_code"] = suffix_map["suffix_set_code"].astype(str).str.lower()

    out["suffix_hint"] = None
    out.loc[missing, "suffix_hint"] = (
        out.loc[missing, "name"].str.extract(r"\(([^()]*)\)$", expand=False)
    )
    out = out.merge(suffix_map[["suffix_hint", "suffix_set_code"]], on="suffix_hint", how="left")
    out["scryfall_collector_number"] = out["collector_number"].astype(str)
    plst_join = missing & out["suffix_set_code"].notna()
    out.loc[plst_join, "scryfall_collector_number"] = (
        out.loc[plst_join, "suffix_set_code"].str.upper()
        + "-"
        + out.loc[plst_join, "collector_number"].astype(str)
    )
    return out


def _join_card_metadata(df: pd.DataFrame, scryfall_cards: pd.DataFrame) -> pd.DataFrame:
    meta_cols = [
        "scryfall_id",
        "set_code",
        "tcgplayer_id",
        "tcgplayer_etched_id",
        "usd",
        "usd_foil",
        "usd_etched",
    ]
    by_id = (
        scryfall_cards[meta_cols]
        .dropna(subset=["scryfall_id"])
        .drop_duplicates(subset=["scryfall_id"], keep="first")
        .rename(
            columns={
                "set_code": "set_code_from_card",
                "tcgplayer_id": "tcgplayer_id_sf",
                "tcgplayer_etched_id": "tcgplayer_etched_id_sf",
                "usd": "usd_sf",
                "usd_foil": "usd_foil_sf",
                "usd_etched": "usd_etched_sf",
            }
        )
    )

    out = df.merge(by_id, on="scryfall_id", how="left")
    out["set_code"] = out["set_code"].fillna(out["set_code_from_card"])
    for col in ("tcgplayer_id", "tcgplayer_etched_id", "usd", "usd_foil", "usd_etched"):
        sf_col = f"{col}_sf"
        if sf_col not in out.columns:
            continue
        if col not in out.columns:
            out[col] = out[sf_col]
        else:
            out[col] = out[col].fillna(out[sf_col])
        out = out.drop(columns=[sf_col], errors="ignore")
    out = out.drop(columns=["set_code_from_card"], errors="ignore")

    # Fallback: set + collector join only when scryfall_id still missing
    still_missing = out["scryfall_id"].isna() & out["set_code"].notna()
    if still_missing.any():
        cards_keyed = scryfall_cards[
            ["scryfall_id", "set_code", "collector_number", "tcgplayer_id", "tcgplayer_etched_id", "usd", "usd_foil", "usd_etched"]
        ].copy()
        cards_keyed["set_code"] = cards_keyed["set_code"].astype(str).str.lower()
        cards_keyed["collector_number"] = cards_keyed["collector_number"].astype(str)
        cards_keyed = cards_keyed.drop_duplicates(subset=["set_code", "collector_number"], keep="first")

        fallback = out.loc[still_missing].merge(
            cards_keyed,
            left_on=["set_code", "scryfall_collector_number"],
            right_on=["set_code", "collector_number"],
            how="left",
            suffixes=("", "_fb"),
        )
        for col in ("scryfall_id", "tcgplayer_id", "tcgplayer_etched_id", "usd", "usd_foil", "usd_etched"):
            fb_col = f"{col}_fb" if f"{col}_fb" in fallback.columns else col
            if fb_col not in fallback.columns:
                continue
            fb_series = pd.Series(
                fallback[fb_col].to_numpy(),
                index=out.loc[still_missing].index,
            )
            out.loc[still_missing, col] = out.loc[still_missing, col].combine_first(fb_series)

    return out


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    if not SCRYFALL_CARDS_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {SCRYFALL_CARDS_LOOKUP}. Run pipeline/refresh_scryfall.py first."
        )

    sets_lookup = load_sets_lookup()
    alias_map = load_alias_map()
    scryfall_cards = pd.read_csv(SCRYFALL_CARDS_LOOKUP, low_memory=False)
    scryfall_cards["set_code"] = scryfall_cards["set_code"].astype(str).str.lower()
    scryfall_cards["collector_number"] = scryfall_cards["collector_number"].astype(str)
    scryfall_cards["scryfall_id"] = scryfall_cards["scryfall_id"].astype(str)

    core_cols = [
        "name",
        "set",
        "collector_number",
        "finish",
        "cash_price",
        "credit_price",
        "max_qty",
    ]
    extra = [c for c in df.columns if c not in core_cols]
    ck = df[core_cols + extra].copy()
    ck["collector_number"] = ck["collector_number"].astype(str)

    ck = _normalize_finish(ck)
    ck = _coalesce_scryfall_id(ck)
    ck = attach_set_codes(ck, sets_lookup, alias_map)
    ck = _plst_collector_fallback(ck, sets_lookup)
    ck = _join_card_metadata(ck, scryfall_cards)

    return ck


def main() -> int:
    ensure_dirs()
    today = date.today().isoformat()
    master = _latest_master_path()
    print(f"Enriching {master}...")
    df = pd.read_csv(master, low_memory=False)
    enriched = enrich(df)
    enriched["snapshot_date"] = today

    out = BUYLIST_ENRICHED_DIR / f"full_ck_buylist_export_{today}.csv"
    enriched.to_csv(out, index=False)

    n = len(enriched)
    id_ok = enriched["scryfall_id"].notna().sum()
    set_ok = enriched["set_code"].notna().sum()
    print(f"Wrote {n} rows to {out}")
    print(f"scryfall_id: {id_ok}/{n} ({100 * id_ok / n:.1f}%)")
    print(f"set_code:    {set_ok}/{n} ({100 * set_ok / n:.1f}%)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
