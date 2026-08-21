-- TCGplayer product id for Pokémon printings (from TCGdex pricing.tcgplayer).

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS tcgplayer_product_id TEXT;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_tcgplayer_product_id
    ON pokemon_cards (tcgplayer_product_id)
    WHERE tcgplayer_product_id IS NOT NULL;
