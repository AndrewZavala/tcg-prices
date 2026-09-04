-- Team Rocket Dark Magneton (base5-11): Sonicboom is [C][C] for 20, not [G][G][C][C] for 40.
-- Upstream TCGdex cost/damage are wrong; also clears false is_multicolor from Grass costs.

UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Sonicboom' THEN
            jsonb_set(
              jsonb_set(elem, '{cost}', '["Colorless", "Colorless"]'::jsonb, true),
              '{damage}',
              '20',
              true
            )
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(attacks) = 'array' THEN attacks ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ),
    is_multicolor = FALSE,
    synced_at = NOW()
WHERE id = 'base5-11'
  AND category = 'Pokemon';
