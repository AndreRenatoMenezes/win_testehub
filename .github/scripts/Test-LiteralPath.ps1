# =============================================================================
#  Teste de regressao: hub em caminho com colchetes (hub.ps1)
#
#  '[' e ']' sao validos em nome de pasta, mas com -Path viram curinga: o hub
#  em "...\hub [teste]" nao achava os cenarios. Garante que listar cenarios,
#  ler/gravar o _state.json, listar testes, mover evidencias para _anterior/,
#  checar CSVs tematicos e gravar o _relatorio funcionam com -LiteralPath,
#  sem tocar a pasta vizinha "hub teste" (que o curinga casaria).
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path -LiteralPath $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Get-NaturalSortKey", "Get-Scripts", "Read-StateFile", "Write-StateFile", "Get-LatestTestResults",
                "Get-ExistingScenarios", "Move-EvidenceToAnterior", "Test-ThematicCSVs", "Get-StateField",
                "Get-RunWarnings", "Get-Median", "Get-CpuFrequencySummary", "Build-ConsolidatedReport") {
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

$guid     = [guid]::NewGuid().ToString('N')
$tmp      = [System.IO.Path]::GetTempPath()
$hub      = Join-Path $tmp "hubtest $guid [teste]"
$neighbor = Join-Path $tmp "hubtest $guid teste"      # "[teste]" como curinga casaria com "t","e","s"...
try {
    $exec    = Join-Path $hub "Execucoes"
    $scen    = Join-Path $exec "cen_PC_2026-11-24"
    $traces  = Join-Path $scen "Traces"
    $testsRt = Join-Path $hub "Testes"
    New-Item -ItemType Directory -Path (Join-Path $traces "2_disco") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testsRt "2_disco") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $testsRt "10_dev_containers") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $neighbor "Execucoes\outro\Traces") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $testsRt "2_disco\2_teste_disco.py") -Value "#"
    Set-Content -LiteralPath (Join-Path $testsRt "10_dev_containers\10_dev_containers.py") -Value "#"
    Set-Content -LiteralPath (Join-Path $testsRt "2_disco\helper.txt") -Value "#"
    Set-Content -LiteralPath (Join-Path $neighbor "sentinela.txt") -Value "intacto"

    $state = [PSCustomObject]@{
        scenario = "cen"; machine = "PC"; modelo = "5440"; patrimonio = "044163"
        createdAt = "2026-11-24T10:00:00"; lastRunAt = "2026-11-24T11:00:00"
        runs = @([PSCustomObject]@{ runId = 1; timestamp = "2026-11-24T11:00:00"; tests = @([PSCustomObject]@{ name = "2_teste_disco.py"; folder = "2_disco"; status = "PASS"; duration = 5 }) })
    }
    Write-StateFile -TraceRunDir $traces -State $state
    Assert-Condition (Test-Path -LiteralPath (Join-Path $traces "_state.json")) "Write-StateFile grava em caminho com colchetes"
    $back = Read-StateFile -TraceRunDir $traces
    Assert-Condition ($null -ne $back -and $back.modelo -eq "5440") "Read-StateFile le de caminho com colchetes"

    $sc = @(Get-ExistingScenarios -ExecucoesDir $exec)
    Assert-Condition ($sc.Count -eq 1 -and $sc[0].Name -eq "cen_PC_2026-11-24") "Get-ExistingScenarios lista o cenario"

    $scripts = Get-Scripts -Root $testsRt -Kind "test"
    $names = @($scripts | ForEach-Object { $_.Name })
    Assert-Condition ($names.Count -eq 2 -and $names[0] -eq "2_teste_disco" -and $names[1] -eq "10_dev_containers") "Get-Scripts lista .py/.ps1 em ordem natural (sem -Include)"

    $mod = Join-Path $traces "2_disco"
    Set-Content -LiteralPath (Join-Path $mod "disco.csv") -Value "a"
    New-Item -ItemType Directory -Path (Join-Path $mod "sub") -Force | Out-Null
    Move-EvidenceToAnterior -ScriptTraceDir $mod -RunId 1
    $moved = @(Get-ChildItem -LiteralPath (Join-Path $mod "_anterior") -Recurse -File)
    Assert-Condition ($moved.Count -eq 1 -and -not (Test-Path -LiteralPath (Join-Path $mod "disco.csv"))) "Move-EvidenceToAnterior move as evidencias"

    Set-Content -LiteralPath (Join-Path $mod "disco.csv") -Value "a"
    $log = Join-Path $scen "run.log"
    $r = Test-ThematicCSVs -TraceRunDir $traces -LogFile $log
    Assert-Condition ($r.Found -ge 1 -and (Test-Path -LiteralPath $log)) "Test-ThematicCSVs acha o CSV e grava o log"

    Build-ConsolidatedReport -TraceRunDir $traces -State $back
    Assert-Condition ((Test-Path -LiteralPath (Join-Path $traces "_relatorio.html")) -and (Test-Path -LiteralPath (Join-Path $traces "_relatorio.json")) -and (Test-Path -LiteralPath (Join-Path $traces "_relatorio.csv"))) "Build-ConsolidatedReport grava os tres arquivos"

    Assert-Condition ((Get-Content -LiteralPath (Join-Path $neighbor "sentinela.txt")) -eq "intacto" -and @(Get-ChildItem -LiteralPath $neighbor -Recurse -File).Count -eq 1) "pasta vizinha intacta"
}
finally {
    Remove-Item -LiteralPath $hub -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $neighbor -Recurse -Force -ErrorAction SilentlyContinue
}

Microsoft.PowerShell.Utility\Write-Host ""
if ($script:falhas -gt 0) {
    Microsoft.PowerShell.Utility\Write-Host "  $($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Microsoft.PowerShell.Utility\Write-Host "  Todas as verificacoes passaram." -ForegroundColor Green
exit 0
