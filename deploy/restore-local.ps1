# Restore a local Postgres dump from deploy/backups/.
# WARNING: replaces the current local database contents.
#
# Usage (from repo root):
#   powershell -File deploy/restore-local.ps1 -BackupFile deploy\backups\tcg_buylist_YYYYMMDD_HHMMSS.sql.gz

param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TcgRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $TcgRoot

$path = Resolve-Path $BackupFile
if (-not (Test-Path $path)) { throw "Backup not found: $BackupFile" }

$user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "tcg" }
$db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "tcg_buylist" }

Write-Host "This will REPLACE local database '$db' from:"
Write-Host "  $path"
$confirm = Read-Host "Type YES to continue"
if ($confirm -ne "YES") { Write-Host "Aborted."; exit 1 }

$tmpSql = Join-Path $env:TEMP ("tcg_restore_{0}.sql" -f [guid]::NewGuid().ToString("N"))

if ($path.Path -like "*.gz") {
  Add-Type -AssemblyName System.IO.Compression
  $fs = [System.IO.File]::OpenRead($path)
  $gz = New-Object System.IO.Compression.GZipStream($fs, [System.IO.Compression.CompressionMode]::Decompress)
  $out = [System.IO.File]::Create($tmpSql)
  $gz.CopyTo($out)
  $out.Close()
  $gz.Close()
  $fs.Close()
} else {
  Copy-Item $path $tmpSql
}

Write-Host "Dropping and recreating database…"
docker compose exec -T postgres psql -U $user -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();" | Out-Null
docker compose exec -T postgres psql -U $user -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $db;"
docker compose exec -T postgres psql -U $user -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $db OWNER $user;"

Write-Host "Restoring…"
Get-Content -Path $tmpSql -Raw | docker compose exec -T postgres psql -U $user -d $db -v ON_ERROR_STOP=1
Remove-Item $tmpSql -Force -ErrorAction SilentlyContinue

Write-Host "Restore complete. Restart web if needed: docker compose restart web"
Write-Host "Open http://localhost:8000"
