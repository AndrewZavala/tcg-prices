-- Need to Pack (planned) reserves free stock the same way packed/sent/paid do.
-- qty_on_hand = unreserved copies only (not also counted as inbound/on-hand
-- while sitting in Need to Pack / Need to Ship / etc.).

CREATE TABLE IF NOT EXISTS app_migrations (
    id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app_migrations WHERE id = '019_reserve_planned_qty') THEN
        UPDATE inventory_lots il
        SET
            qty_on_hand = il.qty_on_hand - p.qty_packing,
            status = CASE
                WHEN il.status = 'cancelled' THEN il.status
                WHEN (il.qty_on_hand - p.qty_packing) <= 0 THEN 'depleted'
                WHEN il.status = 'depleted' THEN 'on_hand'
                ELSE il.status
            END,
            updated_at = NOW()
        FROM (
            SELECT inventory_lot_id, SUM(qty)::int AS qty_packing
            FROM ck_fulfillments
            WHERE status = 'planned'
            GROUP BY inventory_lot_id
        ) p
        WHERE p.inventory_lot_id = il.id
          AND p.qty_packing > 0
          AND il.qty_on_hand >= p.qty_packing;

        INSERT INTO app_migrations (id) VALUES ('019_reserve_planned_qty');
    END IF;
END $$;

-- Refresh view comments via recreate (same shape as 018; clarifies reservation).
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
        -- Copies committed past packing (left free stock at packed+)
        SUM(cf.qty) FILTER (WHERE cf.status IN ('packed', 'sent', 'paid')) AS qty_fulfilled,
        -- Copies reserved in Need to Pack (also leave free stock)
        SUM(cf.qty) FILTER (WHERE cf.status = 'planned') AS qty_packing,
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
