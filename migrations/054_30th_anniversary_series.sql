-- TCGdex files the 30th anniversary sets under Mega Evolution; list them as their own series.
-- Keep in sync with pipeline/refresh_tcgdex.SERIES_OVERRIDES.

UPDATE pokemon_sets
SET series_id = '30th', series_name = '30th Anniversary'
WHERE id IN ('30th', '30th-c')
  AND (series_id IS DISTINCT FROM '30th' OR series_name IS DISTINCT FROM '30th Anniversary');
