-- Purchase queue: GUI writes here; opportunities remain read-only from pipeline.

CREATE TABLE IF NOT EXISTS purchases (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'planned',
    qty INTEGER NOT NULL DEFAULT 1,
    opportunity_id BIGINT,
    snapshot_date DATE,
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    set_name TEXT,
    variant TEXT,
    finish TEXT,
    condition_display TEXT,
    condition_raw TEXT,
    seller TEXT,
    seller_key TEXT,
    seller_price NUMERIC(12, 2),
    shipping_price NUMERIC(12, 2),
    ck_cash NUMERIC(12, 2),
    ck_adj NUMERIC(12, 2),
    order_qty INTEGER,
    profit_per_copy NUMERIC(12, 2),
    order_profit NUMERIC(12, 2),
    order_roi NUMERIC(10, 2),
    tcg_url TEXT,
    ck_url TEXT,
    notes TEXT,
    checkout_key TEXT,
    tcg_order_id TEXT,
    ck_batch_id TEXT,
    CONSTRAINT purchases_status_check CHECK (
        status IN ('planned', 'ordered', 'shipped', 'at_ck', 'paid', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_purchases_status ON purchases (status);
CREATE INDEX IF NOT EXISTS idx_purchases_seller ON purchases (seller_key);
CREATE INDEX IF NOT EXISTS idx_purchases_created ON purchases (created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_purchases_active_dedup
    ON purchases (
        product_id,
        COALESCE(finish, ''),
        COALESCE(condition_raw, ''),
        COALESCE(seller_key, '')
    )
    WHERE status IN ('planned', 'ordered');

CREATE OR REPLACE VIEW purchases_active AS
SELECT *
FROM purchases
WHERE status NOT IN ('paid', 'cancelled');
