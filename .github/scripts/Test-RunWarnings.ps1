# =============================================================================
#  Teste de regressao: avisos da rodada e frequencia da CPU (hub.ps1)
#
#  Add-RunWarning acumula avisos por run no _state.json (sem duplicar);
#  Get-EmptyExportModules ignora o frequencia_cpu.csv do proprio hub;
#  Get-DevCsvWarnings acusa carga com status != OK e carga sensivel a rede;
#  Get-CpuFrequencySummary mede a queda so sob carga; Build-ConsolidatedReport
#  grava "Avisos da rodada" e a frequencia no _relatorio.html/.json; o
#  amostrador (Start-Job) grava o CSV e para.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Get-NaturalSortKey", "Get-StateField", "Get-LatestTestResults", "Get-RunWarnings", "Add-RunWarning",
                "Get-EmptyExportModules", "Get-DevCsvWarnings", "Get-Median", "Get-CpuFrequencySummary",
                "Add-EndOfRunWarnings", "Build-ConsolidatedReport", "Start-CpuSampler", "Stop-CpuSampler", "Test-CpuSamplingEnabled") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $hubPath" }
    . ([scriptblock]::Create($fn.Extent.Text))
}
function Write-Host { }
$config = [PSCustomObject]@{ Settings = [PSCustomObject]@{ HtmlReportTitle = "WinTestHub" } }
$BrandFavicon = ""; $BrandCss = ""; $BrandHeader = ""
$CpuSamplerSettings = [PSCustomObject]@{ Enabled = $true; IntervalSec = 5; ThrottleAlertPct = 20; LoadMinPct = 50 }

$script:falhas = 0
function Assert-Condition {
    param([bool]$Condition, [string]$Description)
    if ($Condition) {
        Microsoft.PowerShell.Utility\Write-Host "  OK      $Description" -ForegroundColor Green
    } else {
        Microsoft.PowerShell.Utility\Write-Host "  FALHOU  $Description" -ForegroundColor Red
        $script:falhas++
    }
}
function Section { param($T) Microsoft.PowerShell.Utility\Write-Host "`n  $T" -ForegroundColor Cyan }

# CSV de frequencia: $n amostras; sob carga ($util) o MHz vai de $from a $to
function New-FreqCsv {
    param([string]$Path, [int]$N, [double]$From, [double]$To, [int]$Util = 90, [string]$Temp = "")
    $lines = @("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC")
    for ($i = 0; $i -lt $N; $i++) {
        $mhz = if ($N -gt 1) { $From + ($To - $From) * $i / ($N - 1) } else { $From }
        $lines += "2026-11-24T10:00:$('{0:D2}' -f ($i % 60)),$Util,100,$([Math]::Round($mhz)),$Temp"
    }
    Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
}

$guid = [guid]::NewGuid().ToString('N')
$root = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest avisos $guid [x]"
$traces = Join-Path $root "Traces"
try {
    Section "Add-RunWarning / Get-RunWarnings"
    $old = [PSCustomObject]@{ scenario = "cen"; machine = "PC"; createdAt = "c"; lastRunAt = "l"; runs = @() }
    Assert-Condition (@(Get-RunWarnings -State $old).Count -eq 0) "state antigo sem 'avisos' -> lista vazia (StrictMode)"
    Add-RunWarning -State $old -Run 1 -Fonte "checagem" -Texto "A"
    Add-RunWarning -State $old -Run 1 -Fonte "checagem" -Texto "A"
    Add-RunWarning -State $old -Run 2 -Fonte "checagem" -Texto "A"
    Add-RunWarning -State $old -Run 2 -Fonte "sobra" -Texto "B"
    Assert-Condition (@(Get-RunWarnings -State $old).Count -eq 3) "mesmo aviso na mesma run nao duplica; em outra run conta"
    $rt = ($old | ConvertTo-Json -Depth 10 | ConvertFrom-Json)
    Assert-Condition (@(Get-RunWarnings -State $rt).Count -eq 3) "avisos sobrevivem ao _state.json (ida e volta em JSON)"
    $one = [PSCustomObject]@{ runs = @() }
    Add-RunWarning -State $one -Run 1 -Fonte "x" -Texto "so um"
    $rt1 = ($one | ConvertTo-Json -Depth 10 | ConvertFrom-Json)
    Assert-Condition (@(Get-RunWarnings -State $rt1).Count -eq 1 -and ($one | ConvertTo-Json -Depth 10) -match '"avisos":\s*\[') "um aviso so continua array no JSON"

    Section "Get-EmptyExportModules"
    foreach ($d in "1_cpu_memo", "2_disco", "7_dev_dotnet\logs", "logs") { New-Item -ItemType Directory -Path (Join-Path $traces $d) -Force | Out-Null }
    Set-Content -LiteralPath (Join-Path $traces "1_cpu_memo\run1.etl") -Value "x"
    Set-Content -LiteralPath (Join-Path $traces "1_cpu_memo\frequencia_cpu.csv") -Value "x"
    Set-Content -LiteralPath (Join-Path $traces "2_disco\disco.csv") -Value "x"
    Set-Content -LiteralPath (Join-Path $traces "7_dev_dotnet\logs\a.txt") -Value "x"
    Set-Content -LiteralPath (Join-Path $traces "logs\hub.txt") -Value "x"
    Set-Content -LiteralPath (Join-Path $traces "_state.json") -Value "{}"
    $empty = @(Get-EmptyExportModules -TraceRunDir $traces)
    Assert-Condition ($empty -contains "1_cpu_memo") "modulo so com .etl + frequencia_cpu.csv -> vazio"
    Assert-Condition ($empty -contains "7_dev_dotnet") "modulo so com pasta logs/ -> vazio"
    Assert-Condition ($empty -notcontains "2_disco" -and $empty -notcontains "logs") "modulo com CSV nao e vazio; 'logs' de 1o nivel nao conta"

    Section "Get-DevCsvWarnings"
    New-Item -ItemType Directory -Path (Join-Path $traces "10_dev_containers") -Force | Out-Null
    $csv = @(
        "carga;status;mediana_s;fria_s;limite_s;execucoes_s;sensivel_rede;motivo",
        "A7a-podman-build-hugo;OK;159.94;182.42;1647;182.42 159.94 152.8;sim;",
        "A7b-podman-compose-healthy;FAIL;;;139;;nao;timeout de 139 s (10x a referencia)",
        "A7b-podman-compose-healthy:up;FAIL;;;;;;"
    )
    [System.IO.File]::WriteAllLines((Join-Path $traces "10_dev_containers\dev_containers.csv"), $csv, (New-Object System.Text.UTF8Encoding($true)))
    $dw = @(Get-DevCsvWarnings -TraceRunDir $traces -Folders @("10_dev_containers"))
    $fail = @($dw | Where-Object { $_.Fonte -eq "carga_dev" })
    $net  = @($dw | Where-Object { $_.Fonte -eq "rede" })
    Assert-Condition ($fail.Count -eq 1 -and $fail[0].Texto -match 'A7b-podman-compose-healthy: FAIL -- timeout') "carga FAIL com motivo; subparte ignorada"
    Assert-Condition ($net.Count -eq 1 -and $net[0].Texto -match 'A7a') "carga sensivel a rede acusada"
    Assert-Condition (@(Get-DevCsvWarnings -TraceRunDir $traces -Folders @("2_disco")).Count -eq 0) "modulo fora da lista nao gera aviso"

    Section "Get-CpuFrequencySummary"
    $fc = Join-Path $root "freq.csv"
    New-FreqCsv -Path $fc -N 2 -From 3000 -To 3000
    Assert-Condition ($null -eq (Get-CpuFrequencySummary -Csv $fc)) "menos de 3 amostras -> ignorado"
    New-FreqCsv -Path $fc -N 60 -From 3000 -To 2100 -Temp "71.5"
    $s = Get-CpuFrequencySummary -Csv $fc -IntervalSec 5 -LoadMinPct 50
    Assert-Condition ($null -ne $s -and $s.Samples -eq 60 -and $s.DropPct -ge 25 -and $s.DropPct -le 31) "queda de ~30% sob carga medida (obtido $($s.DropPct)%)"
    Assert-Condition ($s.MaxTempC -eq 71.5) "temperatura maxima lida"
    New-FreqCsv -Path $fc -N 60 -From 3000 -To 1000 -Util 10
    $s2 = Get-CpuFrequencySummary -Csv $fc -IntervalSec 5 -LoadMinPct 50
    Assert-Condition ($null -ne $s2 -and $null -eq $s2.DropPct) "clock caindo em ocioso nao e throttling (sem queda calculada)"
    Assert-Condition ($null -eq (Get-CpuFrequencySummary -Csv (Join-Path $root "nao_existe.csv"))) "CSV ausente -> null"

    Section "Add-EndOfRunWarnings"
    New-FreqCsv -Path (Join-Path $traces "2_disco\frequencia_cpu.csv") -N 60 -From 3000 -To 2100
    $st = [PSCustomObject]@{ scenario = "cen"; machine = "PC"; createdAt = "c"; lastRunAt = "l"; runs = @() }
    Add-EndOfRunWarnings -State $st -Run 3 -TraceRunDir $traces -Folders @("1_cpu_memo", "2_disco", "10_dev_containers") -MissingCsvFolders @("1_cpu_memo", "5_bateria") -Sampler $CpuSamplerSettings
    $ws = @(Get-RunWarnings -State $st)
    $fontes = @($ws | ForEach-Object { $_.fonte })
    Assert-Condition ($fontes -contains "modulo_vazio" -and $fontes -contains "csv_faltando" -and $fontes -contains "carga_dev" -and $fontes -contains "rede" -and $fontes -contains "throttling") "modulo vazio, CSV faltando, carga FAIL, rede e throttling registrados"
    Assert-Condition (@($ws | Where-Object { $_.texto -match '7_dev_dotnet|5_bateria' }).Count -eq 0) "modulos que nao rodaram nesta run nao geram aviso"
    Assert-Condition (@($ws | Where-Object { $_.run -ne 3 }).Count -eq 0) "avisos marcados com a run"
    $off = [PSCustomObject]@{ Enabled = $false; IntervalSec = 5; ThrottleAlertPct = 20; LoadMinPct = 50 }
    $st2 = [PSCustomObject]@{ runs = @() }
    Add-EndOfRunWarnings -State $st2 -Run 1 -TraceRunDir $traces -Folders @("2_disco") -Sampler $off
    Assert-Condition (@(Get-RunWarnings -State $st2 | Where-Object { $_.fonte -eq "throttling" }).Count -eq 0) "amostrador desligado -> sem aviso de throttling"

    Section "Build-ConsolidatedReport"
    $st | Add-Member -NotePropertyName modelo -NotePropertyValue "5440" -Force
    $st | Add-Member -NotePropertyName patrimonio -NotePropertyValue "044163" -Force
    $st.runs = @(
        [PSCustomObject]@{ runId = 1; timestamp = "t1"; tests = @([PSCustomObject]@{ name = "2_teste_disco.py"; folder = "2_disco"; status = "PASS"; duration = 10 }) },
        [PSCustomObject]@{ runId = 3; timestamp = "t3"; tests = @([PSCustomObject]@{ name = "1_automacao_performance.py"; folder = "1_cpu_memo"; status = "PASS"; duration = 20 }) }
    )
    Add-RunWarning -State $st -Run 1 -Fonte "sobra" -Texto "Encerrada apos x: <Edge> & cia"
    # varios avisos na mesma run: o Sort-Object instavel do PS 5.1 os embaralhava
    foreach ($i in 1..8) { Add-RunWarning -State $st -Run 1 -Fonte "rede" -Texto "aviso de ordem $i" }
    Build-ConsolidatedReport -TraceRunDir $traces -State $st
    $html = Get-Content -LiteralPath (Join-Path $traces "_relatorio.html") -Raw
    $json = Get-Content -LiteralPath (Join-Path $traces "_relatorio.json") -Raw | ConvertFrom-Json
    Assert-Condition ($html -match 'Avisos da rodada' -and $html -match 'run #1' -and $html -match 'run #3') "HTML com a secao de avisos, incluindo a run anterior"
    Assert-Condition ($html -match '&lt;Edge&gt; &amp; cia' -and $html -notmatch '<Edge>') "texto do aviso escapado no HTML"
    Assert-Condition (@($json.Avisos).Count -eq @(Get-RunWarnings -State $st).Count) "JSON com os mesmos avisos"
    $porRun = @{}; foreach ($w in @(Get-RunWarnings -State $st)) { $k = [int]$w.run; if (-not $porRun.ContainsKey($k)) { $porRun[$k] = @() }; $porRun[$k] += "$($w.run)|$($w.texto)" }
    $esperado = @($porRun.Keys | Sort-Object | ForEach-Object { $porRun[$_] })
    $obtido = @($json.Avisos | ForEach-Object { "$($_.run)|$($_.texto)" })
    Assert-Condition (($obtido -join "`n") -eq ($esperado -join "`n")) "avisos por run, na ordem em que foram gravados (sort estavel)"
    $f2 = @($json.FrequenciaCpu | Where-Object { $_.Modulo -eq "2_disco" })
    Assert-Condition ($f2.Count -eq 1 -and $f2[0].QuedaPct -ge 25 -and $html -match 'Frequencia da CPU') "frequencia por modulo no JSON e no HTML"
    $st3 = [PSCustomObject]@{ scenario = "c"; machine = "m"; createdAt = "c"; lastRunAt = "l"; runs = @([PSCustomObject]@{ runId = 1; timestamp = "t"; tests = @([PSCustomObject]@{ name = "a.py"; folder = "zz"; status = "PASS"; duration = 1 }) }) }
    $t3 = Join-Path $root "T3"; New-Item -ItemType Directory -Path $t3 -Force | Out-Null
    Build-ConsolidatedReport -TraceRunDir $t3 -State $st3
    $j3 = Get-Content -LiteralPath (Join-Path $t3 "_relatorio.json") -Raw | ConvertFrom-Json
    Assert-Condition ((Get-Content -LiteralPath (Join-Path $t3 "_relatorio.html") -Raw) -match 'Nenhum aviso' -and @($j3.Avisos).Count -eq 0) "cenario sem avisos: 'Nenhum aviso' e lista vazia"

    Section "Test-CpuSamplingEnabled"
    $on  = [PSCustomObject]@{ Enabled = $true; SkipFolders = @("5_bateria") }
    $offS = [PSCustomObject]@{ Enabled = $false; SkipFolders = @() }
    Assert-Condition (Test-CpuSamplingEnabled -Test ([PSCustomObject]@{ Kind = "test"; ParentFolder = "1_cpu_memo" }) -Settings $on) "teste comum -> amostra"
    Assert-Condition (-not (Test-CpuSamplingEnabled -Test ([PSCustomObject]@{ Kind = "test"; ParentFolder = "5_bateria" }) -Settings $on)) "teste 5 (SkipFolders) -> nao amostra"
    Assert-Condition (-not (Test-CpuSamplingEnabled -Test ([PSCustomObject]@{ Kind = "setup"; ParentFolder = "environment" }) -Settings $on)) "setup -> nao amostra"
    Assert-Condition (-not (Test-CpuSamplingEnabled -Test ([PSCustomObject]@{ Kind = "test"; ParentFolder = "1_cpu_memo" }) -Settings $offS)) "Enabled false -> nao amostra (nenhum CSV)"

    Section "Amostrador (Start-Job)"
    $out = Join-Path $root "amostra.csv"
    Start-CpuSampler -OutFile $out -IntervalSec 1
    # O Start-Job do PS 5.1 leva alguns segundos para subir o processo filho
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline -and -not ((Test-Path -LiteralPath $out) -and @(Get-Content -LiteralPath $out).Count -ge 4)) { Start-Sleep -Milliseconds 500 }
    Stop-CpuSampler
    $rows = @(if (Test-Path -LiteralPath $out) { Import-Csv -LiteralPath $out } else { @() })
    Assert-Condition ($rows.Count -ge 2) "amostrador gravou amostras ($($rows.Count))"
    Assert-Condition ($rows.Count -ge 1 -and [double]$rows[0].effectiveMHz -gt 0) "MHz efetivo positivo"
    $n1 = $rows.Count
    Start-Sleep -Seconds 2
    $n2 = @(Import-Csv -LiteralPath $out).Count
    Assert-Condition ($n2 -eq $n1) "depois do Stop-CpuSampler o arquivo para de crescer"
    Stop-CpuSampler
    Assert-Condition ($true) "Stop-CpuSampler idempotente"
}
finally {
    Stop-CpuSampler
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

Microsoft.PowerShell.Utility\Write-Host ""
if ($script:falhas -gt 0) {
    Microsoft.PowerShell.Utility\Write-Host "  $($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Microsoft.PowerShell.Utility\Write-Host "  Todas as verificacoes passaram." -ForegroundColor Green
exit 0
