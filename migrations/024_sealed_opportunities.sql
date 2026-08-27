-- Sealed-product arbitrage opportunities (CK sealed buylist + TCGCSV)

CREATE TABLE IF NOT EXISTS sealed_opportunities_snapshots (
    snapshot_date DATE PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    ck_buy_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sealed_opportunities (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL REFERENCES sealed_opportunities_snapshots(snapshot_date) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    ck_product_id TEXT,
    name TEXT NOT NULL,
    set_name TEXT,
    tcg_name TEXT,
    match_score NUMERIC(6, 4),
    ck_cash NUMERIC(12, 2),
    ck_max_qty INTEGER,
    lowest_price NUMERIC(12, 2),
    seller_price NUMERIC(12, 2),
    shipping_price NUMERIC(12, 2),
    seller TEXT,
    seller_key TEXT,
    order_qty INTEGER,
    profit_per_copy NUMERIC(12, 2),
    order_profit NUMERIC(12, 2),
    order_roi NUMERIC(10, 2),
    order_cost NUMERIC(12, 2),
    roi NUMERIC(10, 2),
    ck_url TEXT,
    tcg_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_sealed_opportunities_snapshot
    ON sealed_opportunities (snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_sealed_opportunities_profit
    ON sealed_opportunities (snapshot_date, order_profit DESC NULLS LAST);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sealed_opportunities_row_key
    ON sealed_opportunities (
        snapshot_date,
        product_id,
        COALESCE(ck_product_id, ''),
        COALESCE(name, '')
    );

CREATE OR REPLACE VIEW sealed_opportunities_current AS
SELECT o.*
FROM sealed_opportunities o
INNER JOIN (
    SELECT MAX(snapshot_date) AS snapshot_date FROM sealed_opportunities_snapshots
) latest ON o.snapshot_date = latest.snapshot_date;
