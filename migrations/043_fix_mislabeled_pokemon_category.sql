-- Reclassify Pokémon cards mislabeled as Trainer/Energy.
-- Heuristic: hp > 0 plus stage, types, or dex_ids (fossils keep Trainer — HP only).
-- Example: Majestic Dawn Glameow (dp5-65) was stored as Trainer.

UPDATE pokemon_cards
SET category = 'Pokemon',
    card_data = CASE
        WHEN card_data ? 'category'
        THEN jsonb_set(card_data, '{category}', '"Pokemon"')
        ELSE card_data
    END,
    synced_at = NOW()
WHERE category IS DISTINCT FROM 'Pokemon'
  AND hp > 0
  AND (
    (stage IS NOT NULL AND stage <> '')
    OR (types IS NOT NULL AND types <> '{}')
    OR (dex_ids IS NOT NULL AND dex_ids <> '{}')
  );
