"""Shared helpers for nested Spell Tag defs (oracle + art)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text


def load_tag_defs(conn, *, defs_table: str, active_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE active = TRUE" if active_only else ""
    rows = conn.execute(
        text(
            f"""
            SELECT slug, label, description, parent_slug, active,
                   created_at::text AS created_at
            FROM {defs_table}
            {where}
            ORDER BY label, slug
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def children_map(defs: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    out: dict[str | None, list[dict[str, Any]]] = {}
    for d in defs:
        parent = d.get("parent_slug") or None
        out.setdefault(parent, []).append(d)
    for kids in out.values():
        kids.sort(key=lambda x: (str(x.get("label") or ""), str(x.get("slug") or "")))
    return out


def ancestors_of(
    slug: str, by_slug: dict[str, dict[str, Any]]
) -> list[str]:
    """Parent chain excluding slug itself (closest parent first)."""
    out: list[str] = []
    seen: set[str] = {slug}
    cur = by_slug.get(slug)
    while cur:
        parent = cur.get("parent_slug")
        if not parent or parent in seen:
            break
        out.append(str(parent))
        seen.add(str(parent))
        cur = by_slug.get(str(parent))
    return out


def descendants_of(
    slug: str, children: dict[str | None, list[dict[str, Any]]]
) -> list[str]:
    """All descendant slugs (not including slug itself)."""
    out: list[str] = []
    stack = [slug]
    seen: set[str] = {slug}
    while stack:
        cur = stack.pop()
        for kid in children.get(cur, []):
            ks = str(kid["slug"])
            if ks in seen:
                continue
            seen.add(ks)
            out.append(ks)
            stack.append(ks)
    return out


def expand_search_slugs(
    conn, slugs: list[str], *, defs_table: str
) -> list[str]:
    """For each slug, include itself + all descendants (for parent search)."""
    if not slugs:
        return []
    defs = load_tag_defs(conn, defs_table=defs_table, active_only=True)
    kids = children_map(defs)
    known = {str(d["slug"]) for d in defs}
    expanded: list[str] = []
    for slug in slugs:
        s = str(slug)
        if s not in expanded:
            expanded.append(s)
        if s not in known:
            continue
        for d in descendants_of(s, kids):
            if d not in expanded:
                expanded.append(d)
    return expanded


def assert_valid_parent(
    conn,
    *,
    defs_table: str,
    parent_slug: str | None,
    child_slug: str | None = None,
) -> str | None:
    """Validate parent exists, is active, and would not create a cycle."""
    if not parent_slug:
        return None
    parent = parent_slug.strip().lower().replace("_", "-")
    row = conn.execute(
        text(
            f"""
            SELECT slug, parent_slug, active
            FROM {defs_table}
            WHERE slug = :slug
            """
        ),
        {"slug": parent},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail=f"Parent tag not found: {parent}")
    if not row["active"]:
        raise HTTPException(status_code=400, detail=f"Parent tag is inactive: {parent}")
    if child_slug and parent == child_slug:
        raise HTTPException(status_code=400, detail="Tag cannot be its own parent")
    if child_slug:
        # Walk ancestors of parent; none may be child_slug
        defs = load_tag_defs(conn, defs_table=defs_table, active_only=False)
        by_slug = {str(d["slug"]): d for d in defs}
        for anc in ancestors_of(parent, by_slug):
            if anc == child_slug:
                raise HTTPException(status_code=400, detail="Parent would create a cycle")
    return parent


def enrich_tags_with_inheritance(
    conn,
    explicit: list[dict[str, str]],
    *,
    defs_table: str,
) -> list[dict[str, Any]]:
    """
    Return display list: explicit tags first, then inherited ancestors
    (deduped). Inherited rows have inherited=True.
    """
    defs = load_tag_defs(conn, defs_table=defs_table, active_only=True)
    by_slug = {str(d["slug"]): d for d in defs}
    for t in explicit:
        if t.get("slug") and t["slug"] not in by_slug:
            by_slug[str(t["slug"])] = {
                "slug": t["slug"],
                "label": t.get("label") or t["slug"],
                "parent_slug": None,
            }

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in explicit:
        slug = str(t.get("slug") or "")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(
            {
                "slug": slug,
                "label": t.get("label") or by_slug.get(slug, {}).get("label") or slug,
                "inherited": False,
                "parent_slug": by_slug.get(slug, {}).get("parent_slug"),
            }
        )
    # Ancestors after explicit
    for t in list(out):
        if t.get("inherited"):
            continue
        for anc in ancestors_of(str(t["slug"]), by_slug):
            if anc in seen:
                continue
            seen.add(anc)
            d = by_slug.get(anc) or {}
            out.append(
                {
                    "slug": anc,
                    "label": d.get("label") or anc,
                    "inherited": True,
                    "parent_slug": d.get("parent_slug"),
                }
            )
    return out
