"""Tests for binder layout saves and layout snapshots.

DB tests run against DATABASE_URL inside a transaction that is always rolled back.
"""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import spelltag_collections as sc  # noqa: E402
from spelltag_collections import (  # noqa: E402
    BinderMove,
    _binder_layout,
    _daily_snapshot_label,
    _load_binder_cover,
    _sniff_cover_mime,
    _restore_binder_snapshot,
    _store_binder_snapshot,
    _take_requested_snapshot,
    _validate_binder_moves,
    _write_binder_moves,
)


def _expect_http(status: int, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status, exc
        return
    raise AssertionError(f"expected HTTP {status}")


def test_validate_moves_shapes() -> None:
    out = _validate_binder_moves(
        [
            BinderMove(card_id="a", slot=3),
            BinderMove(card_id="b", x=0.5, y=0.25, z=7),
            BinderMove(card_id="c"),
        ]
    )
    assert out[0] == {"card_id": "a", "slot": 3, "x": None, "y": None, "z": None}
    assert out[1] == {"card_id": "b", "slot": None, "x": 0.5, "y": 0.25, "z": 7}
    assert out[2]["slot"] is None and out[2]["x"] is None


def test_validate_moves_rejects_bad_input() -> None:
    _expect_http(400, _validate_binder_moves, [BinderMove(card_id="a", slot=1, x=0.1, y=0.1)])
    _expect_http(400, _validate_binder_moves, [BinderMove(card_id="a", x=0.1)])
    _expect_http(
        400,
        _validate_binder_moves,
        [BinderMove(card_id="a", slot=1), BinderMove(card_id="a", slot=2)],
    )
    for bad in ({"slot": -1}, {"slot": 10000}, {"x": 1.5, "y": 0.2}):
        try:
            BinderMove(card_id="a", **bad)
            raise AssertionError(f"expected validation error for {bad}")
        except ValidationError:
            pass


def test_daily_label_uses_local_day() -> None:
    utc = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)
    assert _daily_snapshot_label(420, now=utc) == "Before editing on Oct 9"
    assert _daily_snapshot_label(0, now=utc) == "Before editing on Oct 10"


@contextmanager
def _sandbox(card_count: int = 4):
    """Yields (conn, collection_id, card_ids) and rolls everything back afterwards."""
    engine = create_engine(os.environ["DATABASE_URL"])
    conn = engine.connect()
    trans = conn.begin()
    try:
        uid = conn.execute(
            text(
                "INSERT INTO users (google_sub, name) VALUES (:sub, 'binder test') RETURNING id::text"
            ),
            {"sub": f"binder-test-{uuid.uuid4()}"},
        ).scalar_one()
        cid = conn.execute(
            text(
                """
                INSERT INTO collections (user_id, name, kind)
                VALUES (CAST(:uid AS uuid), 'Binder test', 'custom') RETURNING id::text
                """
            ),
            {"uid": uid},
        ).scalar_one()
        card_ids = list(
            conn.execute(
                text("SELECT id FROM pokemon_cards ORDER BY id LIMIT :n"), {"n": card_count}
            ).scalars()
        )
        for i, card_id in enumerate(card_ids):
            conn.execute(
                text(
                    """
                    INSERT INTO collection_items (collection_id, card_id, created_at)
                    VALUES (CAST(:cid AS uuid), :card_id, NOW() + make_interval(secs => :i))
                    """
                ),
                {"cid": cid, "card_id": card_id, "i": i},
            )
        yield conn, cid, card_ids
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


def _slots(conn, cid) -> dict[str, int | None]:
    return {row["card_id"]: row["slot"] for row in _binder_layout(conn, cid)}


def _move(card_id, slot=None, x=None, y=None, z=None):
    return {"card_id": card_id, "slot": slot, "x": x, "y": y, "z": z}


def test_db_swap_in_one_transaction() -> None:
    with _sandbox() as (conn, cid, cards):
        a, b = cards[0], cards[1]
        _write_binder_moves(conn, cid, [_move(a, 0), _move(b, 1)])
        _write_binder_moves(conn, cid, [_move(a, 1), _move(b, 0)])
        assert _slots(conn, cid) == {b: 0, a: 1}


def test_db_table_position_round_trip() -> None:
    with _sandbox() as (conn, cid, cards):
        _write_binder_moves(conn, cid, [_move(cards[0], x=0.4, y=0.6, z=3)])
        row = _binder_layout(conn, cid)[0]
        assert row["slot"] is None and abs(row["x"] - 0.4) < 1e-6 and row["z"] == 3


def test_db_rejects_card_from_other_collection() -> None:
    with _sandbox() as (conn, cid, cards):
        _expect_http(400, _write_binder_moves, conn, cid, [_move("not-in-collection-xyz", 0)])
        conn.execute(
            text(
                "UPDATE collection_items SET bucket = 'considering' "
                "WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card"
            ),
            {"cid": cid, "card": cards[0]},
        )
        _expect_http(400, _write_binder_moves, conn, cid, [_move(cards[0], 0)])


def test_db_pocket_clash_is_409() -> None:
    with _sandbox() as (conn, cid, cards):
        _write_binder_moves(conn, cid, [_move(cards[0], 0)])
        nested = conn.begin_nested()
        _expect_http(409, _write_binder_moves, conn, cid, [_move(cards[1], 0)])
        nested.rollback()


def test_db_daily_snapshot_once_per_day() -> None:
    with _sandbox() as (conn, cid, cards):
        assert _take_requested_snapshot(conn, cid, "auto-daily", label=None, tz_offset_minutes=0) is None
        _write_binder_moves(conn, cid, [_move(cards[0], 0)])
        first = _take_requested_snapshot(conn, cid, "auto-daily", label=None, tz_offset_minutes=0)
        second = _take_requested_snapshot(conn, cid, "auto-daily", label=None, tz_offset_minutes=0)
        assert first and second is None
        assert _take_requested_snapshot(
            conn, cid, "before-arrange", label="Before arranging by Type", tz_offset_minutes=0
        )
        _expect_http(400, _take_requested_snapshot, conn, cid, "bogus", label=None, tz_offset_minutes=0)


def test_db_auto_snapshots_trimmed() -> None:
    with _sandbox() as (conn, cid, cards):
        _write_binder_moves(conn, cid, [_move(cards[0], 0)])
        for i in range(sc.BINDER_AUTO_SNAPSHOT_KEEP + 3):
            _store_binder_snapshot(conn, cid, f"auto {i}", is_auto=True)
        _store_binder_snapshot(conn, cid, "named", is_auto=False)
        counts = dict(
            conn.execute(
                text(
                    "SELECT is_auto, COUNT(*) FROM collection_binder_snapshots "
                    "WHERE collection_id = CAST(:cid AS uuid) GROUP BY is_auto"
                ),
                {"cid": cid},
            ).all()
        )
        assert counts == {True: sc.BINDER_AUTO_SNAPSHOT_KEEP, False: 1}


def test_db_restore_handles_added_and_removed_cards() -> None:
    with _sandbox(card_count=5) as (conn, cid, cards):
        a, b, c, d, e = cards
        conn.execute(
            text(
                "DELETE FROM collection_items WHERE collection_id = CAST(:cid AS uuid) AND card_id = :e"
            ),
            {"cid": cid, "e": e},
        )
        _write_binder_moves(conn, cid, [_move(a, 5), _move(b, 0), _move(c, x=0.2, y=0.3, z=1)])
        snap = _store_binder_snapshot(conn, cid, "custom", is_auto=False)

        _write_binder_moves(conn, cid, [_move(a, 0), _move(b, 1), _move(c, 2), _move(d, 3)])
        conn.execute(
            text(
                "DELETE FROM collection_items WHERE collection_id = CAST(:cid AS uuid) AND card_id = :b"
            ),
            {"cid": cid, "b": b},
        )
        conn.execute(
            text(
                "INSERT INTO collection_items (collection_id, card_id) VALUES (CAST(:cid AS uuid), :e)"
            ),
            {"cid": cid, "e": e},
        )

        result = _restore_binder_snapshot(conn, cid, snap)
        layout = {row["card_id"]: row for row in result["layout"]}
        assert layout[a]["slot"] == 5
        assert layout[c]["slot"] is None and abs(layout[c]["x"] - 0.2) < 1e-6
        assert b not in layout
        assert {layout[d]["slot"], layout[e]["slot"]} == {6, 7}
        assert result["backup_snapshot_id"]
        _expect_http(404, _restore_binder_snapshot, conn, cid, str(uuid.uuid4()))


def test_sniff_cover_mime() -> None:
    assert _sniff_cover_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert _sniff_cover_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert _sniff_cover_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert _sniff_cover_mime(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert _sniff_cover_mime(b"GIF89a") is None


def test_db_cover_card_image_and_removed_card() -> None:
    with _sandbox(card_count=2) as (conn, cid, cards):
        a, b = cards
        assert _load_binder_cover(conn, cid) is None
        conn.execute(
            text("INSERT INTO collection_binder_covers (collection_id, card_id) VALUES (CAST(:cid AS uuid), :c)"),
            {"cid": cid, "c": a},
        )
        cover = _load_binder_cover(conn, cid)
        assert cover["type"] == "card" and cover["card_id"] == a and cover["image_url"]
        conn.execute(
            text("DELETE FROM collection_items WHERE collection_id = CAST(:cid AS uuid) AND card_id = :c"),
            {"cid": cid, "c": a},
        )
        assert _load_binder_cover(conn, cid) is None
        conn.execute(
            text(
                """
                UPDATE collection_binder_covers
                SET card_id = NULL, image = :img, image_mime = 'image/jpeg'
                WHERE collection_id = CAST(:cid AS uuid)
                """
            ),
            {"cid": cid, "img": b"\xff\xd8\xff\xe0"},
        )
        cover = _load_binder_cover(conn, cid)
        assert cover["type"] == "image"
        assert cover["image_url"].startswith(f"/api/collections/{cid}/binder/cover?v=")
        nested = conn.begin_nested()
        try:
            conn.execute(
                text("UPDATE collection_binder_covers SET card_id = :c WHERE collection_id = CAST(:cid AS uuid)"),
                {"cid": cid, "c": b},
            )
            raise AssertionError("expected the one-source check to fail")
        except IntegrityError:
            nested.rollback()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        if fn.__name__.startswith("test_db_") and not os.environ.get("DATABASE_URL"):
            print(f"skip {fn.__name__} (no DATABASE_URL)")
            continue
        fn()
    print("ok")
