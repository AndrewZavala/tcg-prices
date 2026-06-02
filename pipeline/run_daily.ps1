$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TCG_ROOT = Resolve-Path (Join-Path $ScriptDir "..")
$env:PYTHONPATH = $ScriptDir

Set-Location $env:TCG_ROOT
Write-Host "[$(Get-Date -Format o)] Starting daily CK buylist pipeline"

python3 "$ScriptDir\scrape_ck.py"
python3 "$ScriptDir\merge_buylist.py"
python3 "$ScriptDir\enrich_buylist.py"
python3 "$ScriptDir\load_postgres.py"

Write-Host "[$(Get-Date -Format o)] Pipeline completed successfully"
