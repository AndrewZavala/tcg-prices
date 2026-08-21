-- Oracle-level custom tags (Spell Tag otag: search).
-- Definitions are admin-curated; attachments apply to pokemon_oracles.

CREATE TABLE IF NOT EXISTS oracle_tag_defs (
    slug TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT,
    created_by UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT oracle_tag_defs_slug_format CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

CREATE TABLE IF NOT EXISTS oracle_tags (
    oracle_id TEXT NOT NULL REFERENCES pokemon_oracles (id) ON DELETE CASCADE,
    tag_slug TEXT NOT NULL REFERENCES oracle_tag_defs (slug) ON DELETE CASCADE,
    tagged_by UUID REFERENCES users (id) ON DELETE SET NULL,
    tagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (oracle_id, tag_slug)
);

CREATE INDEX IF NOT EXISTS idx_oracle_tags_slug ON oracle_tags (tag_slug);
CREATE INDEX IF NOT EXISTS idx_oracle_tags_oracle ON oracle_tags (oracle_id);

INSERT INTO oracle_tag_defs (slug, label, description)
VALUES
    ('rain-dance', 'Rain Dance', 'Attach as many Energy cards from your hand as you like'),
    ('gust', 'Gust', 'Gust effect / switch in an opposing Pokémon'),
    ('switch', 'Switch', 'Switch your Active Pokémon'),
    ('damage-increaser', 'Damage Increaser', 'Increases attack damage')
ON CONFLICT (slug) DO NOTHING;
