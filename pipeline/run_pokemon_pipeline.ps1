# Star Piece / Pokemon catalog pipeline (ingest + enrich)
#
# Examples:
#   .\pipeline\run_pokemon_pipeline.ps1 -Series bw
#   .\pipeline\run_pokemon_pipeline.ps1 -Set sv1 -Set sv2
#   .\pipeline\run_pokemon_pipeline.ps1 -Series pop   # POP Series 1–9
#   .\pipeline\run_pokemon_pipeline.ps1 -Series side  # POP + Nintendo promos + McDonald's + Trainer Kits

param(
    [string[]]$Set,
    [string]$Series,
    [switch]$SkipIngest,
    [switch]$SkipSubtypes,
    [switch]$SkipSpecies,
    [switch]$SkipOracle,
    [switch]$SpeciesFull
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TCG_ROOT = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $env:TCG_ROOT

function Run-DockerStep([string]$Name, [string[]]$PythonArgs) {
    Write-Host "[$(Get-Date -Format o)] $Name"
    $cmd = @("compose", "--profile", "manual", "run", "--rm", "star-piece-pipeline", "python", "pipeline/$($PythonArgs[0])") + $PythonArgs[1..($PythonArgs.Length - 1)]
    docker @cmd
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

if (-not $SkipIngest) {
    if (-not $Series -and (-not $Set -or $Set.Count -eq 0)) {
        Write-Error "Specify -Series or -Set (or use -SkipIngest to re-run enrichment only)."
    }

    $ingestArgs = @("refresh_tcgdex.py", "--skip-migration", "--enrich")
    if ($Series) { $ingestArgs += @("--series", $Series) }
    foreach ($s in $Set) { $ingestArgs += @("--set", $s) }

    Run-DockerStep "TCGdex ingest + enrich" $ingestArgs
} else {
    Write-Host "[$(Get-Date -Format o)] TCGdex ingest - skipped"

    $enrichSets = @()
    if ($Set) { $enrichSets += $Set }
    if ($Series) {
        # Resolve known series blocks the same way refresh_tcgdex.py does
        $seriesLower = $Series.ToLower()
        if ($seriesLower -eq "bw") {
            $enrichSets += @("bw1","bwp","bw2","bw3","bw4","bw5","bw6","dv1","bw7","bw8","bw9","bw10","bw11")
        } elseif ($seriesLower -eq "me") {
            $enrichSets += @("me01","mep","me02","me02.5","me03","me04","me05")
        } elseif ($seriesLower -eq "sv") {
            $enrichSets += @(
                "sv01","sve","svp","sv02","sv03","sv03.5","mfb","sv04","sv04.5","sv05",
                "sv06","sv06.5","sv07","sv08","sv08.5","sv09","sv10","sv10.5b","sv10.5w"
            )
        } elseif ($seriesLower -eq "sm") {
            $enrichSets += @(
                "sm1","smp","sm2","sm3","sm3.5","sm4","sm5","sm6","sm7","sm7.5",
                "sm8","sm9","det1","sm10","sm11","sm115","sma","sm12"
            )
        } elseif ($seriesLower -eq "xy") {
            $enrichSets += @(
                "xyp","xy0","xy1","xya","xy2","xy3","xy4","xy5","dc1",
                "xy6","xy7","xy8","xy9","g1","xy10","xy11","xy12"
            )
        } elseif ($seriesLower -eq "hgss") {
            $enrichSets += @("hgss1","hgssp","hgss2","hgss3","hgss4","col1")
        } elseif ($seriesLower -eq "dp") {
            $enrichSets += @(
                "dp1","dpp","dp2","dp3","dp4","dp5","dp6","dp7",
                "pl1","pl2","pl3","pl4","ru1"
            )
        } elseif ($seriesLower -eq "ex") {
            $enrichSets += @(
                "ex1","ex2","ex3","ex4","ex5","ex5.5","ex6","ex7","ex8","ex9",
                "exu","ex10","ex11","ex12","ex13","ex14","ex15","ex16"
            )
        } elseif ($seriesLower -eq "wotc" -or $seriesLower -eq "wizards") {
            $enrichSets += @(
                "base1","base2","basep","wp","base3","base4","base5",
                "gym1","gym2",
                "neo1","neo2","si1","neo3","neo4",
                "lc",
                "ecard1","bog","ecard2","ecard3"
            )
        } elseif ($seriesLower -eq "swsh") {
            $enrichSets += @(
                "swshp","swsh1","swsh2","swsh3","fut2020","swsh3.5","swsh4",
                "swsh4.5","swsh4.5sv","swsh5","swsh6","swsh7","cel25","cel25cc",
                "swsh8","swsh9","swsh9.5tg","swsh10","swsh10.5tg","swsh10.5",
                "swsh11","swsh11.5tg","swsh12","swsh12.5tg","swsh12.5","swsh12.5gg"
            )
        } elseif ($seriesLower -eq "pop") {
            $enrichSets += @("pop1","pop2","pop3","pop4","pop5","pop6","pop7","pop8","pop9")
        } elseif ($seriesLower -in @("side", "extras")) {
            $enrichSets += @(
                "pop1","pop2","pop3","pop4","pop5","pop6","pop7","pop8","pop9",
                "np",
                "2011bw","2012bw","2014xy","2015xy","2016xy","2017sm","2018sm","2019sm","2021swsh","2022swsh","2023sv","2024sv",
                "tk-ex-latia","tk-ex-latio","tk-ex-m","tk-ex-p","tk-dp-l","tk-dp-m","tk-hs-g","tk-hs-r",
                "tk-bw-e","tk-bw-z","tk-xy-b","tk-xy-latia","tk-xy-latio","tk-xy-n","tk-xy-p","tk-xy-su","tk-xy-sy","tk-xy-w",
                "tk-sm-l","tk-sm-r"
            )
        } elseif ($seriesLower -in @("np", "nintendo")) {
            $enrichSets += @("np")
        } elseif ($seriesLower -in @("mcd", "mcdonalds", "mcdonald")) {
            $enrichSets += @("2011bw","2012bw","2014xy","2015xy","2016xy","2017sm","2018sm","2019sm","2021swsh","2022swsh","2023sv","2024sv")
        } elseif ($seriesLower -in @("tk", "trainer-kits", "trainers")) {
            $enrichSets += @(
                "tk-ex-latia","tk-ex-latio","tk-ex-m","tk-ex-p","tk-dp-l","tk-dp-m","tk-hs-g","tk-hs-r",
                "tk-bw-e","tk-bw-z","tk-xy-b","tk-xy-latia","tk-xy-latio","tk-xy-n","tk-xy-p","tk-xy-su","tk-xy-sy","tk-xy-w",
                "tk-sm-l","tk-sm-r"
            )
        } else {
            Write-Error "Unknown -Series '$Series' with -SkipIngest. Use -Set for individual sets."
        }
    }

    $enrichArgs = @("enrich_pokemon.py")
    if ($SkipSubtypes) { $enrichArgs += "--skip-subtypes" }
    if ($SkipSpecies) { $enrichArgs += "--skip-species" }
    if ($SkipOracle) { $enrichArgs += "--skip-oracle" }
    if ($SpeciesFull) { $enrichArgs += "--species-full" }
    foreach ($s in $enrichSets) { $enrichArgs += @("--set", $s) }

    Run-DockerStep "Pokemon enrich only" $enrichArgs
}

Write-Host "[$(Get-Date -Format o)] Pokemon pipeline completed"
