-- Per-card tags within a user's collection (private labels like draw, recycle).

DROP TABLE IF EXISTS collection_tags;

CREATE TABLE IF NOT EXISTS collection_item_tags (
    collection_id UUID NOT NULL,
    card_id TEXT NOT NULL,
    tag_slug TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (collection_id, card_id, tag_slug),
    FOREIGN KEY (collection_id, card_id)
        REFERENCES collection_items (collection_id, card_id) ON DELETE CASCADE,
    CHECK (char_length(tag_slug) BETWEEN 1 AND 32),
    CHECK (tag_slug ~ '^[a-z0-9][a-z0-9_-]*$')
);

CREATE INDEX IF NOT EXISTS idx_collection_item_tags_slug
    ON collection_item_tags (collection_id, tag_slug);

CREATE INDEX IF NOT EXISTS idx_collection_item_tags_card
    ON collection_item_tags (collection_id, card_id);
