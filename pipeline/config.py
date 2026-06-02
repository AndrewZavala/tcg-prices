"""Project paths and settings from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root (parent of pipeline/)
PIPELINE_DIR = Path(__file__).resolve().parent
TCG_ROOT = Path(os.environ.get("TCG_ROOT", PIPELINE_DIR.parent)).resolve()

load_dotenv(TCG_ROOT / ".env")

HELPER_DIR = TCG_ROOT / "helper"
BUYLIST_RAW_DIR = TCG_ROOT / os.environ.get("BUYLIST_RAW_DIR", "data/buylist/raw")
BUYLIST_LEGACY_DIR = TCG_ROOT / "Buylist"
BUYLIST_MASTER_DIR = TCG_ROOT / "data" / "buylist" / "master"
BUYLIST_ENRICHED_DIR = TCG_ROOT / "data" / "buylist" / "enriched"
MIGRATIONS_DIR = TCG_ROOT / "migrations"

SCRYFALL_SET_LOOKUP = HELPER_DIR / "scryfall_set_lookup.csv"
CK_SET_ALIASES = HELPER_DIR / "ck_set_aliases.csv"
SCRYFALL_CARDS_LOOKUP = HELPER_DIR / "scryfall_cards_lookup.csv"
SCRYFALL_BULK_JSON = HELPER_DIR / "scryfall_default_cards.json"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tcg:tcg_secret@localhost:5432/tcg_buylist",
)

CK_PRICELIST_URL = "https://api.cardkingdom.com/api/v2/pricelist"
CK_CREDIT_MULTIPLIER = 1.3


def raw_dir_for_date(date_str: str) -> Path:
    return BUYLIST_RAW_DIR / date_str


def ensure_dirs() -> None:
    for d in (
        HELPER_DIR,
        BUYLIST_RAW_DIR,
        BUYLIST_MASTER_DIR,
        BUYLIST_ENRICHED_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
