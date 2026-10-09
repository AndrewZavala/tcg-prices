-- Binder view: per-card pocket or table position, plus saved layout snapshots.

ALTER TABLE collection_items
    ADD COLUMN IF NOT EXISTS binder_slot INTEGER,
    ADD COLUMN IF NOT EXISTS table_x REAL,
    ADD COLUMN IF NOT EXISTS table_y REAL,
    ADD COLUMN IF NOT EXISTS table_z INTEGER;

-- One card per pocket; deferred so swaps can be written in a single transaction.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'collection_items_binder_slot_uq'
    ) THEN
        ALTER TABLE collection_items
            ADD CONSTRAINT collection_items_binder_slot_uq
            UNIQUE (collection_id, binder_slot) DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS collection_binder_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    is_auto BOOLEAN NOT NULL DEFAULT TRUE,
    layout JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_binder_snapshots_collection
    ON collection_binder_snapshots (collection_id, created_at DESC);
