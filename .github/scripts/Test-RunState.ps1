# =============================================================================
#  Teste de regressao: gravacao do run no _state.json (hub.ps1)
#
#  Os setups sao gravados no state assim que cada um termina (sair do menu de
#  testes sem rodar nada nao pode perder o setup). Add-RunToState com -RunId
#  junta os resultados no mesmo run, sem duplicar run nem script.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "New-StateObject", "Add-RunToState", "Get-LatestTestResults", "Write-StateFile", "Read-StateFile") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $hubPath" }
    . ([scriptblock]::Create($fn.Extent.Text))
}

$script:falhas = 0
function Assert-Condition {
    param([bool]$Condition, [string]$Description)
    if ($Condition) {
        Write-Host "  OK      $Description" -ForegroundColor Green
    } else {
        Write-Host "  FALHOU  $Description" -ForegroundColor Red
        $script:falhas++
    }
}

function New-Result {
    param([string]$Name, [string]$Status, [string]$Kind = "setup")
    [PSCustomObject]@{
        Name = $Name; Type = "ps1"; Kind = $Kind; Status = $Status; ExitCode = 0
        Duration = 1.5; TraceCount = 0; TraceDir = "C:\x\Traces\$Name"
    }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) "wth_runstate_$PID"
New-Item -ItemType Directory -Path $root -Force | Out-Null
try {
    $state = New-StateObject -Scenario "s" -Machine "m" -Modelo "x" -Patrimonio "1"

    # Fase 1: cada setup gravado no run 1, um por vez, com escrita em disco
    foreach ($r in @((New-Result "1_captura_infos_pc" "PASS"), (New-Result "5_install_py_dependencies" "FAIL"))) {
        $state = Add-RunToState -State $state -Results @($r) -RunId 1
        Write-StateFile -TraceRunDir $root -State $state
    }
    # Operador sai sem testes: o que esta em disco ja tem os setups
    $lido = Read-StateFile -TraceRunDir $root
    $latest = Get-LatestTestResults -State $lido
    Assert-Condition (@($lido.runs).Count -eq 1) "setups gravados em um unico run"
    Assert-Condition ($latest.ContainsKey("1_captura_infos_pc.ps1") -and $latest["1_captura_infos_pc.ps1"].status -eq "PASS") "setup 1 aparece como PASS ao reabrir"
    Assert-Condition ($latest["5_install_py_dependencies.ps1"].status -eq "FAIL") "setup 5 aparece como FAIL ao reabrir"

    # Fim da fase 2: testes entram no mesmo run
    $state = Add-RunToState -State $state -Results @((New-Result "3_rede" "PASS" "test")) -RunId 1
    Assert-Condition (@($state.runs).Count -eq 1) "testes entram no mesmo run dos setups"
    Assert-Condition (@($state.runs[0].tests).Count -eq 3) "run 1 tem 2 setups + 1 teste"

    # Fase 2 sem testes nao cria run vazio extra nem perde setups
    $state = Add-RunToState -State $state -Results @() -RunId 1
    Assert-Condition (@($state.runs).Count -eq 1 -and @($state.runs[0].tests).Count -eq 3) "fase 2 vazia nao altera o run"

    # Reexecutar o mesmo script no mesmo run substitui a entrada
    $state = Add-RunToState -State $state -Results @((New-Result "5_install_py_dependencies" "PASS")) -RunId 1
    $t5 = @($state.runs[0].tests | Where-Object { $_.name -eq "5_install_py_dependencies.ps1" })
    Assert-Condition ($t5.Count -eq 1 -and $t5[0].status -eq "PASS") "mesmo script no mesmo run substitui a entrada"

    # Run seguinte vira run 2
    $state = Add-RunToState -State $state -Results @((New-Result "2_opcoes_energia" "PASS")) -RunId 2
    Assert-Condition (@($state.runs).Count -eq 2 -and $state.runs[1].runId -eq 2) "novo RunId cria run novo"

    # Sem -RunId continua criando o proximo run (compatibilidade)
    $state = Add-RunToState -State $state -Results @((New-Result "x" "PASS"))
    Assert-Condition (@($state.runs).Count -eq 3 -and $state.runs[2].runId -eq 3) "sem -RunId cria o proximo run"
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "  $($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "  Todas as verificacoes passaram." -ForegroundColor Green
exit 0
