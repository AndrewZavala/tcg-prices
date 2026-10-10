-- Binder front cover: either a card from the collection or an uploaded image. No row means a blank cover.

CREATE TABLE IF NOT EXISTS collection_binder_covers (
    collection_id UUID PRIMARY KEY REFERENCES collections (id) ON DELETE CASCADE,
    card_id TEXT,
    image BYTEA,
    image_mime TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT collection_binder_covers_one_source CHECK ((card_id IS NULL) <> (image IS NULL))
);
