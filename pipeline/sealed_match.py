#!/usr/bin/env python3
"""Fuzzy-match CK sealed names to TCGCSV sealed product names."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ORDINAL_ED = re.compile(
    r"\b(?:1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|first|second|third|fourth|fifth|"
    r"sixth|seventh|eighth|ninth|tenth)\s+edition\b"
)

_SYNONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bbooster\s+display\b"), "booster box"),
    (re.compile(r"\bcollector\s+booster\s+display\b"), "collector booster box"),
    (re.compile(r"\bplay\s+booster\s+display\b"), "play booster box"),
    (re.compile(r"\bset\s+booster\s+display\b"), "set booster box"),
    (re.compile(r"\bdraft\s+booster\s+display\b"), "draft booster box"),
    (re.compile(r"\bfat\s+pack\b"), "fat pack"),
    (re.compile(r"\bcollectors?\s+edition\s+commander\s+deck\b"), "collector commander deck"),
    (re.compile(r"\bcollector\s+s\s+edition\s+commander\s+deck\b"), "collector commander deck"),
    (re.compile(r"\bnon\s+english\b"), "japanese"),
]

_PRODUCT_TYPES: list[tuple[str, re.Pattern[str]]] = [
    ("collector_commander_deck", re.compile(r"\bcollector(?:\s+s)?\s+(?:edition\s+)?commander\s+deck\b|\bcollector\s+commander\s+deck\b")),
    ("commander_deck", re.compile(r"\bcommander\s+deck\b")),
    ("collector_booster_box", re.compile(r"\bcollector\s+booster\s+(?:box|display)\b")),
    ("collector_booster_pack", re.compile(r"\bcollector\s+booster\s+pack\b")),
    ("play_booster_box", re.compile(r"\bplay\s+booster\s+(?:box|display)\b")),
    ("play_booster_pack", re.compile(r"\bplay\s+booster\s+pack\b")),
    ("set_booster_box", re.compile(r"\bset\s+booster\s+(?:box|display)\b")),
    ("draft_booster_box", re.compile(r"\bdraft\s+booster\s+(?:box|display)\b")),
    ("draft_booster_pack", re.compile(r"\bdraft\s+booster\s+pack\b")),
    ("vip_pack", re.compile(r"\bvip\b")),
    ("gift_bundle", re.compile(r"\bgift\s+bundle\b")),
    ("commanders_bundle", re.compile(r"\bcommander\s*s?\s+bundle\b")),
    ("chocobo_bundle", re.compile(r"\bchocobo\s+bundle\b")),
    ("bundle", re.compile(r"\bbundle\b")),
    ("fat_pack", re.compile(r"\bfat\s+pack\b")),
    ("scene_box", re.compile(r"\bscene\s+box\b")),
    ("starter_kit", re.compile(r"\bstarter\s+kit\b")),
    ("starter_deck_display", re.compile(r"\bstarter\s+deck\s+display\b")),
    ("prerelease_pack", re.compile(r"\bprerelease\b")),
    ("booster_box", re.compile(r"\bbooster\s+(?:box|display)\b")),
    ("booster_pack", re.compile(r"\bbooster\s+pack\b")),
    ("display_case", re.compile(r"\b(?:display|master)\s+case\b")),
]

_STOP = {
    "the", "a", "an", "and", "of", "mtg", "magic", "edition", "set", "core",
    "booster", "box", "display", "pack", "bundle", "deck", "commander",
    "collector", "collectors", "play", "draft", "gift", "fat", "case", "kit",
    "starter", "prerelease", "vii", "xiv", "vi", "x",
}


def normalize_sealed_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    for pat, repl in _SYNONYMS:
        text = pat.sub(repl, text)
    return _WS.sub(" ", text).strip()


def product_type(name: str) -> str | None:
    norm = normalize_sealed_name(name)
    for key, pat in _PRODUCT_TYPES:
        if pat.search(norm):
            return key
    return None


def _years(name: str) -> set[str]:
    return set(_YEAR.findall(normalize_sealed_name(name)))


def _ordinal_edition(name: str) -> str | None:
    m = _ORDINAL_ED.search(normalize_sealed_name(name))
    return m.group(0) if m else None


def _set_tokens(name: str) -> set[str]:
    norm = normalize_sealed_name(name)
    for _, pat in _PRODUCT_TYPES:
        norm = pat.sub(" ", norm)
    tokens = {t for t in norm.split() if t not in _STOP and len(t) > 1 and not t.isdigit()}
    return {t for t in tokens if not _YEAR.fullmatch(t)}


def sealed_name_score(ck_name: str, tcg_name: str) -> float:
    """Return 0..1 similarity with hard constraints on product type / year."""
    a = normalize_sealed_name(ck_name)
    b = normalize_sealed_name(tcg_name)
    if not a or not b:
        return 0.0

    ck_type = product_type(ck_name)
    tcg_type = product_type(tcg_name)
    # Require identical product type when either side is classified.
    if ck_type or tcg_type:
        if ck_type != tcg_type:
            return 0.0

    ck_years, tcg_years = _years(ck_name), _years(tcg_name)
    if ck_years and tcg_years and ck_years.isdisjoint(tcg_years):
        return 0.0
    if ck_years and not tcg_years and not any(y in b for y in ck_years):
        return 0.0
    if tcg_years and not ck_years and not any(y in a for y in tcg_years):
        return 0.0

    ck_ord, tcg_ord = _ordinal_edition(ck_name), _ordinal_edition(tcg_name)
    if ck_ord and tcg_ord and ck_ord != tcg_ord:
        return 0.0

    ta, tb = _set_tokens(ck_name), _set_tokens(tcg_name)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if not inter:
        return 0.0
    jacc = len(inter) / len(ta | tb)
    if jacc < 0.5:
        return 0.0
    if len(inter) / len(ta) < 0.75:
        return 0.0

    if a == b:
        return 1.0
    if a in b or b in a:
        contain = min(len(a), len(b)) / max(len(a), len(b))
        return max(0.92, contain)

    seq = SequenceMatcher(None, a, b).ratio()
    score = 0.35 * seq + 0.65 * jacc
    if ck_type and tcg_type and ck_type == tcg_type:
        score = min(1.0, score + 0.08)
    return score


def best_sealed_match(
    ck_name: str,
    candidates: list[dict],
    *,
    min_score: float,
) -> tuple[dict | None, float]:
    """Pick best TCG sealed product dict for a CK name."""
    best: dict | None = None
    best_score = 0.0
    ck_type = product_type(ck_name)
    for cand in candidates:
        if ck_type and cand.get("_type") and cand["_type"] != ck_type:
            continue
        if ck_type and not cand.get("_type"):
            continue
        if not ck_type and cand.get("_type"):
            continue
        tcg_raw = cand.get("name") or ""
        score = sealed_name_score(ck_name, tcg_raw)
        if score > best_score:
            best_score = score
            best = cand
    if best is None or best_score < min_score:
        return None, best_score
    return best, best_score
