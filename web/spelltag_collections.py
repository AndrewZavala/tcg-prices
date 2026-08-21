"""Spell Tag user collections (Favorites + custom lists)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spelltag_auth import require_user

router = APIRouter(tags=["collections"])

_engine: Engine | None = None


def init_spelltag_collections(engine: Engine) -> None:
    global _engine
    _engine = engine


class CreateCollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AddItemBody(BaseModel):
    card_id: str = Field(min_length=1, max_length=64)


class ToggleFavoriteBody(BaseModel):
    card_id: str = Field(min_length=1, max_length=64)


def _ensure_favorites(conn, user_id: str) -> str:
    existing = conn.execute(
        text(
            """
            SELECT id::text AS id FROM collections
            WHERE user_id = CAST(:uid AS uuid) AND kind = 'favorites'
            LIMIT 1
            """
        ),
        {"uid": user_id},
    ).mappings().first()
    if existing:
        return str(existing["id"])
    created = conn.execute(
        text(
            """
            INSERT INTO collections (user_id, name, kind)
            VALUES (CAST(:uid AS uuid), 'Favorites', 'favorites')
            RETURNING id::text AS id
            """
        ),
        {"uid": user_id},
    ).mappings().one()
    return str(created["id"])


def _owned_collection(conn, user_id: str, collection_id: str) -> dict[str, Any] | None:
    try:
        UUID(collection_id)
    except ValueError:
        return None
    row = conn.execute(
        text(
            """
            SELECT id::text AS id, name, kind, created_at::text AS created_at
            FROM collections
            WHERE id = CAST(:cid AS uuid) AND user_id = CAST(:uid AS uuid)
            """
        ),
        {"cid": collection_id, "uid": user_id},
    ).mappings().first()
    return dict(row) if row else None


def _card_exists(conn, card_id: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM pokemon_cards WHERE id = :id LIMIT 1"),
            {"id": card_id},
        ).first()
    )


@router.get("/api/me/collections")
def list_collections(request: Request):
    user = require_user(request)
    assert _engine is not None
    with _engine.begin() as conn:
        _ensure_favorites(conn, user["id"])
        rows = conn.execute(
            text(
                """
                SELECT
                    c.id::text AS id,
                    c.name,
                    c.kind,
                    c.created_at::text AS created_at,
                    COUNT(i.id)::int AS item_count
                FROM collections c
                LEFT JOIN collection_items i ON i.collection_id = c.id
                WHERE c.user_id = CAST(:uid AS uuid)
                GROUP BY c.id, c.name, c.kind, c.created_at
                ORDER BY
                    CASE WHEN c.kind = 'favorites' THEN 0 ELSE 1 END,
                    c.name ASC
                """
            ),
            {"uid": user["id"]},
        ).mappings().all()
    return {"collections": [dict(r) for r in rows]}


@router.post("/api/me/collections")
def create_collection(request: Request, body: CreateCollectionBody):
    user = require_user(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    if name.lower() == "favorites":
        raise HTTPException(status_code=400, detail="Favorites is reserved; use the Favorites collection")
    assert _engine is not None
    with _engine.begin() as conn:
        _ensure_favorites(conn, user["id"])
        try:
            row = conn.execute(
                text(
                    """
                    INSERT INTO collections (user_id, name, kind)
                    VALUES (CAST(:uid AS uuid), :name, 'custom')
                    RETURNING id::text AS id, name, kind, created_at::text AS created_at
                    """
                ),
                {"uid": user["id"], "name": name},
            ).mappings().one()
        except Exception as exc:
            raise HTTPException(status_code=409, detail="A collection with that name already exists") from exc
    return {"collection": dict(row), "item_count": 0}


@router.get("/api/me/collections/{collection_id}")
def get_collection(request: Request, collection_id: str):
    user = require_user(request)
    assert _engine is not None
    with _engine.connect() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        cards = conn.execute(
            text(
                """
                SELECT
                    pc.id, pc.name, pc.set_id, s.name AS set_name, pc.local_id,
                    pc.image_url, pc.rarity, pc.illustrator,
                    i.created_at::text AS saved_at
                FROM collection_items i
                INNER JOIN pokemon_cards pc ON pc.id = i.card_id
                INNER JOIN pokemon_sets s ON s.id = pc.set_id
                WHERE i.collection_id = CAST(:cid AS uuid)
                ORDER BY i.created_at DESC
                """
            ),
            {"cid": collection_id},
        ).mappings().all()
    return {
        "collection": coll,
        "cards": [dict(c) for c in cards],
        "total": len(cards),
    }


@router.post("/api/me/collections/{collection_id}/items")
def add_item(request: Request, collection_id: str, body: AddItemBody):
    user = require_user(request)
    card_id = body.card_id.strip()
    assert _engine is not None
    with _engine.begin() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        if not _card_exists(conn, card_id):
            raise HTTPException(status_code=404, detail="Card not found")
        conn.execute(
            text(
                """
                INSERT INTO collection_items (collection_id, card_id)
                VALUES (CAST(:cid AS uuid), :card_id)
                ON CONFLICT (collection_id, card_id) DO NOTHING
                """
            ),
            {"cid": collection_id, "card_id": card_id},
        )
        conn.execute(
            text(
                """
                UPDATE collections SET updated_at = NOW()
                WHERE id = CAST(:cid AS uuid)
                """
            ),
            {"cid": collection_id},
        )
    return {"ok": True, "collection_id": collection_id, "card_id": card_id}


@router.delete("/api/me/collections/{collection_id}/items/{card_id:path}")
def remove_item(request: Request, collection_id: str, card_id: str):
    user = require_user(request)
    assert _engine is not None
    with _engine.begin() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        conn.execute(
            text(
                """
                DELETE FROM collection_items
                WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
                """
            ),
            {"cid": collection_id, "card_id": card_id},
        )
    return {"ok": True}


@router.get("/api/me/cards/{card_id:path}/memberships")
def card_memberships(request: Request, card_id: str):
    user = require_user(request)
    assert _engine is not None
    with _engine.begin() as conn:
        fav_id = _ensure_favorites(conn, user["id"])
        rows = conn.execute(
            text(
                """
                SELECT
                    c.id::text AS id,
                    c.name,
                    c.kind,
                    EXISTS (
                        SELECT 1 FROM collection_items i
                        WHERE i.collection_id = c.id AND i.card_id = :card_id
                    ) AS contains
                FROM collections c
                WHERE c.user_id = CAST(:uid AS uuid)
                ORDER BY
                    CASE WHEN c.kind = 'favorites' THEN 0 ELSE 1 END,
                    c.name ASC
                """
            ),
            {"uid": user["id"], "card_id": card_id},
        ).mappings().all()
    return {
        "favorites_id": fav_id,
        "collections": [
            {
                "id": r["id"],
                "name": r["name"],
                "kind": r["kind"],
                "contains": bool(r["contains"]),
            }
            for r in rows
        ],
    }


@router.post("/api/me/favorites/toggle")
def toggle_favorite(request: Request, body: ToggleFavoriteBody):
    user = require_user(request)
    card_id = body.card_id.strip()
    assert _engine is not None
    with _engine.begin() as conn:
        fav_id = _ensure_favorites(conn, user["id"])
        if not _card_exists(conn, card_id):
            raise HTTPException(status_code=404, detail="Card not found")
        existing = conn.execute(
            text(
                """
                SELECT 1 FROM collection_items
                WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
                """
            ),
            {"cid": fav_id, "card_id": card_id},
        ).first()
        if existing:
            conn.execute(
                text(
                    """
                    DELETE FROM collection_items
                    WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
                    """
                ),
                {"cid": fav_id, "card_id": card_id},
            )
            favorited = False
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO collection_items (collection_id, card_id)
                    VALUES (CAST(:cid AS uuid), :card_id)
                    """
                ),
                {"cid": fav_id, "card_id": card_id},
            )
            favorited = True
        conn.execute(
            text("UPDATE collections SET updated_at = NOW() WHERE id = CAST(:cid AS uuid)"),
            {"cid": fav_id},
        )
    return {"ok": True, "favorited": favorited, "favorites_id": fav_id, "card_id": card_id}
