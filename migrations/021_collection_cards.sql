-- Personal Stacks collection (separate from TCG flip inventory_lots).

CREATE TABLE IF NOT EXISTS collection_import_files (
    file_name TEXT PRIMARY KEY,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS collection_cards (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    batch_file TEXT NOT NULL,
    scan_order TEXT NOT NULL,
    scryfall_id TEXT NOT NULL,
    set_code TEXT,
    collector_number TEXT,
    finish TEXT NOT NULL DEFAULT 'normal',
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    colors TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    sold_at TIMESTAMPTZ,
    notes TEXT,
    CONSTRAINT collection_cards_status_check CHECK (status IN ('active', 'sold')),
    CONSTRAINT collection_cards_qty_check CHECK (quantity >= 1),
    CONSTRAINT collection_cards_batch_scan_unique UNIQUE (batch_file, scan_order)
);

CREATE INDEX IF NOT EXISTS idx_collection_cards_status ON collection_cards (status);
CREATE INDEX IF NOT EXISTS idx_collection_cards_scryfall ON collection_cards (scryfall_id);
CREATE INDEX IF NOT EXISTS idx_collection_cards_batch ON collection_cards (batch_file);
CREATE INDEX IF NOT EXISTS idx_collection_cards_sold_at ON collection_cards (sold_at DESC NULLS LAST);
