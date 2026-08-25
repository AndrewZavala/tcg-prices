-- Nested tag defs: parent_slug for oracle + art tags (subtags).

ALTER TABLE oracle_tag_defs
    ADD COLUMN IF NOT EXISTS parent_slug TEXT REFERENCES oracle_tag_defs (slug) ON DELETE SET NULL;

ALTER TABLE art_tag_defs
    ADD COLUMN IF NOT EXISTS parent_slug TEXT REFERENCES art_tag_defs (slug) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_oracle_tag_defs_parent ON oracle_tag_defs (parent_slug);
CREATE INDEX IF NOT EXISTS idx_art_tag_defs_parent ON art_tag_defs (parent_slug);
