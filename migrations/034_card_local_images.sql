-- Local self-hosted card art flags (files live on disk /media/cards/{id}/).

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS image_local BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS image_local_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_image_local
    ON pokemon_cards (image_local)
    WHERE image_local = FALSE;
