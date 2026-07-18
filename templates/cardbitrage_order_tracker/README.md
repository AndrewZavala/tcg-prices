# Cardbitrage order tracker (Google Sheets)

Track TCGplayer purchases → CK shipments → CK payouts. Emails upsert **Transactions** (audit log) and **Orders** / **Cards** (working state).

## Lifecycle

```
TCG processed email     → Transactions + Orders (per seller) + Cards (line items)
TCG shipped email       → update Orders (tracking, shipped_on); link Cards to tcg_order_id
CK confirmation email   → CK_batches row + link Orders.ck_batch_id (manual trigger today)
CK received email       → CK_batches.status = Received by CK
CK payout email         → CK_batches.status = Paid; Orders → Done
```

## Quick start

### Option A — Excel file (recommended)

```bash
pip install openpyxl
python templates/cardbitrage_order_tracker/build_template.py
```

This creates **`Cardbitrage_Order_Tracker.xlsx`** with four tabs:

| Tab | Purpose |
|-----|---------|
| **Transactions** | One row per email event (audit log) |
| **Orders** | One row per TCG seller order # (email upsert key) |
| **CK_batches** | One row per package you send to Card Kingdom |
| **Cards** | Line items from processed/shipped emails |

**Import to Google Sheets:**

1. [sheets.new](https://sheets.new) → **File → Import → Upload** → choose `Cardbitrage_Order_Tracker.xlsx`
2. Import location: **Replace spreadsheet**
3. Delete the example rows on each tab (row 2+ on Orders/CK_batches/Cards)

### Option B — CSV import

Import each CSV as a separate tab:

- `Transactions.csv`
- `Orders.csv`
- `CK_batches.csv`
- `Cards.csv`

---

## Column reference

### Transactions

| Column | Description |
|--------|-------------|
| `transaction_id` | Unique id, e.g. `2026-07-02:165.79:processed` |
| `email_date` | When the email arrived |
| `email_type` | `tcg_processed`, `tcg_shipped`, `ck_confirmation`, `ck_received`, `ck_payout` |
| `source` | `tcgplayer` or `cardkingdom` |
| `reference` | Checkout key, order #, or CK batch ref |
| `amount_usd` | Grand total or payout amount |
| `raw_subject` | Email subject (debug) |
| `message_id` | MIME Message-ID when available |

### Orders

| Column | Description |
|--------|-------------|
| `tcg_order_id` | **Primary key** — TCGplayer seller order UUID (e.g. `D95E2DBE-6D3607-73354`) |
| `seller` | Marketplace seller name |
| `status` | Dropdown: Ordered → Shipped → Delivered → Packed → Sent to CK → Done |
| `ordered_on` | First confirmation email date |
| `shipped_on` | Shipping notification date |
| `delivered_on` | Delivery date (carrier or manual) |
| `tracking` | USPS / FedEx / UPS tracking number |
| `buy_total` | Seller subtotal from processed email (product + shipping) |
| `shipping` | Shipping paid to seller (if parsed separately) |
| `checkout_key` | Groups orders from one checkout, e.g. `2026-07-02:165.79` |
| `simplified_lot` | Grouping hint: `seller-slug\|card-a\|card-b` |
| `ck_batch_id` | Links to **CK_batches** when you pack for CK |
| `last_email_at` | Last email that touched this row |
| `last_email_subject` | Debug / audit |
| `notes` | Free text |

### CK_batches

| Column | Description |
|--------|-------------|
| `ck_batch_id` | **Primary key** — you assign, e.g. `CK-2026-07-02-A` |
| `label` | Human name, e.g. `Tarkan July lot` |
| `sent_on` | Date mailed to CK |
| `ck_ref` | CK confirmation reference (if any) |
| `expected_ck_usd` | Expected CK payout from arbitrage report |
| `status` | Draft → Sent → Received by CK → Paid → Closed |
| `notes` | Free text |

### Cards

Line-level detail. **`checkout_key`** links items from a multi-seller processed email before **`tcg_order_id`** is known (shipped emails assign the seller order).

| Column | Description |
|--------|-------------|
| `tcg_order_id` | Seller order UUID (blank until shipped email or manual) |
| `checkout_key` | Same as Orders.checkout_key for the checkout |
| `card_name` | Parsed from email Description column |
| `set_name` | Parsed set name |
| `finish` | `normal` or `foil` |
| `condition` | `NM`, `LP`, `MP`, etc. |
| `buy_qty` | Quantity purchased |
| `unit_buy_usd` | Per-card buy price when known |
| `line_total_usd` | Line total when known |
| `ck_adj_usd` | Expected CK payout (manual or from arbitrage report) |

---

## TCG processed email parsing

TCGplayer puts **seller blocks** and **line items** in different sections:

```
Mirrodin Card Bazaar $25.99
Order Number: D95E2DBE-6D3607-73354
...
[table] Qty | Description
        4   | Magic - ... - Minsc & Boo ...
```

The email does **not** say which line item belongs to which seller. The parser:

1. Creates one **Orders** row per seller block (reliable)
2. Creates **Cards** rows from the Qty/Description table
3. Sets **`checkout_key`** on both so you can see they belong together
4. Leaves **`Cards.tcg_order_id`** blank until a **per-seller shipped email** arrives (those emails include the order UUID + items)

**Single seller, multiple cards** (e.g. Tarkan's Cards3 — $197.85 for 7 lines): all cards get the same `tcg_order_id` immediately, but **`unit_buy_usd` is not in the email**. Pull per-unit prices from your TCGplayer order history page:

```bash
# Option A: saved order history HTML (File → Save As from browser)
docker compose exec scheduler python /app/pipeline/parse_tcg_order_email.py \
  /app/tests/fixtures/tcg_processed_jul2_tarkan.html \
  --order-html /path/to/order-page.html --date 2026-07-02

# Option B: live fetch (Edge CDP logged into TCGplayer, same as listings scrape)
docker compose exec scheduler python /app/pipeline/fetch_tcg_order_detail.py AABCFB49-C91747-11736

# Option B via email parser
docker compose exec scheduler python /app/pipeline/parse_tcg_order_email.py \
  /path/to/processed.eml --fetch-prices
```

This fills **`Cards.unit_buy_usd`** and **`Cards.line_total_usd`** (verified against `Orders.buy_total`).

## TCG shipped email parsing

Shipped emails arrive **one per seller** and include the order UUID + line items — this is how we link Cards to Orders.

Parsed fields:

| Field | Source |
|-------|--------|
| `seller` | `"Mirrodin Card Bazaar has shipped your order..."` |
| `tcg_order_id` | `Order Number:` link or `SearchString=` in URL |
| `tracking` | USPS/FedEx/UPS pattern if present (often absent) |
| `ordered_on` | `placed on 7/2/2026` |
| Line items | Same Qty/Description table as processed email |

Test locally:

```bash
# Processed only
docker compose exec scheduler python /app/pipeline/parse_tcg_order_email.py \
  /app/tests/fixtures/tcg_processed_jul2.html --date 2026-07-02

# Shipped only
docker compose exec scheduler python /app/pipeline/parse_tcg_order_email.py \
  /app/tests/fixtures/tcg_shipped_jul2_mirrodin.html --date 2026-07-02 --type shipped

# Link processed + shipped (assigns tcg_order_id on matching cards)
docker compose exec scheduler python /app/pipeline/parse_tcg_order_email.py \
  /app/tests/fixtures/tcg_processed_jul2.html \
  /app/tests/fixtures/tcg_shipped_jul2_mirrodin.html \
  --link --date 2026-07-02
```

---

## Google Sheets setup (after import)

### 1. Status dropdowns (if not imported from xlsx)

**Orders → column C (`status`):**

Data → Data validation → List of items:

```
Ordered,Shipped,Delivered,Packed,Sent to CK,Done
```

**CK_batches → status column:**

```
Draft,Sent,Received by CK,Paid,Closed
```

Apply to rows 2–5000.

### 2. Filter views

**Data → Filter views → Create new filter view**

| View name | Tab | Filter |
|-----------|-----|--------|
| In transit | Orders | `status` = Shipped |
| Ready to pack | Orders | `status` = Delivered, `ck_batch_id` is empty |
| Awaiting CK pay | CK_batches | `status` = Received by CK |

### 3. Conditional formatting (optional)

**Orders → `ck_batch_id` empty and `status` = Delivered**

- Format → Conditional formatting
- Custom formula: `=AND($K2="",$C2="Delivered")`
- Highlight yellow → “needs CK batch assignment”

**Orders → same `simplified_lot`, multiple delivered rows**

- Helps spot orders that probably ship to CK together

### 4. `simplified_lot` convention

Build when you know the cards (from arbitrage buy list or email):

```
tarkans-cards3|oppression|blood-pet|read-runes
```

Rules:

- Lowercase, hyphenated seller slug
- `|` separated sorted card slugs
- **Hint only** — you still assign `ck_batch_id` manually when packing

---

## Linking TCG → CK (manual step)

Emails will **not** auto-link TCG orders to CK payouts.

1. Filter **Ready to pack** view
2. Group by `seller` or `simplified_lot`
3. Create a row on **CK_batches** → `CK-2026-07-02-A`
4. Paste that id into `ck_batch_id` on every related **Orders** row
5. Set those orders to `Sent to CK` when mailed

---

## Postgres inventory (Manifest Bread GUI)

The FastAPI app maintains **`inventory_lots`** (TCG buys) and **`ck_fulfillments`** (CK submissions) in Postgres. One lot per card line from **Opportunities**; multiple fulfillments per lot when you split across CK batches or hit CK max qty.

| Postgres | Sheets equivalent | When to set |
|----------|-------------------|-------------|
| `inventory_lots.tcg_order_id` | `Orders.tcg_order_id` | After checkout — seller order # from TCG order history |
| `ck_fulfillments.ck_batch_id` | `Orders.ck_batch_id` | When you pack a CK shipment (one fulfillment row per send) |

(`checkout_key` on the lot is optional — link by seller order # directly if you prefer.)

### Status mapping

| Sheets `Orders.status` | Lot `status` | Fulfillment `status` |
|------------------------|--------------|----------------------|
| Ordered | `ordered` | — |
| Shipped / Delivered | `inbound` or `on_hand` | — |
| Sent to CK | `on_hand` (qty decrements) | `sent` |
| Done | `depleted` when qty = 0 | `paid` |

### GUI workflow

1. Pick cards on **Opportunities** → **Add to inventory** (`status = on_hand`)
2. After TCG checkout → paste **`tcg_order_id`** on the lot; status → `ordered` / `inbound`
3. When packing for CK → open **→** on the row → add fulfillment with **`ck_batch_id`**, qty, status `sent` (decrements on-hand)
4. After CK payout → mark fulfillment `paid` (optionally set `paid_amount`)

Open [http://localhost:8000/inventory](http://localhost:8000/inventory) — filter by TCG order / CK batch, expected vs realized profit, or **No TCG order yet**.

### Tableau

Connect to Postgres and use:

| View | Use for |
|------|---------|
| `inventory_summary` | Lot-level expected vs realized (`inventory_with_realized`) |
| `inventory_fulfillment_detail` | One row per CK fulfillment joined to lot |
| `ck_fulfillments` | Raw fulfillment events |

### CLI (same DB)

```bash
# Link all unlinked lots from one seller to that seller's TCG order #
python pipeline/link_inventory.py seller \
  --seller "Tarkan's Cards3" \
  --tcg-order-id "D95E2DBE-6D3607-73354"

# Link specific lot ids to a TCG order
python pipeline/link_inventory.py tcg-batch \
  --ids 1,2,3 \
  --tcg-order-id "D95E2DBE-6D3607-73354"

# Record CK shipment (creates ck_fulfillments, decrements qty_on_hand)
python pipeline/link_inventory.py fulfill \
  --ids 1,2,3 \
  --ck-batch-id "CK-2026-07-02-A" \
  --status sent
```

### API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/inventory` | List lots with realized profit columns |
| `PATCH /api/inventory/{id}` | Update lot fields |
| `POST .../fulfillments` | Add CK submission |
| `POST /api/inventory/batch-link` | Bulk assign `tcg_order_id` |
| `POST /api/inventory/link-seller` | All lots from one seller → TCG order # |
| `GET /api/inventory/linking-summary` | Distinct TCG orders / CK batches for filters |

Legacy `/api/purchases/*` and the `purchases` table remain read-only for migration; new data goes through inventory only.

You can keep **Sheets** for email audit and use **Postgres inventory** as the arbitrage pick queue — copy the same `tcg_order_id` / `ck_batch_id` into both when useful.

---

## Email automation (optional)

Yahoo cannot upsert Sheets directly. Path:

```
Yahoo filter → forward tcgplayer.com → Gmail → Apps Script (Code.gs)
```

1. Copy `Code.gs` into **Extensions → Apps Script** on your spreadsheet
2. Set `SHEET_ID` (from the sheet URL: `/d/SHEET_ID/edit`)
3. Forward Yahoo mail to a Gmail inbox; label forwarded mail `cardbitrage/inbox`
4. Run `createTrigger()` once in Apps Script
5. Script runs every 15 minutes: parse order # → update or append **Orders** row

Adjust regex in `extractOrderId_` after you see real TCGplayer email formats.

---

## Weekly workflow

| When | Action |
|------|--------|
| Email arrives | Auto-upsert **Orders** (or log one row by hand) |
| Package arrives | Set `status` = Delivered |
| Pack for CK | Create **CK_batches** row, fill `ck_batch_id` on orders |
| CK pays | Update **CK_batches** `status` = Paid; orders → Done |

---

## Files in this folder

| File | Purpose |
|------|---------|
| `build_template.py` | Generates `Cardbitrage_Order_Tracker.xlsx` |
| `Orders.csv` / `CK_batches.csv` / `Cards.csv` | CSV-only import |
| `Code.gs` | Optional Gmail → Sheets upsert |
| `README.md` | This guide |
