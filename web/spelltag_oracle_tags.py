"""Spell Tag curated oracle tags (otag: search)."""

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

router = APIRouter(tags=["oracle-tags"])

_engine: Engine | None = None
DEFS_TABLE = "oracle_tag_defs"

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


class SetOracleTagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


class MergeOraclesBody(BaseModel):
    """Merge absorb card's oracle into keep card's oracle; union curated tags."""

    keep_card_id: str = Field(min_length=1, max_length=80)
    absorb_card_id: str = Field(min_length=1, max_length=80)


def _normalize_slug(raw: str) -> str:
    slug = (raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]+", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _label_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _title_case_label(raw: str) -> str:
    parts = re.split(r"[\s_-]+", (raw or "").strip())
    return " ".join(p[:1].upper() + p[1:].lower() for p in parts if p)


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
        out_label = _title_case_label(raw_label)
    else:
        out_label = _label_from_slug(out_slug)

    if len(out_label) > 80:
        raise HTTPException(status_code=400, detail="Label is too long")
    return out_slug, out_label


def fetch_oracle_tags_for_oracles(
    conn, oracle_ids: list[str], *, with_inherited: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """Return {oracle_id: [{slug, label, inherited?}, ...]} for active tags only."""
    ids = [oid for oid in dict.fromkeys(oracle_ids) if oid]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT ot.oracle_id, d.slug, d.label, d.parent_slug
            FROM oracle_tags ot
            INNER JOIN oracle_tag_defs d ON d.slug = ot.tag_slug
            WHERE ot.oracle_id = ANY(:oids)
              AND d.active = TRUE
            ORDER BY d.label, d.slug
            """
        ),
        {"oids": ids},
    ).mappings().all()
    explicit: dict[str, list[dict[str, str]]] = {oid: [] for oid in ids}
    for row in rows:
        explicit.setdefault(str(row["oracle_id"]), []).append(
            {"slug": str(row["slug"]), "label": str(row["label"])}
        )
    if not with_inherited:
        return explicit  # type: ignore[return-value]
    out: dict[str, list[dict[str, Any]]] = {}
    for oid, tags in explicit.items():
        out[oid] = enrich_tags_with_inheritance(
            conn, tags, defs_table=DEFS_TABLE
        )
    return out


def expand_oracle_search_slugs(conn, slugs: list[str]) -> list[str]:
    return expand_search_slugs(conn, slugs, defs_table=DEFS_TABLE)


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


def union_oracle_tags(conn, target_oracle_id: str, source_oracle_ids: list[str]) -> int:
    """Copy tags from source oracles onto target; identical slugs stay one row.

    Returns number of tag rows inserted onto the target (conflicts skipped).
    """
    sources = [
        oid
        for oid in dict.fromkeys(source_oracle_ids)
        if oid and oid != target_oracle_id
    ]
    if not sources:
        return 0
    result = conn.execute(
        text(
            """
            INSERT INTO oracle_tags (oracle_id, tag_slug, tagged_by, tagged_at)
            SELECT :target, ot.tag_slug, ot.tagged_by, ot.tagged_at
            FROM oracle_tags ot
            WHERE ot.oracle_id = ANY(:sources)
            ON CONFLICT (oracle_id, tag_slug) DO NOTHING
            """
        ),
        {"target": target_oracle_id, "sources": sources},
    )
    return int(result.rowcount or 0)


def merge_oracle_into(conn, keep_oracle_id: str, absorb_oracle_id: str) -> dict[str, Any]:
    """Move all printings from absorb → keep, union tags, delete absorb oracle."""
    if keep_oracle_id == absorb_oracle_id:
        return {
            "keep_oracle_id": keep_oracle_id,
            "absorb_oracle_id": absorb_oracle_id,
            "moved_printings": 0,
            "tags_unioned": 0,
            "already_same": True,
        }

    keep = conn.execute(
        text("SELECT id, name FROM pokemon_oracles WHERE id = :id"),
        {"id": keep_oracle_id},
    ).mappings().first()
    absorb = conn.execute(
        text("SELECT id, name FROM pokemon_oracles WHERE id = :id"),
        {"id": absorb_oracle_id},
    ).mappings().first()
    if not keep:
        raise HTTPException(status_code=404, detail="Keep oracle not found")
    if not absorb:
        raise HTTPException(status_code=404, detail="Absorb oracle not found")

    tags_unioned = union_oracle_tags(conn, keep_oracle_id, [absorb_oracle_id])
    moved = conn.execute(
        text(
            """
            UPDATE pokemon_cards
            SET oracle_id = :keep
            WHERE oracle_id = :absorb
            """
        ),
        {"keep": keep_oracle_id, "absorb": absorb_oracle_id},
    )
    moved_n = int(moved.rowcount or 0)

    # Drop absorb tags then oracle (CASCADE would also clear tags)
    conn.execute(
        text("DELETE FROM oracle_tags WHERE oracle_id = :oid"),
        {"oid": absorb_oracle_id},
    )
    conn.execute(
        text("DELETE FROM pokemon_oracles WHERE id = :oid"),
        {"oid": absorb_oracle_id},
    )

    count_row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS n,
                   COUNT(DISTINCT illustration_id) AS arts,
                   MIN(s.release_date) AS first_release
            FROM pokemon_cards c
            LEFT JOIN pokemon_sets s ON s.id = c.set_id
            WHERE c.oracle_id = :oid
            """
        ),
        {"oid": keep_oracle_id},
    ).mappings().one()
    conn.execute(
        text(
            """
            UPDATE pokemon_oracles
            SET printing_count = :n,
                art_variant_count = :arts,
                first_release_date = :first_release
            WHERE id = :oid
            """
        ),
        {
            "oid": keep_oracle_id,
            "n": int(count_row["n"] or 0),
            "arts": int(count_row["arts"] or 0),
            "first_release": count_row["first_release"],
        },
    )

    return {
        "keep_oracle_id": keep_oracle_id,
        "absorb_oracle_id": absorb_oracle_id,
        "keep_name": keep.get("name"),
        "absorb_name": absorb.get("name"),
        "moved_printings": moved_n,
        "tags_unioned": tags_unioned,
        "already_same": False,
    }


@router.get("/api/oracle-tags")
def list_oracle_tag_defs(active_only: bool = True) -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        if active_only:
            rows = conn.execute(
                text(
                    """
                    SELECT slug, label, description, parent_slug, active,
                           created_at::text AS created_at
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
                    SELECT slug, label, description, parent_slug, active,
                           created_at::text AS created_at
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
        parent = assert_valid_parent(
            conn,
            defs_table=DEFS_TABLE,
            parent_slug=body.parent_slug,
            child_slug=slug,
        )
        # Prefix child slug with parent when creating a short subtag name
        if parent and not slug.startswith(parent + "-") and slug != parent:
            # Keep user slug if already hierarchical; else status + sleep → status-sleep
            if "-" not in slug or not slug.startswith(parent):
                candidate = f"{parent}-{slug}"
                if SLUG_RE.match(candidate) and len(candidate) <= 80:
                    slug = candidate
        existing = conn.execute(
            text(
                """
                SELECT slug, label, description, parent_slug, active,
                       created_at::text AS created_at
                FROM oracle_tag_defs WHERE slug = :slug
                """
            ),
            {"slug": slug},
        ).mappings().first()
        if existing:
            # Reuse (and reactivate) so "already exists" isn't a dead end in the UI.
            if not existing["active"]:
                existing = conn.execute(
                    text(
                        """
                        UPDATE oracle_tag_defs
                        SET active = TRUE,
                            label = COALESCE(NULLIF(:label, ''), label),
                            parent_slug = COALESCE(:parent, parent_slug)
                        WHERE slug = :slug
                        RETURNING slug, label, description, parent_slug, active,
                                  created_at::text AS created_at
                        """
                    ),
                    {"slug": slug, "label": label, "parent": parent},
                ).mappings().one()
            out = dict(existing)
            out["already_existed"] = True
            return out
        row = conn.execute(
            text(
                """
                INSERT INTO oracle_tag_defs (slug, label, description, created_by, parent_slug)
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
    out = dict(row)
    out["already_existed"] = False
    return out


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
                SELECT slug, label, description, active, parent_slug
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
                UPDATE oracle_tag_defs
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


@router.post("/api/admin/oracles/merge")
def admin_merge_oracles(request: Request, body: MergeOraclesBody) -> dict[str, Any]:
    """Merge one card's oracle into another's; curated tags are unioned (deduped)."""
    require_admin(request)
    keep_raw = (body.keep_card_id or "").strip()
    absorb_raw = (body.absorb_card_id or "").strip()
    if not keep_raw or not absorb_raw:
        raise HTTPException(status_code=400, detail="keep_card_id and absorb_card_id required")
    if keep_raw.lower() == absorb_raw.lower():
        raise HTTPException(status_code=400, detail="Cards must be different")
    assert _engine is not None
    with _engine.begin() as conn:
        keep_card_id, keep_oracle_id = _card_oracle_id(conn, keep_raw)
        absorb_card_id, absorb_oracle_id = _card_oracle_id(conn, absorb_raw)
        result = merge_oracle_into(conn, keep_oracle_id, absorb_oracle_id)
        tags = fetch_oracle_tags_for_oracles(conn, [keep_oracle_id]).get(keep_oracle_id, [])
    result.update(
        {
            "keep_card_id": keep_card_id,
            "absorb_card_id": absorb_card_id,
            "tags": tags,
        }
    )
    return result
