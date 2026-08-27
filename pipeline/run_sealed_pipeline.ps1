$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TCG_ROOT = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$env:PYTHONPATH = $ScriptDir
Set-Location $env:TCG_ROOT

if (-not $env:SEALED_SHIPPING_ESTIMATE) { $env:SEALED_SHIPPING_ESTIMATE = "15" }
if (-not $env:SEALED_MIN_PROFIT) { $env:SEALED_MIN_PROFIT = "5" }
if (-not $env:SEALED_MIN_MATCH_SCORE) { $env:SEALED_MIN_MATCH_SCORE = "0.72" }

function Run-Step([string]$Name, [scriptblock]$Block) {
    Write-Host "[$(Get-Date -Format o)] $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

Write-Host "[$(Get-Date -Format o)] CK sealed opportunities pipeline"

Run-Step "1/4 scrape_ck_sealed" {
    docker compose run --rm pipeline python3 /app/pipeline/scrape_ck_sealed.py 2>&1 | Write-Host
}

$pricesLookup = Join-Path $env:TCG_ROOT "helper\tcgcsv_prices_lookup.csv"
if (Test-Path $pricesLookup) {
    Write-Host "[$(Get-Date -Format o)] 2/4 refresh_tcgcsv skipped (helper/tcgcsv_prices_lookup.csv exists)"
} else {
    Run-Step "2/4 refresh_tcgcsv (prices)" {
        docker compose run --rm pipeline python3 /app/pipeline/refresh_tcgcsv.py 2>&1 | Write-Host
    }
}

$sealedLookup = Join-Path $env:TCG_ROOT "helper\tcgcsv_sealed_products_lookup.csv"
if ($env:SEALED_FORCE_CATALOG -eq "1" -or -not (Test-Path $sealedLookup)) {
    Run-Step "3/4 refresh_tcgcsv_sealed (product catalog)" {
        docker compose run --rm pipeline python3 /app/pipeline/refresh_tcgcsv_sealed.py 2>&1 | Write-Host
    }
} else {
    Write-Host "[$(Get-Date -Format o)] 3/4 refresh_tcgcsv_sealed skipped (set SEALED_FORCE_CATALOG=1 to refresh)"
}

Run-Step "4/4 export_sealed_opportunities" {
    docker compose run --rm `
        -e SEALED_SHIPPING_ESTIMATE=$env:SEALED_SHIPPING_ESTIMATE `
        -e SEALED_MIN_PROFIT=$env:SEALED_MIN_PROFIT `
        -e SEALED_MIN_MATCH_SCORE=$env:SEALED_MIN_MATCH_SCORE `
        pipeline python3 /app/pipeline/export_sealed_opportunities.py 2>&1 | Write-Host
}

Write-Host "[$(Get-Date -Format o)] Sealed opportunities pipeline completed"
