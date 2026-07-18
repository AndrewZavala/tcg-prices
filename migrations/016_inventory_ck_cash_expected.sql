-- Freeze CK cash at buy (from opportunity) for Δ vs latest pipeline sample.

ALTER TABLE inventory_lots
    ADD COLUMN IF NOT EXISTS ck_cash_expected NUMERIC(12, 2);

-- Prefer the opportunity's CK cash at purchase time.
UPDATE inventory_lots il
SET ck_cash_expected = o.ck_cash
FROM opportunities o
WHERE il.opportunity_id = o.id
  AND il.ck_cash_expected IS NULL
  AND o.ck_cash IS NOT NULL;

-- Lots never refreshed still hold buy-time price in ck_cash.
UPDATE inventory_lots
SET ck_cash_expected = ck_cash
WHERE ck_cash_expected IS NULL
  AND ck_cash IS NOT NULL
  AND ck_price_snapshot IS NULL;

-- Manual / unmatched: fall back to current ck_cash so Δ is defined after next refresh.
UPDATE inventory_lots
SET ck_cash_expected = ck_cash
WHERE ck_cash_expected IS NULL
  AND ck_cash IS NOT NULL;

-- Recompute delta vs buy-time expected (not prior snapshot).
UPDATE inventory_lots
SET ck_cash_delta = ROUND(ck_cash - ck_cash_expected, 2)
WHERE ck_cash IS NOT NULL
  AND ck_cash_expected IS NOT NULL;

-- Refresh view so ck_cash_expected is visible via il.*.
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
