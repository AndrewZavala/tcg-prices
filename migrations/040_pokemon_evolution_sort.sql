-- Evolution chain metadata for type-based card sort (keeps lines together).

ALTER TABLE pokemon_species
    ADD COLUMN IF NOT EXISTS evolution_chain_id BIGINT,
    ADD COLUMN IF NOT EXISTS chain_root_dex_id INTEGER,
    ADD COLUMN IF NOT EXISTS chain_stage_order SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS chain_sort_type TEXT;

CREATE INDEX IF NOT EXISTS idx_pokemon_species_evolution_chain
    ON pokemon_species (evolution_chain_id);

CREATE INDEX IF NOT EXISTS idx_pokemon_species_chain_root
    ON pokemon_species (chain_root_dex_id);

CREATE INDEX IF NOT EXISTS idx_pokemon_species_chain_sort_type
    ON pokemon_species (chain_sort_type);
