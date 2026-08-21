-- Oracle (functional identity) and illustration grouping for Pokémon printings.
-- Mirrors Scryfall oracle_id + illustration_id + unique:cards|art|prints rollup.

CREATE TABLE IF NOT EXISTS pokemon_oracles (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    representative_card_id TEXT REFERENCES pokemon_cards (id) ON DELETE SET NULL,
    gameplay JSONB NOT NULL DEFAULT '{}'::jsonb,
    printing_count INTEGER NOT NULL DEFAULT 0,
    art_variant_count INTEGER NOT NULL DEFAULT 0,
    first_release_date DATE,
    built_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS oracle_id TEXT REFERENCES pokemon_oracles (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS illustration_id TEXT,
    ADD COLUMN IF NOT EXISTS illustration_artist TEXT,
    ADD COLUMN IF NOT EXISTS is_oracle_representative BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_oracle_id ON pokemon_cards (oracle_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_illustration_id ON pokemon_cards (illustration_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_oracles_name ON pokemon_oracles (name);
