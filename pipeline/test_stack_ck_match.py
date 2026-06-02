#!/usr/bin/env python3
"""Compare Stacks inventory CSVs against CK buylist API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import requests

from config import BUYLIST_RAW_DIR, CK_PRICELIST_URL, TCG_ROOT, ensure_dirs

STACKS_DIR = TCG_ROOT / "Stacks"
FINISH_TO_FOIL = {"normal": False, "nonfoil": False, "foil": True, "etched": None}


def load_ck_buylist() -> pd.DataFrame:
    today_dirs = sorted(BUYLIST_RAW_DIR.glob("*"), reverse=True)
    for d in today_dirs:
        cached = d / "pricelist.json"
        if cached.is_file():
            print(f"Using cached {cached}")
            payload = json.loads(cached.read_text(encoding="utf-8"))
            return _buylist_from_payload(payload)

    print(f"Fetching {CK_PRICELIST_URL}...")
    payload = requests.get(CK_PRICELIST_URL, timeout=300).json()
    return _buylist_from_payload(payload)


def _buylist_from_payload(payload: dict) -> pd.DataFrame:
    rows = []
    for item in payload.get("data") or []:
        qty = int(item.get("qty_buying") or 0)
        cash = float(item.get("price_buy") or 0)
        if qty <= 0 or cash <= 0:
            continue
        is_foil = str(item.get("is_foil", "")).lower() in ("true", "1", "yes")
        etched = "etched" in (item.get("name") or "").lower() or "etched" in (
            item.get("variation") or ""
        ).lower()
        rows.append(
            {
                "scryfall_id": str(item.get("scryfall_id") or "").strip().lower(),
                "is_foil": is_foil,
                "is_etched": etched,
                "cash_price": cash,
                "credit_price": round(cash * 1.3, 2),
                "max_qty": qty,
                "name": item.get("name"),
                "edition": item.get("edition"),
                "product_id": str(item.get("id", "")),
            }
        )
    return pd.DataFrame(rows)


def load_stacks(batch_limit: int | None = None) -> pd.DataFrame:
    files = sorted(STACKS_DIR.glob("Batch*_export.csv"))
    if batch_limit:
        files = files[-batch_limit:]
    frames = []
    for path in files:
        df = pd.read_csv(path, low_memory=False)
        df["batch_file"] = path.name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No stack CSVs in {STACKS_DIR}")
    out = pd.concat(frames, ignore_index=True)
    out = out.rename(columns={
        "Scryfall ID": "scryfall_id",
        "Set code": "set_code",
        "Collector number": "collector_number",
        "Finish": "finish",
        "Name": "name",
    })
    out["scryfall_id"] = out["scryfall_id"].astype(str).str.strip().str.lower()
    out["finish"] = out["finish"].astype(str).str.strip().str.lower()
    out = out[out["scryfall_id"].notna() & (out["scryfall_id"] != "")]
    return out


def _finish_match(stack_finish: str, ck_row: pd.Series) -> bool:
    if stack_finish == "etched":
        return bool(ck_row.get("is_etched"))
    if stack_finish in ("foil",):
        return bool(ck_row["is_foil"]) and not bool(ck_row.get("is_etched"))
    if stack_finish in ("normal", "nonfoil"):
        return not bool(ck_row["is_foil"])
    return not bool(ck_row["is_foil"])


def compare(stacks: pd.DataFrame, ck: pd.DataFrame) -> pd.DataFrame:
    ck_by_id = ck.groupby("scryfall_id", dropna=False)

    results = []
    for _, row in stacks.iterrows():
        sid = row["scryfall_id"]
        finish = row["finish"]
        if sid not in ck_by_id.groups:
            results.append(
                {
                    **row.to_dict(),
                    "ck_match": "no_scryfall_id",
                    "ck_cash_price": None,
                    "ck_credit_price": None,
                    "ck_max_qty": None,
                }
            )
            continue

        candidates = ck_by_id.get_group(sid)
        matched = candidates[candidates.apply(lambda r: _finish_match(finish, r), axis=1)]
        if matched.empty:
            any_buying = candidates.iloc[0]
            results.append(
                {
                    **row.to_dict(),
                    "ck_match": "id_only_wrong_finish",
                    "ck_cash_price": any_buying["cash_price"],
                    "ck_credit_price": any_buying["credit_price"],
                    "ck_max_qty": any_buying["max_qty"],
                    "ck_edition": any_buying["edition"],
                }
            )
        else:
            best = matched.iloc[0]
            results.append(
                {
                    **row.to_dict(),
                    "ck_match": "matched",
                    "ck_cash_price": best["cash_price"],
                    "ck_credit_price": best["credit_price"],
                    "ck_max_qty": best["max_qty"],
                    "ck_edition": best["edition"],
                }
            )
    return pd.DataFrame(results)


def main() -> int:
    ensure_dirs()
    batch_limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    stacks = load_stacks(batch_limit=batch_limit)
    ck = load_ck_buylist()

    print(f"\nStacks: {len(stacks)} rows from last {batch_limit} batch files")
    print(f"Unique cards (scryfall_id+finish): {stacks.groupby(['scryfall_id','finish']).ngroups}")
    print(f"CK buylist rows: {len(ck)}")
    print(f"CK unique scryfall_ids: {ck['scryfall_id'].nunique()}")

    result = compare(stacks, ck)
    counts = result["ck_match"].value_counts()
    print("\n--- Match breakdown ---")
    for status, n in counts.items():
        print(f"  {status}: {n} ({100*n/len(result):.1f}%)")

    matched = result[result["ck_match"] == "matched"]
    if len(matched) > 0:
        print(f"\nMatched cards CK cash total (sum): ${matched['ck_cash_price'].sum():,.2f}")
        print(f"Matched cards CK credit total (sum): ${matched['ck_credit_price'].sum():,.2f}")

    out = TCG_ROOT / "data" / "stack_ck_match_report.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out, index=False)
    print(f"\nWrote detail report to {out}")

    wrong = result[result["ck_match"] != "matched"].head(20)
    if len(wrong) > 0:
        print("\n--- Sample non-matches (first 20) ---")
        cols = ["batch_file", "name", "set_code", "finish", "scryfall_id", "ck_match"]
        print(wrong[cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
