-- Per-user collection labels (private to the owning account).

CREATE TABLE IF NOT EXISTS collection_tags (
    collection_id UUID NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    tag_slug TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (collection_id, tag_slug),
    CHECK (char_length(tag_slug) BETWEEN 1 AND 32),
    CHECK (tag_slug ~ '^[a-z0-9][a-z0-9_-]*$')
);

CREATE INDEX IF NOT EXISTS idx_collection_tags_slug ON collection_tags (tag_slug);
