-- Card data corrections (types, attack costs, Hoppip attacks) + multicolor recompute
-- without Pokédex flavor text (description). See docs/CARD_DATA_FIXES_PLAN.md.

-- Dark Magneton Team Rocket holo: Sonicboom Colorless×2 / 20
UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Sonicboom' THEN
            jsonb_set(
              jsonb_set(elem, '{cost}', '["Colorless", "Colorless"]'::jsonb, true),
              '{damage}', '20', true
            )
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(attacks) = 'array' THEN attacks ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ),
    synced_at = NOW()
WHERE id = 'base5-11';

-- Umbreon Neo Discovery: Pursuit Darkness (not Metal)
UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Pursuit' THEN
            jsonb_set(elem, '{cost}', '["Darkness", "Colorless", "Colorless"]'::jsonb, true)
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(attacks) = 'array' THEN attacks ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ),
    synced_at = NOW()
WHERE id = 'neo2-32';

-- Volbeat Emerald: Double-edge Grass (not Lightning)
UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Double-edge' THEN
            jsonb_set(elem, '{cost}', '["Grass", "Colorless"]'::jsonb, true)
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(attacks) = 'array' THEN attacks ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ),
    synced_at = NOW()
WHERE id = 'ex9-42';

-- Magnemite δ: Magnetic Blast Lightning (not Grass)
UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Magnetic Blast' THEN
            jsonb_set(elem, '{cost}', '["Lightning", "Colorless"]'::jsonb, true)
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(attacks) = 'array' THEN attacks ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ),
    synced_at = NOW()
WHERE id = 'ex11-74';

-- Yanmega Legends Awakened: Pursue and Turn GGCC (not GGMM)
UPDATE pokemon_cards
SET attacks = (
      SELECT jsonb_agg(
        CASE
          WHEN elem->>'name' = 'Pursue and Turn' THEN
            jsonb_set(
              elem, '{cost}',
              '["Grass", "Grass", "Colorless", "Colorless"]'::jsonb,
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
    synced_at = NOW()
WHERE id = 'dp6-17';

-- Hoppip Expedition: single Sleep Powder Grass / 10
UPDATE pokemon_cards
SET attacks = '[
  {
    "cost": ["Grass"],
    "name": "Sleep Powder",
    "damage": 10,
    "effect": "Flip a coin. If heads, the Defending Pokémon is now Asleep."
  }
]'::jsonb,
    synced_at = NOW()
WHERE id = 'ecard1-112';

-- Type corrections
UPDATE pokemon_cards SET types = ARRAY['Fighting']::text[], synced_at = NOW() WHERE id = 'ex10-44';
UPDATE pokemon_cards SET types = ARRAY['Fighting']::text[], synced_at = NOW() WHERE id = 'ex11-44';
UPDATE pokemon_cards SET types = ARRAY['Fighting']::text[], synced_at = NOW() WHERE id = 'ex11-82';
UPDATE pokemon_cards SET types = ARRAY['Metal']::text[], synced_at = NOW() WHERE id = 'ecard3-H19';

-- Sync card_data.types when present
UPDATE pokemon_cards
SET card_data = jsonb_set(card_data, '{types}', to_jsonb(types), true)
WHERE id IN ('ex10-44', 'ex11-44', 'ex11-82', 'ecard3-H19')
  AND card_data ? 'types';

-- Full multicolor recompute (no description / flavor text)
UPDATE pokemon_cards SET is_multicolor = FALSE;

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
