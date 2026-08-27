$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TCG_ROOT = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$env:PYTHONPATH = $ScriptDir

Set-Location $env:TCG_ROOT
Write-Host "[$(Get-Date -Format o)] Starting daily CK buylist pipeline"

function Get-TcgBrowserCdpUrl {
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 2
        $ws = $version.webSocketDebuggerUrl
        if (-not $ws) { return $null }
        $ip = docker compose run --rm pipeline python3 -c "import socket; print(socket.gethostbyname('host.docker.internal'))" 2>$null |
            Select-Object -Last 1
        if ($ip) {
            $ws = $ws -replace 'ws://(127\.0\.0\.1|localhost):9222', "ws://$ip`:9222"
        }
        return $ws
    } catch {
        return $null
    }
}

docker compose run --rm pipeline python3 /app/pipeline/scrape_ck.py
docker compose run --rm pipeline python3 /app/pipeline/merge_buylist.py
docker compose run --rm pipeline python3 /app/pipeline/refresh_tcgcsv.py

if (-not $env:OPPORTUNITY_USE_SCREENING) { $env:OPPORTUNITY_USE_SCREENING = '1' }
if (-not $env:OPPORTUNITY_MIN_SCREEN_SPREAD) { $env:OPPORTUNITY_MIN_SCREEN_SPREAD = '0.25' }
if (-not $env:OPPORTUNITY_MIN_SCREEN_PCT) { $env:OPPORTUNITY_MIN_SCREEN_PCT = '5' }
if (-not $env:OPPORTUNITY_MIN_CK_CASH) { $env:OPPORTUNITY_MIN_CK_CASH = '0.50' }
if (-not $env:OPPORTUNITY_SCREEN_MAX_CANDIDATES) { $env:OPPORTUNITY_SCREEN_MAX_CANDIDATES = '0' }
if (-not $env:OPPORTUNITY_TOP_N) { $env:OPPORTUNITY_TOP_N = '0' }
if (-not $env:TCG_LISTINGS_MAX_PRODUCTS) { $env:TCG_LISTINGS_MAX_PRODUCTS = '0' }
if (-not $env:TCG_LISTINGS_DELAY_SEC) { $env:TCG_LISTINGS_DELAY_SEC = '0' }

if (-not $env:TCG_BROWSER_CDP_URL) {
    $env:TCG_BROWSER_CDP_URL = Get-TcgBrowserCdpUrl
}
if ($env:TCG_BROWSER_CDP_URL) {
    Write-Host "Using Edge CDP for TCG listings..."
    if (-not $env:TCG_LISTINGS_FETCH_RETRIES) { $env:TCG_LISTINGS_FETCH_RETRIES = "8" }
    if (-not $env:TCG_LISTINGS_FETCH_RETRY_SEC) { $env:TCG_LISTINGS_FETCH_RETRY_SEC = "45" }
    $maxAttempts = [int]$env:TCG_LISTINGS_FETCH_RETRIES
    $retryDelay = [int]$env:TCG_LISTINGS_FETCH_RETRY_SEC
    $tcgOk = $false
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Write-Host "TCG listings attempt $attempt/$maxAttempts..."
        docker compose run --rm `
            -e TCG_BROWSER_CDP_URL=$env:TCG_BROWSER_CDP_URL `
            -e OPPORTUNITY_USE_SCREENING=$env:OPPORTUNITY_USE_SCREENING `
            -e OPPORTUNITY_MIN_SCREEN_SPREAD=$env:OPPORTUNITY_MIN_SCREEN_SPREAD `
            -e OPPORTUNITY_MIN_SCREEN_PCT=$env:OPPORTUNITY_MIN_SCREEN_PCT `
            -e OPPORTUNITY_MIN_CK_CASH=$env:OPPORTUNITY_MIN_CK_CASH `
            -e OPPORTUNITY_SCREEN_MAX_CANDIDATES=$env:OPPORTUNITY_SCREEN_MAX_CANDIDATES `
            -e OPPORTUNITY_TOP_N=$env:OPPORTUNITY_TOP_N `
            -e TCG_LISTINGS_MAX_PRODUCTS=$env:TCG_LISTINGS_MAX_PRODUCTS `
            -e TCG_LISTINGS_DELAY_SEC=$env:TCG_LISTINGS_DELAY_SEC `
            pipeline sh -lc "python3 -m pip install -q playwright && python3 /app/pipeline/browser_tcg_listings.py"
        if ($LASTEXITCODE -eq 0) {
            $tcgOk = $true
            break
        }
        if ($attempt -lt $maxAttempts) {
            Write-Warning "TCG listings failed; retrying in ${retryDelay}s..."
            Start-Sleep -Seconds $retryDelay
            $env:TCG_BROWSER_CDP_URL = Get-TcgBrowserCdpUrl
        }
    }
    if (-not $tcgOk) {
        throw "TCG mp-search listings failed after $maxAttempts attempts"
    }
} else {
    Write-Error "Edge CDP not available on :9222 — cannot fetch mp-search API listings."
    exit 1
}

docker compose run --rm pipeline python3 /app/pipeline/enrich_buylist.py
docker compose run --rm pipeline python3 /app/pipeline/load_postgres.py
docker compose run --rm pipeline python3 /app/pipeline/refresh_inventory_ck.py

Write-Host "[$(Get-Date -Format o)] Pipeline completed successfully"
