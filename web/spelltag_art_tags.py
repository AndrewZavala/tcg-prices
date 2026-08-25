"""Spell Tag curated art tags (art: search) — keyed by illustration_id."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spelltag_auth import require_admin, require_tagger
from spelltag_tag_tree import (
    assert_valid_parent,
    enrich_tags_with_inheritance,
    expand_search_slugs,
)

router = APIRouter(tags=["art-tags"])

_engine: Engine | None = None
DEFS_TABLE = "art_tag_defs"

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def init_spelltag_art_tags(engine: Engine) -> None:
    global _engine
    _engine = engine


class CreateTagDefBody(BaseModel):
    """Accept either a display name or a kebab slug (or both)."""

    slug: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=80)
    name: str | None = Field(
        default=None,
        max_length=80,
        description="Either 'Night Sky' or 'night-sky' — slug/label derived automatically",
    )
    description: str | None = Field(default=None, max_length=400)
    parent_slug: str | None = Field(
        default=None,
        max_length=80,
        description="Optional parent tag slug (subtag under that parent)",
    )


class PatchTagDefBody(BaseModel):
    label: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    active: bool | None = None
    parent_slug: str | None = Field(
        default=None,
        max_length=80,
        description="Set parent; empty string clears parent",
    )


class SetArtTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


def _normalize_slug(raw: str) -> str:
    slug = (raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _label_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _looks_like_slug(raw: str) -> bool:
    s = (raw or "").strip()
    if not s or " " in s:
        return False
    return bool(SLUG_RE.match(s.lower().replace("_", "-")))


def _resolve_slug_and_label(
    *,
    slug: str | None,
    label: str | None,
    name: str | None = None,
) -> tuple[str, str]:
    raw_slug = (slug or "").strip()
    raw_label = (label or "").strip()
    raw_name = (name or "").strip()

    if raw_name and not raw_slug and not raw_label:
        if _looks_like_slug(raw_name):
            raw_slug = raw_name
        else:
            raw_label = raw_name

    if raw_slug and not _looks_like_slug(raw_slug) and not raw_label:
        raw_label = raw_slug
        raw_slug = ""

    if raw_label and _looks_like_slug(raw_label) and not raw_slug:
        raw_slug = raw_label
        raw_label = ""

    out_slug = _normalize_slug(raw_slug or raw_label)
    if not out_slug or not SLUG_RE.match(out_slug):
        raise HTTPException(
            status_code=400,
            detail="Enter a name like Night Sky or a slug like night-sky",
        )

    if raw_label and not _looks_like_slug(raw_label):
        out_label = raw_label
    else:
        out_label = _label_from_slug(out_slug)

    if len(out_label) > 80:
        raise HTTPException(status_code=400, detail="Label is too long")
    return out_slug, out_label


def fetch_art_tags_for_illustrations(
    conn, illustration_ids: list[str], *, with_inherited: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """Return {illustration_id: [{slug, label, inherited?}, ...]} for active tags only."""
    ids = [iid for iid in dict.fromkeys(illustration_ids) if iid]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT at.illustration_id, d.slug, d.label, d.parent_slug
            FROM art_tags at
            INNER JOIN art_tag_defs d ON d.slug = at.tag_slug
            WHERE at.illustration_id = ANY(:iids)
              AND d.active = TRUE
            ORDER BY d.label, d.slug
            """
        ),
        {"iids": ids},
    ).mappings().all()
    explicit: dict[str, list[dict[str, str]]] = {iid: [] for iid in ids}
    for row in rows:
        explicit.setdefault(str(row["illustration_id"]), []).append(
            {"slug": str(row["slug"]), "label": str(row["label"])}
        )
    if not with_inherited:
        return explicit  # type: ignore[return-value]
    out: dict[str, list[dict[str, Any]]] = {}
    for iid, tags in explicit.items():
        out[iid] = enrich_tags_with_inheritance(
            conn, tags, defs_table=DEFS_TABLE
        )
    return out


def expand_art_search_slugs(conn, slugs: list[str]) -> list[str]:
    return expand_search_slugs(conn, slugs, defs_table=DEFS_TABLE)


def _card_illustration_id(conn, card_id: str) -> tuple[str, str]:
    row = conn.execute(
        text(
            """
            SELECT id, illustration_id
            FROM pokemon_cards
            WHERE lower(id) = lower(:id)
            """
        ),
        {"id": card_id.strip()},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    illustration_id = row.get("illustration_id")
    if not illustration_id:
        raise HTTPException(
            status_code=400,
            detail="Card has no illustration id yet; cannot attach art tags",
        )
    return str(row["id"]), str(illustration_id)


@router.get("/api/art-tags")
def list_art_tag_defs(active_only: bool = True) -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        if active_only:
            rows = conn.execute(
                text(
                    """
                    SELECT slug, label, description, parent_slug, active,
                           created_at::text AS created_at
                    FROM art_tag_defs
                    WHERE active = TRUE
                    ORDER BY label, slug
                    """
                )
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT slug, label, description, parent_slug, active,
                           created_at::text AS created_at
                    FROM art_tag_defs
                    ORDER BY active DESC, label, slug
                    """
                )
            ).mappings().all()
    return {"tags": [dict(r) for r in rows]}


@router.post("/api/art-tags")
def create_art_tag_def(request: Request, body: CreateTagDefBody) -> dict[str, Any]:
    user = require_tagger(request)
    slug, label = _resolve_slug_and_label(
        slug=body.slug,
        label=body.label,
        name=body.name,
    )
    assert _engine is not None
    with _engine.begin() as conn:
        parent = assert_valid_parent(
            conn,
            defs_table=DEFS_TABLE,
            parent_slug=body.parent_slug,
            child_slug=slug,
        )
        if parent and not slug.startswith(parent + "-") and slug != parent:
            candidate = f"{parent}-{slug}"
            if SLUG_RE.match(candidate) and len(candidate) <= 80:
                slug = candidate
        existing = conn.execute(
            text("SELECT 1 FROM art_tag_defs WHERE slug = :slug"),
            {"slug": slug},
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tag already exists")
        row = conn.execute(
            text(
                """
                INSERT INTO art_tag_defs (slug, label, description, created_by, parent_slug)
                VALUES (
                    :slug,
                    :label,
                    :description,
                    CAST(:uid AS uuid),
                    :parent
                )
                RETURNING slug, label, description, parent_slug, active,
                          created_at::text AS created_at
                """
            ),
            {
                "slug": slug,
                "label": label,
                "description": (body.description or "").strip() or None,
                "uid": user["id"],
                "parent": parent,
            },
        ).mappings().one()
    return dict(row)


@router.patch("/api/art-tags/{slug}")
def patch_art_tag_def(
    request: Request, slug: str, body: PatchTagDefBody
) -> dict[str, Any]:
    require_admin(request)
    slug_n = _normalize_slug(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        current = conn.execute(
            text(
                """
                SELECT slug, label, description, active, parent_slug
                FROM art_tag_defs WHERE slug = :slug
                """
            ),
            {"slug": slug_n},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Tag not found")
        label = current["label"] if body.label is None else body.label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label required")
        description = (
            current["description"]
            if body.description is None
            else ((body.description or "").strip() or None)
        )
        active = current["active"] if body.active is None else bool(body.active)
        if body.parent_slug is None:
            parent = current.get("parent_slug")
        elif body.parent_slug.strip() == "":
            parent = None
        else:
            parent = assert_valid_parent(
                conn,
                defs_table=DEFS_TABLE,
                parent_slug=body.parent_slug,
                child_slug=slug_n,
            )
        row = conn.execute(
            text(
                """
                UPDATE art_tag_defs
                SET label = :label,
                    description = :description,
                    active = :active,
                    parent_slug = :parent
                WHERE slug = :slug
                RETURNING slug, label, description, parent_slug, active,
                          created_at::text AS created_at
                """
            ),
            {
                "slug": slug_n,
                "label": label,
                "description": description,
                "active": active,
                "parent": parent,
            },
        ).mappings().one()
    return dict(row)


@router.get("/api/pokemon/cards/{card_id}/art-tags")
def get_card_art_tags(card_id: str) -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        _card_id, illustration_id = _card_illustration_id(conn, card_id)
        tags = fetch_art_tags_for_illustrations(conn, [illustration_id]).get(
            illustration_id, []
        )
    return {
        "card_id": _card_id,
        "illustration_id": illustration_id,
        "tags": tags,
    }


@router.put("/api/pokemon/cards/{card_id}/art-tags")
def set_card_art_tags(request: Request, card_id: str, body: SetArtTagsBody) -> dict[str, Any]:
    user = require_tagger(request)
    wanted = []
    for raw in body.tags:
        slug = _normalize_slug(raw)
        if slug and slug not in wanted:
            wanted.append(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, illustration_id = _card_illustration_id(conn, card_id)
        if wanted:
            found = {
                str(r[0])
                for r in conn.execute(
                    text(
                        """
                        SELECT slug FROM art_tag_defs
                        WHERE slug = ANY(:slugs) AND active = TRUE
                        """
                    ),
                    {"slugs": wanted},
                ).all()
            }
            missing = [s for s in wanted if s not in found]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown or inactive tag(s): {', '.join(missing)}",
                )
        conn.execute(
            text("DELETE FROM art_tags WHERE illustration_id = :iid"),
            {"iid": illustration_id},
        )
        for slug in wanted:
            conn.execute(
                text(
                    """
                    INSERT INTO art_tags (illustration_id, tag_slug, tagged_by)
                    VALUES (:iid, :slug, CAST(:uid AS uuid))
                    """
                ),
                {"iid": illustration_id, "slug": slug, "uid": user["id"]},
            )
        tags = fetch_art_tags_for_illustrations(conn, [illustration_id]).get(
            illustration_id, []
        )
    return {
        "card_id": _card_id,
        "illustration_id": illustration_id,
        "tags": tags,
    }


@router.post("/api/pokemon/cards/{card_id}/art-tags/{slug}")
def attach_card_art_tag(request: Request, card_id: str, slug: str) -> dict[str, Any]:
    user = require_tagger(request)
    slug_n = _normalize_slug(slug)
    if not slug_n or not SLUG_RE.match(slug_n):
        raise HTTPException(status_code=400, detail="Invalid tag slug")
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, illustration_id = _card_illustration_id(conn, card_id)
        active = conn.execute(
            text(
                """
                SELECT 1 FROM art_tag_defs
                WHERE slug = :slug AND active = TRUE
                """
            ),
            {"slug": slug_n},
        ).first()
        if not active:
            raise HTTPException(status_code=404, detail="Tag not found")
        conn.execute(
            text(
                """
                INSERT INTO art_tags (illustration_id, tag_slug, tagged_by)
                VALUES (:iid, :slug, CAST(:uid AS uuid))
                ON CONFLICT (illustration_id, tag_slug) DO NOTHING
                """
            ),
            {"iid": illustration_id, "slug": slug_n, "uid": user["id"]},
        )
        tags = fetch_art_tags_for_illustrations(conn, [illustration_id]).get(
            illustration_id, []
        )
    return {
        "card_id": _card_id,
        "illustration_id": illustration_id,
        "tags": tags,
    }


@router.delete("/api/pokemon/cards/{card_id}/art-tags/{slug}")
def detach_card_art_tag(request: Request, card_id: str, slug: str) -> dict[str, Any]:
    require_tagger(request)
    slug_n = _normalize_slug(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, illustration_id = _card_illustration_id(conn, card_id)
        conn.execute(
            text(
                """
                DELETE FROM art_tags
                WHERE illustration_id = :iid AND tag_slug = :slug
                """
            ),
            {"iid": illustration_id, "slug": slug_n},
        )
        tags = fetch_art_tags_for_illustrations(conn, [illustration_id]).get(
            illustration_id, []
        )
    return {
        "card_id": _card_id,
        "illustration_id": illustration_id,
        "tags": tags,
    }
