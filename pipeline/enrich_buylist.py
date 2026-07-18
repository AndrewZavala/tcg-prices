#!/usr/bin/env python3
"""Enrich CK buylist: normalize CK set names, API-first Scryfall IDs, USD/TCG metadata."""

from __future__ import annotations

import re
import sys
import time
from datetime import date

import pandas as pd

from config import (
    BUYLIST_ENRICHED_DIR,
    BUYLIST_MASTER_DIR,
    SCRYFALL_CARDS_LOOKUP,
    ensure_dirs,
)
from scrape_tcg_listings import read_listings_lookup
from tcg_condition import apply_condition_prices
from set_normalize import attach_set_codes, load_alias_map, load_sets_lookup
from sku_resolve import apply_sku_tcgplayer_resolution


def _latest_master_path():
    files = sorted(BUYLIST_MASTER_DIR.glob("cardkingdom_buylist_master_*.csv"))
    if not files:
        raise FileNotFoundError(f"No master files in {BUYLIST_MASTER_DIR}")
    return files[-1]


def _normalize_finish(df: pd.DataFrame) -> pd.DataFrame:
    name = df["name"].astype(str)
    set_col = df["set"].astype(str)
    out = df.copy()

    if "finish" in out.columns:
        raw = out["finish"].astype(str).str.strip().str.lower()
        mapped = raw.replace({"nonfoil": "normal", "": "normal", "nan": "normal"})
        out["finish"] = mapped.where(mapped.isin(["normal", "foil", "etched"]), "normal")
    else:
        out["finish"] = "normal"

    out.loc[name.str.contains("Foil Etched", case=False, na=False), "finish"] = "etched"
    out.loc[set_col.str.contains(r"\bFOIL\b", case=False, na=False), "finish"] = "foil"
    return out


def _collector_base(series: pd.Series) -> pd.Series:
    """Strip foil/etched star suffixes so 182 matches 182★ on Scryfall."""
    return (
        series.astype(str)
        .str.replace(r"[★*]+", "", regex=True)
        .str.strip()
    )


def _numeric_prices(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            continue
        out[col] = pd.to_numeric(
            out[col].astype(str).replace({"NA": pd.NA, "nan": pd.NA, "": pd.NA}),
            errors="coerce",
        )
    return out


def _resolve_finish_prices(df: pd.DataFrame, scryfall_cards: pd.DataFrame) -> pd.DataFrame:
    """Backfill foil/etched prices from sibling Scryfall printings (e.g. 7ed #182 vs #182★)."""
    out = _numeric_prices(df, ("usd", "usd_foil", "usd_etched"))
    sc = _numeric_prices(scryfall_cards, ("usd", "usd_foil", "usd_etched"))
    sc["set_code"] = sc["set_code"].astype(str).str.lower()
    sc["collector_number"] = sc["collector_number"].astype(str)
    sc["collector_base"] = _collector_base(sc["collector_number"])

    def _alt_index(price_col: str) -> pd.DataFrame:
        alt = sc[sc[price_col].notna()].copy()
        alt = alt.sort_values(price_col, ascending=False)
        return alt.drop_duplicates(subset=["set_code", "collector_base"], keep="first")

    foil_alt = _alt_index("usd_foil")
    etched_alt = _alt_index("usd_etched")

    finish = out["finish"].astype(str).str.lower()
    out["collector_base"] = _collector_base(out["collector_number"])

    foil_missing = finish.eq("foil") & out["usd_foil"].isna() & out["set_code"].notna()
    if foil_missing.any() and not foil_alt.empty:
        merged = out.loc[foil_missing, ["set_code", "collector_base"]].merge(
            foil_alt[
                ["set_code", "collector_base", "usd_foil", "tcgplayer_id", "scryfall_id"]
            ].rename(columns={"scryfall_id": "scryfall_id_foil"}),
            on=["set_code", "collector_base"],
            how="left",
        )
        idx = out.index[foil_missing]
        out.loc[idx, "usd_foil"] = merged["usd_foil"].values
        foil_ids = merged["scryfall_id_foil"].values
        current_ids = out.loc[idx, "scryfall_id"].values
        out.loc[idx, "scryfall_id"] = [
            foil_ids[i] if pd.notna(foil_ids[i]) else current_ids[i]
            for i in range(len(idx))
        ]

    etched_missing = finish.eq("etched") & out["usd_etched"].isna() & out["set_code"].notna()
    if etched_missing.any() and not etched_alt.empty:
        merged = out.loc[etched_missing, ["set_code", "collector_base"]].merge(
            etched_alt[["set_code", "collector_base", "usd_etched", "scryfall_id"]].rename(
                columns={"scryfall_id": "scryfall_id_etched"}
            ),
            on=["set_code", "collector_base"],
            how="left",
        )
        idx = out.index[etched_missing]
        out.loc[idx, "usd_etched"] = merged["usd_etched"].values
        etched_ids = merged["scryfall_id_etched"].values
        current_ids = out.loc[idx, "scryfall_id"].values
        out.loc[idx, "scryfall_id"] = [
            etched_ids[i] if pd.notna(etched_ids[i]) else current_ids[i]
            for i in range(len(idx))
        ]

    return out.drop(columns=["collector_base"], errors="ignore")


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


def _normalize_tcg_product_id(value) -> pd.Series:
    s = pd.Series(value, dtype=object).astype(str).str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)
    s = s.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    num = pd.to_numeric(s, errors="coerce")
    normalized = s.copy()
    normalized = normalized.where(num.isna(), num.astype("Int64").astype(str))
    return normalized


def _effective_tcg_product_id(df: pd.DataFrame) -> pd.Series:
    finish = df["finish"].astype(str).str.lower()
    etched = _normalize_tcg_product_id(df.get("tcgplayer_etched_id"))
    base = _normalize_tcg_product_id(df.get("tcgplayer_id"))
    return etched.where(finish.eq("etched") & etched.notna(), base)


def _apply_no_listings(df: pd.DataFrame) -> pd.DataFrame:
    """No mp-search listing data — leave TCG buy fields empty."""
    out = df.copy()
    out["ck_cash_adjusted"] = out["cash_price"]
    out["condition_multiplier"] = 1.0
    if "tcg_listing_condition" not in out.columns:
        out["tcg_listing_condition"] = pd.NA
    if "tcg_buy_price" not in out.columns:
        out["tcg_buy_price"] = pd.NA
    return out


def enrich(df: pd.DataFrame, *, include_listings: bool = True) -> pd.DataFrame:
    if not SCRYFALL_CARDS_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {SCRYFALL_CARDS_LOOKUP}. Run pipeline/refresh_scryfall.py first."
        )

    t0 = time.perf_counter()
    sets_lookup = load_sets_lookup()
    alias_map = load_alias_map()
    scryfall_cards = pd.read_csv(SCRYFALL_CARDS_LOOKUP, low_memory=False)
    scryfall_cards["set_code"] = scryfall_cards["set_code"].astype(str).str.lower()
    scryfall_cards["collector_number"] = scryfall_cards["collector_number"].astype(str)
    scryfall_cards["scryfall_id"] = scryfall_cards["scryfall_id"].astype(str)
    print(f"  loaded Scryfall lookup ({time.perf_counter() - t0:.1f}s)")

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
    print(f"  joined Scryfall metadata ({time.perf_counter() - t0:.1f}s)")

    t_sku = time.perf_counter()
    ck = apply_sku_tcgplayer_resolution(ck, scryfall_cards)
    print(f"  SKU tcgplayer resolution ({time.perf_counter() - t_sku:.1f}s)")

    ck = _resolve_finish_prices(ck, scryfall_cards)

    if include_listings:
        t_list = time.perf_counter()
        listings_raw = read_listings_lookup()
        if len(listings_raw) > 0:
            listings_raw["product_id"] = listings_raw["product_id"].astype(str)
            listings_raw["finish"] = listings_raw["finish"].astype(str).str.lower()
            ck = apply_condition_prices(ck, listings_raw)
            print(f"  listing prices ({time.perf_counter() - t_list:.1f}s)")
        else:
            ck = _apply_no_listings(ck)
    else:
        ck = _apply_no_listings(ck)

    print(f"  enrich total ({time.perf_counter() - t0:.1f}s)")
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
    buy_ok = enriched["tcg_buy_price"].notna().sum()
    print(f"Wrote {n} rows to {out}")
    print(f"scryfall_id: {id_ok}/{n} ({100 * id_ok / n:.1f}%)")
    print(f"set_code:    {set_ok}/{n} ({100 * set_ok / n:.1f}%)")
    print(f"tcg_buy:     {buy_ok}/{n} ({100 * buy_ok / n:.1f}%)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
