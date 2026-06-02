$ErrorActionPreference = "Stop"
$tcgRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $tcgRoot "Stacks"))) {
    $tcgRoot = "c:\Users\andre\Desktop\Cursor Projects\TCG"
}
$stacksDir = Join-Path $tcgRoot "Stacks"
$batchLimit = if ($args[0]) { [int]$args[0] } else { 10 }

$files = Get-ChildItem $stacksDir -Filter "Batch*_export.csv" |
    Sort-Object { [int]($_.BaseName -replace '\D', '') } |
    Select-Object -Last $batchLimit

Write-Host "Loading $($files.Count) stack files..."

$stacks = foreach ($f in $files) {
    Import-Csv $f.FullName | ForEach-Object {
        [pscustomobject]@{
            batch_file         = $f.Name
            name               = $_.Name
            set_code           = $_.'Set code'
            collector_number   = $_.'Collector number'
            finish             = ($_.Finish + '').ToLower().Trim()
            scryfall_id        = ($_.'Scryfall ID' + '').ToLower().Trim()
            quantity           = if ($_.Quantity) { [int]$_.Quantity } else { 1 }
        }
    }
}
$stacks = @($stacks | Where-Object { $_.scryfall_id })
Write-Host "Stack rows with Scryfall ID: $($stacks.Count)"

Write-Host "Fetching CK pricelist (may take ~30s)..."
$r = Invoke-RestMethod -Uri "https://api.cardkingdom.com/api/v2/pricelist" -TimeoutSec 300
$ck = @($r.data | Where-Object {
        [int]$_.qty_buying -gt 0 -and [decimal]$_.price_buy -gt 0
    } | ForEach-Object {
        $etched = ($_.name -match 'etched') -or ($_.variation -match 'etched')
        [pscustomobject]@{
            scryfall_id  = ($_.scryfall_id + '').ToLower().Trim()
            is_foil      = ($_.is_foil + '').ToLower() -in @('true', '1', 'yes')
            is_etched    = [bool]$etched
            cash_price   = [decimal]$_.price_buy
            credit_price = [decimal]$_.price_buy * 1.3
            max_qty      = [int]$_.qty_buying
            edition      = $_.edition
            name         = $_.name
        }
    })
Write-Host "CK buylist rows: $($ck.Count)"

$ckById = @{}
foreach ($row in $ck) {
    if (-not $row.scryfall_id) { continue }
    if (-not $ckById.ContainsKey($row.scryfall_id)) {
        $ckById[$row.scryfall_id] = [System.Collections.ArrayList]@()
    }
    [void]$ckById[$row.scryfall_id].Add($row)
}

function Test-FinishMatch($stackFinish, $ckRow) {
    if ($stackFinish -eq 'etched') { return $ckRow.is_etched }
    if ($stackFinish -eq 'foil') { return $ckRow.is_foil -and -not $ckRow.is_etched }
    return -not $ckRow.is_foil
}

$stats = @{ matched = 0; no_scryfall_id = 0; id_only_wrong_finish = 0 }
$results = [System.Collections.ArrayList]@()

foreach ($s in $stacks) {
    if (-not $ckById.ContainsKey($s.scryfall_id)) {
        $stats.no_scryfall_id++
        [void]$results.Add([pscustomobject]@{
                batch_file = $s.batch_file
                name       = $s.name
                set_code   = $s.set_code
                finish     = $s.finish
                scryfall_id = $s.scryfall_id
                quantity   = $s.quantity
                ck_match   = 'no_scryfall_id'
            })
        continue
    }
    $cands = $ckById[$s.scryfall_id]
    $hit = $null
    foreach ($c in $cands) {
        if (Test-FinishMatch $s.finish $c) { $hit = $c; break }
    }
    if ($hit) {
        $stats.matched++
        [void]$results.Add([pscustomobject]@{
                batch_file   = $s.batch_file
                name         = $s.name
                set_code     = $s.set_code
                finish       = $s.finish
                scryfall_id  = $s.scryfall_id
                quantity     = $s.quantity
                ck_match     = 'matched'
                ck_cash      = $hit.cash_price
                ck_credit    = $hit.credit_price
                ck_max_qty   = $hit.max_qty
                ck_edition   = $hit.edition
            })
    }
    else {
        $stats.id_only_wrong_finish++
        $any = $cands[0]
        [void]$results.Add([pscustomobject]@{
                batch_file  = $s.batch_file
                name        = $s.name
                set_code    = $s.set_code
                finish      = $s.finish
                scryfall_id = $s.scryfall_id
                quantity    = $s.quantity
                ck_match    = 'id_only_wrong_finish'
                ck_cash     = $any.cash_price
                ck_edition  = $any.edition
            })
    }
}

$total = $stacks.Count
Write-Host ""
Write-Host "--- Match breakdown (last $batchLimit batches) ---"
Write-Host ("  matched: {0} ({1}%)" -f $stats.matched, [math]::Round(100 * $stats.matched / $total, 1))
Write-Host ("  not on CK buylist (no scryfall_id): {0} ({1}%)" -f $stats.no_scryfall_id, [math]::Round(100 * $stats.no_scryfall_id / $total, 1))
Write-Host ("  on CK but wrong finish: {0} ({1}%)" -f $stats.id_only_wrong_finish, [math]::Round(100 * $stats.id_only_wrong_finish / $total, 1))

$matchedRows = $results | Where-Object { $_.ck_match -eq 'matched' }
$cashSum = ($matchedRows | ForEach-Object { $_.ck_cash * $_.quantity } | Measure-Object -Sum).Sum
Write-Host ""
Write-Host ("Matched inventory CK cash value (qty-weighted): `${0:N2}" -f $cashSum)

$out = Join-Path $tcgRoot "data\stack_ck_match_report.csv"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$results | Export-Csv $out -NoTypeInformation
Write-Host "Wrote $out"

Write-Host ""
Write-Host "--- Sample non-matches (up to 15) ---"
$results | Where-Object { $_.ck_match -ne 'matched' } | Select-Object -First 15 | Format-Table -AutoSize
