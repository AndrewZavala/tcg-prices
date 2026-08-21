-- User collections (Favorites + custom lists of card arts / printings).

CREATE TABLE IF NOT EXISTS collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom'
        CHECK (kind IN ('favorites', 'custom')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_collections_one_favorites
    ON collections (user_id)
    WHERE kind = 'favorites';

CREATE INDEX IF NOT EXISTS idx_collections_user ON collections (user_id);

CREATE TABLE IF NOT EXISTS collection_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    card_id TEXT NOT NULL REFERENCES pokemon_cards (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (collection_id, card_id)
);

CREATE INDEX IF NOT EXISTS idx_collection_items_card ON collection_items (card_id);
CREATE INDEX IF NOT EXISTS idx_collection_items_collection ON collection_items (collection_id);
