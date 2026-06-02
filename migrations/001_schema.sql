-- CK buylist schema v1

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS buylist_snapshots (
    snapshot_date DATE PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'api'
);

CREATE TABLE IF NOT EXISTS buylist_cards (
    snapshot_date DATE NOT NULL REFERENCES buylist_snapshots(snapshot_date) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    set_name TEXT NOT NULL,
    collector_number TEXT,
    finish TEXT,
    cash_price NUMERIC(12, 2),
    credit_price NUMERIC(12, 2),
    max_qty INTEGER,
    slug TEXT,
    rarity_bucket TEXT,
    card_type TEXT,
    source_file TEXT,
    clean_set TEXT,
    set_code TEXT,
    scryfall_collector_number TEXT,
    scryfall_id TEXT,
    tcgplayer_id TEXT,
    tcgplayer_etched_id TEXT,
    usd NUMERIC(12, 2),
    usd_foil NUMERIC(12, 2),
    usd_etched NUMERIC(12, 2),
    sku TEXT,
    variation TEXT,
    PRIMARY KEY (snapshot_date, product_id)
);

CREATE INDEX IF NOT EXISTS idx_buylist_cards_scryfall_id
    ON buylist_cards (scryfall_id);

CREATE INDEX IF NOT EXISTS idx_buylist_cards_set_code
    ON buylist_cards (set_code);

CREATE INDEX IF NOT EXISTS idx_buylist_cards_name_trgm
    ON buylist_cards USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_buylist_cards_cash_price
    ON buylist_cards (cash_price DESC NULLS LAST);

CREATE OR REPLACE VIEW buylist_current AS
SELECT c.*
FROM buylist_cards c
INNER JOIN (
    SELECT MAX(snapshot_date) AS snapshot_date FROM buylist_snapshots
) latest ON c.snapshot_date = latest.snapshot_date;
