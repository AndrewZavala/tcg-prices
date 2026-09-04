-- Cached flag for is:multicolor search (types + attack costs + energy-in-text).
-- Colorless ignored unless the Pokémon is Colorless-type.

ALTER TABLE pokemon_cards
  ADD COLUMN IF NOT EXISTS is_multicolor BOOLEAN NOT NULL DEFAULT FALSE;

-- One-shot backfill (startup re-applies all migrations; skip if already populated).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pokemon_cards WHERE category = 'Pokemon' LIMIT 1)
     AND NOT EXISTS (SELECT 1 FROM pokemon_cards WHERE is_multicolor LIMIT 1)
  THEN
    UPDATE pokemon_cards AS c
    SET is_multicolor = TRUE
    WHERE c.category = 'Pokemon'
      AND (
        SELECT COUNT(DISTINCT color) FROM (
          SELECT t.color
          FROM unnest(COALESCE(c.types, ARRAY[]::text[])) AS t(color)
          WHERE t.color IS NOT NULL AND t.color <> ''

          UNION

          SELECT cost_row.cost_el AS color
          FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(c.attacks) = 'array' THEN c.attacks ELSE '[]'::jsonb END
          ) AS atk,
          LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(atk->'cost') = 'array' THEN atk->'cost' ELSE '[]'::jsonb END
          ) AS cost_row(cost_el)
          WHERE cost_row.cost_el IS NOT NULL
            AND cost_row.cost_el <> ''
            AND (
              cost_row.cost_el <> 'Colorless'
              OR 'Colorless' = ANY(COALESCE(c.types, ARRAY[]::text[]))
            )

          UNION

          SELECT v.color
          FROM (
            SELECT
              COALESCE(c.description, '') || ' ' ||
              COALESCE(c.card_data->>'effect', '') || ' ' ||
              COALESCE(c.attacks::text, '') || ' ' ||
              COALESCE(c.abilities::text, '') AS txt
          ) AS rules
          CROSS JOIN (
            VALUES
              ('Grass', 'G'),
              ('Fire', 'R'),
              ('Water', 'W'),
              ('Lightning', 'L'),
              ('Psychic', 'P'),
              ('Fighting', 'F'),
              ('Darkness', 'D'),
              ('Metal', 'M'),
              ('Fairy', 'Y'),
              ('Dragon', 'N')
          ) AS v(color, letter)
          WHERE rules.txt ILIKE ('%' || v.color || ' Energy%')
             OR rules.txt LIKE ('%{' || v.letter || '}%')
             OR rules.txt ILIKE ('%{' || v.color || '}%')
        ) AS colors
        WHERE color IS NOT NULL AND color <> ''
      ) >= 2;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_pokemon_cards_multicolor
  ON pokemon_cards (is_multicolor)
  WHERE is_multicolor;
