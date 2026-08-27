-- Keep: still in personal collection, but hidden from CK sell list.

ALTER TABLE collection_cards
  DROP CONSTRAINT IF EXISTS collection_cards_status_check;

ALTER TABLE collection_cards
  ADD CONSTRAINT collection_cards_status_check
  CHECK (status IN ('active', 'sold', 'keep'));
