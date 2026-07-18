-- Inventory + CK fulfillments (replaces purchases as source of truth for on-hand stock).
-- Pipeline still writes opportunities only; GUI writes inventory_lots + ck_fulfillments.

CREATE TABLE IF NOT EXISTS inventory_lots (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acquired_at DATE,
    status TEXT NOT NULL DEFAULT 'on_hand',
    qty_original INTEGER NOT NULL DEFAULT 1,
    qty_on_hand INTEGER NOT NULL DEFAULT 1,
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
    ck_max_qty INTEGER,
    expected_ck_qty INTEGER,
    profit_per_copy NUMERIC(12, 2),
    expected_profit NUMERIC(12, 2),
    expected_roi NUMERIC(10, 2),
    tcg_url TEXT,
    ck_url TEXT,
    notes TEXT,
    checkout_key TEXT,
    tcg_order_id TEXT,
    legacy_ck_batch_id TEXT,
    legacy_purchase_id BIGINT,
    CONSTRAINT inventory_lots_status_check CHECK (
        status IN ('ordered', 'inbound', 'on_hand', 'depleted', 'cancelled')
    ),
    CONSTRAINT inventory_lots_qty_original_check CHECK (qty_original >= 1),
    CONSTRAINT inventory_lots_qty_on_hand_check CHECK (qty_on_hand >= 0),
    CONSTRAINT inventory_lots_qty_on_hand_lte_original CHECK (qty_on_hand <= qty_original)
);

CREATE TABLE IF NOT EXISTS ck_fulfillments (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    inventory_lot_id BIGINT NOT NULL REFERENCES inventory_lots (id) ON DELETE CASCADE,
    qty INTEGER NOT NULL,
    ck_batch_id TEXT,
    ck_ref TEXT,
    ck_adj NUMERIC(12, 2),
    status TEXT NOT NULL DEFAULT 'planned',
    paid_amount NUMERIC(12, 2),
    sent_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    notes TEXT,
    CONSTRAINT ck_fulfillments_qty_check CHECK (qty >= 1),
    CONSTRAINT ck_fulfillments_status_check CHECK (
        status IN ('planned', 'sent', 'paid', 'rejected', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_inventory_lots_status ON inventory_lots (status);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_seller ON inventory_lots (seller_key);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_tcg_order ON inventory_lots (tcg_order_id)
    WHERE tcg_order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_lots_created ON inventory_lots (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_product ON inventory_lots (product_id);

CREATE INDEX IF NOT EXISTS idx_ck_fulfillments_lot ON ck_fulfillments (inventory_lot_id);
CREATE INDEX IF NOT EXISTS idx_ck_fulfillments_batch ON ck_fulfillments (ck_batch_id)
    WHERE ck_batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ck_fulfillments_status ON ck_fulfillments (status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_lots_active_dedup
    ON inventory_lots (
        product_id,
        COALESCE(finish, ''),
        COALESCE(condition_raw, ''),
        COALESCE(seller_key, '')
    )
    WHERE status IN ('ordered', 'inbound', 'on_hand');

-- One-time migration from purchases (idempotent via legacy_purchase_id).
INSERT INTO inventory_lots (
    created_at,
    updated_at,
    acquired_at,
    status,
    qty_original,
    qty_on_hand,
    opportunity_id,
    snapshot_date,
    product_id,
    name,
    set_name,
    variant,
    finish,
    condition_display,
    condition_raw,
    seller,
    seller_key,
    seller_price,
    shipping_price,
    ck_cash,
    ck_adj,
    expected_ck_qty,
    profit_per_copy,
    expected_profit,
    expected_roi,
    tcg_url,
    ck_url,
    notes,
    checkout_key,
    tcg_order_id,
    legacy_ck_batch_id,
    legacy_purchase_id
)
SELECT
    p.created_at,
    p.updated_at,
    COALESCE(p.snapshot_date, p.created_at::date),
    CASE
        WHEN p.status = 'cancelled' THEN 'cancelled'
        WHEN p.status IN ('planned', 'ordered', 'shipped') THEN
            CASE WHEN p.status = 'ordered' THEN 'ordered' ELSE 'on_hand' END
        WHEN p.status IN ('at_ck', 'paid') THEN 'on_hand'
        ELSE 'on_hand'
    END,
    p.qty,
    p.qty,
    p.opportunity_id,
    p.snapshot_date,
    p.product_id,
    p.name,
    p.set_name,
    p.variant,
    p.finish,
    p.condition_display,
    p.condition_raw,
    p.seller,
    p.seller_key,
    p.seller_price,
    p.shipping_price,
    p.ck_cash,
    p.ck_adj,
    COALESCE(p.order_qty, p.qty),
    p.profit_per_copy,
    p.order_profit,
    p.order_roi,
    p.tcg_url,
    p.ck_url,
    p.notes,
    p.checkout_key,
    p.tcg_order_id,
    p.ck_batch_id,
    p.id
FROM purchases p
WHERE NOT EXISTS (
    SELECT 1 FROM inventory_lots il WHERE il.legacy_purchase_id = p.id
);

CREATE OR REPLACE VIEW inventory_with_realized AS
SELECT
    il.*,
    COALESCE(f.qty_fulfilled, 0) AS qty_fulfilled,
    COALESCE(f.qty_fulfilled_paid, 0) AS qty_fulfilled_paid,
    il.qty_on_hand AS qty_remaining,
    f.realized_profit_paid,
    f.realized_profit_sent,
    CASE
        WHEN il.qty_on_hand > 0 AND il.seller_price IS NOT NULL THEN
            ROUND(
                il.qty_on_hand * il.seller_price
                + COALESCE(il.shipping_price, 0) * (il.qty_on_hand::numeric / NULLIF(il.qty_original, 0)),
                2
            )
        ELSE 0
    END AS at_risk_cost
FROM inventory_lots il
LEFT JOIN LATERAL (
    SELECT
        SUM(cf.qty) AS qty_fulfilled,
        SUM(cf.qty) FILTER (WHERE cf.status = 'paid') AS qty_fulfilled_paid,
        ROUND(
            SUM(
                CASE
                    WHEN cf.status = 'paid' THEN
                        COALESCE(
                            cf.paid_amount,
                            cf.qty * COALESCE(cf.ck_adj, il.ck_adj, 0)
                        )
                        - (
                            cf.qty * COALESCE(il.seller_price, 0)
                            + COALESCE(il.shipping_price, 0)
                              * (cf.qty::numeric / NULLIF(il.qty_original, 0))
                        )
                    ELSE 0
                END
            ),
            2
        ) AS realized_profit_paid,
        ROUND(
            SUM(
                CASE
                    WHEN cf.status IN ('sent', 'paid') THEN
                        cf.qty * COALESCE(cf.ck_adj, il.ck_adj, 0)
                        - (
                            cf.qty * COALESCE(il.seller_price, 0)
                            + COALESCE(il.shipping_price, 0)
                              * (cf.qty::numeric / NULLIF(il.qty_original, 0))
                        )
                    ELSE 0
                END
            ),
            2
        ) AS realized_profit_sent
    FROM ck_fulfillments cf
    WHERE cf.inventory_lot_id = il.id
      AND cf.status NOT IN ('cancelled', 'rejected')
) f ON TRUE;
