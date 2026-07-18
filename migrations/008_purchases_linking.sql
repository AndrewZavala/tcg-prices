-- Phase 2: indexes for order-tracker linking columns on purchases.

CREATE INDEX IF NOT EXISTS idx_purchases_checkout_key
    ON purchases (checkout_key)
    WHERE checkout_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_purchases_tcg_order_id
    ON purchases (tcg_order_id)
    WHERE tcg_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_purchases_ck_batch_id
    ON purchases (ck_batch_id)
    WHERE ck_batch_id IS NOT NULL;
