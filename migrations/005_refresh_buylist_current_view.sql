-- Postgres views with SELECT * do not pick up new table columns automatically.

CREATE OR REPLACE VIEW buylist_current AS
SELECT c.*
FROM buylist_cards c
INNER JOIN (
    SELECT MAX(snapshot_date) AS snapshot_date FROM buylist_snapshots
) latest ON c.snapshot_date = latest.snapshot_date;
