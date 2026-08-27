# Collections — sharing, visibility & grouping

Plan for (1) shareable collections with **private / unlisted / public** visibility and (2) **group by** on collection detail views.

**Status:** planned (not implemented)  
**Branch target:** `spell-tag`  
**Related:** `032_spelltag_collections.sql`, `038_collection_item_tags.sql`, `web/spelltag_collections.py`, `web/static/collections.js`

---

## Goals

### Sharing

1. Let owners set collection visibility: **private** (default), **unlisted**, or **public**.
2. **Unlisted** and **public** — anyone with the link can view without signing in.
3. **Public** only — appears on the owner’s profile when that ships; **unlisted** never does.
4. Keep **edit**, **import**, and **per-card tags** owner-only.
5. Keep **Favorites** always private.

### Grouping

6. On collection detail, add **Group by** alongside existing **Sort by**.
7. Example: group by **category** (Pokémon / Trainer / Energy), sort within each group by **set**.
8. Persist `group` + `sort` in the URL (same pattern as today’s `?sort=set&tag=draw`).

Non-goals for v1:

- Site-wide directory of all public collections
- Collaborative editing / fork
- Comments or likes

---

## Current state

| Area | Today |
|------|--------|
| Schema | `collections(id, user_id, name, kind)` — no visibility |
| Auth | All routes under `/api/me/collections/*` require Google session |
| Access check | `_owned_collection(conn, user_id, collection_id)` |
| UI | `/collections` and `/collections/{uuid}` — owner-only API calls |
| Tags | `collection_item_tags` — private labels per card in a collection |
| Detail controls | **Sort:** saved, name, set, number, tag · **Filter:** tag · **Search:** client-side name |
| Card fields | No `category` on collection card rows (needed for grouping) |

Manifest Bread’s `web/collection_share.py` (MTG inventory HTML export) is **unrelated**.

---

## Part 1 — Visibility & sharing

### Visibility model

| Value | Who can view | Listed on profile (phase 3) | Typical use |
|-------|----------------|-----------------------------|-------------|
| `private` | Owner only | No | Default; work-in-progress lists |
| `unlisted` | Anyone with link | No | Share with friends; not discoverable |
| `public` | Anyone with link | Yes | Showcase cube / binders on profile |

**Hard rules:**

- `kind = 'favorites'` → always `private` (enforce in API even if UI hides toggle).
- `collection_item_tags` → never returned on public/unlisted endpoints.
- `private` collections → **404** on anonymous read (not 403).
- **`unlisted` and `public`** both resolve via share link; difference is profile listing only.

**`public_url` helper (server-computed):**

- Set when `visibility IN ('unlisted', 'public')`.
- Prefer slug: `https://spelltag.com/c/{share_slug}`
- Fallback: `https://spelltag.com/collections/{uuid}`
- `null` when `private`

### Schema (migration `039_collection_visibility.sql`)

```sql
ALTER TABLE collections
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'
    CHECK (visibility IN ('private', 'unlisted', 'public')),
  ADD COLUMN IF NOT EXISTS share_slug TEXT UNIQUE;

CREATE INDEX IF NOT EXISTS idx_collections_listable_updated
  ON collections (updated_at DESC)
  WHERE visibility = 'public';

CREATE INDEX IF NOT EXISTS idx_collections_shareable
  ON collections (share_slug)
  WHERE visibility IN ('unlisted', 'public');

ALTER TABLE collections
  ADD CONSTRAINT collections_share_slug_format
  CHECK (
    share_slug IS NULL
    OR (
      char_length(share_slug) BETWEEN 3 AND 48
      AND share_slug ~ '^[a-z0-9][a-z0-9-]*$'
    )
  );
```

Register in `web/star_piece_main.py` → `POKEMON_MIGRATIONS`.

### API — owner routes

| Method | Path | Body | Notes |
|--------|------|------|-------|
| `PATCH` | `/api/me/collections/{id}` | `{ "visibility"?, "share_slug"? }` | Reject non-private on favorites |
| `GET` | `/api/me/collections` | — | Include `visibility`, `share_slug`, `public_url` |
| `GET` | `/api/me/collections/{id}` | `?sort=&tag=&group=` | Owner view; see grouping below |

### API — public read routes

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/collections/{id_or_slug}` | Cards + metadata |
| | | **404** if `visibility = 'private'` |
| | | **200** if `visibility IN ('unlisted', 'public')` |

Anonymous requests ignore `tag` filter (tags are private). `sort` and `group` work on public/unlisted views.

**Lookup:** UUID or `share_slug` (case-insensitive) → require `visibility != 'private'`.

### UI — sharing

**Collection detail (owner):**

- Visibility control: **Private · Unlisted · Public** (segmented or select).
- When unlisted or public: **Copy link** + optional **share slug** editor.
- Badges on list page: `Unlisted`, `Public`.
- Hide control on Favorites.

**Visitor view (unlisted/public):**

- Read-only grid + card modal.
- No tags, edit, import, add/remove.
- Header: `{owner.name} · {collection name} · {n} cards`.

### HTTP routes

| Path | Notes |
|------|--------|
| `/collections/{uuid}` | Owner API first; fallback to public read |
| `/c/{share_slug}` | Public read for unlisted/public |

---

## Part 2 — Group by (collection detail)

### Concept

**Sort** and **Group by** are independent:

| Control | Question it answers | Examples |
|---------|---------------------|----------|
| **Group by** | Which section headers divide the grid? | None, Category, Set (later) |
| **Sort by** | Order of cards *within* each section? | Saved, Name, Set, Number, Tag |

**Example:** `group=category` + `sort=set`

```
Pokémon (240)
  [cards sorted by set name, then collector number]

Trainer (115)
  [cards sorted by set name, then collector number]

Energy (5)
  [cards sorted by set name, then collector number]
```

### Group-by options (v1)

| `group` value | Section key | Section label | Section order |
|---------------|-------------|---------------|---------------|
| `none` | — | Flat grid (today) | — |
| `category` | `pc.category` | Pokémon · Trainer · Energy | Pokémon → Trainer → Energy |

**Future (not v1):**

| `group` | Notes |
|---------|--------|
| `set` | One header per set name |
| `rarity` | Common / Uncommon / Rare / … |
| `tag` | One section per tag (untagged → “Untagged”) |
| `type` | Energy type for Pokémon (Fire, Water, …) |

### API changes

**Query params** on `GET /api/me/collections/{id}` and `GET /api/collections/{id_or_slug}`:

```
?sort=saved|name|set|number|tag
&group=none|category
&tag=draw          # owner-only filter
```

**SQL:**

1. Add `pc.category` to the collection cards SELECT (required for grouping labels and client fallback).
2. When `group=category`, prepend category to `ORDER BY`:

```sql
ORDER BY
  CASE pc.category
    WHEN 'Pokemon' THEN 0
    WHEN 'Trainer' THEN 1
    WHEN 'Energy' THEN 2
    ELSE 3
  END,
  {existing_sort_clause}
```

3. Response echoes `"group": "category"` so the client knows to render headers.

**Response shape** (flat list — client inserts headers at category boundaries):

```json
{
  "collection": { … },
  "cards": [
    { "id": "sv01-025", "name": "Pikachu", "category": "Pokemon", "set_name": "Scarlet & Violet", … },
    { "id": "sv01-181", "name": "Professor's Research", "category": "Trainer", … }
  ],
  "sort": "set",
  "group": "category",
  "total": 360
}
```

Alternative (optional later): server returns `"groups": [{ "key": "Pokemon", "label": "Pokémon", "count": 240, "cards": [...] }]`. Start with flat + client headers — less API churn.

### UI changes

**Controls row** (collection detail):

```
[ Search… ]  [ Tag filter ▼ ]  [ Group by ▼ ]  [ Sort by ▼ ]
```

| Group by | Sort by |
|----------|---------|
| None | Saved · Name · Set · Number · Tag |
| Category (Pokémon / Trainer / Energy) | Saved · Name · Set · Number · Tag |

**URL persistence:**

```
/collections/{id}?group=category&sort=set
/collections/{id}?group=category&sort=set&tag=draw   # owner only
```

**Rendering (`collections.js`):**

1. Fetch cards (already sorted server-side).
2. If `group === 'none'` → flat grid (current behavior).
3. If `group === 'category'` → walk list; on category change, insert:

```html
<section class="sp-collection-group">
  <h2 class="sp-collection-group-title">Pokémon <span class="sp-collection-group-count">240</span></h2>
  <div class="sp-grid sp-collections-grid">…tiles…</div>
</section>
```

4. Empty group after tag/search filter → hide section or show “No trainers match …”.

**CSS:** group title sticky optional; spacing between sections; count badge.

### Search + group interaction

- **Search** stays client-side (filter before group render).
- **Tag filter** stays server-side (owner only).
- Order: API filter/sort/group → client search filter → render grouped sections.

---

## Security & privacy

| Concern | Mitigation |
|---------|------------|
| Tag leakage | Never join `collection_item_tags` on anonymous read |
| Favorites exposure | API rejects `unlisted`/`public` when `kind = favorites` |
| Enumeration | Private → 404 on public endpoint |
| Unlisted vs public | Same link access; only profile query distinguishes |
| Slug squatting | Owner-only PATCH; format validation |

---

## Implementation phases

### Phase 1 — Sharing + grouping core

**Estimate:** ~1.5 days

**Sharing:**

- [ ] Migration `039_collection_visibility.sql` (`private` \| `unlisted` \| `public`)
- [ ] `PATCH /api/me/collections/{id}` (visibility, slug)
- [ ] `GET /api/collections/{id_or_slug}` (unlisted + public)
- [ ] UI: Private · Unlisted · Public + copy link
- [ ] `collections.js`: owner vs visitor; public fallback

**Grouping:**

- [ ] Add `pc.category` to collection card query
- [ ] `group` query param + `_card_group_order_clause()`
- [ ] UI: Group by dropdown; section headers in grid
- [ ] URL sync for `group`

**Tests:**

- [ ] Private → 404 anonymous; unlisted/public → 200
- [ ] Favorites cannot leave private
- [ ] Tags absent from public JSON
- [ ] `group=category&sort=set` ordering
- [ ] Group headers render correct counts

### Phase 2 — Pretty share URLs

**Estimate:** ~half day

- [ ] `GET /c/{share_slug}` page route
- [ ] Slug validation + uniqueness errors in UI

### Phase 3 — Public profiles

**Estimate:** ~1–2 days

- [ ] `users.profile_slug`
- [ ] `GET /api/users/{slug}/collections` — **`visibility = 'public'` only** (not unlisted)
- [ ] Profile page `/u/{slug}`

### Phase 4 — More group-by dimensions (optional)

- [ ] `group=set`, `group=rarity`, `group=tag`
- [ ] Sticky group headers; collapse sections

---

## Files to touch

| File | Change |
|------|--------|
| `migrations/039_collection_visibility.sql` | Visibility + slug |
| `web/star_piece_main.py` | Migration; `/c/{slug}` |
| `web/spelltag_collections.py` | PATCH, public GET, `group` param, category in SELECT |
| `web/static/collections.js` | Visibility UI; group render; URL sync |
| `web/static/collections.html` | Group-by control markup |
| `web/static/spell-tag.css` | Group sections; visibility badges |
| `web/test_collection_sharing.py` | Visibility tests |
| `web/test_collection_grouping.py` | Group + sort SQL tests |

---

## Test plan

### Sharing

1. Default visibility = `private`; anonymous GET → 404.
2. Set `unlisted` → link works; not returned from profile API (phase 3).
3. Set `public` → link works; listed on profile (phase 3).
4. Favorites → PATCH `unlisted`/`public` → 400.
5. Revoke to `private` → old link 404.

### Grouping

1. `group=none` — flat grid unchanged.
2. `group=category&sort=set` — Pokémon block before Trainer before Energy; within block sorted by set.
3. Tag filter + grouping — sections only show matching cards; counts update.
4. Client search + grouping — sections hide when empty.
5. Public/unlisted view — grouping works; no tag filter in UI.

---

## Open questions

1. **Slug scope:** global `/c/my-cube` vs `/c/@user/my-cube`?
2. **Unlisted badge:** show “Unlisted” to owner only, or also to visitors?
3. **Empty categories:** hide section or show “Trainer (0)”?
4. **Default group for cubes:** keep `none`, or default new imports to `category`?
5. **Public card modal:** full detail or image + name only?

---

## References

- `migrations/032_spelltag_collections.sql` — collections schema
- `migrations/038_collection_item_tags.sql` — per-card tags (private)
- `web/spelltag_collections.py` — `_card_sort_clause`, detail GET
- `web/static/collections.js` — sort/tag URL helpers, `renderDetailGrid`
