"""TCG listing conditions and CK buylist condition adjustments (Cardbitrage parity)."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd

# When TCG supply exceeds CK's per-order buy cap, estimate profit across a few CK orders.
# CK only reliably accepts max qty once/day, so keep this conservative (default 2×).
CK_MAX_QTY_ORDER_MULTIPLIER = int(os.environ.get("CK_MAX_QTY_ORDER_MULTIPLIER", "2"))

# CK pays a fraction of listed NM cash for lower conditions (Cardbitrage parity).
# TCGplayer grade → CK grade: NM=NM, LP=EX, MP=VG, HP=G, Damaged=no buy.
CONDITION_MULTIPLIERS: dict[str, float] = {
    "near mint": 1.00,
    "near mint foil": 1.00,
    "lightly played": 0.75,
    "lightly played foil": 0.75,
    "moderately played": 0.50,
    "moderately played foil": 0.50,
    "heavily played": 0.25,
    "heavily played foil": 0.25,
    "damaged": 0.00,
    "damaged foil": 0.00,
}

CK_CONDITION_LABEL: dict[str, str] = {
    "near mint": "NM (100%)",
    "near mint foil": "NM (100%)",
    "lightly played": "LP / EX (75%)",
    "lightly played foil": "LP / EX (75%)",
    "moderately played": "MP / VG (50%)",
    "moderately played foil": "MP / VG (50%)",
    "heavily played": "HP / G (25%)",
    "heavily played foil": "HP / G (25%)",
    "damaged": "Damaged (0%)",
    "damaged foil": "Damaged (0%)",
}

# Aliases users / TCGplayer sometimes emit.
CONDITION_ALIASES: dict[str, str] = {
    "nm": "near mint",
    "near-mint": "near mint",
    "mint": "near mint",
    "lp": "lightly played",
    "lightly-played": "lightly played",
    "ex": "lightly played",
    "excellent": "lightly played",
    "mp": "moderately played",
    "moderately-played": "moderately played",
    "moderately played": "moderately played",
    "vg": "moderately played",
    "very good": "moderately played",
    "hp": "heavily played",
    "heavily-played": "heavily played",
    "g": "heavily played",
    "good": "heavily played",
    "poor": "heavily played",
    "damaged": "damaged",
}


def tcg_product_url(
    product_id: str,
    finish: str = "normal",
    condition: str | None = None,
    seller_key: str | None = None,
) -> str:
    """TCGplayer product page with optional printing and condition filters.

    ``seller_key`` is accepted for call-site compatibility but ignored — seller
    filters made links brittle and are stored separately on opportunities/lots.
    """
    pid = str(product_id or "").strip().replace(".0", "")
    if not pid or pid.lower() in {"nan", "none"}:
        return ""
    params: dict[str, str] = {"Language": "English"}
    finish_l = str(finish or "normal").lower()
    printing = {"foil": "Foil", "etched": "Etched"}.get(finish_l)
    if printing:
        params["Printing"] = printing
    cond_key = normalize_condition(condition)
    condition_label = {
        "near mint": "Near Mint",
        "lightly played": "Lightly Played",
        "moderately played": "Moderately Played",
        "heavily played": "Heavily Played",
        "damaged": "Damaged",
    }.get(cond_key or "")
    if condition_label:
        params["Condition"] = condition_label
    _ = seller_key  # intentionally unused
    return f"https://www.tcgplayer.com/product/{pid}?{urlencode(params)}"


def strip_seller_from_tcg_url(url: str | None) -> str | None:
    """Remove Sellers/sellers query params from a TCG product URL."""
    if not url or not str(url).strip():
        return url
    raw = str(url).strip()
    try:
        parts = urlparse(raw)
    except Exception:
        return raw
    if not parts.query:
        return raw
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() != "sellers"
    ]
    query = urlencode(pairs)
    cleaned = urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, query, parts.fragment)
    )
    return cleaned or raw


def normalize_condition(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "<na>"}:
        return None
    if text in CONDITION_ALIASES:
        text = CONDITION_ALIASES[text]
    if text in CONDITION_MULTIPLIERS:
        return text
    return None


def condition_multiplier(condition: str | None) -> float | None:
    key = normalize_condition(condition)
    if key is None:
        return None
    return CONDITION_MULTIPLIERS.get(key)


def format_condition_display(condition: str | None) -> str:
    if condition is None or (isinstance(condition, float) and pd.isna(condition)):
        return "—"
    raw = str(condition).strip()
    key = normalize_condition(raw)
    if key is None:
        return raw
    label = CK_CONDITION_LABEL.get(key, raw)
    return f"{raw} ({label})" if label and label not in raw else raw


def listing_arbitrage(
    ck_cash: float,
    condition: str,
    price: float,
) -> dict | None:
    """Profit for buying one listing: CK cash × condition% − TCG price."""
    mult = condition_multiplier(condition)
    if mult is None:
        return None
    adj = round(float(ck_cash) * mult, 2)
    buy = float(price)
    profit = round(adj - buy, 2)
    roi = round(profit / buy * 100, 2) if buy > 0 else None
    return {
        "condition": condition,
        "condition_multiplier": mult,
        "ck_cash_adjusted": adj,
        "tcg_buy_price": buy,
        "profit": profit,
        "roi": roi,
    }


def _listing_price(row: pd.Series) -> float | None:
    raw = row.get("price")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        raw = row.get("tcg_buy_price")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _listing_shipping(row: pd.Series) -> float:
    for col in ("shipping_price", "shippingPrice", "seller_shipping_price", "sellerShippingPrice"):
        raw = row.get(col)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        try:
            value = float(str(raw).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        return max(value, 0.0)
    return 0.0


def pick_best_listing_profit(listings: pd.DataFrame, ck_cash: float) -> dict | None:
    """Listing with highest (CK adj − price) across all rows; each uses its own condition."""
    best: dict | None = None
    best_profit = None
    for _, row in listings.iterrows():
        price = _listing_price(row)
        if price is None:
            continue
        arb = listing_arbitrage(ck_cash, str(row["condition"]), price)
        if arb is None:
            continue
        if best is None or arb["profit"] > best_profit:
            best = arb
            best_profit = arb["profit"]
    return best


def finish_matches_listing(finish: str, condition: str) -> bool:
    finish_l = str(finish or "normal").lower()
    cond_l = str(condition or "").lower()
    if finish_l == "foil":
        return "foil" in cond_l and "etched" not in cond_l
    if finish_l == "etched":
        return "etched" in cond_l
    return "foil" not in cond_l and "etched" not in cond_l


def finish_matches_printing(finish: str, printing: str) -> bool:
    finish_l = str(finish or "normal").lower()
    printing_l = str(printing or "").lower()
    if finish_l == "foil":
        return "foil" in printing_l and "etched" not in printing_l
    if finish_l == "etched":
        return "etched" in printing_l
    return printing_l in {"normal", "nonfoil", "non-foil"} or (
        "foil" not in printing_l and "etched" not in printing_l
    )


def aggregate_best_listings(listings: pd.DataFrame) -> pd.DataFrame:
    """Best single seller per (product_id, finish, condition): highest qty, then lowest price."""
    if listings.empty:
        return pd.DataFrame(
            columns=[
                "product_id",
                "finish",
                "condition",
                "tcg_buy_price",
                "listing_qty",
                "listing_seller",
            ]
        )

    df = listings.copy()
    df["product_id"] = df["product_id"].astype(str)
    df["finish"] = df["finish"].astype(str).str.lower()
    df["condition"] = df["condition"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity_available"] = pd.to_numeric(df["quantity_available"], errors="coerce").fillna(0)
    df = df[df["price"].notna() & (df["price"] > 0)]

    df = df.sort_values(
        ["product_id", "finish", "condition", "quantity_available", "price"],
        ascending=[True, True, True, False, True],
    )
    best = df.drop_duplicates(subset=["product_id", "finish", "condition"], keep="first")
    return best.rename(
        columns={
            "price": "tcg_buy_price",
            "quantity_available": "listing_qty",
            "seller": "listing_seller",
        }
    )[
        [
            "product_id",
            "finish",
            "condition",
            "tcg_buy_price",
            "listing_qty",
            "listing_seller",
        ]
    ]


def effective_profit_qty(tcg_qty: float, ck_max_qty: float | None) -> float:
    """Max copies we can profitably flip given TCG supply and CK per-order limits.

    CK max qty is the per-order bottleneck. When TCG has more than CK will accept in
    one order, cap at CK_MAX_QTY_ORDER_MULTIPLIER × ck_max_qty (separate CK orders).
    When TCG supply is at or below CK's cap, TCG quantity is the limit.
    """
    qty = max(float(tcg_qty or 0), 0.0)
    if qty <= 0:
        return 0.0
    if ck_max_qty is None or ck_max_qty <= 0:
        return qty
    ck_cap = float(ck_max_qty)
    if qty <= ck_cap:
        return qty
    return min(qty, ck_cap * CK_MAX_QTY_ORDER_MULTIPLIER)


def summarize_listings_per_condition(
    listings: pd.DataFrame,
    ck_cash: float,
    ck_max_qty: float | None = None,
) -> list[dict]:
    """One export row per TCG condition using shipping-adjusted order economics."""
    if listings.empty:
        return []

    df = listings.copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    if "shipping_price" not in df.columns:
        df["shipping_price"] = 0.0
    if "seller_key" not in df.columns:
        df["seller_key"] = ""
    df["shipping_price"] = pd.to_numeric(df["shipping_price"], errors="coerce").fillna(0)
    df["quantity_available"] = pd.to_numeric(
        df["quantity_available"], errors="coerce"
    ).fillna(0)
    df = df[df["price"].notna() & (df["price"] > 0)]
    if df.empty:
        return []

    df["_cond_key"] = df["condition"].map(normalize_condition)
    df = df[df["_cond_key"].notna()]
    if df.empty:
        return []

    rows: list[dict] = []
    for _, grp in df.groupby("_cond_key", sort=False):
        grp = grp.copy()
        grp["_buy_qty"] = grp["quantity_available"].map(
            lambda q: effective_profit_qty(q, ck_max_qty)
        )
        grp = grp[grp["_buy_qty"] > 0]
        if grp.empty:
            continue
        condition = str(grp.iloc[0]["condition"])
        mult = condition_multiplier(condition)
        if mult is None:
            continue
        ck_cash_adjusted = round(float(ck_cash) * mult, 2)

        grp["_order_cost"] = grp["price"] * grp["_buy_qty"] + grp["shipping_price"]
        grp["_landed_unit_price"] = grp["_order_cost"] / grp["_buy_qty"]
        grp["_unit_profit"] = ck_cash_adjusted - grp["_landed_unit_price"]
        grp["_order_profit"] = ck_cash_adjusted * grp["_buy_qty"] - grp["_order_cost"]
        best_order = grp.sort_values(
            ["_order_profit", "_buy_qty", "_unit_profit"],
            ascending=[False, False, False],
        ).iloc[0]
        max_qty_row = grp.loc[grp["quantity_available"].idxmax()]
        condition = str(best_order["condition"])
        arb = listing_arbitrage(ck_cash, condition, float(best_order["_landed_unit_price"]))
        if arb is None:
            continue
        order_profit = round(float(best_order["_order_profit"]), 2)
        order_roi = (
            round(order_profit / float(best_order["_order_cost"]) * 100, 2)
            if float(best_order["_order_cost"]) > 0
            else None
        )
        rows.append(
            {
                "condition": condition,
                "condition_display": format_condition_display(condition),
                "lowest_price": round(float(best_order["_landed_unit_price"]), 2),
                "lowest_qty": float(best_order["quantity_available"]),
                "shipping_price": round(float(best_order["shipping_price"]), 2),
                "seller_price": round(float(best_order["price"]), 2),
                "seller": str(best_order.get("seller") or ""),
                "seller_key": str(best_order.get("seller_key") or ""),
                "listing_id": best_order.get("listing_id") or "",
                "order_qty": float(best_order["_buy_qty"]),
                "order_cost": round(float(best_order["_order_cost"]), 2),
                "order_profit": order_profit,
                "order_roi": order_roi,
                "max_qty_price": round(float(max_qty_row["price"]), 2),
                "max_qty": float(max_qty_row["quantity_available"]),
                "profit": arb["profit"],
                "roi": arb["roi"],
                "tcg_buy_price": arb["tcg_buy_price"],
                "ck_cash_adjusted": arb["ck_cash_adjusted"],
            }
        )

    rows.sort(
        key=lambda r: (-(r["order_profit"] if r["order_profit"] is not None else -1e9), r["lowest_price"] or 0)
    )
    return rows


def pick_best_condition_row(
    buylist_row: pd.Series,
    listings: pd.DataFrame,
) -> pd.Series:
    """Pick the condition row with the best cash diff (adjusted CK − TCG buy)."""
    pid = str(buylist_row.get("_tcg_pid") or "")
    finish = str(buylist_row.get("finish") or "normal").lower()
    cash = buylist_row.get("cash_price")
    if not pid or pd.isna(cash):
        return pd.Series(
            {
                "tcg_buy_price": pd.NA,
                "tcg_listing_condition": pd.NA,
                "ck_cash_adjusted": pd.NA,
                "condition_multiplier": pd.NA,
            }
        )

    subset = listings[
        (listings["product_id"] == pid) & (listings["finish"] == finish)
    ]
    if subset.empty:
        return pd.Series(
            {
                "tcg_buy_price": pd.NA,
                "tcg_listing_condition": pd.NA,
                "ck_cash_adjusted": pd.NA,
                "condition_multiplier": pd.NA,
            }
        )

    best_diff = None
    best: dict | None = None
    for _, row in subset.iterrows():
        price = _listing_price(row)
        if price is None:
            continue
        arb = listing_arbitrage(float(cash), str(row["condition"]), price)
        if arb is None:
            continue
        diff = arb["profit"]
        if best is None or diff > best_diff:
            best_diff = diff
            best = {
                "tcg_buy_price": arb["tcg_buy_price"],
                "tcg_listing_condition": arb["condition"],
                "ck_cash_adjusted": arb["ck_cash_adjusted"],
                "condition_multiplier": arb["condition_multiplier"],
            }

    if best is None:
        return pd.Series(
            {
                "tcg_buy_price": pd.NA,
                "tcg_listing_condition": pd.NA,
                "ck_cash_adjusted": pd.NA,
                "condition_multiplier": pd.NA,
            }
        )
    return pd.Series(best)


def _vector_tcg_pid(df: pd.DataFrame) -> pd.Series:
    finish = df["finish"].astype(str).str.lower()
    etched = df.get("tcgplayer_etched_id")
    base = df.get("tcgplayer_id")
    if etched is None:
        etched = pd.Series(pd.NA, index=df.index)
    if base is None:
        base = pd.Series(pd.NA, index=df.index)
    etched_pid = etched.map(_clean_pid)
    base_pid = base.map(_clean_pid)
    return etched_pid.where(finish.eq("etched") & etched_pid.notna(), base_pid)


def apply_condition_prices(
    df: pd.DataFrame,
    best_listings: pd.DataFrame,
) -> pd.DataFrame:
    """Merge mp-search listing prices with CK condition adjustments."""
    out = df.copy()
    out["tcg_buy_price"] = pd.NA
    out["tcg_listing_condition"] = pd.NA
    out["ck_cash_adjusted"] = out["cash_price"]
    out["condition_multiplier"] = 1.0

    if best_listings.empty:
        return out

    lk = best_listings.copy()
    lk["product_id"] = lk["product_id"].astype(str)
    lk["finish"] = lk["finish"].astype(str).str.lower()
    lk["price"] = pd.to_numeric(lk["price"], errors="coerce")
    lk = lk[lk["price"].notna() & (lk["price"] > 0)]
    if lk.empty:
        return out

    finish_l = out["finish"].astype(str).str.lower()
    pid = _vector_tcg_pid(out)
    has_pid = pid.notna()
    if not has_pid.any():
        return out

    listing_pairs = lk[["product_id", "finish"]].drop_duplicates()
    eligible = out.loc[has_pid, ["cash_price"]].copy()
    eligible["_tcg_pid"] = pid.loc[has_pid]
    eligible["finish"] = finish_l.loc[has_pid]
    eligible = (
        eligible.reset_index(names="row_id")
        .merge(listing_pairs, left_on=["_tcg_pid", "finish"], right_on=["product_id", "finish"])
        .drop(columns=["product_id"], errors="ignore")
    )
    if eligible.empty:
        return out

    joined = eligible[["row_id", "_tcg_pid", "finish", "cash_price"]].merge(
        lk[["product_id", "finish", "condition", "price"]],
        left_on=["_tcg_pid", "finish"],
        right_on=["product_id", "finish"],
        how="inner",
    )
    if joined.empty:
        return out

    joined["_mult"] = joined["condition"].map(condition_multiplier)
    joined = joined[joined["_mult"].notna()]
    if joined.empty:
        return out

    cash = joined["cash_price"].astype(float)
    price = joined["price"].astype(float)
    joined["ck_cash_adjusted"] = (cash * joined["_mult"]).round(2)
    joined["profit"] = joined["ck_cash_adjusted"] - price

    best = joined.loc[joined.groupby("row_id")["profit"].idxmax()]
    out.loc[best["row_id"], "tcg_buy_price"] = best["price"].values
    out.loc[best["row_id"], "tcg_listing_condition"] = best["condition"].values
    out.loc[best["row_id"], "ck_cash_adjusted"] = best["ck_cash_adjusted"].values
    out.loc[best["row_id"], "condition_multiplier"] = best["_mult"].values
    return out


def _row_tcg_pid(row: pd.Series) -> str | None:
    finish = str(row.get("finish") or "normal").lower()
    if finish == "etched":
        pid = row.get("tcgplayer_etched_id")
        if pd.notna(pid):
            return _clean_pid(pid)
    pid = row.get("tcgplayer_id")
    return _clean_pid(pid) if pd.notna(pid) else None


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


def parse_listing_items(payload: dict | list | None, product_id: str, finish: str) -> list[dict]:
    """Normalize mp-search-api listings POST response."""
    if not payload:
        return []

    if isinstance(payload, list):
        items = payload
    else:
        items = (
            payload.get("results")
            or payload.get("data")
            or payload.get("listings")
            or payload.get("items")
            or []
        )

    if items and isinstance(items[0], dict) and "results" in items[0]:
        items = items[0].get("results") or []

    if items and isinstance(items[0], dict) and "listings" in items[0]:
        items = [
            listing
            for result in items
            for listing in (result.get("listings") or [])
            if isinstance(listing, dict)
        ]

    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        listing_type = str(item.get("listingType", "standard")).lower()
        if listing_type not in {"standard", "listingwithoutphotos"}:
            continue
        lang_id = item.get("languageId")
        if lang_id is not None and lang_id != 1:
            continue
        lang = (item.get("language") or item.get("languageAbbreviation") or "").lower()
        if lang and lang not in ("english", "en"):
            continue
        if (item.get("customData") or {}).get("images"):
            continue

        condition = item.get("condition") or item.get("conditionName") or "Near Mint"
        printing = item.get("printing") or item.get("variant") or item.get("printingType")
        if printing:
            if not finish_matches_printing(finish, printing):
                continue
        elif not finish_matches_listing(finish, condition):
            continue

        price_raw = item.get("price") or item.get("sellerPrice")
        try:
            price = float(str(price_raw).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue

        qty_raw = item.get("quantity") or item.get("quantityAvailable") or 0
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            qty = 0

        rows.append(
            {
                "product_id": product_id,
                "finish": finish,
                "condition": condition,
                "price": price,
                "shipping_price": _listing_shipping(item),
                "seller_shipping_price": item.get("sellerShippingPrice"),
                "ranked_shipping_price": item.get("rankedShippingPrice"),
                "quantity_available": qty,
                "seller": item.get("sellerName") or "",
                "seller_key": str(item.get("sellerKey") or item.get("seller_key") or ""),
                "listing_id": item.get("listingId") or "",
            }
        )
    return rows
