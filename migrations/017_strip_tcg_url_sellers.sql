-- Strip seller filters from stored TCG product URLs (seller is tracked separately).

UPDATE inventory_lots
SET tcg_url = regexp_replace(
        regexp_replace(
            regexp_replace(tcg_url, '([?&])[Ss]ellers=[^&]*', '\1', 'g'),
            '[?&]{2,}',
            '?',
            'g'
        ),
        '[?&]$',
        '',
        'g'
    ),
    updated_at = NOW()
WHERE tcg_url ~* '[?&]sellers=';

UPDATE opportunities
SET tcg_url = regexp_replace(
        regexp_replace(
            regexp_replace(tcg_url, '([?&])[Ss]ellers=[^&]*', '\1', 'g'),
            '[?&]{2,}',
            '?',
            'g'
        ),
        '[?&]$',
        '',
        'g'
    )
WHERE tcg_url ~* '[?&]sellers=';
