"""Tests for Limitless decklist detection in refresh_limitless_decklists."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_limitless_decklists import (  # noqa: E402
    decklist_status,
    limitless_card_url,
    needs_check,
)


def _p(flag, *, standard=True) -> dict:
    return {"limitless_decklists": flag, "is_standard": standard}


def test_limitless_card_url() -> None:
    assert limitless_card_url("asc", "196") == "https://limitlesstcg.com/cards/ASC/196"
    assert limitless_card_url("PAL", "082") == "https://limitlesstcg.com/cards/PAL/82"
    assert limitless_card_url("SVP", "SVP001") == "https://limitlesstcg.com/cards/SVP/SVP001"
    assert limitless_card_url("", "1") is None


def test_decklist_status() -> None:
    assert decklist_status("This card does not appear in any decklist from our main database.") is False
    assert decklist_status('<a href="/decks/list/12345">Clefairy Ogerpon</a>') is True
    assert decklist_status("<html>Not found</html>") is None


def test_needs_check_standard_only() -> None:
    assert needs_check([_p(None)], recheck_all=False)
    assert needs_check([_p(False)], recheck_all=False)
    assert not needs_check([_p(True)], recheck_all=False)
    assert needs_check([_p(True)], recheck_all=True)
    assert not needs_check([_p(None, standard=False)], recheck_all=True)


def test_reprint_of_standard_card_is_checked() -> None:
    assert needs_check([_p(None, standard=False), _p(None, standard=True)], recheck_all=False)
    assert needs_check([_p(True, standard=False), _p(None, standard=True)], recheck_all=False)
