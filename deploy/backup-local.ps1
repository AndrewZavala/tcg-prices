# Dump local Docker Postgres to deploy/backups/ (Windows / laptop).
# Does NOT touch cloud. Local GUI keeps working; this is only a recoverable snapshot.
#
# Usage (from repo root):
#   powershell -File deploy/backup-local.ps1
# Restore:
#   powershell -File deploy/restore-local.ps1 -BackupFile deploy\backups\tcg_buylist_YYYYMMDD_HHMMSS.sql.gz

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TcgRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $TcgRoot

$BackupDir = Join-Path $ScriptDir "backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "tcg" }
$db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "tcg_buylist" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$sql = Join-Path $BackupDir "tcg_buylist_${stamp}.sql"
$out = Join-Path $BackupDir "tcg_buylist_${stamp}.sql.gz"

Write-Host "Dumping local Postgres ($db)..."
docker compose exec -T postgres pg_dump -U $user $db | Set-Content -Path $sql -Encoding utf8

if (-not (Test-Path $sql) -or (Get-Item $sql).Length -lt 100) {
  throw "pg_dump produced an empty file. Is postgres running? (docker compose ps)"
}

Add-Type -AssemblyName System.IO.Compression
$inBytes = [System.IO.File]::ReadAllBytes($sql)
$fs = [System.IO.File]::Create($out)
$gz = New-Object System.IO.Compression.GZipStream($fs, [System.IO.Compression.CompressionMode]::Compress)
$gz.Write($inBytes, 0, $inBytes.Length)
$gz.Close()
$fs.Close()
Remove-Item $sql -Force

$mb = [math]::Round((Get-Item $out).Length / 1MB, 2)
Write-Host "Wrote $out ($mb MB)"

# Keep last 14 dumps
$all = Get-ChildItem $BackupDir -File |
  Where-Object { $_.Name -match '^tcg_buylist_\d{8}_\d{6}\.sql\.gz$' } |
  Sort-Object Name -Descending
$all | Select-Object -Skip 14 | ForEach-Object { Remove-Item $_.FullName -Force }

Write-Host "Done. http://localhost:8000 is unchanged; restore only if you need this snapshot back."
