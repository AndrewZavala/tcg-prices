# One-shot: copy pokemon_* tables from Manifest Bread Postgres -> Star Piece Postgres.

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "Starting Manifest Bread postgres + Star Piece db/web..."
docker compose up -d postgres star-piece-db
docker compose up -d --build star-piece

Write-Host "Waiting for databases..."
for ($i = 0; $i -lt 40; $i++) {
    docker compose exec -T postgres pg_isready -U tcg -d tcg_buylist 2>$null | Out-Null
    $a = $LASTEXITCODE
    docker compose exec -T star-piece-db pg_isready -U starpiece -d star_piece 2>$null | Out-Null
    $b = $LASTEXITCODE
    if ($a -eq 0 -and $b -eq 0) { break }
    Start-Sleep -Seconds 2
}

Write-Host "Waiting for Star Piece schema migrations..."
Start-Sleep -Seconds 5

Write-Host "Dumping pokemon_* inside postgres container..."
docker compose exec -T postgres sh -c "pg_dump -U tcg -d tcg_buylist --data-only --no-owner --no-acl -t pokemon_sets -t pokemon_cards -t pokemon_oracles -t pokemon_species -t pokemon_sync_log > /tmp/pokemon_dump.sql"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

$dumpHost = Join-Path $env:TEMP "star_piece_pokemon_dump.sql"
Write-Host "Copying dump via host ($dumpHost)..."
docker compose cp postgres:/tmp/pokemon_dump.sql $dumpHost
if ($LASTEXITCODE -ne 0) { throw "docker compose cp from postgres failed" }
docker compose cp $dumpHost star-piece-db:/tmp/pokemon_dump.sql
if ($LASTEXITCODE -ne 0) { throw "docker compose cp to star-piece-db failed" }

Write-Host "Loading into star_piece (FK checks off)..."
docker compose exec -T star-piece-db psql -U starpiece -d star_piece -v ON_ERROR_STOP=1 -c "TRUNCATE pokemon_sync_log, pokemon_oracles, pokemon_cards, pokemon_sets, pokemon_species CASCADE;"
docker compose exec -T star-piece-db sh -c @'
psql -U starpiece -d star_piece -v ON_ERROR_STOP=1 <<EOF
SET session_replication_role = replica;
\i /tmp/pokemon_dump.sql
SET session_replication_role = DEFAULT;
EOF
'@
if ($LASTEXITCODE -ne 0) { throw "Data copy failed" }

Write-Host "Star Piece counts:"
docker compose exec -T star-piece-db psql -U starpiece -d star_piece -c "SELECT 'sets' AS t, count(*)::text FROM pokemon_sets UNION ALL SELECT 'cards', count(*)::text FROM pokemon_cards UNION ALL SELECT 'oracles', count(*)::text FROM pokemon_oracles UNION ALL SELECT 'species', count(*)::text FROM pokemon_species;"

Write-Host "Done - http://localhost:8001"
