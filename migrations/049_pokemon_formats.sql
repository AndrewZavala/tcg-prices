-- Format legality for f:standard / f:expanded (and the Standard-only Limitless decklist crawl).
-- Standard = regulation mark >= the mark of the latest rotation that has started, plus basic Energy.
-- To schedule next year's rotation ahead of time, add a row (it takes effect on starts_on).

CREATE TABLE IF NOT EXISTS pokemon_standard_rotations (
    starts_on DATE PRIMARY KEY,
    min_regulation_mark TEXT NOT NULL CHECK (min_regulation_mark ~ '^[A-Z]$')
);

INSERT INTO pokemon_standard_rotations (starts_on, min_regulation_mark) VALUES
    ('2025-04-11', 'G'),
    ('2026-04-10', 'H')
ON CONFLICT (starts_on) DO NOTHING;

CREATE OR REPLACE FUNCTION spelltag_standard_min_mark() RETURNS TEXT
LANGUAGE sql STABLE AS $$
    SELECT min_regulation_mark
    FROM pokemon_standard_rotations
    WHERE starts_on <= CURRENT_DATE
    ORDER BY starts_on DESC
    LIMIT 1
$$;

-- Basic Energy needs a basic name and a non-Special type: pre-BW "Darkness Energy" / "Metal Energy"
-- were Special Energy with basic-looking names.
-- min_mark must appear only once in the body so Postgres can inline the function (callers pass
-- a sub-SELECT); a NULL min_mark yields NULL, which callers treat as not legal.
CREATE OR REPLACE FUNCTION pokemon_printing_is_standard(
    mark TEXT,
    category TEXT,
    card_name TEXT,
    energy_type TEXT,
    min_mark TEXT
) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT (
        category = 'Energy'
        AND card_name ~ '^(Basic )?(Grass|Fire|Water|Lightning|Psychic|Fighting|Darkness|Metal|Fairy) Energy$'
        AND energy_type IS DISTINCT FROM 'Special'
    )
    OR (mark ~ '^[A-Z]$' AND mark >= min_mark)
$$;
