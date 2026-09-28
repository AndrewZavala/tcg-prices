-- Celebrations Classic Collection art on pokemontcg.io is filed under each reprint's
-- original collector number (Charizard = 4_A), not CC###.
-- Local copies downloaded from a wrong URL are unmarked so the corrected remote image
-- is served until the downloader is re-run with --force.

UPDATE pokemon_cards AS c
SET image_local = CASE
        WHEN NULLIF(BTRIM(c.image_url), '') IS NOT NULL AND c.image_url <> v.url THEN FALSE
        ELSE c.image_local
    END,
    image_url = v.url
FROM (
    VALUES
        ('cel25cc-CC001', 'https://images.pokemontcg.io/cel25c/2_A_hires.png'),
        ('cel25cc-CC002', 'https://images.pokemontcg.io/cel25c/4_A_hires.png'),
        ('cel25cc-CC003', 'https://images.pokemontcg.io/cel25c/15_A_hires.png'),
        ('cel25cc-CC004', 'https://images.pokemontcg.io/cel25c/73_A_hires.png'),
        ('cel25cc-CC005', 'https://images.pokemontcg.io/cel25c/8_A_hires.png'),
        ('cel25cc-CC006', 'https://images.pokemontcg.io/cel25c/15_B_hires.png'),
        ('cel25cc-CC007', 'https://images.pokemontcg.io/cel25c/15_C_hires.png'),
        ('cel25cc-CC008', 'https://images.pokemontcg.io/cel25c/24_A_hires.png'),
        ('cel25cc-CC009', 'https://images.pokemontcg.io/cel25c/20_A_hires.png'),
        ('cel25cc-CC010', 'https://images.pokemontcg.io/cel25c/66_A_hires.png'),
        ('cel25cc-CC011', 'https://images.pokemontcg.io/cel25c/9_A_hires.png'),
        ('cel25cc-CC012', 'https://images.pokemontcg.io/cel25c/86_A_hires.png'),
        ('cel25cc-CC013', 'https://images.pokemontcg.io/cel25c/88_A_hires.png'),
        ('cel25cc-CC014', 'https://images.pokemontcg.io/cel25c/93_A_hires.png'),
        ('cel25cc-CC015', 'https://images.pokemontcg.io/cel25c/17_A_hires.png'),
        ('cel25cc-CC016', 'https://images.pokemontcg.io/cel25c/15_D_hires.png'),
        ('cel25cc-CC017', 'https://images.pokemontcg.io/cel25c/109_A_hires.png'),
        ('cel25cc-CC018', 'https://images.pokemontcg.io/cel25c/145_A_hires.png'),
        ('cel25cc-CC019', 'https://images.pokemontcg.io/cel25c/107_A_hires.png'),
        ('cel25cc-CC020', 'https://images.pokemontcg.io/cel25c/113_A_hires.png'),
        ('cel25cc-CC021', 'https://images.pokemontcg.io/cel25c/114_A_hires.png'),
        ('cel25cc-CC022', 'https://images.pokemontcg.io/cel25c/54_A_hires.png'),
        ('cel25cc-CC023', 'https://images.pokemontcg.io/cel25c/97_A_hires.png'),
        ('cel25cc-CC024', 'https://images.pokemontcg.io/cel25c/76_A_hires.png'),
        ('cel25cc-CC025', 'https://images.pokemontcg.io/cel25c/60_A_hires.png')
) AS v(id, url)
WHERE c.id = v.id
  AND c.image_url IS DISTINCT FROM v.url;
