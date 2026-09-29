-- Trainers that pokemontcg.io couldn't match have no subtype tag (Crown Zenith, trainer kits, …).
-- Use TCGdex's trainerType, else the subtype most same-name printings carry.

WITH missing AS (
    SELECT id, name, card_data->>'trainerType' AS trainer_type
    FROM pokemon_cards
    WHERE category = 'Trainer'
      AND NOT (
          COALESCE(tags, ARRAY[]::text[])
          && ARRAY['supporter', 'item', 'pokemon-tool', 'stadium', 'technical-machine']
      )
),
by_name AS (
    SELECT DISTINCT ON (name) name, sub
    FROM (
        SELECT c.name, t AS sub, COUNT(*) AS n
        FROM pokemon_cards c, unnest(c.tags) AS t
        WHERE c.category = 'Trainer'
          AND t IN ('supporter', 'item', 'pokemon-tool', 'stadium')
        GROUP BY c.name, t
    ) counts
    ORDER BY name, n DESC, sub
),
resolved AS (
    SELECT m.id,
           COALESCE(
               CASE m.trainer_type
                   WHEN 'Supporter' THEN 'supporter'
                   WHEN 'Item' THEN 'item'
                   WHEN 'Tool' THEN 'pokemon-tool'
                   WHEN 'Stadium' THEN 'stadium'
                   WHEN 'Technical Machine' THEN 'technical-machine'
               END,
               b.sub
           ) AS sub
    FROM missing m
    LEFT JOIN by_name b ON b.name = m.name
)
UPDATE pokemon_cards c
SET tags = array_append(COALESCE(c.tags, ARRAY[]::text[]), r.sub)
FROM resolved r
WHERE c.id = r.id AND r.sub IS NOT NULL;
