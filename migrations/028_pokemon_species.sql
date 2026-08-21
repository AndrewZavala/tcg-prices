-- Pokémon species metadata (generation, legendary/mythical) from PokeAPI.

CREATE TABLE IF NOT EXISTS pokemon_species (
    dex_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    generation_id INTEGER NOT NULL,
    generation_name TEXT NOT NULL,
    is_legendary BOOLEAN NOT NULL DEFAULT FALSE,
    is_mythical BOOLEAN NOT NULL DEFAULT FALSE,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pokemon_species_generation ON pokemon_species (generation_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_species_legendary ON pokemon_species (is_legendary) WHERE is_legendary;
CREATE INDEX IF NOT EXISTS idx_pokemon_species_mythical ON pokemon_species (is_mythical) WHERE is_mythical;
