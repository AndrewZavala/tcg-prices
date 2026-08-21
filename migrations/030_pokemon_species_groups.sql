-- Species flags/groups for Star Piece filters (baby, starter, paradox, etc.).

ALTER TABLE pokemon_species
    ADD COLUMN IF NOT EXISTS is_baby BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE pokemon_species
    ADD COLUMN IF NOT EXISTS species_groups TEXT[] NOT NULL DEFAULT '{}'::text[];

CREATE INDEX IF NOT EXISTS idx_pokemon_species_baby
    ON pokemon_species (is_baby)
    WHERE is_baby;

CREATE INDEX IF NOT EXISTS idx_pokemon_species_groups
    ON pokemon_species USING gin (species_groups);
