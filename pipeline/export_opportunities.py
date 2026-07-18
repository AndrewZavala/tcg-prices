#!/usr/bin/env python3
"""Rank CK buylist by cash price, fetch live TCG listings for top N, export HTML report."""

from __future__ import annotations

import asyncio
import html
import os
import sys
from datetime import date
from urllib.parse import urlencode

import pandas as pd

from browser_tcg_listings import scrape_targets_browser
from config import (
    BUYLIST_ENRICHED_DIR,
    OPPORTUNITIES_DIR,
    TCG_LISTINGS_LOOKUP,
    ensure_dirs,
)
from enrich_buylist import _effective_tcg_product_id, _latest_master_path, enrich
from screen_candidates import (
    USE_SCREENING,
    print_screen_summary,
    select_opportunity_targets,
)
from scrape_tcg_listings import format_listings_df, read_listings_lookup, write_listings_lookup
from tcg_condition import (
    summarize_listings_per_condition,
    tcg_product_url,
)

def _env_int(key: str, default: str) -> int:
    raw = os.environ.get(key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    return int(raw)


TOP_N = _env_int("OPPORTUNITY_TOP_N", "0")
SKIP_FETCH = os.environ.get("OPPORTUNITY_SKIP_FETCH", "").lower() in {"1", "true", "yes"}
CHART_TOP_N = int(os.environ.get("OPPORTUNITY_CHART_TOP_N", "40"))
LANE_TOP_N = int(os.environ.get("OPPORTUNITY_LANE_TOP_N", "20"))
SELLER_TOP_N = int(os.environ.get("OPPORTUNITY_SELLER_TOP_N", "50"))
MIN_REPORT_PROFIT = float(
    os.environ.get(
        "OPPORTUNITY_MIN_REPORT_PROFIT",
        os.environ.get("OPPORTUNITY_SELLER_MIN_PROFIT", "0.50"),
    )
)
USE_CACHED_ENRICHED = os.environ.get("OPPORTUNITY_USE_CACHED_ENRICHED", "").lower() in {
    "1",
    "true",
    "yes",
}


def _text(value) -> str:
    """Coerce pandas/CSV nulls to empty string (NaN is truthy, so `x or ''` is not enough)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>"} else text


def ck_buylist_url(card_name: str) -> str:
    name = str(card_name or "").strip().lower()
    if not name:
        return ""
    params = {
        "filter[sort]": "price_desc",
        "filter[search]": "mtg_advanced",
        "filter[name]": name,
        "filter[edition]": "",
        "filter[format]": "",
        "filter[foils]": "1",
        "filter[singles]": "1",
        "filter[price_op]": "",
        "filter[price]": "",
    }
    return f"https://www.cardkingdom.com/purchasing/mtg_singles?{urlencode(params)}"


def _collector_display(row: pd.Series) -> str:
    if "sku" in row.index:
        sku = str(row.get("sku") or "").strip()
        if sku and sku.lower() not in {"", "api", "nan", "none"}:
            return sku
    return str(row.get("collector_number") or "").strip()


def _latest_enriched_path():
    files = sorted(BUYLIST_ENRICHED_DIR.glob("full_ck_buylist_export_*.csv"))
    if not files:
        raise FileNotFoundError(f"No enriched exports in {BUYLIST_ENRICHED_DIR}")
    return files[-1]


def load_cached_enriched() -> pd.DataFrame:
    """Load cached enriched export (SKU resolution already applied during enrich)."""
    enriched_path = _latest_enriched_path()
    print(f"Loading cached enriched export {enriched_path}...")
    return pd.read_csv(enriched_path, low_memory=False)


def rank_buylist_targets(enriched: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Pick top-N CK rows to fetch live TCG listings for (by CK cash, not tcgcsv)."""
    out = enriched.copy()
    out["product_id"] = _effective_tcg_product_id(out)
    out["cash_price"] = pd.to_numeric(out["cash_price"], errors="coerce")
    out = out[out["product_id"].notna() & out["cash_price"].notna()]
    out = out.sort_values("cash_price", ascending=False)
    return out.drop_duplicates(subset=["product_id", "finish"], keep="first").head(top_n)


def targets_from_ranked(ranked: pd.DataFrame) -> pd.DataFrame:
    df = ranked.copy()
    df["card_name"] = df["name"].astype(str).str.strip()
    df["edition"] = (
        df["edition"].fillna("").astype(str).str.strip() if "edition" in df.columns else ""
    )
    df["set_name"] = df["set"].fillna("").astype(str).str.strip() if "set" in df.columns else ""
    df["variation"] = (
        df["variation"].fillna("").astype(str).str.strip() if "variation" in df.columns else ""
    )
    df["set_code"] = (
        df["set_code"].fillna("").astype(str).str.strip().str.lower()
        if "set_code" in df.columns
        else ""
    )
    df["collector_number"] = df.apply(_collector_display, axis=1)
    return df[
        [
            "product_id",
            "card_name",
            "edition",
            "set_name",
            "set_code",
            "collector_number",
            "variation",
            "finish",
            "cash_price",
        ]
    ].reset_index(drop=True)


def build_export_rows(ranked: pd.DataFrame, listings: pd.DataFrame) -> list[dict]:
    if listings.empty:
        grouped: dict[tuple[str, str], pd.DataFrame] = {}
    else:
        listings = listings.copy()
        listings["product_id"] = listings["product_id"].astype(str)
        listings["finish"] = listings["finish"].astype(str).str.lower()
        grouped = {
            (pid, finish): grp
            for (pid, finish), grp in listings.groupby(["product_id", "finish"])
        }

    rows: list[dict] = []
    for row in ranked.itertuples(index=False):
        pid = str(row.product_id)
        finish = str(row.finish).lower()
        cash = float(row.cash_price)
        name = _text(getattr(row, "name", "") or getattr(row, "card_name", ""))
        edition = _text(
            getattr(row, "edition", "")
            or getattr(row, "set_name", "")
            or getattr(row, "set", "")
        )
        variant = _text(getattr(row, "variation", ""))
        ck_max_qty_raw = getattr(row, "max_qty", None)
        ck_max_qty = None if pd.isna(ck_max_qty_raw) else float(ck_max_qty_raw)
        base = {
            "name": name,
            "set": edition,
            "variant": variant,
            "finish": finish,
            "ck_cash": cash,
            "ck_max_qty": ck_max_qty,
            "product_id": pid,
            "ck_url": ck_buylist_url(name),
        }
        condition_rows = summarize_listings_per_condition(
            grouped.get((pid, finish), pd.DataFrame()),
            cash,
            ck_max_qty=ck_max_qty,
        )
        if not condition_rows:
            rows.append(
                {
                    **base,
                    "condition": "—",
                    "ck_adj": None,
                    "lowest_price": None,
                    "seller_price": None,
                    "shipping_price": None,
                    "seller": "",
                    "seller_key": "",
                    "lowest_qty": None,
                    "max_qty_price": None,
                    "max_qty": None,
                    "profit": None,
                    "roi": None,
                    "order_qty": None,
                    "order_profit": None,
                    "profit_per_copy": None,
                    "order_roi": None,
                    "order_cost": None,
                    "tcg_url": "",
                }
            )
            continue
        for summary in condition_rows:
            unit_profit = summary["profit"]
            condition_raw = summary["condition"]
            seller_key = _text(summary.get("seller_key"))
            rows.append(
                {
                    **base,
                    "condition": summary["condition_display"] or condition_raw,
                    "condition_raw": condition_raw,
                    "ck_adj": summary["ck_cash_adjusted"],
                    "lowest_price": summary["lowest_price"],
                    "seller_price": summary.get("seller_price"),
                    "shipping_price": summary.get("shipping_price"),
                    "seller": summary.get("seller", ""),
                    "seller_key": seller_key,
                    "lowest_qty": summary["lowest_qty"],
                    "max_qty_price": summary["max_qty_price"],
                    "max_qty": summary["max_qty"],
                    "profit": summary.get("order_profit"),
                    "roi": summary.get("order_roi"),
                    "order_qty": summary.get("order_qty"),
                    "order_profit": summary.get("order_profit"),
                    "profit_per_copy": unit_profit,
                    "order_roi": summary.get("order_roi"),
                    "order_cost": summary.get("order_cost"),
                    "tcg_url": tcg_product_url(
                        pid,
                        finish,
                        condition=condition_raw,
                    ),
                }
            )

    rows.sort(
        key=lambda r: (r["order_profit"] is None, -(r["order_profit"] or 0), -r["ck_cash"]),
    )
    return rows


def _passes_report_filter(row: dict) -> bool:
    order_profit = row.get("order_profit")
    order_roi = row.get("order_roi")
    if order_profit is None or order_roi is None:
        return False
    if float(order_profit) < MIN_REPORT_PROFIT:
        return False
    if float(order_roi) < 0:
        return False
    return True


def _filter_report_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if _passes_report_filter(row)]


def _money(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"${float(value):,.2f}"


def _num(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    n = float(value)
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def _pct(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):.2f}%"


def _short_condition(value) -> str:
    text = str(value or "").lower()
    if "near mint" in text:
        return "NM"
    if "lightly played" in text:
        return "LP"
    if "moderately played" in text:
        return "MP"
    if "heavily played" in text:
        return "HP"
    if "damaged" in text:
        return "Damaged"
    return str(value or "—")


def _row_key(r: dict) -> str:
    return "|".join(_text(r.get(k)) for k in ("product_id", "finish", "variant", "condition", "name"))


def _chart_subtitle(r: dict) -> str:
    return r["variant"] or r["set"] or r["finish"] or ""


def _chart_rows(rows: list[dict], top_n: int) -> list[dict]:
    """Best unique card opportunities with positive profit for the summary chart."""
    seen: set[tuple[str, str, str, str]] = set()
    picked: list[dict] = []
    for r in rows:
        profit = r.get("profit")
        if profit is None or profit <= 0:
            continue
        key = (r["name"], r.get("variant", ""), r.get("set", ""), r.get("finish", ""))
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= top_n:
            break
    return picked


def _lane_key(r: dict) -> tuple[str, str, str, str]:
    return (r["name"], r.get("variant", ""), r.get("set", ""), r.get("finish", ""))


def _top_lane_rows(rows: list[dict], lane: str, top_n: int = LANE_TOP_N) -> list[dict]:
    candidates: list[dict] = []
    for r in rows:
        order_profit = r.get("order_profit")
        order_roi = r.get("order_roi")
        profit_per_copy = r.get("profit_per_copy")
        order_qty = r.get("order_qty")
        if (
            order_profit is None
            or order_roi is None
            or profit_per_copy is None
            or order_qty is None
            or order_profit <= 0
        ):
            continue

        if lane == "roi":
            if order_roi >= 75 and order_profit >= 5:
                candidates.append(r)
        elif lane == "whale":
            if order_profit >= 20 and order_qty <= 5 and profit_per_copy >= 5:
                candidates.append(r)
        elif lane == "volume":
            if order_qty >= 20 and 0.25 <= profit_per_copy <= 1 and order_profit >= 10:
                candidates.append(r)

    if lane == "roi":
        candidates.sort(key=lambda r: (-(r["order_roi"] or 0), -(r["order_profit"] or 0)))
    else:
        candidates.sort(key=lambda r: (-(r["order_profit"] or 0), -(r["order_roi"] or 0)))

    seen: set[tuple[str, str, str, str]] = set()
    picked: list[dict] = []
    for r in candidates:
        key = _lane_key(r)
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= top_n:
            break
    return picked


def _lane_table(title: str, subtitle: str, rows: list[dict]) -> str:
    body: list[str] = []
    for r in rows:
        ck_link = (
            f'<a href="{html.escape(r["ck_url"])}" target="_blank" rel="noopener">CK</a>'
            if r["ck_url"]
            else "—"
        )
        tcg_link = (
            f'<a href="{html.escape(r["tcg_url"])}" target="_blank" rel="noopener">TCG</a>'
            if r["tcg_url"]
            else "—"
        )
        body.append(
            f"""<tr>
              <td>{html.escape(r['name'])}</td>
              <td class="col-set" title="{html.escape(r['set'])}">{html.escape(r['set'])}</td>
              <td class="col-variant" title="{html.escape(r['variant'] or '—')}">{html.escape(r['variant'] or '—')}</td>
              <td class="col-condition" title="{html.escape(str(r['condition']))}">{html.escape(_short_condition(r['condition']))}</td>
              <td>{html.escape(r['finish'])}</td>
              <td data-sort="{r['ck_cash']:.4f}">{_money(r['ck_cash'])}</td>
              <td data-sort="{(r['ck_adj'] if r.get('ck_adj') is not None else 0):.4f}">{_money(r.get('ck_adj'))}</td>
              <td data-sort="{(r['lowest_price'] or 0):.4f}">{_money(r['lowest_price'])}</td>
              <td data-sort="{(r['seller_price'] or 0):.4f}">{_money(r['seller_price'])}</td>
              <td data-sort="{(r['shipping_price'] or 0):.4f}">{_money(r['shipping_price'])}</td>
              <td title="{html.escape(_text(r.get('seller')))}">{html.escape(_text(r.get('seller')) or '—')}</td>
              <td data-sort="{(r['order_qty'] or 0):.4f}">{_num(r['order_qty'])}</td>
              <td data-sort="{(r['lowest_qty'] or 0):.4f}">{_num(r['lowest_qty'])}</td>
              <td data-sort="{(r['max_qty_price'] or 0):.4f}">{_money(r['max_qty_price'])}</td>
              <td data-sort="{(r['max_qty'] or 0):.4f}">{_num(r['max_qty'])}</td>
              <td class="pos" data-sort="{(r['profit'] if r['profit'] is not None else -1e9):.4f}">{_money(r['profit'])}</td>
              <td data-sort="{(r['roi'] if r['roi'] is not None else -1e9):.4f}">{_pct(r['roi'])}</td>
              <td data-sort="{(r['profit_per_copy'] or -1e9):.4f}">{_money(r['profit_per_copy'])}</td>
              <td>{ck_link}</td>
              <td>{tcg_link}</td>
            </tr>"""
        )
    rows_html = "".join(body) if body else '<tr><td colspan="19">No matching rows.</td></tr>'
    return f"""
      <section class="lane-section">
        <h3>{html.escape(title)}</h3>
        <p class="lane-subnote">{html.escape(subtitle)}</p>
        <div class="table-wrap lane-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th class="col-set">Set</th>
                <th class="col-variant">Variant</th>
                <th class="col-condition">Cond</th>
                <th>Finish</th>
                <th>CK NM $</th>
                <th>CK adj $</th>
                <th>TCG landed $</th>
                <th>Seller $</th>
                <th>Ship $</th>
                <th>Seller</th>
                <th>Buy qty</th>
                <th>Seller qty</th>
                <th>Max qty $</th>
                <th>Max qty</th>
                <th>Order profit</th>
                <th>Order ROI</th>
                <th>Profit/copy</th>
                <th>CK</th>
                <th>TCG</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
      </section>"""


def _seller_summary_rows(rows: list[dict], top_n: int = SELLER_TOP_N) -> list[dict]:
    sellers: dict[str, dict] = {}
    for r in rows:
        seller = _text(r.get("seller"))
        order_profit = r.get("order_profit")
        order_qty = r.get("order_qty")
        if not seller or not _passes_report_filter(r):
            continue
        buy_qty = float(order_qty or 0)
        bucket = sellers.setdefault(
            seller,
            {
                "seller": seller,
                "cards": 0,
                "order_qty": 0.0,
                "ck_total": 0.0,
                "merch_cost": 0.0,
                "shipping_price": 0.0,
                "buy_list": [],
            },
        )
        bucket["cards"] += 1
        bucket["order_qty"] += buy_qty
        bucket["ck_total"] += float(r.get("ck_adj") or 0) * buy_qty
        bucket["merch_cost"] += float(r.get("seller_price") or 0) * buy_qty
        bucket["shipping_price"] = max(
            float(bucket["shipping_price"]),
            float(r.get("shipping_price") or 0),
        )
        bucket["buy_list"].append(
            {
                "name": r["name"],
                "set": r.get("set") or "",
                "variant": r.get("variant") or "",
                "condition": r.get("condition") or "—",
                "finish": r.get("finish") or "",
                "order_qty": buy_qty,
                "seller_price": r.get("seller_price"),
                "ck_adj": r.get("ck_adj"),
                "order_profit": float(order_profit or 0),
                "ck_url": r.get("ck_url") or "",
                "tcg_url": r.get("tcg_url") or "",
            }
        )

    out = []
    for seller in sellers.values():
        cost = seller["merch_cost"] + seller["shipping_price"]
        profit = seller["ck_total"] - cost
        if profit <= 0:
            continue
        seller["shipping_price"] = round(seller["shipping_price"], 2)
        seller["ck_total"] = round(seller["ck_total"], 2)
        seller["merch_cost"] = round(seller["merch_cost"], 2)
        seller["order_profit"] = round(profit, 2)
        seller["order_cost"] = round(cost, 2)
        seller["order_qty"] = round(seller["order_qty"], 2)
        seller["order_roi"] = round(seller["order_profit"] / cost * 100, 2) if cost > 0 else None
        seller["buy_list"].sort(key=lambda item: item["order_profit"], reverse=True)
        out.append(seller)
    out.sort(key=lambda r: (-(r["order_profit"] or 0), -(r["order_roi"] or 0)))
    return out[:top_n]


def _seller_buy_list_html(items: list[dict]) -> str:
    rows: list[str] = []
    for item in items:
        ck_link = (
            f'<a href="{html.escape(item["ck_url"])}" target="_blank" rel="noopener">CK</a>'
            if item["ck_url"]
            else "—"
        )
        tcg_link = (
            f'<a href="{html.escape(item["tcg_url"])}" target="_blank" rel="noopener" title="TCG listing">TCG</a>'
            if item["tcg_url"]
            else "—"
        )
        rows.append(
            f"""<tr>
              <td>{html.escape(item['name'])}</td>
              <td class="col-set" title="{html.escape(item['set'])}">{html.escape(item['set'] or '—')}</td>
              <td class="col-variant" title="{html.escape(item['variant'] or '—')}">{html.escape(item['variant'] or '—')}</td>
              <td class="col-condition" title="{html.escape(str(item['condition']))}">{html.escape(_short_condition(item['condition']))}</td>
              <td>{html.escape(item['finish'] or '—')}</td>
              <td>{_num(item['order_qty'])}</td>
              <td>{_money(item['seller_price'])}</td>
              <td>{_money(item['ck_adj'])}</td>
              <td class="pos">{_money(item['order_profit'])}</td>
              <td>{ck_link}</td>
              <td>{tcg_link}</td>
            </tr>"""
        )
    return f"""
      <div class="buy-list-panel">
        <p class="buy-list-hint">Buy qty is everything available from the seller. Ctrl+click TCG links to open seller-filtered listings.</p>
        <table class="buy-list-table">
          <thead>
            <tr>
              <th>Name</th>
              <th class="col-set">Set</th>
              <th class="col-variant">Variant</th>
              <th class="col-condition">Cond</th>
              <th>Finish</th>
              <th>Buy qty</th>
              <th>Seller $</th>
              <th>CK adj $</th>
              <th>Profit</th>
              <th>CK</th>
              <th>TCG</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>"""


def _seller_table(rows: list[dict]) -> str:
    body: list[str] = []
    for idx, r in enumerate(rows):
        seller_id = str(idx)
        body.append(
            f"""<tr class="seller-row" data-seller-id="{seller_id}">
              <td>{html.escape(r['seller'])}</td>
              <td data-sort="{r['cards']:.4f}">{_num(r['cards'])}</td>
              <td data-sort="{r['order_qty']:.4f}">{_num(r['order_qty'])}</td>
              <td data-sort="{r['shipping_price']:.4f}">{_money(r['shipping_price'])}</td>
              <td data-sort="{r['order_cost']:.4f}">{_money(r['order_cost'])}</td>
              <td class="pos" data-sort="{r['order_profit']:.4f}">{_money(r['order_profit'])}</td>
              <td data-sort="{(r['order_roi'] if r['order_roi'] is not None else -1e9):.4f}">{_pct(r['order_roi'])}</td>
              <td>
                <button type="button" class="buy-list-toggle" data-seller-id="{seller_id}">
                  View buy list ({r['cards']})
                </button>
              </td>
            </tr>
            <tr class="seller-buy-list-row" data-seller-id="{seller_id}">
              <td colspan="8">{_seller_buy_list_html(r['buy_list'])}</td>
            </tr>"""
        )
    rows_html = "".join(body) if body else '<tr><td colspan="8">No seller rows with positive order profit.</td></tr>'
    return f"""
      <h2>Seller report — top {SELLER_TOP_N} by max order profit</h2>
      <p class="lane-subnote">
        Groups positive opportunity rows by selected TCGplayer seller.
        TCG links in buy lists include seller, condition, and printing filters when seller keys are available.
        Max profit assumes buying each listed opportunity from that seller and applying that seller's shipping charge once.
      </p>
      <input id="sellerSearchBox" type="search" placeholder="Search seller or card…" />
      <div class="table-wrap lane-table-wrap">
        <table id="sellerTable">
          <thead>
            <tr>
              <th class="sortable" data-col="0" data-type="text">Seller</th>
              <th class="sortable" data-col="1" data-type="num">Rows</th>
              <th class="sortable" data-col="2" data-type="num">Total qty</th>
              <th class="sortable" data-col="3" data-type="num">Ship once</th>
              <th class="sortable" data-col="4" data-type="num">Total cost</th>
              <th class="sortable sort-desc" data-col="5" data-type="num" data-sort-dir="desc">Max profit</th>
              <th class="sortable" data-col="6" data-type="num">Order ROI</th>
              <th>Buy list</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>"""


def render_html(rows: list[dict], snapshot_date: str, fetched: int, ranked_n: int) -> str:
    with_listings = sum(1 for r in rows if r["profit"] is not None)

    chart_rows = _chart_rows(rows, CHART_TOP_N)
    roi_rows = _top_lane_rows(rows, "roi")
    whale_rows = _top_lane_rows(rows, "whale")
    volume_rows = _top_lane_rows(rows, "volume")
    seller_rows = _seller_summary_rows(rows)
    lane_html = "\n".join(
        [
            _lane_table(
                "ROI Rocket",
                "Top rows with order ROI >= 75% and order profit >= $5.",
                roi_rows,
            ),
            _lane_table(
                "Whale Bite",
                "Top low-quantity rows with order profit >= $20, order qty <= 5, and profit/copy >= $5.",
                whale_rows,
            ),
            _lane_table(
                "Volume Grinder",
                "Top high-quantity rows with order qty >= 20, profit/copy $0.25-$1.00, and order profit >= $10.",
                volume_rows,
            ),
        ]
    )
    seller_html = _seller_table(seller_rows)
    max_profit = max((r["profit"] or 0) for r in chart_rows) if chart_rows else 1
    max_profit = max(max_profit, 0.01)

    chart_html: list[str] = []
    for r in chart_rows:
        profit = float(r["profit"])
        roi = max(0.0, min(float(r["roi"] or 0), 100))
        width = max(2, int(profit / max_profit * 100))
        subtitle = _chart_subtitle(r)
        label_text = f"{r['name']} ({subtitle})" if subtitle else r["name"]
        label = html.escape(label_text[:60])
        chart_html.append(
            f"""
            <div class="chart-row">
              <div class="chart-label" title="{label}">{label}</div>
              <div class="chart-bar-wrap">
                <div class="profit-bar" style="width:{width}%">
                  <div class="roi-bar" style="width:{roi}%"></div>
                  <span class="bar-text">{_money(profit)} · {_pct(r['roi'])}</span>
                </div>
              </div>
            </div>"""
        )

    table_rows: list[str] = []
    for r in rows:
        ck_link = (
            f'<a href="{html.escape(r["ck_url"])}" target="_blank" rel="noopener">CK</a>'
            if r["ck_url"]
            else "—"
        )
        tcg_link = (
            f'<a href="{html.escape(r["tcg_url"])}" target="_blank" rel="noopener">TCG</a>'
            if r["tcg_url"]
            else "—"
        )
        profit_cls = "pos" if (r["profit"] or 0) > 0 else ""
        row_key = html.escape(_row_key(r), quote=True)
        table_rows.append(
            f"""<tr class="data-row" data-row-key="{row_key}">
              <td>{html.escape(r['name'])}</td>
              <td class="col-set" title="{html.escape(r['set'])}">{html.escape(r['set'])}</td>
              <td class="col-variant" title="{html.escape(r['variant'] or '—')}">{html.escape(r['variant'] or '—')}</td>
              <td class="col-condition" title="{html.escape(str(r['condition']))}">{html.escape(_short_condition(r['condition']))}</td>
              <td>{html.escape(r['finish'])}</td>
              <td data-sort="{r['ck_cash']:.4f}">{_money(r['ck_cash'])}</td>
              <td data-sort="{(r['ck_adj'] if r.get('ck_adj') is not None else 0):.4f}">{_money(r.get('ck_adj'))}</td>
              <td data-sort="{(r['lowest_price'] or 0):.4f}">{_money(r['lowest_price'])}</td>
              <td data-sort="{(r['seller_price'] or 0):.4f}">{_money(r['seller_price'])}</td>
              <td data-sort="{(r['shipping_price'] or 0):.4f}">{_money(r['shipping_price'])}</td>
              <td title="{html.escape(_text(r.get('seller')))}">{html.escape(_text(r.get('seller')) or '—')}</td>
              <td data-sort="{(r['order_qty'] or 0):.4f}">{_num(r['order_qty'])}</td>
              <td data-sort="{(r['lowest_qty'] or 0):.4f}">{_num(r['lowest_qty'])}</td>
              <td data-sort="{(r['max_qty_price'] or 0):.4f}">{_money(r['max_qty_price'])}</td>
              <td data-sort="{(r['max_qty'] or 0):.4f}">{_num(r['max_qty'])}</td>
              <td class="{profit_cls}" data-sort="{(r['profit'] if r['profit'] is not None else -1e9):.4f}">{_money(r['profit'])}</td>
              <td data-sort="{(r['roi'] if r['roi'] is not None else -1e9):.4f}">{_pct(r['roi'])}</td>
              <td data-sort="{(r['profit_per_copy'] or -1e9):.4f}">{_money(r['profit_per_copy'])}</td>
              <td>{ck_link}</td>
              <td>{tcg_link}</td>
            </tr>"""
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Manifest Bread — CK Arbitrage {snapshot_date}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
      margin: 30px;
      background: #f5f7fa;
      color: #222;
    }}
    h1, h2 {{ margin-bottom: 8px; }}
    .subnote {{ margin-bottom: 18px; color: #555; font-size: 14px; }}
    .chart-block, .table-block {{
      background: white;
      border-radius: 12px;
      box-shadow: 0 3px 10px rgba(0,0,0,0.08);
      padding: 18px;
      margin-bottom: 24px;
    }}
    .chart-row {{ display: flex; align-items: center; gap: 14px; margin-bottom: 10px; }}
    .chart-label {{
      width: 280px; min-width: 280px; font-size: 13px;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .chart-bar-wrap {{
      flex: 1; background: #e9eef5; border-radius: 999px; height: 28px;
      position: relative; overflow: hidden;
    }}
    .profit-bar {{
      height: 100%;
      background: linear-gradient(90deg, #2c7be5, #59a5ff);
      border-radius: 999px; position: relative; min-width: 2px;
    }}
    .roi-bar {{
      position: absolute; left: 0; top: 50%; transform: translateY(-50%);
      height: 10px; background: rgba(255,255,255,0.85); border-radius: 999px;
    }}
    .bar-text {{
      position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
      font-size: 12px; font-weight: 600; color: #0f172a;
    }}
    input {{ width: 320px; padding: 8px 10px; margin-bottom: 14px; font-size: 14px; }}
    .table-wrap {{ overflow: auto; max-height: 70vh; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th {{
      background: #1f2937; color: white; text-align: left; padding: 10px;
      font-size: 13px; position: sticky; top: 0; z-index: 1;
    }}
    th.sortable {{ cursor: pointer; padding-right: 22px; }}
    th.sortable::after {{ content: '↕'; position: absolute; right: 8px; color: #cbd5e1; }}
    th.sortable.sort-asc::after {{ content: '▲'; color: #fff; }}
    th.sortable.sort-desc::after {{ content: '▼'; color: #fff; }}
    td {{ padding: 9px 10px; border-bottom: 1px solid #eee; white-space: nowrap; font-size: 13px; }}
    th.col-set, th.col-variant, td.col-set, td.col-variant {{
      max-width: 140px;
      width: 140px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    th.col-condition, td.col-condition {{
      max-width: 54px;
      width: 54px;
      text-align: center;
    }}
    tr:hover {{ background: #f1f6ff; }}
    tr.data-row {{ cursor: pointer; }}
    tr.row-selected {{
      background: #dbeafe !important;
      box-shadow: inset 4px 0 0 #2563eb;
    }}
    tr.row-selected:hover {{ background: #cfe0fc !important; }}
    td.pos {{ color: #047857; font-weight: 600; }}
    a {{ color: #2563eb; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
    .tab-button {{
      border: 1px solid #cbd5e1; background: #f8fafc; color: #1f2937;
      border-radius: 999px; padding: 8px 14px; cursor: pointer; font-weight: 600;
    }}
    .tab-button.active {{ background: #1f2937; color: white; border-color: #1f2937; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .lane-section {{ margin-bottom: 28px; }}
    .lane-section h3 {{ margin: 0 0 4px; }}
    .lane-subnote {{ margin: 0 0 10px; color: #555; font-size: 13px; }}
    .lane-table-wrap {{ max-height: none; }}
    .buy-list-toggle {{
      border: 1px solid #cbd5e1;
      background: #f8fafc;
      color: #1f2937;
      border-radius: 999px;
      padding: 6px 12px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .buy-list-toggle:hover {{ background: #e2e8f0; }}
    tr.seller-buy-list-row {{ display: none; }}
    tr.seller-buy-list-row.open {{ display: table-row; }}
    tr.seller-buy-list-row td {{
      background: #f8fafc;
      white-space: normal;
      padding-top: 0;
    }}
    .buy-list-panel {{ padding: 8px 0 12px; }}
    .buy-list-hint {{ color: #64748b; font-size: 12px; margin: 0 0 10px; }}
    .buy-list-table {{
      width: 100%;
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      overflow: hidden;
    }}
    .buy-list-table th {{
      position: static;
      background: #334155;
      font-size: 12px;
      padding: 8px 10px;
    }}
    .buy-list-table td {{ font-size: 12px; padding: 8px 10px; }}
  </style>
</head>
<body>
  <h1>Manifest Bread — CK arbitrage</h1>
  <p class="subnote">
    Snapshot {html.escape(snapshot_date)} · ranked top {ranked_n:,} by CK cash price ·
    live listings fetched for {fetched:,} products · {with_listings:,} rows shown.
    Filter: order profit &gt;= ${MIN_REPORT_PROFIT:.2f} and order ROI &gt;= 0%.
    Order profit = (CK adj × buy qty) − (seller price × buy qty + shipping once).
    Buy qty is full seller availability from the listing.
    (NM 100%, LP/EX 75%, MP/VG 50%, HP/G 25%, Damaged 0%). One row per condition grade.
    Shipping is applied once per estimated order and allocated into TCG landed unit cost when available.
  </p>

  <div class="chart-block">
    <h2>Top {min(CHART_TOP_N, len(chart_rows))} by profit</h2>
    {''.join(chart_html) if chart_html else '<p>No rows with positive profit.</p>'}
  </div>

  <div class="table-block">
    <div class="tabs">
      <button class="tab-button active" data-tab="all">All opportunities</button>
      <button class="tab-button" data-tab="lanes">Deal lanes</button>
      <button class="tab-button" data-tab="sellers">Seller report</button>
    </div>

    <div id="tab-all" class="tab-panel active">
      <h2>All opportunities</h2>
      <input id="searchBox" type="search" placeholder="Search card name…" />
      <div class="table-wrap">
        <table id="dataTable">
          <thead>
            <tr>
              <th>Name</th>
              <th class="col-set">Set</th>
              <th class="col-variant">Variant</th>
              <th class="col-condition">Cond</th>
              <th>Finish</th>
              <th class="sortable" data-col="5" data-type="num">CK NM $</th>
              <th class="sortable" data-col="6" data-type="num">CK adj $</th>
              <th class="sortable" data-col="7" data-type="num">TCG landed $</th>
              <th class="sortable" data-col="8" data-type="num">Seller $</th>
              <th class="sortable" data-col="9" data-type="num">Ship $</th>
              <th>Seller</th>
              <th class="sortable" data-col="11" data-type="num">Buy qty</th>
              <th class="sortable" data-col="12" data-type="num">Seller qty</th>
              <th class="sortable" data-col="13" data-type="num">Max qty $</th>
              <th class="sortable" data-col="14" data-type="num">Max qty</th>
              <th class="sortable sort-desc" data-col="15" data-type="num" data-sort-dir="desc">Order profit</th>
              <th class="sortable" data-col="16" data-type="num">Order ROI</th>
              <th class="sortable" data-col="17" data-type="num">Profit/copy</th>
              <th>CK</th>
              <th>TCG</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows)}
          </tbody>
        </table>
      </div>
    </div>

    <div id="tab-lanes" class="tab-panel">
      <h2>Deal lanes — top {LANE_TOP_N} each</h2>
      {lane_html}
    </div>

    <div id="tab-sellers" class="tab-panel">
      {seller_html}
    </div>
  </div>

  <script>
    const searchBox = document.getElementById('searchBox');
    const table = document.getElementById('dataTable');
    const tbody = table.querySelector('tbody');
    const sellerSearchBox = document.getElementById('sellerSearchBox');
    const sellerTable = document.getElementById('sellerTable');
    const sellerTbody = sellerTable ? sellerTable.querySelector('tbody') : null;
    const tabButtons = document.querySelectorAll('.tab-button');

    tabButtons.forEach(button => {{
      button.addEventListener('click', function() {{
        tabButtons.forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));
        this.classList.add('active');
        document.getElementById(`tab-${{this.dataset.tab}}`).classList.add('active');
      }});
    }});

    searchBox.addEventListener('input', function() {{
      const filter = this.value.toLowerCase();
      tbody.querySelectorAll('tr').forEach(row => {{
        row.style.display = row.cells[0].innerText.toLowerCase().includes(filter) ? '' : 'none';
      }});
    }});

    if (sellerSearchBox && sellerTbody) {{
      sellerSearchBox.addEventListener('input', function() {{
        const filter = this.value.toLowerCase();
        sellerTbody.querySelectorAll('tr.seller-row').forEach(row => {{
          const sellerId = row.dataset.sellerId;
          const detail = sellerTbody.querySelector(`tr.seller-buy-list-row[data-seller-id="${{sellerId}}"]`);
          const haystack = detail
            ? `${{row.innerText}} ${{detail.innerText}}`.toLowerCase()
            : row.innerText.toLowerCase();
          const match = haystack.includes(filter);
          row.style.display = match ? '' : 'none';
          if (detail) detail.style.display = match && detail.classList.contains('open') ? '' : 'none';
        }});
      }});
    }}

    document.querySelectorAll('.buy-list-toggle').forEach(button => {{
      button.addEventListener('click', function(e) {{
        e.stopPropagation();
        if (!sellerTbody) return;
        const sellerId = this.dataset.sellerId;
        const detail = sellerTbody.querySelector(`tr.seller-buy-list-row[data-seller-id="${{sellerId}}"]`);
        if (!detail) return;
        const open = detail.classList.toggle('open');
        const count = this.textContent.match(/\\((\\d+)\\)/)?.[1] || '';
        this.textContent = open ? `Hide buy list (${{count}})` : `View buy list (${{count}})`;
        detail.style.display = open ? '' : 'none';
      }});
    }});

    function setupSortableTable(tableEl) {{
      const tableBody = tableEl.querySelector('tbody');
      const tableHeaders = tableEl.querySelectorAll('th.sortable');
      tableHeaders.forEach(header => {{
        if (!header.dataset.sortDir) header.dataset.sortDir = 'desc';
        header.addEventListener('click', function() {{
          const colIndex = parseInt(this.dataset.col, 10);
          const type = this.dataset.type;
          const newDir = this.dataset.sortDir === 'asc' ? 'desc' : 'asc';
          tableHeaders.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
          this.dataset.sortDir = newDir;
          this.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');
          const rows = Array.from(tableBody.querySelectorAll('tr'));
          rows.sort((a, b) => {{
            let aVal = a.cells[colIndex].dataset.sort ?? a.cells[colIndex].innerText.trim();
            let bVal = b.cells[colIndex].dataset.sort ?? b.cells[colIndex].innerText.trim();
            if (type === 'num') {{
              aVal = parseFloat(String(aVal).replace(/[^0-9.-]/g, '')) || 0;
              bVal = parseFloat(String(bVal).replace(/[^0-9.-]/g, '')) || 0;
            }} else {{
              aVal = String(aVal).toLowerCase();
              bVal = String(bVal).toLowerCase();
            }}
            if (aVal < bVal) return newDir === 'asc' ? -1 : 1;
            if (aVal > bVal) return newDir === 'asc' ? 1 : -1;
            return 0;
          }});
          rows.forEach(row => tableBody.appendChild(row));
        }});
      }});
    }}

    function setupSellerSortableTable(tableEl) {{
      const tableBody = tableEl.querySelector('tbody');
      const tableHeaders = tableEl.querySelectorAll('th.sortable');
      tableHeaders.forEach(header => {{
        if (!header.dataset.sortDir) header.dataset.sortDir = 'desc';
        header.addEventListener('click', function() {{
          const colIndex = parseInt(this.dataset.col, 10);
          const type = this.dataset.type;
          const newDir = this.dataset.sortDir === 'asc' ? 'desc' : 'asc';
          tableHeaders.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
          this.dataset.sortDir = newDir;
          this.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');
          const sellerRows = Array.from(tableBody.querySelectorAll('tr.seller-row'));
          sellerRows.sort((a, b) => {{
            let aVal = a.cells[colIndex].dataset.sort ?? a.cells[colIndex].innerText.trim();
            let bVal = b.cells[colIndex].dataset.sort ?? b.cells[colIndex].innerText.trim();
            if (type === 'num') {{
              aVal = parseFloat(String(aVal).replace(/[^0-9.-]/g, '')) || 0;
              bVal = parseFloat(String(bVal).replace(/[^0-9.-]/g, '')) || 0;
            }} else {{
              aVal = String(aVal).toLowerCase();
              bVal = String(bVal).toLowerCase();
            }}
            if (aVal < bVal) return newDir === 'asc' ? -1 : 1;
            if (aVal > bVal) return newDir === 'asc' ? 1 : -1;
            return 0;
          }});
          sellerRows.forEach(row => {{
            tableBody.appendChild(row);
            const detail = tableBody.querySelector(`tr.seller-buy-list-row[data-seller-id="${{row.dataset.sellerId}}"]`);
            if (detail) tableBody.appendChild(detail);
          }});
        }});
      }});
    }}

    setupSortableTable(table);
    if (sellerTable) setupSellerSortableTable(sellerTable);

    const ROW_STORAGE_KEY = 'manifestBreadSelectedRow';
    function selectRow(tr) {{
      tbody.querySelectorAll('tr.row-selected').forEach(r => r.classList.remove('row-selected'));
      if (!tr) return;
      tr.classList.add('row-selected');
      const key = tr.dataset.rowKey;
      if (key) localStorage.setItem(ROW_STORAGE_KEY, key);
    }}

    tbody.addEventListener('click', function(e) {{
      if (e.target.closest('a')) return;
      const tr = e.target.closest('tr.data-row');
      if (!tr) return;
      selectRow(tr);
    }});

    const savedKey = localStorage.getItem(ROW_STORAGE_KEY);
    if (savedKey) {{
      const saved = Array.from(tbody.querySelectorAll('tr.data-row'))
        .find(tr => tr.dataset.rowKey === savedKey);
      if (saved) selectRow(saved);
    }}
  </script>
</body>
</html>"""


async def async_main() -> int:
    ensure_dirs()
    today = date.today().isoformat()
    if USE_CACHED_ENRICHED:
        enriched = load_cached_enriched()
    else:
        master = _latest_master_path()
        print(f"Loading and enriching {master} (Scryfall IDs only)...", flush=True)
        master_df = pd.read_csv(master, low_memory=False)
        print(f"  master rows: {len(master_df):,}", flush=True)
        enriched = enrich(master_df, include_listings=False)
        print(f"  enriched rows: {len(enriched):,}", flush=True)

    ranked = select_opportunity_targets(enriched)
    if USE_SCREENING:
        print_screen_summary(ranked, len(enriched))
    else:
        print(f"Ranked top {len(ranked):,} CK buylist targets by cash price", flush=True)
    if ranked.empty:
        label = "screening candidates" if USE_SCREENING else "rankable rows"
        print(f"No {label} (check Scryfall + tcgplayer ID joins / tcgcsv).", file=sys.stderr)
        return 1

    targets = targets_from_ranked(ranked)
    listings = pd.DataFrame()
    if SKIP_FETCH:
        print("OPPORTUNITY_SKIP_FETCH=1 — using cached listings lookup")
        listings = read_listings_lookup()
        if not listings.empty:
            print(f"Loaded {len(listings):,} listing rows (latest scrape only)")
    else:
        if not os.environ.get("TCG_BROWSER_CDP_URL"):
            print(
                "WARNING: TCG_BROWSER_CDP_URL not set; listing fetch may fail without Edge CDP.",
                file=sys.stderr,
            )
        print(f"Fetching live TCG listings for {len(targets):,} products...", flush=True)
        listings = await scrape_targets_browser(targets)
        listings["scraped_date"] = today
        if listings.empty:
            print(
                "ERROR: Live mp-search API returned no listings. Retry with Edge CDP.",
                file=sys.stderr,
            )
            return 1
        listings = format_listings_df(listings)
        row_count = write_listings_lookup(listings)
        print(f"Wrote {row_count:,} rows to listings lookup (replaced prior scrape)")

    export_rows = build_export_rows(ranked, listings)
    report_rows = _filter_report_rows(export_rows)
    out_path = OPPORTUNITIES_DIR / f"cardbitrage_{today}.html"
    out_path.write_text(
        render_html(report_rows, today, len(targets), len(ranked)),
        encoding="utf-8",
    )
    print(
        f"Wrote {out_path} ({len(report_rows):,} rows after filter, "
        f"{len(export_rows):,} before filter)"
    )

    try:
        from load_opportunities import load_opportunities

        n = load_opportunities(
            report_rows,
            snapshot_date=date.fromisoformat(today),
            target_count=len(targets),
            ranked_count=len(ranked),
        )
        print(f"Loaded {n:,} rows into Postgres opportunities ({today})")
    except Exception as exc:
        print(f"WARN: Postgres opportunities load skipped: {exc}", file=sys.stderr)

    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
