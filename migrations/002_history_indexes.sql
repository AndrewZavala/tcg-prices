-- Indexes for price history and collection matching

CREATE INDEX IF NOT EXISTS idx_buylist_cards_history
    ON buylist_cards (scryfall_id, finish, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_buylist_cards_name_snapshot
    ON buylist_cards (name, snapshot_date DESC);
