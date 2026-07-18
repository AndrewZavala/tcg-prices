$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TCG_ROOT = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$env:PYTHONPATH = $ScriptDir
Set-Location $env:TCG_ROOT

if (-not $env:OPPORTUNITY_USE_SCREENING) { $env:OPPORTUNITY_USE_SCREENING = "1" }
if (-not $env:OPPORTUNITY_MIN_SCREEN_SPREAD) { $env:OPPORTUNITY_MIN_SCREEN_SPREAD = "0.25" }
if (-not $env:OPPORTUNITY_MIN_SCREEN_PCT) { $env:OPPORTUNITY_MIN_SCREEN_PCT = "5" }
if (-not $env:OPPORTUNITY_MIN_CK_CASH) { $env:OPPORTUNITY_MIN_CK_CASH = "0.50" }
if (-not $env:OPPORTUNITY_TOP_N) { $env:OPPORTUNITY_TOP_N = "0" }
if (-not $env:TCG_LISTINGS_MAX_PRODUCTS) { $env:TCG_LISTINGS_MAX_PRODUCTS = "0" }
if (-not $env:TCG_LISTINGS_DELAY_SEC) { $env:TCG_LISTINGS_DELAY_SEC = "0" }
if (-not $env:TCG_LISTINGS_FETCH_RETRIES) { $env:TCG_LISTINGS_FETCH_RETRIES = "8" }
if (-not $env:TCG_LISTINGS_FETCH_RETRY_SEC) { $env:TCG_LISTINGS_FETCH_RETRY_SEC = "45" }

function Ensure-EdgeCdp {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 3
    } catch {
        $profile = Join-Path $env:TCG_ROOT "helper\tcgplayer-edge-cdp-profile"
        if (-not (Test-Path $profile)) { New-Item -ItemType Directory -Path $profile | Out-Null }
        $edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        if (-not (Test-Path $edge)) { $edge = "C:\Program Files\Microsoft\Edge\Application\msedge.exe" }
        if (-not (Test-Path $edge)) { throw "Microsoft Edge not found for CDP" }
        Start-Process $edge -ArgumentList @(
            "--user-data-dir=$profile",
            "--remote-debugging-port=9222",
            "--remote-debugging-address=0.0.0.0",
            "--no-first-run",
            "https://www.tcgplayer.com"
        )
        Start-Sleep -Seconds 8
        return Invoke-RestMethod -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 10
    }
}

function Get-DockerCdpUrl {
    param($Version)
    $hostIp = "192.168.65.254"
    return $Version.webSocketDebuggerUrl -replace 'ws://(127\.0\.0\.1|localhost):9222', "ws://$hostIp`:9222"
}

function Run-Step([string]$Name, [scriptblock]$Block) {
    Write-Host "[$(Get-Date -Format o)] $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

Write-Host "[$(Get-Date -Format o)] CK arbitrage opportunities pipeline (fresh)"
$version = Ensure-EdgeCdp
$ws = Get-DockerCdpUrl $version
Write-Host "[$(Get-Date -Format o)] Using CDP $ws"

Run-Step "1/8 scrape_ck" { docker compose run --rm pipeline python3 /app/pipeline/scrape_ck.py 2>&1 | Write-Host }
Run-Step "2/8 merge_buylist" { docker compose run --rm pipeline python3 /app/pipeline/merge_buylist.py 2>&1 | Write-Host }
Run-Step "3/8 refresh_scryfall" { docker compose run --rm pipeline python3 /app/pipeline/refresh_scryfall.py 2>&1 | Write-Host }
Run-Step "4/8 refresh_tcgcsv" { docker compose run --rm pipeline python3 /app/pipeline/refresh_tcgcsv.py 2>&1 | Write-Host }

$tcgOk = $false
$maxAttempts = [int]$env:TCG_LISTINGS_FETCH_RETRIES
$retryDelay = [int]$env:TCG_LISTINGS_FETCH_RETRY_SEC
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    Write-Host "[$(Get-Date -Format o)] 5/8 live TCG listings attempt $attempt/$maxAttempts"
    docker compose run --rm `
        -e TCG_BROWSER_CDP_URL=$ws `
        -e OPPORTUNITY_USE_SCREENING=$env:OPPORTUNITY_USE_SCREENING `
        -e OPPORTUNITY_MIN_SCREEN_SPREAD=$env:OPPORTUNITY_MIN_SCREEN_SPREAD `
        -e OPPORTUNITY_MIN_SCREEN_PCT=$env:OPPORTUNITY_MIN_SCREEN_PCT `
        -e OPPORTUNITY_MIN_CK_CASH=$env:OPPORTUNITY_MIN_CK_CASH `
        -e OPPORTUNITY_SCREEN_MAX_CANDIDATES=$env:OPPORTUNITY_SCREEN_MAX_CANDIDATES `
        -e OPPORTUNITY_TOP_N=$env:OPPORTUNITY_TOP_N `
        -e TCG_LISTINGS_MAX_PRODUCTS=$env:TCG_LISTINGS_MAX_PRODUCTS `
        -e TCG_LISTINGS_DELAY_SEC=$env:TCG_LISTINGS_DELAY_SEC `
        pipeline sh -lc "python3 -m pip install -q playwright && PYTHONUNBUFFERED=1 python3 /app/pipeline/browser_tcg_listings.py" 2>&1 | Write-Host
    if ($LASTEXITCODE -eq 0) {
        $tcgOk = $true
        break
    }
    if ($attempt -lt $maxAttempts) {
        Write-Warning "TCG listings failed; retrying in ${retryDelay}s..."
        Start-Sleep -Seconds $retryDelay
        $version = Ensure-EdgeCdp
        $ws = Get-DockerCdpUrl $version
    }
}
if (-not $tcgOk) { throw "TCG mp-search listings failed after $maxAttempts attempts" }

Run-Step "6/8 enrich_buylist" { docker compose run --rm pipeline python3 /app/pipeline/enrich_buylist.py 2>&1 | Write-Host }
Run-Step "7/8 load_postgres" { docker compose run --rm pipeline python3 /app/pipeline/load_postgres.py 2>&1 | Write-Host }
Run-Step "7b refresh inventory CK" { docker compose run --rm pipeline python3 /app/pipeline/refresh_inventory_ck.py 2>&1 | Write-Host }
Run-Step "8/8 export HTML report" {
    docker compose run --rm `
        -e OPPORTUNITY_USE_CACHED_ENRICHED=1 `
        -e OPPORTUNITY_SKIP_FETCH=1 `
        -e OPPORTUNITY_USE_SCREENING=$env:OPPORTUNITY_USE_SCREENING `
        -e OPPORTUNITY_MIN_SCREEN_SPREAD=$env:OPPORTUNITY_MIN_SCREEN_SPREAD `
        -e OPPORTUNITY_MIN_SCREEN_PCT=$env:OPPORTUNITY_MIN_SCREEN_PCT `
        -e OPPORTUNITY_MIN_CK_CASH=$env:OPPORTUNITY_MIN_CK_CASH `
        -e OPPORTUNITY_SCREEN_MAX_CANDIDATES=$env:OPPORTUNITY_SCREEN_MAX_CANDIDATES `
        -e OPPORTUNITY_TOP_N=$env:OPPORTUNITY_TOP_N `
        pipeline python3 /app/pipeline/export_opportunities.py 2>&1 | Write-Host
}

Write-Host "[$(Get-Date -Format o)] CK arbitrage pipeline completed"
