-- Pokémon TCG catalog (TCGdex ingest) — separate from MTG buylist tables.

CREATE TABLE IF NOT EXISTS pokemon_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    series_id TEXT,
    series_name TEXT,
    release_date DATE,
    logo_url TEXT,
    symbol_url TEXT,
    card_count_official INTEGER,
    card_count_total INTEGER,
    legal_standard BOOLEAN,
    legal_expanded BOOLEAN,
    tcg_online_code TEXT,
    source_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pokemon_cards (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES pokemon_sets (id) ON DELETE CASCADE,
    local_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    hp INTEGER,
    types TEXT[],
    stage TEXT,
    evolve_from TEXT,
    dex_ids INTEGER[],
    description TEXT,
    rarity TEXT,
    illustrator TEXT,
    regulation_mark TEXT,
    legal_standard BOOLEAN,
    legal_expanded BOOLEAN,
    image_url TEXT,
    retreat INTEGER,
    attacks JSONB,
    abilities JSONB,
    weaknesses JSONB,
    resistances JSONB,
    variants JSONB,
    card_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_set_id ON pokemon_cards (set_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_name_trgm ON pokemon_cards USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_dex_ids ON pokemon_cards USING gin (dex_ids);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_stage ON pokemon_cards (stage);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_evolve_from ON pokemon_cards (evolve_from);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_category ON pokemon_cards (category);

CREATE TABLE IF NOT EXISTS pokemon_sync_log (
    id BIGSERIAL PRIMARY KEY,
    set_id TEXT NOT NULL,
    cards_upserted INTEGER NOT NULL DEFAULT 0,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
