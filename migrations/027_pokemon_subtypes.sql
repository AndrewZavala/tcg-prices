-- Subtype enrichment from pokemontcg.io (tags = slugified subtypes for is: search).

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS subtypes TEXT[],
    ADD COLUMN IF NOT EXISTS tags TEXT[];

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_subtypes ON pokemon_cards USING gin (subtypes);
CREATE INDEX IF NOT EXISTS idx_pokemon_cards_tags ON pokemon_cards USING gin (tags);
