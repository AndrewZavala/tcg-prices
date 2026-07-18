#!/usr/bin/env python3
"""Screen full CK buylist with tcgcsv spreads; pick live-scrape candidates."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from config import TCGCSV_PRICES_LOOKUP
from enrich_buylist import _effective_tcg_product_id

USE_SCREENING = os.environ.get("OPPORTUNITY_USE_SCREENING", "1").lower() in {
    "1",
    "true",
    "yes",
}
MIN_SCREEN_SPREAD = float(os.environ.get("OPPORTUNITY_MIN_SCREEN_SPREAD", "0.25"))
MIN_SCREEN_PCT = float(os.environ.get("OPPORTUNITY_MIN_SCREEN_PCT", "5"))
MIN_CK_CASH = float(os.environ.get("OPPORTUNITY_MIN_CK_CASH", "0.50") or "0.50")


def _env_int(key: str, default: str) -> int:
    raw = os.environ.get(key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    return int(raw)


MAX_SCREEN_CANDIDATES = _env_int("OPPORTUNITY_SCREEN_MAX_CANDIDATES", "0")
FALLBACK_TOP_N = _env_int("OPPORTUNITY_TOP_N", "0")


def finish_to_sub_type(finish: str) -> str:
    key = str(finish or "normal").strip().lower()
    if key in {"foil"}:
        return "Foil"
    if key in {"etched", "foil etched"}:
        return "Foil"
    return "Normal"


def _normalize_finish(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .replace({"nonfoil": "normal", "": "normal", "nan": "normal"})
    )


def load_tcgcsv_prices() -> pd.DataFrame:
    if not TCGCSV_PRICES_LOOKUP.exists() or TCGCSV_PRICES_LOOKUP.stat().st_size == 0:
        raise FileNotFoundError(
            f"Missing {TCGCSV_PRICES_LOOKUP}. Run pipeline/refresh_tcgcsv.py first."
        )
    prices = pd.read_csv(TCGCSV_PRICES_LOOKUP, low_memory=False)
    prices["product_id"] = prices["product_id"].astype(str)
    prices["sub_type_name"] = prices["sub_type_name"].astype(str).str.strip()
    for col in ("low_price", "market_price", "mid_price"):
        if col in prices.columns:
            prices[col] = pd.to_numeric(prices[col], errors="coerce")
    return prices.drop_duplicates(subset=["product_id", "sub_type_name"], keep="last")


def attach_tcgcsv_prices(enriched: pd.DataFrame, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Join tcgcsv low/market onto enriched rows by tcg product id + finish."""
    out = enriched.copy()
    out["finish_norm"] = _normalize_finish(out["finish"])
    out["tcg_product_id"] = _effective_tcg_product_id(out)
    out["sub_type_name"] = out["finish_norm"].map(finish_to_sub_type)

    if prices is None:
        prices = load_tcgcsv_prices()

    joined = out.merge(
        prices[
            ["product_id", "sub_type_name", "low_price", "market_price", "mid_price"]
        ].rename(columns={"product_id": "tcg_product_id"}),
        on=["tcg_product_id", "sub_type_name"],
        how="left",
    )
    joined["tcg_low"] = joined["low_price"]
    joined["tcg_market"] = joined["market_price"]
    joined["tcg_mid"] = joined.get("mid_price")
    return joined


def tcg_reference_price(ck_cash: pd.Series, tcg_low: pd.Series, tcg_market: pd.Series) -> pd.Series:
    """Same nearest-to-CK pick used by the buylist search API."""
    ck = pd.to_numeric(ck_cash, errors="coerce")
    low = pd.to_numeric(tcg_low, errors="coerce")
    market = pd.to_numeric(tcg_market, errors="coerce")
    both = low.notna() & market.notna()
    ref = low.copy()
    ref[both] = np.where(
        (ck[both] - low[both]).abs() <= (ck[both] - market[both]).abs(),
        low[both],
        market[both],
    )
    return ref.fillna(market)


def screen_candidates(enriched: pd.DataFrame, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return CK rows worth live listing scrape, sorted by estimated spread."""
    df = attach_tcgcsv_prices(enriched, prices)
    df["cash_price"] = pd.to_numeric(df["cash_price"], errors="coerce")
    df["product_id"] = df["tcg_product_id"]

    df = df[df["product_id"].notna() & df["cash_price"].notna()].copy()
    if MIN_CK_CASH > 0:
        df = df[df["cash_price"] >= MIN_CK_CASH]

    df["tcg_screen_price"] = tcg_reference_price(df["cash_price"], df["tcg_low"], df["tcg_market"])
    df = df[df["tcg_screen_price"].notna() & (df["tcg_screen_price"] > 0)]

    df["screen_spread"] = (df["cash_price"] - df["tcg_screen_price"]).round(2)
    df["screen_pct"] = (df["screen_spread"] / df["tcg_screen_price"] * 100).round(2)

    df = df[df["screen_spread"] >= MIN_SCREEN_SPREAD]
    if MIN_SCREEN_PCT > 0:
        df = df[df["screen_pct"] >= MIN_SCREEN_PCT]

    df = df.sort_values(
        ["screen_spread", "screen_pct", "cash_price"],
        ascending=[False, False, False],
    )
    df = df.drop_duplicates(subset=["product_id", "finish_norm"], keep="first")

    if MAX_SCREEN_CANDIDATES > 0 and len(df) > MAX_SCREEN_CANDIDATES:
        df = df.head(MAX_SCREEN_CANDIDATES)

    return df.reset_index(drop=True)


def to_scrape_targets(candidates: pd.DataFrame) -> pd.DataFrame:
    """Shape screened rows for browser scrape / export (matches _build_scrape_targets)."""
    from export_opportunities import targets_from_ranked

    ranked = candidates.copy()
    ranked["product_id"] = ranked["product_id"].astype(str)
    ranked["finish"] = ranked["finish_norm"] if "finish_norm" in ranked.columns else ranked["finish"]
    return targets_from_ranked(ranked)


def build_scrape_targets_from_master(
    master: pd.DataFrame,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Screened targets when enabled; otherwise legacy top-N by CK cash."""
    from scrape_tcg_listings import _build_scrape_targets_legacy

    if not USE_SCREENING:
        from config import SCRYFALL_CARDS_LOOKUP
        import pandas as pd

        scry = pd.read_csv(SCRYFALL_CARDS_LOOKUP, low_memory=False)
        return _build_scrape_targets_legacy(master, scry)

    if enriched is None:
        from enrich_buylist import enrich

        enriched = enrich(master, include_listings=False)

    candidates = screen_candidates(enriched)
    if candidates.empty:
        raise RuntimeError(
            "Screening returned no candidates. Check tcgcsv freshness and "
            f"thresholds (spread>={MIN_SCREEN_SPREAD}, pct>={MIN_SCREEN_PCT})."
        )
    return to_scrape_targets(candidates)


def select_opportunity_targets(enriched: pd.DataFrame) -> pd.DataFrame:
    """Rows used for live listing fetch + opportunity export."""
    if USE_SCREENING:
        return screen_candidates(enriched)
    from export_opportunities import rank_buylist_targets

    top_n = FALLBACK_TOP_N if FALLBACK_TOP_N > 0 else 5000
    return rank_buylist_targets(enriched, top_n)


def print_screen_summary(candidates: pd.DataFrame, total: int) -> None:
    print(
        f"Screened {total:,} buylist rows → {len(candidates):,} scrape candidates "
        f"(spread>=${MIN_SCREEN_SPREAD:.2f}, roi>={MIN_SCREEN_PCT:.1f}%, "
        f"ck>=${MIN_CK_CASH:.2f})"
    )
    if candidates.empty:
        return
    print(
        f"  spread range ${candidates['screen_spread'].min():.2f}"
        f"–${candidates['screen_spread'].max():.2f} · "
        f"median ${candidates['screen_spread'].median():.2f}"
    )


def main() -> int:
    from enrich_buylist import _latest_master_path, enrich

    master = pd.read_csv(_latest_master_path(), low_memory=False)
    enriched = enrich(master, include_listings=False)
    candidates = screen_candidates(enriched)
    print_screen_summary(candidates, len(enriched))
    if not candidates.empty:
        print("\nTop 10 candidates:")
        cols = ["name", "set", "finish_norm", "cash_price", "tcg_screen_price", "screen_spread", "screen_pct"]
        show = [c for c in cols if c in candidates.columns]
        print(candidates[show].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
