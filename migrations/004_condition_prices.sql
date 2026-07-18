-- Condition-aware TCG buy prices and adjusted CK cash

ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS tcg_buy_price NUMERIC(12, 2);
ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS tcg_listing_condition TEXT;
ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS ck_cash_adjusted NUMERIC(12, 2);
ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS condition_multiplier NUMERIC(6, 4);

-- Recreate view so new columns are visible (Postgres does not expand SELECT * on ALTER)
CREATE OR REPLACE VIEW buylist_current AS
SELECT c.*
FROM buylist_cards c
INNER JOIN (
    SELECT MAX(snapshot_date) AS snapshot_date FROM buylist_snapshots
) latest ON c.snapshot_date = latest.snapshot_date;
