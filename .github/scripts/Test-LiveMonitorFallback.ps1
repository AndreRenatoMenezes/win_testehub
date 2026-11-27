# =============================================================================
#  Teste de regressao: monitor ao vivo da Fase 2 (hub.ps1, Spec 004)
#
#  - LiveMonitor do config.json (config novo, antigo sem a secao e "Enabled"
#    como texto) via Merge-ConfigSection;
#  - Test-LiveMonitorLowImpact (0_consumo_basal / 5_bateria vs 2_disco);
#  - New-LiveMonitorStatePayload (fila, status, secao, avisos da rodada);
#  - Test-LiveMonitorAvailable: fallback com Enabled=false, sem live_monitor.py
#    ou com Python sem rich;
#  - ConvertTo-ProcessArgument (aspas do Windows);
#  - Invoke-LiveMonitorProcess ponta a ponta quando ha Python com rich
#    (opcional: -PythonExe; pulado se nenhum Python tiver rich).
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param(
    [string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"),
    [string]$PythonExe = ""
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path $HubPath).Path
$repoRoot = Split-Path $hubPath
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Merge-ConfigSection", "Get-StateField", "Get-RunWarnings", "Resolve-PythonExe", "Test-LiveMonitorAvailable",
                "Test-LiveMonitorLowImpact", "New-LiveMonitorStatePayload", "ConvertTo-ProcessArgument", "Invoke-LiveMonitorProcess") {
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
function Section { param($T) Write-Host "`n  $T" -ForegroundColor Cyan }

# Mesmo bloco de carga do hub.ps1 (padroes + conversao do Enabled)
function Get-LiveSettings {
    param([PSCustomObject]$Config)
    $s = Merge-ConfigSection $Config "LiveMonitor" @{ Enabled = $true; RefreshHz = 1; LogTailLines = 8; TelemetryIntervalSec = 2; LowImpactFolders = @("0_consumo_basal", "5_bateria") }
    try { $s.Enabled = [System.Convert]::ToBoolean([string]$s.Enabled) } catch { $s.Enabled = $true }
    return $s
}

Section "Carga do LiveMonitor (config.json)"
$hubText = Get-Content -LiteralPath $hubPath -Raw
Assert-Condition ($hubText -match 'Merge-ConfigSection \$config "LiveMonitor"') "hub.ps1 carrega LiveMonitor com Merge-ConfigSection"
Assert-Condition ($hubText -match '(?s)\$defaultConfig\s*=\s*@\{.*LiveMonitor\s*=\s*@\{') "hub.ps1 inclui LiveMonitor no defaultConfig"
$cfgReal = Get-Content -LiteralPath (Join-Path $repoRoot "config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$s = Get-LiveSettings $cfgReal
Assert-Condition ($s.Enabled -eq $true -and [int]$s.RefreshHz -eq 1 -and [int]$s.LogTailLines -eq 8 -and [int]$s.TelemetryIntervalSec -eq 2) "config.json do repo: Enabled/RefreshHz/LogTailLines/TelemetryIntervalSec"
Assert-Condition ((@($s.LowImpactFolders) -join ",") -eq "0_consumo_basal,5_bateria") "config.json do repo: LowImpactFolders = 0_consumo_basal, 5_bateria"
$s = Get-LiveSettings ([PSCustomObject]@{ Settings = [PSCustomObject]@{} })
Assert-Condition ($s.Enabled -eq $true -and (@($s.LowImpactFolders).Count -eq 2)) "config antigo (sem a secao) usa os padroes"
$s = Get-LiveSettings ([PSCustomObject]@{ LiveMonitor = [PSCustomObject]@{ Enabled = "false"; LogTailLines = 4 } })
Assert-Condition ($s.Enabled -eq $false -and [int]$s.LogTailLines -eq 4 -and [int]$s.RefreshHz -eq 1) "Enabled = ""false"" (texto) desliga; chaves ausentes ficam no padrao"
$s = Get-LiveSettings ([PSCustomObject]@{ LiveMonitor = [PSCustomObject]@{ Enabled = "talvez" } })
Assert-Condition ($s.Enabled -eq $true) "Enabled invalido volta ao padrao (true)"

Section "Test-LiveMonitorLowImpact"
$settings = Get-LiveSettings $cfgReal
Assert-Condition (Test-LiveMonitorLowImpact -Test ([PSCustomObject]@{ ParentFolder = "0_consumo_basal" }) -Settings $settings) "0_consumo_basal -> baixo impacto"
Assert-Condition (Test-LiveMonitorLowImpact -Test ([PSCustomObject]@{ ParentFolder = "5_bateria" }) -Settings $settings) "5_bateria -> baixo impacto"
Assert-Condition (-not (Test-LiveMonitorLowImpact -Test ([PSCustomObject]@{ ParentFolder = "2_disco" }) -Settings $settings)) "2_disco -> modo completo"
Assert-Condition (-not (Test-LiveMonitorLowImpact -Test ([PSCustomObject]@{ ParentFolder = "0_consumo_basal" }) -Settings ([PSCustomObject]@{ Enabled = $true }))) "sem LowImpactFolders -> modo completo"

Section "New-LiveMonitorStatePayload"
$state = [PSCustomObject]@{
    scenario = "ImagemLimpa"; machine = "DESKTOP-ABC"; modelo = "5440"; patrimonio = "045163"; runs = @()
    avisos = @(
        [PSCustomObject]@{ run = 2; fonte = "checagem"; texto = "Pouco espaco livre" },
        [PSCustomObject]@{ run = 1; fonte = "sobra"; texto = "Run anterior" }
    )
}
$tests = @(
    [PSCustomObject]@{ Name = "0_teste_consumo_basal"; Type = "py"; ParentFolder = "0_consumo_basal"; SectionLabel = "Escritorio" },
    [PSCustomObject]@{ Name = "1_automacao_performance"; Type = "py"; ParentFolder = "1_cpu_memo"; SectionLabel = "Escritorio" },
    [PSCustomObject]@{ Name = "2_teste_disco"; Type = "py"; ParentFolder = "2_disco" }
)
$results = @([PSCustomObject]@{ Status = "PASS"; Duration = 642.4321 })
$sampler = [PSCustomObject]@{ Enabled = $true; ThrottleAlertPct = 25; LoadMinPct = 40 }
$p = New-LiveMonitorStatePayload -State $state -RunId 2 -RunStart (Get-Date "2026-11-27T10:00:00") -Tests $tests -Results $results -CurrentIndex 1 -Settings $settings -Sampler $sampler
Assert-Condition ($p.scenario -eq "ImagemLimpa" -and $p.machine -eq "DESKTOP-ABC" -and $p.modelo -eq "5440" -and $p.patrimonio -eq "045163") "cenario, maquina, modelo e patrimonio"
Assert-Condition ($p.runId -eq 2 -and $p.currentIndex -eq 1 -and $p.runStartEpoch -gt 1700000000) "runId, currentIndex e runStartEpoch (epoch em segundos)"
$st = @($p.queue | ForEach-Object { $_.status }) -join ","
Assert-Condition ($st -eq "PASS,running,pending") "status da fila: PASS, running, pending"
Assert-Condition ([double]$p.queue[0].duration -eq 642.432) "duracao do teste concluido"
Assert-Condition ($p.queue[0].section -eq "Escritorio" -and $p.queue[2].section -eq "") "section da Spec 003 (ou vazia sem SectionLabel)"
Assert-Condition (@($p.warnings).Count -eq 1 -and $p.warnings[0].texto -eq "Pouco espaco livre") "warnings so da run atual"
Assert-Condition ([double]$p.throttleAlertPct -eq 25 -and [double]$p.loadMinPct -eq 40 -and [int]$p.logTailLines -eq 8) "parametros do CpuSampler e do LiveMonitor"
$json = $p | ConvertTo-Json -Depth 6
$back = $json | ConvertFrom-Json
Assert-Condition (@($back.queue).Count -eq 3 -and @($back.warnings).Count -eq 1) "serializa em JSON com fila e avisos como listas"
$p1 = New-LiveMonitorStatePayload -State ([PSCustomObject]@{ scenario = "X" }) -RunId 1 -RunStart (Get-Date) -Tests @($tests[0]) -CurrentIndex 0 -Settings $settings -Sampler $null
$j1 = $p1 | ConvertTo-Json -Depth 6
Assert-Condition ($j1 -match '"queue":\s*\[' -and $j1 -match '"warnings":\s*\[') "fila de 1 teste e sem avisos continuam listas no JSON"

Section "Test-LiveMonitorAvailable (fallback)"
$monitor = Join-Path $repoRoot "Testes\_lib\live_monitor.py"
$off = Get-LiveSettings ([PSCustomObject]@{ LiveMonitor = [PSCustomObject]@{ Enabled = $false } })
$r = Test-LiveMonitorAvailable -Settings $off -PythonExe "python" -MonitorScript $monitor
Assert-Condition (-not $r.Available -and $r.Reason -match "Enabled") "Enabled = false -> painel classico"
$r = Test-LiveMonitorAvailable -Settings $settings -PythonExe "python" -MonitorScript (Join-Path $repoRoot "nao_existe.py")
Assert-Condition (-not $r.Available -and $r.Reason -match "live_monitor") "live_monitor.py ausente -> painel classico"
$r = Test-LiveMonitorAvailable -Settings $settings -PythonExe "C:\nao\existe\python.exe" -MonitorScript $monitor
Assert-Condition (-not $r.Available -and $r.Reason -match "rich") "Python inexistente -> painel classico sem excecao"
$fakeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("hubtest live " + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fakeDir -Force | Out-Null
$fakePy = Join-Path $fakeDir "python_sem_rich.cmd"
Set-Content -LiteralPath $fakePy -Value "@exit /b 1" -Encoding ASCII
$r = Test-LiveMonitorAvailable -Settings $settings -PythonExe $fakePy -MonitorScript $monitor
Assert-Condition (-not $r.Available -and $r.Reason -match "rich") "Python sem rich (import falha) -> painel classico"
Assert-Condition ($hubText -match '\$useLiveMonitor = \$liveCheck\.Available' -and $hubText -match 'Show-ExecutionProgress -TestsToRun \$toRun') "loop da Fase 2 mantem o painel classico como fallback"
$venv = Join-Path $fakeDir ".venv"
Assert-Condition ((Resolve-PythonExe -VenvPath $venv) -in @("python", "python3")) "Resolve-PythonExe sem .venv usa o Python do PATH"
New-Item -ItemType Directory -Path (Join-Path $venv "Scripts") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $venv "Scripts\python.exe") -Value "" -Encoding ASCII
Assert-Condition ((Resolve-PythonExe -VenvPath $venv) -eq (Join-Path $venv "Scripts\python.exe")) "Resolve-PythonExe prefere o .venv"

Section "ConvertTo-ProcessArgument"
Assert-Condition ((ConvertTo-ProcessArgument "abc") -eq 'abc') "sem espaco: sem aspas"
Assert-Condition ((ConvertTo-ProcessArgument "C:\a b\c.py") -eq '"C:\a b\c.py"') "com espaco: entre aspas"
Assert-Condition ((ConvertTo-ProcessArgument "C:\a b\") -eq '"C:\a b\\"') "barra final dobrada antes da aspa"
Assert-Condition ((ConvertTo-ProcessArgument 'x"y') -eq '"x\"y"') "aspas internas escapadas"
Assert-Condition ((ConvertTo-ProcessArgument "") -eq '""') "vazio vira """""

Section "Invoke-LiveMonitorProcess (ponta a ponta)"
$py = $PythonExe
if (-not $py) {
    foreach ($c in @((Join-Path $repoRoot ".venv\Scripts\python.exe"), "python")) {
        try { & $c -c "import rich" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
    }
}
if (-not $py) {
    Write-Host "  --      nenhum Python com rich disponivel: ponta a ponta pulado" -ForegroundColor DarkGray
} else {
    $mockDir = Join-Path $fakeDir "teste [x] com espaco"
    New-Item -ItemType Directory -Path $mockDir -Force | Out-Null
    $mock = Join-Path $mockDir "mock.py"
    $lib = (Join-Path $repoRoot "Testes\_lib") -replace '\\', '/'
    Set-Content -LiteralPath $mock -Encoding ASCII -Value @(
        "import os, sys",
        "sys.path.insert(0, '$lib')",
        "from hub_progress import emit_progress, emit_alert",
        "emit_progress('Ciclo 1/1', 1, 1)",
        "emit_alert('alerta mock')",
        "print('PID=' + os.environ.get('HUB_MONITOR_PID', ''))",
        "print('[ERRO] falha mock')",
        "sys.exit(2)"
    )
    $live = Invoke-LiveMonitorProcess -PythonExe $py -MonitorScript $monitor -Payload $p1 -Command @($py, "-u", $mock) -LowImpact
    Assert-Condition ($null -ne $live.Result -and [int]$live.Result.exitCode -eq 2) "resultado JSON lido com exitCode 2"
    Assert-Condition ($live.Result.lastStage -eq "Ciclo 1/1" -and @($live.Result.alerts).Count -eq 1) "lastStage e alerts do --result"
    Assert-Condition ((@($live.Lines) -join "`n") -match '\[HUB:PROGRESS\]' -and (@($live.Lines) -join "`n") -match 'PID=\d+') "linhas [HUB:PROGRESS] e HUB_MONITOR_PID no stdout capturado"
    Assert-Condition (-not (Test-Path (Join-Path $env:TEMP "wintesthub_live_state_*.json"))) "arquivos temporarios removidos"
    $broken = Invoke-LiveMonitorProcess -PythonExe $py -MonitorScript (Join-Path $fakeDir "nao_existe.py") -Payload $p1 -Command @($py, "-u", $mock)
    Assert-Condition ($null -eq $broken.Result -and $broken.Error -match "sem gravar") "monitor quebrado: erro claro, sem resultado"
}
Remove-Item -LiteralPath $fakeDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
