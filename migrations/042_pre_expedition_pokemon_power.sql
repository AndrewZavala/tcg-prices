-- Rewrite mislabeled Poké-POWER / Poké-BODY → Pokemon Power on pre-Expedition sets.
-- Poké-Power was introduced with Expedition (e-Card); earlier sets only had Pokémon Power.
-- Sets: Base Set, Jungle, Fossil, Base Set 2, Team Rocket, Gym Heroes/Challenge, Neo 1–4.

UPDATE pokemon_cards AS c
SET abilities = sub.fixed,
    synced_at = NOW()
FROM (
  SELECT
    c2.id,
    (
      SELECT jsonb_agg(
        CASE
          WHEN regexp_replace(
                 translate(
                   lower(COALESCE(elem->>'type', '')),
                   'àáâãäåāăąèéêëēĕėęěìíîïīĭįıòóôõöøōŏőùúûüūŭůűųýÿñç',
                   'aaaaaaaaaeeeeeeeeeeiiiiiiiiiooooooooouuuuuuuuuuyync'
                 ),
                 '[^a-z0-9]',
                 '',
                 'g'
               ) IN ('pokepower', 'pokebody')
          THEN jsonb_set(elem, '{type}', '"Pokemon Power"', true)
          ELSE elem
        END
        ORDER BY ord
      )
      FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(c2.abilities) = 'array' THEN c2.abilities ELSE '[]'::jsonb END
      ) WITH ORDINALITY AS t(elem, ord)
    ) AS fixed
  FROM pokemon_cards c2
  WHERE c2.set_id IN (
      'base1', 'base2', 'base3', 'base4', 'base5',
      'gym1', 'gym2',
      'neo1', 'neo2', 'neo3', 'neo4'
    )
    AND c2.abilities IS NOT NULL
    AND jsonb_typeof(c2.abilities) = 'array'
    AND jsonb_array_length(c2.abilities) > 0
    AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(c2.abilities) AS elem
      WHERE regexp_replace(
              translate(
                lower(COALESCE(elem->>'type', '')),
                'àáâãäåāăąèéêëēĕėęěìíîïīĭįıòóôõöøōŏőùúûüūŭůűųýÿñç',
                'aaaaaaaaaeeeeeeeeeeiiiiiiiiiooooooooouuuuuuuuuuyync'
              ),
              '[^a-z0-9]',
              '',
              'g'
            ) IN ('pokepower', 'pokebody')
    )
) AS sub
WHERE c.id = sub.id
  AND sub.fixed IS NOT NULL;
