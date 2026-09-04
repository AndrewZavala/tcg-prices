# Plan: Card data corrections (types, costs, oracle, images, multicolor)

**Status: implemented** in code + migration `046_card_data_fixes_plan.sql` (deploy + Golduck image download still needed on VPS).

Track and fix upstream/source mislabels that break search (`is:multicolor`, type filters) and card detail. Prefer the existing correction pipeline: `pipeline/pokemon_card_corrections.py` + startup SQL migrations + ingest recomputation.

Related in-progress: Dark Magneton `base5-11` Sonicboom cost/damage (`045` migration, not yet pushed).

---

## 1. Multicolor false positives (flavor text)

**Root cause:** `compute_is_multicolor` / migration `044` treat `pokemon_cards.description` (Pokédex flavor) as rules text. Flavor lines like “psychic energy” match `Psychic Energy` and inflate the color set.

**Confirmed examples (live):**

| ID | Card | Why flagged |
|----|------|-------------|
| `sm11-57` | Alolan Raichu (Unified Minds) | Flavor: “psychic energy into its tail…” |
| `sv01-051` | Bruxish (SV) | Flavor: “fires the psychic energy…” |
| `swsh3-77` | Golurk (Darkness Ablaze) | Flavor mentions energy / psychic wording |
| `swsh9-083` | Golurk (Brilliant Stars) | Same flavor family |

**Fix:**

1. Remove `description` from `_multicolor_rules_text` (Python).
2. Update migration `044` backfill SQL **and** `persist_multicolor_flags` to drop `c.description` from the text blob (keep attack/ability **effects** + optional `card_data.effect` only).
3. New migration `046` (or fold into next): `UPDATE … SET is_multicolor = FALSE` then re-run the corrected backfill (or call `persist_multicolor_flags` once on deploy).
4. Add regression tests: Bruxish / Alolan Raichu flavor must **not** yield multicolor; White Kyurem-style “Fire Energy” in **attack effect** still must.

**Do not** strip flavor from `o:` oracle-text search unless we decide later; this change is multicolor-only.

---

## 2. Attack cost corrections (`ATTACK_FIELD_BY_NAME`)

| ID | Card | Field | Wrong → Correct |
|----|------|-------|-----------------|
| `neo2-32` | Umbreon (Neo Discovery) | Pursuit `cost` | Metal → **Darkness** (+ keep rest) |
| `ex9-42` | Volbeat (Emerald) | Double-edge `cost` | Lightning → **Grass** (verify full cost list on card) |
| `ex11-74` | Magnemite δ (Delta Species) | Magnetic Blast `cost` | Grass → **Lightning** |
| `dp6-17` | Yanmega (Legends Awakened) | Pursue and Turn `cost` | Grass×2+Metal×2 → **Grass×2+Colorless×2** |
| `base5-11` | Dark Magneton (Team Rocket) | Sonicboom | Already staged: Colorless×2 / **20** |

Also clear / recompute `is_multicolor` after cost fixes (Umbreon, Magnemite δ, Yanmega, Dark Magneton).

---

## 3. Printed type corrections (`types` / category)

Add a small `TYPES_BY_ID` (or extend corrections) + SQL migration, and recompute multicolor/oracle after.

| ID | Card | Wrong → Correct |
|----|------|-----------------|
| `ex10-44` | Quagsire (Unseen Forces) | Fire → **Fighting** |
| `ex11-44` | Hariyama δ (Delta Species) | Fire → **Fighting** |
| `ex11-82` | Sandshrew δ (Delta Species) | Water → **Fighting** |
| `ecard3-H19` | Magneton (Skyridge holo) | Lightning → **Metal** (attacks already Metal; matches `ecard3-20`) |

**Verify before shipping:**

- `ecard3-19` / `ecard3-H18` (Electric Blast) — likely **legit Lightning** Magnetons; do not blanket-fix all Skyridge Magneton.
- Confirm Volbeat / Magnemite full cost arrays from pokemontcg.io or Limitless.

---

## 4. Hoppip Expedition — attack merge (`ecard1-112`)

**Live (broken):**

1. Sleep Powder — Water+C+C / `20x` + sleep effect  
2. Nameless attack — Grass / 10  

**Target (single attack):**

- **Sleep Powder** — `{G}` / **10**  
- Effect: Flip a coin. If heads, the Defending Pokémon is now Asleep.

**Implementation:**

- Prefer a dedicated correction (replace entire `attacks` array for `ecard1-112`) rather than field-only patch, because name/cost/damage are split across two rows.
- Drop nameless stub (same idea as `DROP_NAMELESS_ATTACKS`).
- Rebuild oracle for this card after fix (fingerprint changes).

---

## 5. Golduck Aquapolis — missing local images

| ID | Notes |
|----|------|
| `ecard2-50a` | `image_local=false`; remote `https://images.pokemontcg.io/ecard2/50a_hires.png` |
| `ecard2-50b` | same pattern for `50b` |

**Status:** Remote URLs are already correct — no `pokemon_image_urls` map change needed.

**Ops (VPS after deploy):**

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --set ecard2 --force
```

Optionally filter to just the two IDs if the script supports it; otherwise full-set force is fine.

---

## 6. Implementation order

1. **Multicolor flavor exclusion** + full flag recompute (unblocks trust in `is:multicolor`).
2. **Batch corrections** in `pokemon_card_corrections.py` (costs, types, Hoppip attacks, Dark Magneton if not pushed).
3. **Migration(s)** to patch live rows + recompute `is_multicolor` for touched IDs (and global recompute once for flavor fix).
4. **Oracle rebuild** for cards whose gameplay fingerprint changed (Hoppip, type/cost fixes):  
   `python pipeline/build_pokemon_oracle.py` (or set-scoped rebuilds).
5. **Golduck image download** (ops; independent of SQL).
6. Deploy: `git pull` + rebuild `star-piece` (migrations on startup); run pipeline image job for Golduck / oracle as needed.

---

## 7. Tests

- `compute_is_multicolor`: flavor-only “psychic energy” → false; attack-effect “Fire Energy” → true when off-type.
- `correct_attacks` / type helpers for each ID in §2–§4.
- Optional API smoke: `is:multicolor Alolan Raichu` should not return `sm11-57` after recompute.

---

## 8. Out of scope / watch list

- Mass TCGdex re-ingest alone will **reintroduce** several of these unless corrections stay in the ingest path.
- `o:` search still indexes description today; only multicolor stops using flavor (per your note).
- Sonic Wave on `dp6-17` currently has empty `cost: []` (0 energy) — confirm intentional; not part of the Pursue/Turn Metal bug.
