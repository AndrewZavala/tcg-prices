-- Latest TCGplayer USD prices (tcgcsv.com, refreshed monthly). One row per printing + variant.

CREATE TABLE IF NOT EXISTS pokemon_card_prices (
    card_id TEXT NOT NULL REFERENCES pokemon_cards(id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    product_id TEXT NOT NULL,
    market_price NUMERIC(12, 2),
    low_price NUMERIC(12, 2),
    mid_price NUMERIC(12, 2),
    high_price NUMERIC(12, 2),
    direct_low_price NUMERIC(12, 2),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (card_id, variant)
);

-- Cheapest variant price, cached for sort / usd filters / collection totals.
ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS price_usd NUMERIC(12, 2);
ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS price_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_price_usd
    ON pokemon_cards (price_usd)
    WHERE price_usd IS NOT NULL;
