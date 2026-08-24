-- Art-level custom tags (Spell Tag art: search).
-- Definitions are admin/tagger-curated; attachments apply to illustration_id
-- (same artwork across printings shares tags).

CREATE TABLE IF NOT EXISTS art_tag_defs (
    slug TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT,
    created_by UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT art_tag_defs_slug_format CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE TABLE IF NOT EXISTS art_tags (
    illustration_id TEXT NOT NULL,
    tag_slug TEXT NOT NULL REFERENCES art_tag_defs (slug) ON DELETE CASCADE,
    tagged_by UUID REFERENCES users (id) ON DELETE SET NULL,
    tagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (illustration_id, tag_slug)
);

CREATE INDEX IF NOT EXISTS idx_art_tags_slug ON art_tags (tag_slug);
CREATE INDEX IF NOT EXISTS idx_art_tags_illustration ON art_tags (illustration_id);

INSERT INTO art_tag_defs (slug, label, description)
VALUES
    ('night', 'Night', 'Nighttime / dark sky scene'),
    ('city', 'City', 'Urban or cityscape setting'),
    ('beach', 'Beach', 'Beach, shore, or oceanfront'),
    ('close-up', 'Close-up', 'Tight portrait or facial close-up'),
    ('full-body', 'Full Body', 'Full-body character pose')
ON CONFLICT (slug) DO NOTHING;
