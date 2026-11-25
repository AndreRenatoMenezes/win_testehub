# =============================================================================
#  Teste de regressao: reinicio com retomada (hub.ps1, feature 006)
#
#  Get-ScriptStatus mapeia 3010 para REINICIAR; New-ResumeQueue monta a fila
#  a partir do setup que pediu e conta reinicios seguidos; Read-ResumeQueue
#  recusa fila ausente, corrompida, incompleta ou de cenario inexistente;
#  Resolve-ResumeQueue volta aos scripts atuais na ordem da fila.
#  A tarefa agendada e o reinicio nao rodam na CI (validacao no lab).
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Get-ScriptStatus", "New-ResumeQueue", "Write-ResumeQueue", "Read-ResumeQueue", "Remove-ResumeQueue", "Resolve-ResumeQueue") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $hubPath" }
    . ([scriptblock]::Create($fn.Extent.Text))
}
# Constantes do hub usadas pelas funcoes
foreach ($var in "RebootExitCode", "ResumeFileName", "ResumeMaxReboots") {
    $assign = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq "`$$var"
    }, $false) | Select-Object -First 1
    if (-not $assign) { throw "Constante `$$var nao encontrada em $hubPath" }
    . ([scriptblock]::Create($assign.Extent.Text))
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

function New-Script { param([string]$Name) [PSCustomObject]@{ Name = $Name; Type = "ps1"; Display = $Name } }

$root = Join-Path ([System.IO.Path]::GetTempPath()) "wth_resume_$PID"
$scen = Join-Path $root "cenario_x"
$trace = Join-Path $scen "Traces"
New-Item -ItemType Directory -Path $trace -Force | Out-Null
try {
    # ---- Get-ScriptStatus ------------------------------------------------------
    Assert-Condition ((Get-ScriptStatus -ExitCode 0) -eq "PASS") "exit 0 -> PASS"
    Assert-Condition ((Get-ScriptStatus -ExitCode 3010) -eq "REINICIAR") "exit 3010 -> REINICIAR"
    Assert-Condition ((Get-ScriptStatus -ExitCode 1) -eq "FAIL") "exit 1 -> FAIL"
    Assert-Condition ((Get-ScriptStatus -ExitCode -1) -eq "FAIL") "exit -1 -> FAIL"

    # ---- New-ResumeQueue -------------------------------------------------------
    $rest = @((New-Script "10_preparar_podman"), (New-Script "11_ca_corporativa_dev"), (New-Script "13_remover_onedrive"))
    $q1 = New-ResumeQueue -ScenarioDir "$scen\" -RunId 2 -Remaining $rest -RequestedBy "10_preparar_podman.ps1" -Previous $null
    Assert-Condition ((@($q1.fila) -join ",") -eq "10_preparar_podman.ps1,11_ca_corporativa_dev.ps1,13_remover_onedrive.ps1") "fila com o setup que pediu e os seguintes, na ordem"
    Assert-Condition ($q1.reinicios -eq 1 -and $q1.runId -eq 2) "primeiro pedido: reinicios 1, run preservado"
    Assert-Condition (-not $q1.scenarioDir.EndsWith('\')) "scenarioDir sem barra no fim (aspas da tarefa)"

    $q2 = New-ResumeQueue -ScenarioDir $scen -RunId 2 -Remaining $rest -RequestedBy "10_preparar_podman.ps1" -Previous $q1
    $q3 = New-ResumeQueue -ScenarioDir $scen -RunId 2 -Remaining $rest -RequestedBy "10_preparar_podman.ps1" -Previous $q2
    Assert-Condition ($q2.reinicios -eq 2 -and $q3.reinicios -eq 3) "mesmo setup seguido soma reinicios"
    Assert-Condition ($q3.reinicios -ge $ResumeMaxReboots) "terceira vez atinge o limite (vira FAIL no hub)"
    $qOutro = New-ResumeQueue -ScenarioDir $scen -RunId 2 -Remaining @($rest[1]) -RequestedBy "11_ca_corporativa_dev.ps1" -Previous $q2
    Assert-Condition ($qOutro.reinicios -eq 1) "outro setup volta reinicios a 1"

    # ---- Write/Read/Remove -----------------------------------------------------
    Assert-Condition ($null -eq (Read-ResumeQueue -TraceRunDir $trace)) "fila ausente -> `$null"

    Write-ResumeQueue -TraceRunDir $trace -Queue $q1
    $lida = Read-ResumeQueue -TraceRunDir $trace
    Assert-Condition ($null -ne $lida -and [int]$lida.runId -eq 2 -and @($lida.fila).Count -eq 3) "fila gravada e lida de volta"
    Assert-Condition ([string]$lida.pedidoPor -eq "10_preparar_podman.ps1") "pedidoPor preservado"

    # Uma fila com um so item continua sendo lista depois do JSON
    $q1item = New-ResumeQueue -ScenarioDir $scen -RunId 1 -Remaining @($rest[0]) -RequestedBy "10_preparar_podman.ps1" -Previous $null
    Write-ResumeQueue -TraceRunDir $trace -Queue $q1item
    $lida1 = Read-ResumeQueue -TraceRunDir $trace
    Assert-Condition ($null -ne $lida1 -and @($lida1.fila).Count -eq 1) "fila de um item lida como um item"

    $file = Join-Path $trace $ResumeFileName
    Set-Content -LiteralPath $file -Value "{ isto nao e json" -Encoding UTF8
    Assert-Condition ($null -eq (Read-ResumeQueue -TraceRunDir $trace)) "JSON invalido -> `$null"

    Set-Content -LiteralPath $file -Value '{ "scenarioDir": "x", "runId": 1 }' -Encoding UTF8
    Assert-Condition ($null -eq (Read-ResumeQueue -TraceRunDir $trace)) "campos faltando -> `$null"

    $fantasma = New-ResumeQueue -ScenarioDir (Join-Path $root "nao_existe") -RunId 1 -Remaining $rest -RequestedBy "10_preparar_podman.ps1" -Previous $null
    Write-ResumeQueue -TraceRunDir $trace -Queue $fantasma
    Assert-Condition ($null -eq (Read-ResumeQueue -TraceRunDir $trace)) "cenario inexistente -> `$null"

    Write-ResumeQueue -TraceRunDir $trace -Queue $q1
    Remove-ResumeQueue -TraceRunDir $trace
    Assert-Condition (-not (Test-Path -LiteralPath $file)) "Remove-ResumeQueue apaga a fila"
    Remove-ResumeQueue -TraceRunDir $trace
    Assert-Condition ($true) "Remove-ResumeQueue sem fila nao da erro"

    # ---- Resolve-ResumeQueue ---------------------------------------------------
    $atuais = @((New-Script "13_remover_onedrive"), (New-Script "10_preparar_podman"), (New-Script "12_remover_appx_bloatware"))
    $r = Resolve-ResumeQueue -Queue $q1 -Scripts $atuais
    Assert-Condition ((@($r.Found | ForEach-Object { $_.Name }) -join ",") -eq "10_preparar_podman,13_remover_onedrive") "resolve na ordem da fila, nao na dos scripts"
    Assert-Condition ((@($r.Missing) -join ",") -eq "11_ca_corporativa_dev.ps1") "script que sumiu vai para Missing"
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
