-- Lock fulfillment expected CK revenue to ck_fulfillments.ck_adj (snapshot at sell order).
-- Do not fall back to live inventory_lots.ck_adj after pipeline CK price refresh.

CREATE TABLE IF NOT EXISTS app_migrations (
    id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_migrations WHERE id = '022_lock_fulfillment_ck_adj') THEN
        -- Best-effort lock for open lines that never stored a snapshot.
        UPDATE ck_fulfillments cf
        SET ck_adj = il.ck_adj
        FROM inventory_lots il
        WHERE il.id = cf.inventory_lot_id
          AND cf.ck_adj IS NULL
          AND il.ck_adj IS NOT NULL
          AND cf.status IN ('planned', 'packed', 'sent', 'paid');

        INSERT INTO app_migrations (id) VALUES ('022_lock_fulfillment_ck_adj');
    END IF;
END $$;

DROP VIEW IF EXISTS inventory_summary;
DROP VIEW IF EXISTS inventory_with_realized;

CREATE VIEW inventory_with_realized AS
SELECT
    il.*,
    COALESCE(f.qty_fulfilled, 0) AS qty_fulfilled,
    COALESCE(f.qty_packing, 0) AS qty_packing,
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
        SUM(cf.qty) FILTER (WHERE cf.status IN ('packed', 'sent', 'paid')) AS qty_fulfilled,
        SUM(cf.qty) FILTER (WHERE cf.status = 'planned') AS qty_packing,
        SUM(cf.qty) FILTER (WHERE cf.status = 'paid') AS qty_fulfilled_paid,
        ROUND(
            SUM(
                CASE
                    WHEN cf.status = 'paid' THEN
                        COALESCE(
                            cf.paid_amount,
                            cf.qty * COALESCE(cf.ck_adj, 0)
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
                        COALESCE(
                            CASE WHEN cf.status = 'paid' THEN cf.paid_amount ELSE NULL END,
                            cf.qty * COALESCE(cf.ck_adj, 0)
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
        ) AS realized_profit_sent
    FROM ck_fulfillments cf
    WHERE cf.inventory_lot_id = il.id
      AND cf.status NOT IN ('cancelled', 'rejected')
) f ON TRUE;

COMMENT ON VIEW inventory_with_realized IS
    'Inventory lots with fulfillment rollups; unpaid/sent expected revenue uses locked ck_fulfillments.ck_adj.';

CREATE VIEW inventory_summary AS
SELECT *
FROM inventory_with_realized;
