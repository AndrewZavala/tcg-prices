"""Self-contained HTML export of active collection cards for sharing with friends."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any


def _mana_class(colors: str | None) -> str:
    raw = (colors or "").strip().upper().replace(" ", "")
    if not raw or raw in {"NA", "C", "COLORLESS"}:
        return "mana-c"
    letters = sorted(set(ch for ch in raw if ch in "WUBRG"))
    if not letters:
        return "mana-c"
    if len(letters) >= 2:
        return "mana-m"
    return f"mana-{letters[0].lower()}"


def _batch_label(batch_file: str | None) -> str:
    """Batch10_export.csv → Batch10; otherwise return as-is."""
    raw = (batch_file or "").strip()
    if not raw:
        return ""
    m = re.match(r"^(Batch\d+)", raw, flags=re.I)
    if m:
        return m.group(1)
    return re.sub(r"_export\.csv$", "", raw, flags=re.I) or raw


def _helper_dir() -> Path:
    root = Path(os.environ.get("TCG_ROOT", Path(__file__).resolve().parents[1]))
    return root / "helper"


def _finish_to_sub_type(finish: str | None) -> str:
    key = str(finish or "normal").strip().lower()
    if key in {"foil", "etched", "foil etched"}:
        return "Foil"
    return "Normal"


def _parse_money(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def attach_tcg_market_prices(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach TCGPlayer market_price onto collection rows via Scryfall + tcgcsv lookups."""
    helper = _helper_dir()
    scry_path = helper / "scryfall_cards_lookup.csv"
    price_path = helper / "tcgcsv_prices_lookup.csv"

    scry_by_id: dict[str, dict[str, str]] = {}
    if scry_path.is_file():
        with open(scry_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                sid = (row.get("scryfall_id") or "").strip()
                if sid:
                    scry_by_id[sid] = row

    prices: dict[tuple[str, str], float] = {}
    if price_path.is_file():
        with open(price_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pid = str(row.get("product_id") or "").strip()
                if not pid:
                    continue
                sub = (row.get("sub_type_name") or "Normal").strip() or "Normal"
                market = _parse_money(row.get("market_price"))
                if market is None:
                    market = _parse_money(row.get("mid_price")) or _parse_money(row.get("low_price"))
                if market is not None:
                    prices[(pid, sub)] = market

    for card in cards:
        card["market_price"] = None
        sid = str(card.get("scryfall_id") or "").strip()
        finish = str(card.get("finish") or "normal").strip().lower()
        scry = scry_by_id.get(sid) if sid else None

        product_id = ""
        if scry:
            if finish in {"etched", "foil etched"}:
                product_id = str(scry.get("tcgplayer_etched_id") or scry.get("tcgplayer_id") or "").strip()
            else:
                product_id = str(scry.get("tcgplayer_id") or "").strip()
            if product_id.endswith(".0"):
                product_id = product_id[:-2]

        sub = _finish_to_sub_type(finish)
        market = prices.get((product_id, sub)) if product_id else None
        if market is None and product_id:
            # Try alternate subtype keys used by tcgcsv.
            for alt in ("Normal", "Foil", ""):
                if alt == sub:
                    continue
                market = prices.get((product_id, alt))
                if market is not None:
                    break

        if market is None and scry:
            if finish in {"etched", "foil etched"}:
                market = _parse_money(scry.get("usd_etched")) or _parse_money(scry.get("usd_foil"))
            elif finish == "foil":
                market = _parse_money(scry.get("usd_foil")) or _parse_money(scry.get("usd"))
            else:
                market = _parse_money(scry.get("usd"))

        if market is not None:
            card["market_price"] = round(float(market), 2)

        card["tcgplayer_id"] = product_id or None
        if product_id:
            foil_q = "?Printing=Foil" if finish in {"foil", "etched", "foil etched"} else ""
            card["tcg_url"] = f"https://www.tcgplayer.com/product/{product_id}{foil_q}"
        else:
            card["tcg_url"] = None

    return cards


def build_share_html(cards: list[dict[str, Any]], *, exported_on: date | None = None) -> str:
    """Build a standalone HTML page with search + set filter (active + keep).

    First-version style: data embedded as JSON, table rendered by JS.
    """
    when = (exported_on or date.today()).isoformat()
    cards = attach_tcg_market_prices([dict(c) for c in cards])
    payload = []
    for c in cards:
        set_code = (c.get("set_code") or "").strip().lower()
        set_name = (c.get("set_name") or "").strip() or set_code.upper() or "Unknown set"
        status = (c.get("status") or "active").strip().lower()
        market = c.get("market_price")
        try:
            market_f = float(market) if market is not None else None
        except (TypeError, ValueError):
            market_f = None
        payload.append(
            {
                "id": int(c["id"]) if c.get("id") is not None else None,
                "name": c.get("name") or "",
                "set_code": set_code,
                "set_name": set_name,
                "collector_number": c.get("collector_number") or "",
                "finish": (c.get("finish") or "normal").strip().lower(),
                "quantity": int(c.get("quantity") or 1),
                "mana": _mana_class(c.get("colors")),
                "batch": _batch_label(c.get("batch_file")),
                "pos": str(c.get("scan_order") or ""),
                "status": status if status in {"active", "keep"} else "active",
                "market_price": market_f,
                "tcgplayer_id": str(c.get("tcgplayer_id") or "") or None,
                "tcg_url": c.get("tcg_url") or None,
            }
        )

    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("<", "\\u003c").replace(">", "\\u003e")

    unique = len(payload)
    copies = sum(r["quantity"] for r in payload)
    priced = sum(1 for r in payload if r.get("market_price") is not None)
    market_total = round(
        sum((r["market_price"] or 0) * (r["quantity"] or 0) for r in payload),
        2,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Inventory — {when}</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1a1d21;
      --muted: #5c6570;
      --line: #d8dee6;
      --accent: #2f6fed;
      --accent-soft: #e8f0ff;
      --radius: 10px;
      --shadow: 0 1px 2px rgba(26, 29, 33, 0.06), 0 8px 24px rgba(26, 29, 33, 0.06);
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(1200px 500px at 10% -10%, #dfe9ff 0%, transparent 55%),
        radial-gradient(900px 400px at 100% 0%, #fff1d6 0%, transparent 45%),
        var(--bg);
      min-height: 100vh;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 1.5rem 1rem 3rem;
    }}
    header {{ margin-bottom: 1.25rem; }}
    h1 {{
      margin: 0 0 0.35rem;
      font-size: clamp(1.6rem, 3vw, 2.1rem);
      letter-spacing: -0.02em;
    }}
    .sub {{
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .kpis {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 1rem;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 0.65rem 0.9rem;
      min-width: 7rem;
      box-shadow: var(--shadow);
    }}
    .kpi span {{
      display: block;
      font-size: 0.75rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .kpi strong {{ font-size: 1.25rem; }}
    .toolbar {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 0.75rem;
      margin: 1.25rem 0 0.75rem;
      position: sticky;
      top: 0;
      z-index: 5;
      padding: 0.75rem 0;
      background: linear-gradient(to bottom, rgba(244,246,248,0.96), rgba(244,246,248,0.92));
      backdrop-filter: blur(6px);
    }}
    @media (max-width: 720px) {{
      .toolbar {{ grid-template-columns: 1fr; }}
    }}
    label.field {{
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      font-size: 0.8rem;
      color: var(--muted);
      font-weight: 600;
    }}
    input[type="search"], .set-panel {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font: inherit;
    }}
    input[type="search"] {{
      padding: 0.65rem 0.75rem;
    }}
    input[type="search"]:focus {{
      outline: 2px solid var(--accent);
      outline-offset: 1px;
    }}
    .set-wrap {{ position: relative; }}
    .set-toggle {{
      width: 100%;
      text-align: left;
      padding: 0.65rem 0.75rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      cursor: pointer;
      font: inherit;
      color: var(--text);
    }}
    .set-panel {{
      display: none;
      position: absolute;
      left: 0;
      right: 0;
      top: calc(100% + 4px);
      max-height: 280px;
      overflow: auto;
      padding: 0.5rem;
      box-shadow: var(--shadow);
      z-index: 10;
    }}
    .set-panel.is-open {{ display: block; }}
    .set-panel input[type="search"] {{
      margin-bottom: 0.4rem;
    }}
    .set-actions {{
      display: flex;
      gap: 0.4rem;
      margin-bottom: 0.4rem;
    }}
    .set-actions button {{
      border: 1px solid var(--line);
      background: var(--accent-soft);
      color: var(--text);
      border-radius: 6px;
      padding: 0.25rem 0.55rem;
      font: inherit;
      font-size: 0.8rem;
      cursor: pointer;
    }}
    .set-option {{
      display: flex;
      align-items: flex-start;
      gap: 0.45rem;
      padding: 0.35rem 0.25rem;
      border-radius: 6px;
      font-weight: 500;
      color: var(--text);
      cursor: pointer;
    }}
    .set-option:hover {{ background: var(--accent-soft); }}
    .set-option .code {{
      color: var(--muted);
      font-size: 0.78rem;
      margin-left: auto;
      text-transform: uppercase;
    }}
    .summary {{
      color: var(--muted);
      font-size: 0.9rem;
      margin: 0 0 0.6rem;
    }}
    .inv-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      margin: 0 0 0.65rem;
    }}
    .inv-actions button {{
      border: 1px solid var(--line);
      background: var(--accent);
      color: #fff;
      border-radius: 8px;
      padding: 0.45rem 0.85rem;
      font: inherit;
      font-size: 0.9rem;
      cursor: pointer;
    }}
    .inv-actions button:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
    }}
    .inv-actions button.ghost {{
      background: var(--accent-soft);
      color: var(--text);
    }}
    .inv-actions .hint {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .toast {{
      position: fixed;
      bottom: 1.25rem;
      left: 50%;
      transform: translateX(-50%);
      background: #1a1d21;
      color: #fff;
      padding: 0.65rem 1rem;
      border-radius: 8px;
      font-size: 0.9rem;
      z-index: 50;
      box-shadow: var(--shadow);
    }}
    .toast[hidden] {{ display: none; }}
    .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: auto;
      box-shadow: var(--shadow);
      max-height: calc(100vh - 14rem);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      padding: 0.55rem 0.7rem;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef2f6;
      z-index: 1;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .finish {{
      display: inline-block;
      font-size: 0.75rem;
      padding: 0.1rem 0.4rem;
      border-radius: 999px;
      background: #eef2f6;
      color: var(--muted);
      text-transform: capitalize;
    }}
    .finish.is-foil {{ background: #fff3cd; color: #7a5b00; }}
    .finish.is-etched {{ background: #e8e0ff; color: #4b3a8c; }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .price {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .price.is-missing {{ color: var(--muted); }}
    a.tcg-link {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.82rem;
    }}
    a.tcg-link:hover {{ text-decoration: underline; }}
    .name-cell {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem 0.55rem; }}
    .name-cell .card-name {{ font-weight: 600; }}
    .deck-total {{
      margin: 0.65rem 0 0;
      font-weight: 650;
      font-size: 1.05rem;
    }}
    .deck-total span {{ color: var(--muted); font-weight: 500; font-size: 0.9rem; }}
    .deck-total-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      margin-top: 0.55rem;
    }}
    .badge.keep {{
      display: inline-block;
      margin-left: 0.35rem;
      padding: 0.1rem 0.4rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      background: #e8f5e9;
      color: #2e7d32;
      vertical-align: middle;
    }}
    tbody tr.mana-w {{ background-color: #fffde3; }}
    tbody tr.mana-u {{ background-color: #cfe8ff; }}
    tbody tr.mana-b {{ background-color: #d9d2e9; }}
    tbody tr.mana-r {{ background-color: #f8caca; }}
    tbody tr.mana-g {{ background-color: #cfeccf; }}
    tbody tr.mana-m {{ background-color: #ffe59d; }}
    tbody tr.mana-c {{ background-color: #d9d9d9; }}
    tbody tr:hover {{ filter: brightness(0.97); }}
    .empty {{
      padding: 2rem 1rem;
      text-align: center;
      color: var(--muted);
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .deck-check {{
      margin: 1.25rem 0 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 0.9rem 1rem 1rem;
    }}
    .deck-check h2 {{
      margin: 0 0 0.35rem;
      font-size: 1.05rem;
      letter-spacing: -0.01em;
    }}
    .deck-check .hint {{
      margin: 0 0 0.65rem;
      color: var(--muted);
      font-size: 0.85rem;
    }}
    .deck-check textarea {{
      width: 100%;
      min-height: 8.5rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0.65rem 0.75rem;
      font: 0.85rem/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      resize: vertical;
      color: var(--text);
      background: #fafbfc;
    }}
    .deck-check textarea:focus {{
      outline: 2px solid var(--accent);
      outline-offset: 1px;
    }}
    .deck-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.65rem;
      align-items: center;
    }}
    .deck-actions label.hide-missing {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.88rem;
      color: var(--muted);
      font-weight: 600;
      cursor: pointer;
      margin-left: 0.25rem;
    }}
    .deck-actions button {{
      border: 1px solid var(--line);
      background: var(--accent);
      color: #fff;
      border-radius: 8px;
      padding: 0.45rem 0.85rem;
      font: inherit;
      font-size: 0.9rem;
      cursor: pointer;
    }}
    .deck-actions button.ghost {{
      background: var(--accent-soft);
      color: var(--text);
    }}
    .deck-summary {{
      margin: 0.75rem 0 0.4rem;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .deck-results {{
      margin-top: 0.5rem;
      max-height: 22rem;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .deck-results[hidden] {{ display: none; }}
    .deck-results table {{ font-size: 0.88rem; }}
    .deck-results th {{ position: sticky; top: 0; }}
    .match {{
      font-size: 0.78rem;
      font-weight: 700;
      white-space: nowrap;
    }}
    .match.is-exact {{ color: #1b7a3d; }}
    .match.is-close {{ color: #9a6b00; }}
    .match.is-missing {{ color: #a33; }}
    .deck-lot {{ color: var(--muted); font-size: 0.82rem; }}
    .deck-results button {{
      border: 1px solid var(--line);
      background: var(--accent-soft);
      color: var(--text);
      border-radius: 6px;
      padding: 0.2rem 0.5rem;
      font: inherit;
      font-size: 0.78rem;
      cursor: pointer;
      margin-left: 0.35rem;
    }}
    footer {{
      margin-top: 1rem;
      font-size: 0.8rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Card inventory</h1>
      <p class="sub">Active + keep · exported {when} · TCGPlayer market prices · search by name or filter by set</p>
      <div class="kpis">
        <div class="kpi"><span>Unique</span><strong id="kpiUnique">{unique}</strong></div>
        <div class="kpi"><span>Copies</span><strong id="kpiCopies">{copies}</strong></div>
        <div class="kpi"><span>Showing</span><strong id="kpiShowing">{unique}</strong></div>
        <div class="kpi"><span>Market value</span><strong id="kpiMarket">${market_total:,.2f}</strong></div>
        <div class="kpi"><span>Priced</span><strong id="kpiPriced">{priced}/{unique}</strong></div>
      </div>
    </header>

    <section class="deck-check" aria-label="Deck check">
      <h2>Deck check</h2>
      <p class="hint">Paste a Moxfield export (tags like #!ramp are ignored). Matches exact set + collector (+ foil when marked), then falls back to card name. Matched lines show TCGPlayer market × copies you can buy (min need/have).</p>
      <textarea id="deckText" placeholder="1 Blood Crypt (EXP) 8 *F*&#10;1 Sol Ring (SLD) 913 *F*" spellcheck="false"></textarea>
      <div class="deck-actions">
        <button type="button" id="deckRun">Check inventory</button>
        <button type="button" class="ghost" id="deckClear">Clear</button>
        <button type="button" class="ghost" id="deckCopy" hidden>Copy buy list</button>
        <label class="hide-missing">
          <input type="checkbox" id="deckHideMissing" checked />
          Hide missing
        </label>
      </div>
      <p class="deck-summary" id="deckSummary">Paste a list and run check.</p>
      <div class="deck-results" id="deckResults" hidden>
        <table>
          <thead>
            <tr>
              <th>Deck line</th>
              <th>Match</th>
              <th class="num">Have</th>
              <th class="num">Need</th>
              <th class="num">Market</th>
              <th class="num">Line $</th>
              <th>In inventory</th>
              <th><span class="sr-only">TCG</span></th>
            </tr>
          </thead>
          <tbody id="deckBody"></tbody>
        </table>
        <p class="deck-total" id="deckTotal" hidden></p>
      </div>
    </section>

    <div class="toolbar">
      <label class="field">
        Card search
        <input type="search" id="q" placeholder="Search card names…" autocomplete="off" />
      </label>
      <div class="field">
        <span>Set filter</span>
        <div class="set-wrap">
          <button type="button" class="set-toggle" id="setToggle" aria-expanded="false" aria-controls="setPanel">
            All sets
          </button>
          <div class="set-panel" id="setPanel" role="group" aria-label="Sets">
            <input type="search" id="setQ" placeholder="Search sets…" autocomplete="off" />
            <div class="set-actions">
              <button type="button" id="setAll">All</button>
              <button type="button" id="setNone">None</button>
            </div>
            <div id="setList"></div>
          </div>
        </div>
      </div>
    </div>

    <p class="summary" id="resultSummary"></p>
    <div class="inv-actions">
      <button type="button" id="markSoldBtn" disabled>Mark sold</button>
      <button type="button" class="ghost" id="selectVisibleBtn">Select visible</button>
      <button type="button" class="ghost" id="clearSelectBtn">Clear selection</button>
      <button type="button" class="ghost" id="copyListBtn">Copy list + prices</button>
      <span class="hint" id="selectHint">0 selected · mark sold without a CK order (needs this app running)</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="num" style="width:2.5rem"><input type="checkbox" id="selectAllVisible" title="Select all visible" aria-label="Select all visible" /></th>
            <th>Name</th>
            <th>Set</th>
            <th>#</th>
            <th>Finish</th>
            <th class="num">Qty</th>
            <th class="num">Market</th>
            <th>TCG</th>
            <th>Batch</th>
            <th class="num">Pos</th>
          </tr>
        </thead>
        <tbody id="body"></tbody>
      </table>
      <p class="empty" id="empty" hidden>No cards match your filters.</p>
    </div>
    <footer>Open from Sell list while Manifest Bread is running to mark sold. Save As for an offline copy for friends (sold actions won’t work offline).</footer>
  </main>
  <div class="toast" id="toast" hidden></div>

  <script id="inventory-data" type="application/json">{data_json}</script>
  <script>
    const CARDS = JSON.parse(document.getElementById("inventory-data").textContent);
    const els = {{
      q: document.getElementById("q"),
      setToggle: document.getElementById("setToggle"),
      setPanel: document.getElementById("setPanel"),
      setQ: document.getElementById("setQ"),
      setList: document.getElementById("setList"),
      setAll: document.getElementById("setAll"),
      setNone: document.getElementById("setNone"),
      body: document.getElementById("body"),
      empty: document.getElementById("empty"),
      summary: document.getElementById("resultSummary"),
      kpiUnique: document.getElementById("kpiUnique"),
      kpiCopies: document.getElementById("kpiCopies"),
      kpiShowing: document.getElementById("kpiShowing"),
      kpiMarket: document.getElementById("kpiMarket"),
      kpiPriced: document.getElementById("kpiPriced"),
      markSoldBtn: document.getElementById("markSoldBtn"),
      selectVisibleBtn: document.getElementById("selectVisibleBtn"),
      clearSelectBtn: document.getElementById("clearSelectBtn"),
      copyListBtn: document.getElementById("copyListBtn"),
      selectAllVisible: document.getElementById("selectAllVisible"),
      selectHint: document.getElementById("selectHint"),
      toast: document.getElementById("toast"),
    }};

    const selectedIds = new Set();

    const sets = [...new Map(
      CARDS.map((c) => [c.set_code || "_", {{ code: c.set_code || "", name: c.set_name || "Unknown set" }}])
    ).values()].sort((a, b) => a.name.localeCompare(b.name, undefined, {{ sensitivity: "base" }}));

    const selected = new Set(sets.map((s) => s.code));

    function escapeHtml(s) {{
      return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function fmtUsd(n) {{
      if (n == null || Number.isNaN(Number(n))) return "—";
      return "$" + Number(n).toFixed(2);
    }}

    function cardMarket(card) {{
      if (!card || card.market_price == null || Number.isNaN(Number(card.market_price))) return null;
      return Number(card.market_price);
    }}

    function deckLineCost(row) {{
      if (!row || row.match === "missing") return null;
      const hit = row.cards && row.cards[0];
      const unit = cardMarket(hit);
      if (unit == null) return null;
      const need = Number(row.line?.qty) || 0;
      const have = Number(row.qty_have) || 0;
      const buyQty = Math.min(need, have);
      if (buyQty <= 0) return null;
      return {{ unit, buyQty, line: unit * buyQty }};
    }}

    function tcgHref(card) {{
      if (!card) return "";
      if (card.tcg_url) return String(card.tcg_url);
      const id = card.tcgplayer_id;
      if (!id) return "";
      const foil = isFoilFinish(card.finish) ? "?Printing=Foil" : "";
      return `https://www.tcgplayer.com/product/${{id}}${{foil}}`;
    }}

    function formatInventoryLine(card) {{
      const qty = Number(card.quantity) || 1;
      const set = (card.set_code || "").toUpperCase() || (card.set_name || "");
      const cn = card.collector_number ? ` ${{card.collector_number}}` : "";
      const finish = isFoilFinish(card.finish) ? " *F*" : "";
      const unit = cardMarket(card);
      const price = unit == null ? "" : ` — ${{fmtUsd(unit)}}`;
      const lineTotal =
        unit == null || qty === 1 ? "" : ` (×${{qty}} = ${{fmtUsd(unit * qty)}})`;
      const url = tcgHref(card);
      const link = url ? ` ${{url}}` : "";
      return `${{qty}} ${{card.name || ""}} (${{set}})${{cn}}${{finish}}${{price}}${{lineTotal}}${{link}}`;
    }}

    async function copyText(text, okMsg) {{
      const body = String(text || "").trim();
      if (!body) {{
        showToast("Nothing to copy");
        return;
      }}
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(body);
        }} else {{
          const ta = document.createElement("textarea");
          ta.value = body;
          ta.setAttribute("readonly", "");
          ta.style.position = "fixed";
          ta.style.left = "-9999px";
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }}
        showToast(okMsg || "Copied");
      }} catch (err) {{
        alert("Copy failed: " + (err.message || String(err)));
      }}
    }}

    function copyVisibleInventoryList() {{
      const selectedOnly = selectedIds.size > 0;
      const rows = filteredCards()
        .filter((c) => !selectedOnly || selectedIds.has(c.id))
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name, undefined, {{ sensitivity: "base" }}));
      const lines = rows.map(formatInventoryLine);
      const marketSum = rows.reduce((n, r) => {{
        const unit = cardMarket(r);
        return n + (unit == null ? 0 : unit * (r.quantity || 0));
      }}, 0);
      const header = selectedOnly
        ? `Selected cards (${{rows.length}}) · ${{fmtUsd(marketSum)}}`
        : `Visible cards (${{rows.length}}) · ${{fmtUsd(marketSum)}}`;
      const text = [header, ""].concat(lines).join("\\n");
      const label = selectedOnly ? "selected" : "visible";
      copyText(text, `Copied ${{rows.length}} ${{label}} card${{rows.length === 1 ? "" : "s"}}`);
    }}

    function copyDeckBuyList() {{
      const hideMissing = !deckEls.hideMissing || deckEls.hideMissing.checked;
      const rows = (hideMissing ? deckRows.filter((r) => r.match !== "missing") : deckRows)
        .filter((r) => r.match !== "missing");
      const lines = [];
      let total = 0;
      let priced = 0;
      for (const r of rows) {{
        const hit = r.cards && r.cards[0];
        const cost = deckLineCost(r);
        const need = Number(r.line?.qty) || 0;
        const have = Number(r.qty_have) || 0;
        const buyQty = Math.min(need, have) || need;
        const name = hit?.name || r.line?.name || r.line?.raw || "";
        const set = (hit?.set_code || r.line?.set_code || "").toUpperCase();
        const cn = hit?.collector_number || r.line?.collector_number || "";
        const finish = (isFoilFinish(hit?.finish) || r.line?.foil) ? " *F*" : "";
        const unit = cost ? cost.unit : cardMarket(hit);
        const priceBit = unit == null ? "" : ` — ${{fmtUsd(unit)}}`;
        const lineBit = cost ? ` (×${{cost.buyQty}} = ${{fmtUsd(cost.line)}})` : "";
        const url = tcgHref(hit);
        const link = url ? ` ${{url}}` : "";
        lines.push(`${{buyQty}} ${{name}}${{set ? ` (${{set}})` : ""}}${{cn ? ` ${{cn}}` : ""}}${{finish}}${{priceBit}}${{lineBit}}${{link}}`);
        if (cost) {{
          total += cost.line;
          priced += 1;
        }}
      }}
      const header = `Deck buy list · ${{priced}} priced · total ${{fmtUsd(total)}}`;
      copyText([header, ""].concat(lines).join("\\n"), `Copied ${{lines.length}} deck line${{lines.length === 1 ? "" : "s"}}`);
    }}

    function finishClass(finish) {{
      if (finish === "foil") return "finish is-foil";
      if (finish === "etched") return "finish is-etched";
      return "finish";
    }}

    function updateSetToggleLabel() {{
      if (selected.size === sets.length) {{
        els.setToggle.textContent = "All sets";
        return;
      }}
      if (selected.size === 0) {{
        els.setToggle.textContent = "No sets selected";
        return;
      }}
      if (selected.size === 1) {{
        const code = [...selected][0];
        const row = sets.find((s) => s.code === code);
        els.setToggle.textContent = row ? row.name : "1 set";
        return;
      }}
      els.setToggle.textContent = `${{selected.size}} sets selected`;
    }}

    function renderSetOptions() {{
      const needle = (els.setQ.value || "").trim().toLowerCase();
      els.setList.innerHTML = sets
        .filter((s) => {{
          if (!needle) return true;
          return (
            s.name.toLowerCase().includes(needle) ||
            s.code.toLowerCase().includes(needle)
          );
        }})
        .map((s) => {{
          const checked = selected.has(s.code) ? "checked" : "";
          return `<label class="set-option">
            <input type="checkbox" data-code="${{escapeHtml(s.code)}}" ${{checked}} />
            <span>${{escapeHtml(s.name)}}</span>
            <span class="code">${{escapeHtml((s.code || "").toUpperCase())}}</span>
          </label>`;
        }})
        .join("");
    }}

    function showToast(msg) {{
      if (!els.toast) return;
      els.toast.textContent = msg;
      els.toast.hidden = false;
      clearTimeout(showToast._t);
      showToast._t = setTimeout(() => {{ els.toast.hidden = true; }}, 3200);
    }}

    function updateSelectionUi() {{
      const n = selectedIds.size;
      if (els.selectHint) {{
        els.selectHint.textContent =
          n > 0
            ? `${{n}} selected · Copy list uses selection · mark sold needs app running`
            : `0 selected · Copy list uses visible cards · mark sold needs app running`;
      }}
      if (els.markSoldBtn) els.markSoldBtn.disabled = n === 0;
      const boxes = [...els.body.querySelectorAll(".row-check")];
      if (els.selectAllVisible && boxes.length) {{
        const checked = boxes.filter((b) => b.checked).length;
        els.selectAllVisible.checked = checked === boxes.length;
        els.selectAllVisible.indeterminate = checked > 0 && checked < boxes.length;
      }} else if (els.selectAllVisible) {{
        els.selectAllVisible.checked = false;
        els.selectAllVisible.indeterminate = false;
      }}
    }}

    function refreshKpis() {{
      const unique = CARDS.length;
      const copies = CARDS.reduce((n, r) => n + (r.quantity || 0), 0);
      if (els.kpiUnique) els.kpiUnique.textContent = String(unique);
      if (els.kpiCopies) els.kpiCopies.textContent = String(copies);
    }}

    function apiOriginOk() {{
      return location.protocol === "http:" || location.protocol === "https:";
    }}

    async function markSoldIds(ids) {{
      const clean = [...new Set(ids.map((x) => parseInt(x, 10)).filter((x) => x > 0))];
      if (!clean.length) return 0;
      if (!apiOriginOk()) {{
        throw new Error(
          "Open this page from Sell list → Share inventory HTML (in the browser, not a downloaded file) while Manifest Bread is running."
        );
      }}
      const res = await fetch("/api/collection/mark-sold", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ ids: clean }}),
      }});
      if (!res.ok) {{
        let msg = await res.text();
        try {{
          const parsed = JSON.parse(msg);
          if (parsed.detail) msg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
        }} catch {{ /* keep */ }}
        throw new Error(msg);
      }}
      const data = await res.json();
      const updated = new Set(data.ids || clean);
      for (let i = CARDS.length - 1; i >= 0; i--) {{
        if (updated.has(CARDS[i].id)) CARDS.splice(i, 1);
      }}
      updated.forEach((id) => selectedIds.delete(id));
      if (deckRows.length) {{
        deckRows = deckRows.map((r) => matchDeckLine(r.line));
      }}
      refreshKpis();
      render();
      if (deckRows.length) renderDeckResults();
      return data.updated ?? updated.size;
    }}

    function filteredCards() {{
      const needle = (els.q.value || "").trim().toLowerCase();
      return CARDS.filter((c) => {{
        if (!selected.has(c.set_code || "")) return false;
        if (!needle) return true;
        return String(c.name || "").toLowerCase().includes(needle);
      }});
    }}

    function render() {{
      const rows = filteredCards().slice().sort((a, b) => {{
        const byName = a.name.localeCompare(b.name, undefined, {{ sensitivity: "base" }});
        if (byName) return byName;
        const bySet = (a.set_name || "").localeCompare(b.set_name || "", undefined, {{ sensitivity: "base" }});
        if (bySet) return bySet;
        const byBatch = String(a.batch || "").localeCompare(String(b.batch || ""), undefined, {{
          numeric: true,
          sensitivity: "base",
        }});
        if (byBatch) return byBatch;
        return String(a.pos || "").localeCompare(String(b.pos || ""), undefined, {{ numeric: true }});
      }});
      const copies = rows.reduce((n, r) => n + (r.quantity || 0), 0);
      const marketSum = rows.reduce((n, r) => {{
        const unit = cardMarket(r);
        return n + (unit == null ? 0 : unit * (r.quantity || 0));
      }}, 0);
      const pricedN = rows.filter((r) => cardMarket(r) != null).length;
      els.kpiShowing.textContent = String(rows.length);
      if (els.kpiMarket) els.kpiMarket.textContent = fmtUsd(marketSum);
      if (els.kpiPriced) els.kpiPriced.textContent = `${{pricedN}}/${{rows.length}}`;
      els.summary.textContent = rows.length
        ? `Showing ${{rows.length.toLocaleString()}} cards · ${{copies.toLocaleString()}} copies · ${{fmtUsd(marketSum)}} market`
        : "No matches";
      els.empty.hidden = rows.length > 0;
      els.body.innerHTML = rows
        .map((r) => {{
          const setLabel = r.set_name
            ? `${{escapeHtml(r.set_name)}}`
            : escapeHtml((r.set_code || "").toUpperCase());
          const id = r.id != null ? String(r.id) : "";
          const checked = id && selectedIds.has(r.id) ? "checked" : "";
          const market = cardMarket(r);
          const marketCls = market == null ? "price is-missing" : "price";
          const tcg = tcgHref(r);
          const tcgCell = tcg
            ? `<a class="tcg-link" href="${{escapeHtml(tcg)}}" target="_blank" rel="noopener">TCG</a>`
            : `<span class="price is-missing">—</span>`;
          return `<tr class="${{escapeHtml(r.mana)}}" data-id="${{escapeHtml(id)}}">
            <td class="num"><input type="checkbox" class="row-check" data-id="${{escapeHtml(id)}}" ${{checked}} aria-label="Select ${{escapeHtml(r.name)}}" /></td>
            <td>${{escapeHtml(r.name)}}${{r.status === "keep" ? ' <span class="badge keep">keep</span>' : ""}}</td>
            <td>${{setLabel}}</td>
            <td>${{escapeHtml(r.collector_number)}}</td>
            <td><span class="${{finishClass(r.finish)}}">${{escapeHtml(r.finish || "normal")}}</span></td>
            <td class="num">${{r.quantity}}</td>
            <td class="num ${{marketCls}}">${{fmtUsd(market)}}</td>
            <td>${{tcgCell}}</td>
            <td>${{escapeHtml(r.batch)}}</td>
            <td class="num">${{escapeHtml(r.pos)}}</td>
          </tr>`;
        }})
        .join("");
      updateSetToggleLabel();
      updateSelectionUi();
    }}

    els.setToggle.addEventListener("click", () => {{
      const open = !els.setPanel.classList.contains("is-open");
      els.setPanel.classList.toggle("is-open", open);
      els.setToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) els.setQ.focus();
    }});

    document.addEventListener("click", (e) => {{
      if (!e.target.closest(".set-wrap")) {{
        els.setPanel.classList.remove("is-open");
        els.setToggle.setAttribute("aria-expanded", "false");
      }}
    }});

    els.setList.addEventListener("change", (e) => {{
      const input = e.target.closest('input[type="checkbox"][data-code]');
      if (!input) return;
      if (input.checked) selected.add(input.dataset.code);
      else selected.delete(input.dataset.code);
      render();
    }});

    els.setAll.addEventListener("click", () => {{
      sets.forEach((s) => selected.add(s.code));
      renderSetOptions();
      render();
    }});

    els.setNone.addEventListener("click", () => {{
      selected.clear();
      renderSetOptions();
      render();
    }});

    els.setQ.addEventListener("input", renderSetOptions);
    els.q.addEventListener("input", render);

    els.body.addEventListener("change", (e) => {{
      const box = e.target.closest(".row-check");
      if (!box) return;
      const id = parseInt(box.dataset.id, 10);
      if (!id) return;
      if (box.checked) selectedIds.add(id);
      else selectedIds.delete(id);
      updateSelectionUi();
    }});

    els.selectAllVisible?.addEventListener("change", () => {{
      const on = !!els.selectAllVisible.checked;
      filteredCards().forEach((c) => {{
        if (c.id == null) return;
        if (on) selectedIds.add(c.id);
        else selectedIds.delete(c.id);
      }});
      render();
    }});

    els.selectVisibleBtn?.addEventListener("click", () => {{
      filteredCards().forEach((c) => {{
        if (c.id != null) selectedIds.add(c.id);
      }});
      render();
    }});

    els.clearSelectBtn?.addEventListener("click", () => {{
      selectedIds.clear();
      render();
    }});

    els.markSoldBtn?.addEventListener("click", async () => {{
      const ids = [...selectedIds];
      if (!ids.length) return;
      if (!confirm(`Mark ${{ids.length}} card${{ids.length === 1 ? "" : "s"}} as sold?`)) return;
      try {{
        const n = await markSoldIds(ids);
        showToast(`Marked ${{n}} sold`);
      }} catch (err) {{
        alert(err.message || String(err));
      }}
    }});

    const deckEls = {{
      text: document.getElementById("deckText"),
      run: document.getElementById("deckRun"),
      clear: document.getElementById("deckClear"),
      copy: document.getElementById("deckCopy"),
      hideMissing: document.getElementById("deckHideMissing"),
      summary: document.getElementById("deckSummary"),
      results: document.getElementById("deckResults"),
      body: document.getElementById("deckBody"),
      total: document.getElementById("deckTotal"),
    }};
    let deckRows = [];

    // Qty + name + (SET) + CN + optional *F* + optional Moxfield tags (#!ramp, # comment).
    const MOXFIELD_LINE = /^\\s*(\\d+)\\s+(.+?)\\s+\\(([A-Za-z0-9]+)\\)\\s+([^\\s#*]+?)(?:\\s+\\*F\\*)?(?:\\s+#.*)?\\s*$/i;

    function normCn(cn) {{
      return String(cn || "").replaceAll("★", "").replaceAll("*", "").trim().toLowerCase();
    }}

    function nameKeys(name) {{
      const full = String(name || "").toLowerCase().replace(/\\s+/g, " ").trim();
      if (!full) return [];
      const keys = [full];
      if (full.includes(" / ")) {{
        const front = full.split(" / ")[0].trim();
        if (front && !keys.includes(front)) keys.push(front);
      }}
      return keys;
    }}

    function isFoilFinish(finish) {{
      const key = String(finish || "normal").trim().toLowerCase();
      return key === "foil" || key === "etched" || key === "foil etched";
    }}

    function fallbackName(raw) {{
      // Best-effort name when the Moxfield regex does not match.
      let s = String(raw || "").replace(/\\s+#.*$/, "").replace(/\\s+\\*F\\*\\s*$/i, "").trim();
      s = s.replace(/^\\d+\\s+/, "");
      s = s.replace(/\\s+\\([A-Za-z0-9]+\\)\\s+\\S+\\s*$/, "").trim();
      return s || raw;
    }}

    function parseMoxfield(text) {{
      return String(text || "")
        .split(/\\r?\\n/)
        .map((raw) => raw.trim())
        .filter((raw) => raw && !raw.startsWith("//") && !raw.startsWith("#"))
        .filter((raw) => !/^[A-Za-z][A-Za-z\\s]+:\\s*$/.test(raw))
        .map((raw) => {{
          const foil = /\\*\\s*F\\s*\\*/i.test(raw);
          const m = raw.match(MOXFIELD_LINE);
          if (!m) {{
            return {{
              raw,
              qty: 1,
              name: fallbackName(raw),
              set_code: "",
              collector_number: "",
              foil,
              parse_ok: false,
            }};
          }}
          return {{
            raw,
            qty: parseInt(m[1], 10) || 1,
            name: m[2].trim(),
            set_code: m[3].trim().toLowerCase(),
            collector_number: m[4].trim(),
            foil,
            parse_ok: true,
          }};
        }});
    }}

    function matchDeckLine(line) {{
      const wantFoil = !!line.foil;
      let matched = [];
      let quality = "missing";

      if (line.parse_ok && line.set_code && line.collector_number) {{
        const cn = normCn(line.collector_number);
        const samePrint = CARDS.filter(
          (c) =>
            (c.set_code || "").toLowerCase() === line.set_code &&
            normCn(c.collector_number) === cn
        );
        if (samePrint.length) {{
          const preferred = samePrint.filter((c) => isFoilFinish(c.finish) === wantFoil);
          if (preferred.length) {{
            matched = preferred;
            quality = "exact";
          }} else {{
            matched = samePrint;
            quality = "foil_mismatch";
          }}
        }}
      }}

      if (quality === "missing") {{
        const keys = nameKeys(line.name);
        for (const key of keys) {{
          const hits = CARDS.filter((c) => nameKeys(c.name).includes(key));
          if (hits.length) {{
            matched = hits;
            quality = line.parse_ok && line.set_code ? "other_printing" : "name";
            break;
          }}
        }}
        if (quality === "missing" && keys.length) {{
          const front = keys[keys.length - 1];
          const hits = CARDS.filter((c) => {{
            const nk = nameKeys(c.name);
            return nk.some((n) => n === front || n.startsWith(front + " / "));
          }});
          if (hits.length) {{
            matched = hits;
            quality = line.parse_ok && line.set_code ? "other_printing" : "name";
          }}
        }}
      }}

      const qtyHave = matched.reduce((n, c) => n + (c.quantity || 0), 0);
      return {{ line, match: quality, qty_have: qtyHave, cards: matched.slice(0, 6) }};
    }}

    const MATCH_LABELS = {{
      exact: "Exact",
      foil_mismatch: "Finish differs",
      other_printing: "Other printing",
      name: "Name match",
      missing: "Missing",
    }};

    function matchClass(match) {{
      if (match === "exact") return "is-exact";
      if (match === "missing") return "is-missing";
      return "is-close";
    }}

    function runDeckCheck() {{
      const parsed = parseMoxfield(deckEls.text.value);
      if (!parsed.length) {{
        deckRows = [];
        deckEls.summary.textContent = "No card lines found.";
        deckEls.results.hidden = true;
        deckEls.body.innerHTML = "";
        return;
      }}
      deckRows = parsed.map(matchDeckLine);
      renderDeckResults();
    }}

    function renderDeckResults() {{
      const rows = deckRows;
      if (!rows.length) {{
        deckEls.results.hidden = true;
        deckEls.body.innerHTML = "";
        if (deckEls.total) deckEls.total.hidden = true;
        return;
      }}
      const counts = {{
        exact: rows.filter((r) => r.match === "exact").length,
        foil_mismatch: rows.filter((r) => r.match === "foil_mismatch").length,
        other_printing: rows.filter((r) => r.match === "other_printing").length,
        name: rows.filter((r) => r.match === "name").length,
        missing: rows.filter((r) => r.match === "missing").length,
      }};
      const have = counts.exact + counts.foil_mismatch + counts.other_printing + counts.name;
      const hideMissing = !deckEls.hideMissing || deckEls.hideMissing.checked;
      const visible = hideMissing ? rows.filter((r) => r.match !== "missing") : rows;
      let costTotal = 0;
      let costLines = 0;
      let unpriced = 0;
      for (const r of visible) {{
        if (r.match === "missing") continue;
        const cost = deckLineCost(r);
        if (cost) {{
          costTotal += cost.line;
          costLines += 1;
        }} else if (r.cards && r.cards.length) {{
          unpriced += 1;
        }}
      }}
      deckEls.summary.textContent =
        `${{have}} have · ${{counts.missing}} missing · ${{counts.exact}} exact · ` +
        `${{counts.foil_mismatch}} finish ≠ · ${{counts.other_printing + counts.name}} name/other` +
        (hideMissing ? ` · showing ${{visible.length}} (missing hidden)` : "") +
        (costLines ? ` · buy total ${{fmtUsd(costTotal)}}` : "");
      if (deckEls.total) {{
        if (costLines) {{
          deckEls.total.hidden = false;
          deckEls.total.innerHTML =
            `Deck buy total: ${{fmtUsd(costTotal)}}` +
            ` <span>(${{costLines}} priced line${{costLines === 1 ? "" : "s"}}` +
            (unpriced ? ` · ${{unpriced}} unmatched price` : "") +
            ` · qty = min(need, have) × market)</span>`;
        }} else {{
          deckEls.total.hidden = true;
        }}
      }}
      if (deckEls.copy) deckEls.copy.hidden = !(costLines || have);
      deckEls.results.hidden = false;
      if (!visible.length) {{
        deckEls.body.innerHTML = `<tr><td colspan="8" class="deck-lot">No rows to show (all missing are hidden).</td></tr>`;
        return;
      }}
      deckEls.body.innerHTML = visible
        .map((r) => {{
          const line = r.line;
          const lineLabel = line.parse_ok
            ? `${{line.qty}}× ${{line.name}}` +
              (line.set_code ? ` (${{line.set_code.toUpperCase()}})` : "") +
              (line.collector_number ? ` ${{line.collector_number}}` : "") +
              (line.foil ? " ★F" : "")
            : line.raw;
          const hit = r.cards[0];
          const lotLabel = hit
            ? `${{hit.quantity}}× · ${{hit.set_name || (hit.set_code || "").toUpperCase()}}` +
              (hit.collector_number ? ` #${{hit.collector_number}}` : "") +
              (hit.finish ? ` · ${{hit.finish}}` : "") +
              (hit.batch ? ` · ${{hit.batch}}` : "")
            : "—";
          const showBtn = hit
            ? `<button type="button" class="ghost deck-goto" data-name="${{escapeHtml(hit.name || line.name)}}">Show</button>`
            : "";
          const sellBtn =
            hit && hit.id
              ? `<button type="button" class="ghost deck-sell" data-id="${{hit.id}}">Mark sold</button>`
              : "";
          const cost = deckLineCost(r);
          const unitLabel = cost ? fmtUsd(cost.unit) : fmtUsd(cardMarket(hit));
          const lineLabelCost = cost ? fmtUsd(cost.line) : "—";
          const priceCls = cost ? "price" : "price is-missing";
          const tcg = tcgHref(hit);
          const tcgCell = tcg
            ? `<a class="tcg-link" href="${{escapeHtml(tcg)}}" target="_blank" rel="noopener">TCG</a>`
            : "—";
          return `<tr>
            <td>${{escapeHtml(lineLabel)}}</td>
            <td><span class="match ${{matchClass(r.match)}}">${{escapeHtml(MATCH_LABELS[r.match] || r.match)}}</span></td>
            <td class="num">${{r.qty_have}}</td>
            <td class="num">${{line.qty}}</td>
            <td class="num ${{priceCls}}" title="${{cost ? `${{cost.buyQty}}× ${{fmtUsd(cost.unit)}}` : "No market price"}}">${{unitLabel}}</td>
            <td class="num ${{priceCls}}">${{lineLabelCost}}</td>
            <td class="deck-lot">${{escapeHtml(lotLabel)}} ${{showBtn}} ${{sellBtn}}</td>
            <td>${{tcgCell}}</td>
          </tr>`;
        }})
        .join("");
    }}

    deckEls.run.addEventListener("click", runDeckCheck);
    deckEls.hideMissing?.addEventListener("change", renderDeckResults);
    deckEls.copy?.addEventListener("click", copyDeckBuyList);
    els.copyListBtn?.addEventListener("click", copyVisibleInventoryList);
    deckEls.clear.addEventListener("click", () => {{
      deckRows = [];
      deckEls.text.value = "";
      deckEls.summary.textContent = "Paste a list and run check.";
      deckEls.results.hidden = true;
      deckEls.body.innerHTML = "";
      if (deckEls.total) deckEls.total.hidden = true;
      if (deckEls.copy) deckEls.copy.hidden = true;
    }});
    deckEls.body.addEventListener("click", async (e) => {{
      const goto = e.target.closest(".deck-goto");
      if (goto) {{
        els.q.value = goto.dataset.name || "";
        render();
        els.q.focus();
        window.scrollTo({{ top: els.q.getBoundingClientRect().top + window.scrollY - 80, behavior: "smooth" }});
        return;
      }}
      const sell = e.target.closest(".deck-sell");
      if (!sell) return;
      const id = parseInt(sell.dataset.id, 10);
      if (!id) return;
      const card = CARDS.find((c) => c.id === id);
      const label = card ? card.name : `#${{id}}`;
      if (!confirm(`Mark "${{label}}" as sold?`)) return;
      try {{
        const n = await markSoldIds([id]);
        showToast(`Marked ${{n}} sold`);
      }} catch (err) {{
        alert(err.message || String(err));
      }}
    }});

    renderSetOptions();
    render();
  </script>
</body>
</html>
"""
