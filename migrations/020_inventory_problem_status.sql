-- Problem lots: physical stock waiting on TCG/seller resolution (wrong card, etc.).
-- Still inventory capital, but not sellable to CK until status returns to on_hand.

ALTER TABLE inventory_lots DROP CONSTRAINT IF EXISTS inventory_lots_status_check;

ALTER TABLE inventory_lots ADD CONSTRAINT inventory_lots_status_check CHECK (
    status IN ('ordered', 'inbound', 'on_hand', 'problem', 'depleted', 'cancelled')
);
