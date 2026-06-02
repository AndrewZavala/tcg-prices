# Phase 2 extension points

v1 ships the enriched CK buylist in Postgres and a public search UI. Personal inventory and sell-list tooling from `Master_runfile_040926.Rmd` are deferred but the schema and API are designed to extend cleanly.

## Reserved database tables (add in future migrations)

### `inventory_cards`

Mirrors stack CSV exports joined to Scryfall:

| Column | Source |
|--------|--------|
| `batch_file` | Stacks/Batch*_export.csv filename |
| `scan_order` | Scan Order |
| `scryfall_id` | Scryfall ID |
| `set_code` | Set code |
| `collector_number` | Collector number |
| `finish` | Finish |
| `name` | Name |
| `quantity` | Quantity |
| `status` | active / sold |

Populate using the same logic as the `Batch Inventory` chunk in `Master_runfile_040926.Rmd` (`processed_stack_files.csv` tracking).

### `sell_list_items`

Active rows from `stack_with_ck` (inventory left-joined to `buylist_current` on `scryfall_id` + finish).

| Column | Notes |
|--------|-------|
| `scryfall_id`, `finish` | Join keys |
| `cash_price`, `credit_price` | From CK buylist |
| `tcg_price` | Derived from Scryfall USD columns |
| `batch_file`, `scan_order` | Shipment grouping |

### `buylist_price_history`

Optional retention of prior `buylist_cards` snapshots (Master runfile already builds `ck_hist` from dated `cardkingdom_buylist_master_*.csv` files). Either:

- Stop deleting old snapshot dates in `load_postgres.py`, or
- Append-only table keyed by `(snapshot_date, product_id, credit_price)`.

## Implemented (v1.1)

| Route | Purpose |
|-------|---------|
| `POST /api/collection/match` | Upload CSV, match to `buylist_current` |
| `GET /api/history/search` | Find cards for charts |
| `GET /api/history/series` | Time series CK vs TCG for one `scryfall_id` + finish |

## Reserved API routes

| Route | Purpose |
|-------|---------|
| `GET /api/inventory` | List active inventory with CK prices |
| `GET /api/sell-list` | Current sell list with batch totals |
| `POST /api/sell-list/export` | CK upload CSV for checked rows |
| `POST /api/sell-list/sold` | Mark scan orders sold |
| `GET /api/card/{product_id}/history` | CK credit/cash over time |

## R report split

Keep interactive HTML in `reports/sell_list.Rmd` sourcing:

1. `pipeline/merge_buylist.R`
2. `pipeline/enrich_ck.R`
3. Local inventory chunks from Master runfile

## Auth

When inventory endpoints ship, add session auth (e.g. API key or OAuth) and scope queries by `user_id`. Public buylist routes remain unauthenticated.
