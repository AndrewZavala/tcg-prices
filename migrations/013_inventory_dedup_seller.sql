-- Dedup active inventory by seller identity, not just empty seller_key.
-- Previously product_id + blank seller_key blocked every seller of the same printing.

DROP INDEX IF EXISTS idx_inventory_lots_active_dedup;

CREATE UNIQUE INDEX idx_inventory_lots_active_dedup
    ON inventory_lots (
        product_id,
        COALESCE(finish, ''),
        COALESCE(condition_raw, ''),
        COALESCE(
            NULLIF(BTRIM(seller_key), ''),
            LOWER(BTRIM(COALESCE(seller, '')))
        )
    )
    WHERE status IN ('ordered', 'inbound', 'on_hand');
