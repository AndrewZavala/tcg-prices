-- CK price refresh: prior snapshot + day-over-day delta on inventory lots.

ALTER TABLE inventory_lots
    ADD COLUMN IF NOT EXISTS ck_cash_prior NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS ck_cash_delta NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS ck_price_snapshot DATE;

-- Must drop — CREATE OR REPLACE cannot reorder expanded il.* columns in PostgreSQL.
DROP VIEW IF EXISTS inventory_summary;
DROP VIEW IF EXISTS inventory_with_realized;

CREATE VIEW inventory_with_realized AS
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

CREATE VIEW inventory_summary AS
SELECT *
FROM inventory_with_realized;
