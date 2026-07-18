-- Daily arbitrage opportunities (GUI read-only source)

CREATE TABLE IF NOT EXISTS opportunities_snapshots (
    snapshot_date DATE PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0,
    target_count INTEGER NOT NULL DEFAULT 0,
    ranked_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS opportunities (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL REFERENCES opportunities_snapshots(snapshot_date) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    set_name TEXT,
    variant TEXT,
    finish TEXT,
    condition_display TEXT,
    condition_raw TEXT,
    ck_cash NUMERIC(12, 2),
    ck_adj NUMERIC(12, 2),
    ck_max_qty INTEGER,
    lowest_price NUMERIC(12, 2),
    seller_price NUMERIC(12, 2),
    shipping_price NUMERIC(12, 2),
    seller TEXT,
    seller_key TEXT,
    lowest_qty INTEGER,
    max_qty INTEGER,
    max_qty_price NUMERIC(12, 2),
    order_qty INTEGER,
    profit_per_copy NUMERIC(12, 2),
    order_profit NUMERIC(12, 2),
    order_roi NUMERIC(10, 2),
    order_cost NUMERIC(12, 2),
    roi NUMERIC(10, 2),
    ck_url TEXT,
    tcg_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_opportunities_snapshot
    ON opportunities (snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_opportunities_profit
    ON opportunities (snapshot_date, order_profit DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_opportunities_seller
    ON opportunities (snapshot_date, seller_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunities_row_key
    ON opportunities (
        snapshot_date,
        product_id,
        COALESCE(finish, ''),
        COALESCE(condition_raw, ''),
        COALESCE(seller_key, ''),
        COALESCE(name, '')
    );

CREATE OR REPLACE VIEW opportunities_current AS
SELECT o.*
FROM opportunities o
INNER JOIN (
    SELECT MAX(snapshot_date) AS snapshot_date FROM opportunities_snapshots
) latest ON o.snapshot_date = latest.snapshot_date;
