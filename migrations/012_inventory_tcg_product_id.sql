-- Canonical TCGplayer product id for CK buylist matching (independent of manual dedup keys).

ALTER TABLE inventory_lots
    ADD COLUMN IF NOT EXISTS tcg_product_id TEXT;

CREATE INDEX IF NOT EXISTS idx_inventory_lots_tcg_product_id
    ON inventory_lots (tcg_product_id)
    WHERE tcg_product_id IS NOT NULL;

-- Numeric product_id values from opportunity-sourced lots.
UPDATE inventory_lots
SET tcg_product_id = TRIM(product_id)
WHERE tcg_product_id IS NULL
  AND product_id ~ '^\d+$';

-- Parse /product/{id} from stored listing URLs.
UPDATE inventory_lots
SET tcg_product_id = (regexp_match(tcg_url, '/product/(\d+)', 'i'))[1]
WHERE tcg_product_id IS NULL
  AND tcg_url ~* '/product/\d+';
