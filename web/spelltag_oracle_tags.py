"""Spell Tag curated oracle tags (otag: search)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spelltag_auth import require_admin, require_tagger

router = APIRouter(tags=["oracle-tags"])

_engine: Engine | None = None

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def init_spelltag_oracle_tags(engine: Engine) -> None:
    global _engine
    _engine = engine


class CreateTagDefBody(BaseModel):
    """Accept either a display name or a kebab slug (or both)."""

    slug: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=80)
    name: str | None = Field(
        default=None,
        max_length=80,
        description="Either 'Rain Dance' or 'rain-dance' — slug/label derived automatically",
    )
    description: str | None = Field(default=None, max_length=400)


class PatchTagDefBody(BaseModel):
    label: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    active: bool | None = None


class SetOracleTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


def _normalize_slug(raw: str) -> str:
    slug = (raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _label_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _looks_like_slug(raw: str) -> bool:
    """True for kebab-case like rain-dance (no spaces, mostly lowercase)."""
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
    """
    Derive (slug, label) from user input.
    - "Rain Dance" → ("rain-dance", "Rain Dance")
    - "rain-dance" → ("rain-dance", "Rain Dance")
    """
    raw_slug = (slug or "").strip()
    raw_label = (label or "").strip()
    raw_name = (name or "").strip()

    if raw_name and not raw_slug and not raw_label:
        if _looks_like_slug(raw_name):
            raw_slug = raw_name
        else:
            raw_label = raw_name

    # Slug field filled with a display name (spaces / Title Case)
    if raw_slug and not _looks_like_slug(raw_slug) and not raw_label:
        raw_label = raw_slug
        raw_slug = ""

    # Label field filled with a kebab slug
    if raw_label and _looks_like_slug(raw_label) and not raw_slug:
        raw_slug = raw_label
        raw_label = ""

    out_slug = _normalize_slug(raw_slug or raw_label)
    if not out_slug or not SLUG_RE.match(out_slug):
        raise HTTPException(
            status_code=400,
            detail="Enter a name like Rain Dance or a slug like rain-dance",
        )

    if raw_label and not _looks_like_slug(raw_label):
        out_label = raw_label
    else:
        out_label = _label_from_slug(out_slug)

    if len(out_label) > 80:
        raise HTTPException(status_code=400, detail="Label is too long")
    return out_slug, out_label


def fetch_oracle_tags_for_oracles(
    conn, oracle_ids: list[str]
) -> dict[str, list[dict[str, str]]]:
    """Return {oracle_id: [{slug, label}, ...]} for active tags only."""
    ids = [oid for oid in dict.fromkeys(oracle_ids) if oid]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT ot.oracle_id, d.slug, d.label
            FROM oracle_tags ot
            INNER JOIN oracle_tag_defs d ON d.slug = ot.tag_slug
            WHERE ot.oracle_id = ANY(:oids)
              AND d.active = TRUE
            ORDER BY d.label, d.slug
            """
        ),
        {"oids": ids},
    ).mappings().all()
    out: dict[str, list[dict[str, str]]] = {oid: [] for oid in ids}
    for row in rows:
        out.setdefault(str(row["oracle_id"]), []).append(
            {"slug": str(row["slug"]), "label": str(row["label"])}
        )
    return out


def _card_oracle_id(conn, card_id: str) -> tuple[str, str]:
    row = conn.execute(
        text(
            """
            SELECT id, oracle_id
            FROM pokemon_cards
            WHERE lower(id) = lower(:id)
            """
        ),
        {"id": card_id.strip()},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    oracle_id = row.get("oracle_id")
    if not oracle_id:
        raise HTTPException(
            status_code=400,
            detail="Card has no oracle grouping yet; cannot attach oracle tags",
        )
    return str(row["id"]), str(oracle_id)


@router.get("/api/oracle-tags")
def list_oracle_tag_defs(active_only: bool = True) -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        if active_only:
            rows = conn.execute(
                text(
                    """
                    SELECT slug, label, description, active, created_at::text AS created_at
                    FROM oracle_tag_defs
                    WHERE active = TRUE
                    ORDER BY label, slug
                    """
                )
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT slug, label, description, active, created_at::text AS created_at
                    FROM oracle_tag_defs
                    ORDER BY active DESC, label, slug
                    """
                )
            ).mappings().all()
    return {"tags": [dict(r) for r in rows]}


@router.post("/api/oracle-tags")
def create_oracle_tag_def(request: Request, body: CreateTagDefBody) -> dict[str, Any]:
    user = require_tagger(request)
    slug, label = _resolve_slug_and_label(
        slug=body.slug,
        label=body.label,
        name=body.name,
    )
    assert _engine is not None
    with _engine.begin() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM oracle_tag_defs WHERE slug = :slug"),
            {"slug": slug},
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tag already exists")
        row = conn.execute(
            text(
                """
                INSERT INTO oracle_tag_defs (slug, label, description, created_by)
                VALUES (
                    :slug,
                    :label,
                    :description,
                    CAST(:uid AS uuid)
                )
                RETURNING slug, label, description, active, created_at::text AS created_at
                """
            ),
            {
                "slug": slug,
                "label": label,
                "description": (body.description or "").strip() or None,
                "uid": user["id"],
            },
        ).mappings().one()
    return dict(row)


@router.patch("/api/oracle-tags/{slug}")
def patch_oracle_tag_def(
    request: Request, slug: str, body: PatchTagDefBody
) -> dict[str, Any]:
    require_admin(request)
    slug_n = _normalize_slug(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        current = conn.execute(
            text(
                """
                SELECT slug, label, description, active
                FROM oracle_tag_defs WHERE slug = :slug
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
        row = conn.execute(
            text(
                """
                UPDATE oracle_tag_defs
                SET label = :label,
                    description = :description,
                    active = :active
                WHERE slug = :slug
                RETURNING slug, label, description, active, created_at::text AS created_at
                """
            ),
            {
                "slug": slug_n,
                "label": label,
                "description": description,
                "active": active,
            },
        ).mappings().one()
    return dict(row)


@router.get("/api/pokemon/cards/{card_id}/oracle-tags")
def get_card_oracle_tags(card_id: str) -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        _card_id, oracle_id = _card_oracle_id(conn, card_id)
        tags = fetch_oracle_tags_for_oracles(conn, [oracle_id]).get(oracle_id, [])
    return {"card_id": _card_id, "oracle_id": oracle_id, "tags": tags}


@router.put("/api/pokemon/cards/{card_id}/oracle-tags")
def set_card_oracle_tags(request: Request, card_id: str, body: SetOracleTagsBody) -> dict[str, Any]:
    user = require_tagger(request)
    wanted = []
    for raw in body.tags:
        slug = _normalize_slug(raw)
        if slug and slug not in wanted:
            wanted.append(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, oracle_id = _card_oracle_id(conn, card_id)
        if wanted:
            found = {
                str(r[0])
                for r in conn.execute(
                    text(
                        """
                        SELECT slug FROM oracle_tag_defs
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
            text("DELETE FROM oracle_tags WHERE oracle_id = :oid"),
            {"oid": oracle_id},
        )
        for slug in wanted:
            conn.execute(
                text(
                    """
                    INSERT INTO oracle_tags (oracle_id, tag_slug, tagged_by)
                    VALUES (:oid, :slug, CAST(:uid AS uuid))
                    """
                ),
                {"oid": oracle_id, "slug": slug, "uid": user["id"]},
            )
        tags = fetch_oracle_tags_for_oracles(conn, [oracle_id]).get(oracle_id, [])
    return {"card_id": _card_id, "oracle_id": oracle_id, "tags": tags}


@router.post("/api/pokemon/cards/{card_id}/oracle-tags/{slug}")
def attach_card_oracle_tag(request: Request, card_id: str, slug: str) -> dict[str, Any]:
    user = require_tagger(request)
    slug_n = _normalize_slug(slug)
    if not slug_n or not SLUG_RE.match(slug_n):
        raise HTTPException(status_code=400, detail="Invalid tag slug")
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, oracle_id = _card_oracle_id(conn, card_id)
        active = conn.execute(
            text(
                """
                SELECT 1 FROM oracle_tag_defs
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
                INSERT INTO oracle_tags (oracle_id, tag_slug, tagged_by)
                VALUES (:oid, :slug, CAST(:uid AS uuid))
                ON CONFLICT (oracle_id, tag_slug) DO NOTHING
                """
            ),
            {"oid": oracle_id, "slug": slug_n, "uid": user["id"]},
        )
        tags = fetch_oracle_tags_for_oracles(conn, [oracle_id]).get(oracle_id, [])
    return {"card_id": _card_id, "oracle_id": oracle_id, "tags": tags}


@router.delete("/api/pokemon/cards/{card_id}/oracle-tags/{slug}")
def detach_card_oracle_tag(request: Request, card_id: str, slug: str) -> dict[str, Any]:
    require_tagger(request)
    slug_n = _normalize_slug(slug)
    assert _engine is not None
    with _engine.begin() as conn:
        _card_id, oracle_id = _card_oracle_id(conn, card_id)
        conn.execute(
            text(
                """
                DELETE FROM oracle_tags
                WHERE oracle_id = :oid AND tag_slug = :slug
                """
            ),
            {"oid": oracle_id, "slug": slug_n},
        )
        tags = fetch_oracle_tags_for_oracles(conn, [oracle_id]).get(oracle_id, [])
    return {"card_id": _card_id, "oracle_id": oracle_id, "tags": tags}
