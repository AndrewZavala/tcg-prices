-- Tableau / reporting views for inventory + fulfillments.

CREATE OR REPLACE VIEW inventory_fulfillment_detail AS
SELECT
    cf.id AS fulfillment_id,
    cf.created_at AS fulfillment_created_at,
    cf.updated_at AS fulfillment_updated_at,
    cf.qty AS fulfillment_qty,
    cf.ck_batch_id,
    cf.ck_ref,
    cf.ck_adj AS fulfillment_ck_adj,
    cf.status AS fulfillment_status,
    cf.paid_amount,
    cf.sent_at,
    cf.paid_at,
    cf.notes AS fulfillment_notes,
    il.id AS lot_id,
    il.created_at AS lot_created_at,
    il.acquired_at,
    il.status AS lot_status,
    il.qty_original,
    il.qty_on_hand,
    il.opportunity_id,
    il.snapshot_date,
    il.product_id,
    il.name,
    il.set_name,
    il.variant,
    il.finish,
    il.condition_display,
    il.seller,
    il.seller_key,
    il.seller_price,
    il.shipping_price,
    il.ck_cash,
    il.ck_adj AS lot_ck_adj,
    il.ck_max_qty,
    il.expected_ck_qty,
    il.expected_profit,
    il.expected_roi,
    il.tcg_order_id,
    il.tcg_url,
    il.ck_url,
    il.notes AS lot_notes
FROM ck_fulfillments cf
JOIN inventory_lots il ON il.id = cf.inventory_lot_id
WHERE cf.status NOT IN ('cancelled', 'rejected');

CREATE OR REPLACE VIEW inventory_summary AS
SELECT *
FROM inventory_with_realized;
