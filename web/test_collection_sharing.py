"""Unit tests for collection visibility and share helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException

from spelltag_collections import (  # noqa: E402
    _card_group_order_clause,
    _card_order_by,
    _normalize_share_slug,
    _normalize_visibility,
    _public_url,
)


def test_normalize_visibility_values() -> None:
    assert _normalize_visibility("public") == "public"
    assert _normalize_visibility("unlisted") == "unlisted"
    assert _normalize_visibility("private") == "private"


def test_normalize_share_slug() -> None:
    assert _normalize_share_slug("My-Cube") == "my-cube"
    assert _normalize_share_slug("", allow_clear=True) is None


def test_normalize_visibility_rejects_invalid() -> None:
    try:
        _normalize_visibility("hidden")
        raise AssertionError("expected HTTPException")
    except HTTPException:
        pass


def test_normalize_share_slug_rejects_short() -> None:
    try:
        _normalize_share_slug("ab")
        raise AssertionError("expected HTTPException")
    except HTTPException:
        pass


def test_public_url_private() -> None:
    assert _public_url("private", "uuid", "slug") is None


def test_public_url_unlisted_with_slug() -> None:
    url = _public_url("unlisted", "uuid", "my-cube")
    assert url is not None
    assert url.endswith("/c/my-cube")


def test_group_order_category() -> None:
    clause = _card_group_order_clause("category")
    assert "Pokemon" in clause
    assert "Trainer" in clause


def test_order_by_group_then_sort() -> None:
    sql = _card_order_by("set", "category")
    assert sql.startswith("CASE pc.category")
    assert "s.name ASC" in sql


def test_order_by_shuffle() -> None:
    sql = _card_order_by("shuffle", "none")
    assert "random()" in sql


if __name__ == "__main__":
    test_normalize_visibility_values()
    test_normalize_visibility_rejects_invalid()
    test_normalize_share_slug()
    test_normalize_share_slug_rejects_short()
    test_public_url_private()
    test_public_url_unlisted_with_slug()
    test_group_order_category()
    test_order_by_group_then_sort()
    test_order_by_shuffle()
    print("ok")
