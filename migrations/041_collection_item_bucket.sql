-- Main vs considering bucket for cube/list building.

ALTER TABLE collection_items
    ADD COLUMN IF NOT EXISTS bucket TEXT NOT NULL DEFAULT 'main'
        CHECK (bucket IN ('main', 'considering'));

CREATE INDEX IF NOT EXISTS idx_collection_items_collection_bucket
    ON collection_items (collection_id, bucket);
