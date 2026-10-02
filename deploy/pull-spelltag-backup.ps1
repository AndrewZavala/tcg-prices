# Copy the newest Spell Tag database dump from the VPS into deploy/backups/ (not committed).
#   powershell -File deploy/pull-spelltag-backup.ps1
#   powershell -File deploy/pull-spelltag-backup.ps1 -VpsHost root@203.0.113.10
param(
    [string]$VpsHost = "root@spelltag.com"
)
$ErrorActionPreference = "Stop"

$remote = "$(ssh $VpsHost "ls -t /opt/spelltag/deploy/backups/spelltag_*.dump 2>/dev/null | head -n 1")".Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Couldn't connect to $VpsHost - check that 'ssh $VpsHost' works on its own first."
}
if (-not $remote) {
    throw "No spelltag_*.dump found on $VpsHost - has deploy/backup-spelltag.sh run yet?"
}

$dest = Join-Path $PSScriptRoot "backups"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$local = Join-Path $dest (Split-Path $remote -Leaf)
scp "${VpsHost}:$remote" $local
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

Write-Host ("Saved {0} ({1:N1} MB)" -f $local, ((Get-Item $local).Length / 1MB))
