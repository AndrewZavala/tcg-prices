"""Spell Tag user collections (Favorites + custom lists)."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spelltag_auth import PUBLIC_URL, current_user, require_user
from pokemon_api import _image_url
from pokemon_type_sort_sql import COLLECTION_SPECIES_JOINS, build_card_type_sort_sql
from spelltag_cube_import import extract_cube_entries, match_cube_entries

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


class CubeImportPreviewBody(BaseModel):
    cube: dict[str, Any]


class CubeImportBody(BaseModel):
    cube: dict[str, Any]
    collection_id: str | None = None
    new_collection_name: str | None = Field(default=None, max_length=80)


class UpdateCollectionItemTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)


class UpdateCollectionItemBucketBody(BaseModel):
    bucket: str = Field(min_length=1, max_length=16)


class UpdateCollectionBody(BaseModel):
    visibility: str | None = None
    share_slug: str | None = None


_TAG_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHARE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SHAREABLE_VISIBILITIES = frozenset({"unlisted", "public"})
_ITEM_BUCKETS = frozenset({"main", "considering"})


def _normalize_item_bucket(raw: str) -> str:
    val = (raw or "main").strip().lower()
    if val not in _ITEM_BUCKETS:
        raise HTTPException(status_code=400, detail="bucket must be main or considering")
    return val


def _normalize_item_tag(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or len(s) > 32 or not _TAG_SLUG_RE.match(s):
        raise HTTPException(
            status_code=400,
            detail="Tags must be 1–32 characters: lowercase letters, numbers, hyphens",
        )
    return s


def _normalize_item_tags(raw_tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in raw_tags:
        slug = _normalize_item_tag(str(raw))
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    if len(out) > 20:
        raise HTTPException(status_code=400, detail="At most 20 tags per card")
    return out


def _fetch_item_tags(conn, collection_id: str) -> dict[str, list[str]]:
    rows = conn.execute(
        text(
            """
            SELECT card_id, tag_slug
            FROM collection_item_tags
            WHERE collection_id = CAST(:cid AS uuid)
            ORDER BY tag_slug ASC
            """
        ),
        {"cid": collection_id},
    ).mappings().all()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(str(row["card_id"]), []).append(str(row["tag_slug"]))
    return out


def _distinct_collection_card_tags(conn, collection_id: str) -> list[str]:
    return list(
        conn.execute(
            text(
                """
                SELECT DISTINCT tag_slug
                FROM collection_item_tags
                WHERE collection_id = CAST(:cid AS uuid)
                ORDER BY tag_slug ASC
                """
            ),
            {"cid": collection_id},
        ).scalars().all()
    )


def _replace_item_tags(
    conn, collection_id: str, card_id: str, tags: list[str]
) -> list[str]:
    conn.execute(
        text(
            """
            DELETE FROM collection_item_tags
            WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
            """
        ),
        {"cid": collection_id, "card_id": card_id},
    )
    for slug in tags:
        conn.execute(
            text(
                """
                INSERT INTO collection_item_tags (collection_id, card_id, tag_slug)
                VALUES (CAST(:cid AS uuid), :card_id, :slug)
                """
            ),
            {"cid": collection_id, "card_id": card_id, "slug": slug},
        )
    if tags:
        conn.execute(
            text("UPDATE collections SET updated_at = NOW() WHERE id = CAST(:cid AS uuid)"),
            {"cid": collection_id},
        )
    return tags


def _card_sort_clause(sort: str, *, group: str = "none") -> str:
    key = (sort or "saved").lower()
    if key == "type":
        grouped = (group or "none").lower() == "category"
        return build_card_type_sort_sql("pc", include_category_bucket=not grouped)
    if key == "name":
        return "pc.name ASC, pc.id ASC"
    if key == "set":
        return "s.name ASC, pc.local_id ASC, pc.id ASC"
    if key == "number":
        return "pc.local_id ASC, pc.name ASC, pc.id ASC"
    if key == "tag":
        return """COALESCE((
            SELECT MIN(cit.tag_slug)
            FROM collection_item_tags cit
            WHERE cit.collection_id = i.collection_id AND cit.card_id = i.card_id
        ), 'zzz') ASC, pc.name ASC, pc.id ASC"""
    if key in ("shuffle", "random"):
        return "random(), pc.id ASC"
    return "i.created_at DESC, pc.id ASC"


def _card_group_order_clause(group: str) -> str:
    key = (group or "none").lower()
    if key == "category":
        return """CASE pc.category
            WHEN 'Pokemon' THEN 0
            WHEN 'Trainer' THEN 1
            WHEN 'Energy' THEN 2
            ELSE 3
        END,"""
    return ""


def _card_bucket_order_clause(*, split_buckets: bool) -> str:
    if not split_buckets:
        return ""
    return """CASE COALESCE(i.bucket, 'main')
        WHEN 'considering' THEN 1
        ELSE 0
    END,"""


def _card_order_by(sort: str, group: str, *, split_buckets: bool = False) -> str:
    key = (sort or "saved").lower()
    group_key = (group or "none").lower()
    bucket_prefix = _card_bucket_order_clause(split_buckets=split_buckets)
    group_prefix = _card_group_order_clause(group_key) if group_key == "category" else ""
    return f"{bucket_prefix}{group_prefix}{_card_sort_clause(key, group=group_key)}"


def _normalize_visibility(raw: str | None) -> str:
    val = (raw or "private").strip().lower()
    if val not in ("private", "unlisted", "public"):
        raise HTTPException(
            status_code=400,
            detail="visibility must be private, unlisted, or public",
        )
    return val


def _normalize_share_slug(raw: str | None, *, allow_clear: bool = False) -> str | None:
    if raw is None:
        return None
    s = raw.strip().lower()
    if not s:
        if allow_clear:
            return None
        raise HTTPException(status_code=400, detail="Share slug cannot be empty")
    if len(s) < 3 or len(s) > 48 or not _SHARE_SLUG_RE.match(s):
        raise HTTPException(
            status_code=400,
            detail="Share slug must be 3–48 characters: lowercase letters, numbers, hyphens",
        )
    return s


def _public_url(visibility: str, collection_id: str, share_slug: str | None) -> str | None:
    if visibility not in _SHAREABLE_VISIBILITIES:
        return None
    base = (PUBLIC_URL or "").rstrip("/")
    if share_slug:
        return f"{base}/c/{share_slug}"
    return f"{base}/collections/{collection_id}"


def _attach_collection_meta(row: dict[str, Any]) -> dict[str, Any]:
    vis = str(row.get("visibility") or "private")
    cid = str(row.get("id") or "")
    slug = row.get("share_slug")
    row["visibility"] = vis
    row["share_slug"] = slug
    row["public_url"] = _public_url(vis, cid, slug)
    return row


def _collection_select_sql(*, owner_user_id: str | None = None) -> str:
    owner_clause = ""
    if owner_user_id:
        owner_clause = "AND c.user_id = CAST(:uid AS uuid)"
    return f"""
        SELECT
            c.id::text AS id,
            c.name,
            c.kind,
            c.visibility,
            c.share_slug,
            c.created_at::text AS created_at,
            c.updated_at::text AS updated_at
        FROM collections c
        WHERE c.id = CAST(:cid AS uuid)
        {owner_clause}
    """


def _parse_cube_payload(cube: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(cube, dict):
        raise HTTPException(status_code=400, detail="Invalid cube JSON")
    entries = extract_cube_entries(cube)
    if not entries:
        raise HTTPException(
            status_code=400,
            detail="No cards found — expected a CubeKoga / Tabletop Simulator export (ObjectStates → ContainedObjects)",
        )
    if len(entries) > 2000:
        raise HTTPException(status_code=400, detail="Cube too large (max 2000 cards)")
    return entries


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
        text(_collection_select_sql(owner_user_id=user_id)),
        {"cid": collection_id, "uid": user_id},
    ).mappings().first()
    return _attach_collection_meta(dict(row)) if row else None


def _resolve_collection(conn, id_or_slug: str) -> dict[str, Any] | None:
    """Lookup by UUID or share_slug (case-insensitive)."""
    key = (id_or_slug or "").strip()
    if not key:
        return None
    try:
        UUID(key)
        row = conn.execute(
            text(
                """
                SELECT
                    c.id::text AS id,
                    c.user_id::text AS user_id,
                    c.name,
                    c.kind,
                    c.visibility,
                    c.share_slug,
                    c.created_at::text AS created_at,
                    c.updated_at::text AS updated_at,
                    u.name AS owner_name,
                    u.picture_url AS owner_picture_url
                FROM collections c
                INNER JOIN users u ON u.id = c.user_id
                WHERE c.id = CAST(:cid AS uuid)
                """
            ),
            {"cid": key},
        ).mappings().first()
    except ValueError:
        row = conn.execute(
            text(
                """
                SELECT
                    c.id::text AS id,
                    c.user_id::text AS user_id,
                    c.name,
                    c.kind,
                    c.visibility,
                    c.share_slug,
                    c.created_at::text AS created_at,
                    c.updated_at::text AS updated_at,
                    u.name AS owner_name,
                    u.picture_url AS owner_picture_url
                FROM collections c
                INNER JOIN users u ON u.id = c.user_id
                WHERE lower(c.share_slug) = lower(:slug)
                """
            ),
            {"slug": key},
        ).mappings().first()
    if not row:
        return None
    out = dict(row)
    out["owner"] = {
        "name": out.pop("owner_name"),
        "picture_url": out.pop("owner_picture_url"),
    }
    return _attach_collection_meta(out)


def _load_collection_cards(
    conn,
    collection_id: str,
    *,
    sort: str,
    group: str,
    tag_slug: str | None,
    include_tags: bool,
    main_only: bool = False,
    split_buckets: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    order_by = _card_order_by(sort, group, split_buckets=split_buckets)
    needs_species = (sort or "saved").lower() == "type"
    species_joins = COLLECTION_SPECIES_JOINS if needs_species else ""
    tag_filter = ""
    params: dict[str, Any] = {"cid": collection_id}
    if tag_slug:
        tag_filter = """
            AND EXISTS (
                SELECT 1 FROM collection_item_tags cit
                WHERE cit.collection_id = i.collection_id
                  AND cit.card_id = i.card_id
                  AND cit.tag_slug = :tag
            )
        """
        params["tag"] = tag_slug

    bucket_filter = ""
    if main_only:
        bucket_filter = "AND COALESCE(i.bucket, 'main') = 'main'"

    card_tags: dict[str, list[str]] = {}
    known_tags: list[str] = []
    if include_tags:
        card_tags = _fetch_item_tags(conn, collection_id)
        known_tags = _distinct_collection_card_tags(conn, collection_id)

    rows = conn.execute(
        text(
            f"""
            SELECT
                pc.id, pc.name, pc.category, pc.set_id, s.name AS set_name, pc.local_id,
                pc.image_url, pc.image_local, pc.rarity, pc.illustrator,
                s.release_date::text AS release_date,
                i.created_at::text AS saved_at,
                COALESCE(i.bucket, 'main') AS bucket
            FROM collection_items i
            INNER JOIN pokemon_cards pc ON pc.id = i.card_id
            INNER JOIN pokemon_sets s ON s.id = pc.set_id
            {species_joins}
            WHERE i.collection_id = CAST(:cid AS uuid)
            {bucket_filter}
            {tag_filter}
            ORDER BY {order_by}
            """
        ),
        params,
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for c in rows:
        row = dict(c)
        if include_tags:
            row["tags"] = card_tags.get(str(row.get("id") or ""), [])
        remote_base = row.get("image_url")
        local = bool(row.get("image_local"))
        row["image_local"] = local
        row["image_url"] = _image_url(
            remote_base,
            card_id=row.get("id"),
            local_id=row.get("local_id"),
            image_local=local,
            size="low",
        )
        row["image_url_high"] = _image_url(
            remote_base,
            card_id=row.get("id"),
            local_id=row.get("local_id"),
            image_local=local,
            size="high",
        )
        out.append(row)
    return out, known_tags


def _card_exists(conn, card_id: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM pokemon_cards WHERE id = :id LIMIT 1"),
            {"id": card_id},
        ).first()
    )


@router.get("/api/me/collections")
def list_collections(
    request: Request,
    sort: str = Query("name", description="name | count | updated"),
):
    user = require_user(request)
    sort_key = (sort or "name").lower()
    if sort_key not in ("name", "count", "updated"):
        raise HTTPException(status_code=400, detail="sort must be name, count, or updated")

    assert _engine is not None
    with _engine.begin() as conn:
        _ensure_favorites(conn, user["id"])
        order_sql = {
            "name": "CASE WHEN c.kind = 'favorites' THEN 0 ELSE 1 END, c.name ASC",
            "count": "CASE WHEN c.kind = 'favorites' THEN 0 ELSE 1 END, item_count DESC, c.name ASC",
            "updated": "CASE WHEN c.kind = 'favorites' THEN 0 ELSE 1 END, c.updated_at DESC, c.name ASC",
        }[sort_key]
        rows = conn.execute(
            text(
                f"""
                SELECT
                    c.id::text AS id,
                    c.name,
                    c.kind,
                    c.visibility,
                    c.share_slug,
                    c.created_at::text AS created_at,
                    c.updated_at::text AS updated_at,
                    COUNT(i.id)::int AS item_count
                FROM collections c
                LEFT JOIN collection_items i ON i.collection_id = c.id
                WHERE c.user_id = CAST(:uid AS uuid)
                GROUP BY c.id, c.name, c.kind, c.visibility, c.share_slug,
                         c.created_at, c.updated_at
                ORDER BY {order_sql}
                """
            ),
            {"uid": user["id"]},
        ).mappings().all()
    return {
        "collections": [_attach_collection_meta(dict(r)) for r in rows],
        "sort": sort_key,
    }


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
    return {"collection": _attach_collection_meta(dict(row)), "item_count": 0}


@router.patch("/api/me/collections/{collection_id}")
def update_collection(
    request: Request,
    collection_id: str,
    body: UpdateCollectionBody,
):
    user = require_user(request)
    assert _engine is not None
    with _engine.begin() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")

        updates: dict[str, Any] = {}
        if body.visibility is not None:
            vis = _normalize_visibility(body.visibility)
            if coll.get("kind") == "favorites" and vis != "private":
                raise HTTPException(
                    status_code=400,
                    detail="Favorites must stay private",
                )
            updates["visibility"] = vis

        if body.share_slug is not None:
            slug = _normalize_share_slug(body.share_slug, allow_clear=True)
            updates["share_slug"] = slug

        if not updates:
            return {"collection": coll}

        set_parts = []
        params: dict[str, Any] = {"cid": collection_id}
        if "visibility" in updates:
            set_parts.append("visibility = :visibility")
            params["visibility"] = updates["visibility"]
        if "share_slug" in updates:
            set_parts.append("share_slug = :share_slug")
            params["share_slug"] = updates["share_slug"]
        set_parts.append("updated_at = NOW()")

        try:
            row = conn.execute(
                text(
                    f"""
                    UPDATE collections
                    SET {", ".join(set_parts)}
                    WHERE id = CAST(:cid AS uuid)
                    RETURNING
                        id::text AS id,
                        name,
                        kind,
                        visibility,
                        share_slug,
                        created_at::text AS created_at,
                        updated_at::text AS updated_at
                    """
                ),
                params,
            ).mappings().one()
        except Exception as exc:
            if "share_slug" in str(exc).lower() or "unique" in str(exc).lower():
                raise HTTPException(
                    status_code=409,
                    detail="That share link slug is already taken",
                ) from exc
            raise
    return {"collection": _attach_collection_meta(dict(row))}


@router.get("/api/me/collections/{collection_id}/add-context")
def collection_add_context(request: Request, collection_id: str):
    """Lightweight context for bulk-add search UI (name + existing card ids)."""
    user = require_user(request)
    assert _engine is not None
    with _engine.connect() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        card_ids = conn.execute(
            text(
                """
                SELECT card_id
                FROM collection_items
                WHERE collection_id = CAST(:cid AS uuid)
                """
            ),
            {"cid": collection_id},
        ).scalars().all()
    return {
        "collection": coll,
        "card_ids": list(card_ids),
        "item_count": len(card_ids),
    }


@router.get("/api/me/collections/{collection_id}/card-tags")
def list_collection_card_tags(request: Request, collection_id: str):
    user = require_user(request)
    assert _engine is not None
    with _engine.connect() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        tags = _distinct_collection_card_tags(conn, collection_id)
    return {"collection_id": collection_id, "tags": tags}


@router.put("/api/me/collections/{collection_id}/items/{card_id:path}/tags")
def update_collection_item_tags(
    request: Request,
    collection_id: str,
    card_id: str,
    body: UpdateCollectionItemTagsBody,
):
    user = require_user(request)
    tags = _normalize_item_tags(body.tags)
    assert _engine is not None
    with _engine.begin() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        in_collection = conn.execute(
            text(
                """
                SELECT 1 FROM collection_items
                WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
                """
            ),
            {"cid": collection_id, "card_id": card_id},
        ).first()
        if not in_collection:
            raise HTTPException(status_code=404, detail="Card not in this collection")
        saved = _replace_item_tags(conn, collection_id, card_id, tags)
    return {"ok": True, "collection_id": collection_id, "card_id": card_id, "tags": saved}


@router.patch("/api/me/collections/{collection_id}/items/{card_id:path}")
def update_item_bucket(
    request: Request,
    collection_id: str,
    card_id: str,
    body: UpdateCollectionItemBucketBody,
):
    user = require_user(request)
    bucket = _normalize_item_bucket(body.bucket)
    assert _engine is not None
    with _engine.begin() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        if coll.get("kind") == "favorites":
            raise HTTPException(status_code=400, detail="Favorites does not support considering")
        updated = conn.execute(
            text(
                """
                UPDATE collection_items
                SET bucket = :bucket
                WHERE collection_id = CAST(:cid AS uuid) AND card_id = :card_id
                """
            ),
            {"cid": collection_id, "card_id": card_id, "bucket": bucket},
        ).rowcount
        if not updated:
            raise HTTPException(status_code=404, detail="Card not in this collection")
        conn.execute(
            text(
                """
                UPDATE collections SET updated_at = NOW()
                WHERE id = CAST(:cid AS uuid)
                """
            ),
            {"cid": collection_id},
        )
    return {"ok": True, "collection_id": collection_id, "card_id": card_id, "bucket": bucket}


@router.get("/api/me/collections/{collection_id}")
def get_collection(
    request: Request,
    collection_id: str,
    sort: str = Query("saved", description="saved | name | set | number | tag | type | shuffle"),
    group: str = Query("none", description="none | category"),
    tag: str | None = Query(None, description="Filter to cards with this tag"),
):
    user = require_user(request)
    sort_key = (sort or "saved").lower()
    if sort_key == "random":
        sort_key = "shuffle"
    if sort_key not in ("saved", "name", "set", "number", "tag", "type", "shuffle"):
        raise HTTPException(
            status_code=400,
            detail="sort must be saved, name, set, number, tag, type, or shuffle",
        )
    group_key = (group or "none").lower()
    if group_key not in ("none", "category"):
        raise HTTPException(status_code=400, detail="group must be none or category")
    tag_slug = None
    if tag:
        tag_slug = _normalize_item_tag(tag)

    assert _engine is not None
    with _engine.connect() as conn:
        coll = _owned_collection(conn, user["id"], collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")
        cards, known_tags = _load_collection_cards(
            conn,
            collection_id,
            sort=sort_key,
            group=group_key,
            tag_slug=tag_slug,
            include_tags=True,
            main_only=False,
            split_buckets=coll.get("kind") != "favorites",
        )
    return {
        "collection": coll,
        "cards": cards,
        "total": len(cards),
        "sort": sort_key,
        "group": group_key,
        "tag": tag_slug,
        "card_tags": known_tags,
        "is_owner": True,
    }


@router.get("/api/collections/{id_or_slug}")
def get_shared_collection(
    request: Request,
    id_or_slug: str,
    sort: str = Query("saved", description="saved | name | set | number | tag | type | shuffle"),
    group: str = Query("none", description="none | category"),
    tag: str | None = Query(None, description="Filter to cards with this tag (owner only)"),
):
    """Public read for unlisted/public collections; owners see tags when signed in."""
    viewer = current_user(request)
    sort_key = (sort or "saved").lower()
    if sort_key == "random":
        sort_key = "shuffle"
    group_key = (group or "none").lower()
    if group_key not in ("none", "category"):
        raise HTTPException(status_code=400, detail="group must be none or category")

    assert _engine is not None
    with _engine.connect() as conn:
        coll = _resolve_collection(conn, id_or_slug)
        if not coll:
            raise HTTPException(status_code=404, detail="Collection not found")

        is_owner = bool(viewer and str(viewer["id"]) == str(coll.get("user_id")))
        visibility = str(coll.get("visibility") or "private")
        if visibility == "private" and not is_owner:
            raise HTTPException(status_code=404, detail="Collection not found")

        allowed_sorts = (
            ("saved", "name", "set", "number", "tag", "type", "shuffle")
            if is_owner
            else ("saved", "name", "set", "number", "type", "shuffle")
        )
        if sort_key not in allowed_sorts:
            raise HTTPException(
                status_code=400,
                detail=f"sort must be one of: {', '.join(allowed_sorts)}",
            )

        tag_slug = None
        if tag and is_owner:
            tag_slug = _normalize_item_tag(tag)

        public_coll = {k: v for k, v in coll.items() if k != "user_id"}
        cards, known_tags = _load_collection_cards(
            conn,
            str(coll["id"]),
            sort=sort_key,
            group=group_key,
            tag_slug=tag_slug,
            include_tags=is_owner,
            main_only=not is_owner or coll.get("kind") == "favorites",
            split_buckets=False,
        )

    return {
        "collection": public_coll,
        "cards": cards,
        "total": len(cards),
        "sort": sort_key,
        "group": group_key,
        "tag": tag_slug,
        "card_tags": known_tags if is_owner else [],
        "is_owner": is_owner,
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
        result = conn.execute(
            text(
                """
                INSERT INTO collection_items (collection_id, card_id)
                VALUES (CAST(:cid AS uuid), :card_id)
                ON CONFLICT (collection_id, card_id) DO NOTHING
                """
            ),
            {"cid": collection_id, "card_id": card_id},
        )
        added = bool(result.rowcount)
        if added:
            conn.execute(
                text(
                    """
                    UPDATE collections SET updated_at = NOW()
                    WHERE id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": collection_id},
            )
    return {
        "ok": True,
        "added": added,
        "collection_id": collection_id,
        "card_id": card_id,
    }


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


def _bulk_add_cards(conn, collection_id: str, card_ids: list[str]) -> dict[str, int]:
    added = 0
    skipped = 0
    for card_id in card_ids:
        if not _card_exists(conn, card_id):
            skipped += 1
            continue
        result = conn.execute(
            text(
                """
                INSERT INTO collection_items (collection_id, card_id)
                VALUES (CAST(:cid AS uuid), :card_id)
                ON CONFLICT (collection_id, card_id) DO NOTHING
                """
            ),
            {"cid": collection_id, "card_id": card_id},
        )
        if result.rowcount:
            added += 1
        else:
            skipped += 1
    if added:
        conn.execute(
            text("UPDATE collections SET updated_at = NOW() WHERE id = CAST(:cid AS uuid)"),
            {"cid": collection_id},
        )
    return {"added": added, "skipped": skipped}


@router.post("/api/me/collections/import/preview")
def preview_cube_import(request: Request, body: CubeImportPreviewBody):
    user = require_user(request)
    assert _engine is not None
    entries = _parse_cube_payload(body.cube)
    with _engine.connect() as conn:
        preview = match_cube_entries(conn, entries)
    preview["ok"] = True
    return preview


@router.post("/api/me/collections/import")
def import_cube(request: Request, body: CubeImportBody):
    user = require_user(request)
    assert _engine is not None
    entries = _parse_cube_payload(body.cube)
    collection_id = (body.collection_id or "").strip() or None
    new_name = (body.new_collection_name or "").strip() or None

    if collection_id and new_name:
        raise HTTPException(status_code=400, detail="Choose an existing collection or a new name, not both")
    if not collection_id and not new_name:
        raise HTTPException(status_code=400, detail="Select a collection or enter a name for a new one")
    if new_name and new_name.lower() == "favorites":
        raise HTTPException(status_code=400, detail="Favorites is reserved")

    with _engine.begin() as conn:
        _ensure_favorites(conn, user["id"])
        preview = match_cube_entries(conn, entries)
        card_ids = preview.get("card_ids") or []
        if not card_ids:
            raise HTTPException(status_code=400, detail="No cards could be matched in Spell Tag")

        if new_name:
            try:
                row = conn.execute(
                    text(
                        """
                        INSERT INTO collections (user_id, name, kind)
                        VALUES (CAST(:uid AS uuid), :name, 'custom')
                        RETURNING id::text AS id, name, kind
                        """
                    ),
                    {"uid": user["id"], "name": new_name},
                ).mappings().one()
            except Exception as exc:
                raise HTTPException(status_code=409, detail="A collection with that name already exists") from exc
            collection_id = str(row["id"])
            coll = dict(row)
        else:
            assert collection_id is not None
            coll = _owned_collection(conn, user["id"], collection_id)
            if not coll:
                raise HTTPException(status_code=404, detail="Collection not found")

        counts = _bulk_add_cards(conn, collection_id, card_ids)

    return {
        "ok": True,
        "collection": coll,
        "collection_id": collection_id,
        "preview": {
            "total": preview["total"],
            "matched": preview["matched"],
            "unique_matched": preview["unique_matched"],
            "unmatched": preview["unmatched"],
            "duplicate_slots": preview["duplicate_slots"],
        },
        **counts,
    }
