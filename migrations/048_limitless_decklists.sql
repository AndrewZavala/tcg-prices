-- Whether a Standard-legal card appears in Limitless TCG decklists (is:competitive). NULL = not checked.
-- Limitless shares decklists across reprints, so the flag is copied to every printing of an oracle.

ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS limitless_decklists BOOLEAN;
ALTER TABLE pokemon_cards
    ADD COLUMN IF NOT EXISTS limitless_checked_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_limitless_decklists
    ON pokemon_cards (limitless_decklists)
    WHERE limitless_decklists;
