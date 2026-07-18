-- TCGplayer prices from tcgcsv.com (market / low / mid per product + printing)

ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS tcg_market NUMERIC(12, 2);
ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS tcg_low NUMERIC(12, 2);
ALTER TABLE buylist_cards ADD COLUMN IF NOT EXISTS tcg_mid NUMERIC(12, 2);
