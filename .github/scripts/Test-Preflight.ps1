# =============================================================================
#  Teste de regressao: checagem antes da fila e sobras de teste (hub.ps1)
#
#  Get-PreflightFindings so acusa o que os testes selecionados precisam;
#  Get-TestLeftovers so detecta processos abertos por testes do hub (pela
#  linha de comando / flags de automacao, nunca so pelo nome); Remove-BlockedTests
#  tira da fila os testes com achados 'Impede'. As sondas do sistema (tomada,
#  internet, disco, ferramentas, processos, wpr, podman) sao substituidas.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hubPath = (Resolve-Path $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "New-PreflightFinding", "Get-DevModuleTools", "Test-SpeedtestConfigured", "Get-PreflightFindings",
                "Test-WprRecording", "Get-TestLeftovers", "Remove-BlockedTests", "Clear-TestLeftovers", "Stop-TestLeftovers") {
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

# ---- Sondas substituidas -----------------------------------------------------
$script:power    = "AC"
$script:internet = $true
$script:freeGB   = 100
$script:tools    = @{}        # cmd -> texto da versao ($null = ausente)
$script:procs    = @()
$script:wpr      = $null
$script:podman   = [PSCustomObject]@{ Available = $false; Containers = @(); MachineRunning = $false }
function Get-PowerSource { $script:power }
function Test-InternetReachable { param($HostName) $script:internet }
function Get-FreeSpaceGB { param($Path) $script:freeGB }
function Test-CommandAvailable { param($Cmd) $script:tools.ContainsKey($Cmd) -and $null -ne $script:tools[$Cmd] }
function Get-ToolVersion {
    param($Cmd, $VersionArgs)
    if (-not $script:tools.ContainsKey($Cmd) -or $null -eq $script:tools[$Cmd]) { return $null }
    $out = $script:tools[$Cmd]
    $ver = $null
    if ($out -match '(\d+)\.(\d+)') { $ver = [version]"$($Matches[1]).$($Matches[2])" }
    [PSCustomObject]@{ Path = "C:\fake\$Cmd.exe"; Output = $out; Version = $ver }
}
function Get-ProcessSnapshot { $script:procs }
function Get-WprStatus { $script:wpr }
function Get-PodmanState { $script:podman }
function Get-HighCpuProcesses { param($ThresholdPct) @() }

# ---- Estrutura temporaria do hub (com colchetes: -LiteralPath) ---------------
$guid = [guid]::NewGuid().ToString('N')
$hub  = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest preflight $guid [x]"
$testsRoot = Join-Path $hub "Testes"
foreach ($d in "1_cpu_memo", "3_rede", "5_bateria", "8_dev_go", "10_dev_containers", "2_disco") {
    New-Item -ItemType Directory -Path (Join-Path $testsRoot $d) -Force | Out-Null
}
Set-Content -LiteralPath (Join-Path $testsRoot "8_dev_go\cargas.json") -Encoding UTF8 -Value '{"ferramentas":[{"cmd":"go","versao":["go","version"],"minima":"1.21"}],"repos":[{"nome":"hugo"}]}'
Set-Content -LiteralPath (Join-Path $testsRoot "10_dev_containers\cargas.json") -Encoding UTF8 -Value '{"ferramentas":[{"cmd":"podman","versao":["podman","--version"],"minima":"5.0"}],"repos":[]}'

function New-T { param($Folder, $Name, $Type = "py") [PSCustomObject]@{ Name = $Name; Type = $Type; ParentFolder = $Folder } }
$tCpu  = New-T "1_cpu_memo" "1_automacao_performance"
$tRede = New-T "3_rede" "3_teste_rede"
$tBat  = New-T "5_bateria" "5_teste_bateria"
$tGo   = New-T "8_dev_go" "8_dev_go"
$tPod  = New-T "10_dev_containers" "10_dev_containers"
$tDisk = New-T "2_disco" "2_teste_disco"
$settings = [PSCustomObject]@{ MinFreeGB = 20; CpuAlertPct = 10; InternetHost = "example.invalid" }
$okTools = @{ wpr = "wpr"; wpaexporter = "wpa"; go = "go version go1.22.3 windows/amd64"; git = "git version 2.45.1"; podman = "podman version 5.2.0" }

function Get-F { param($Tests) Get-PreflightFindings -Tests $Tests -TestsRoot $testsRoot -HubRoot $hub -Settings $settings -SkipLeftovers }
function Find-Item { param($F, $Pattern) return ,@($F | Where-Object { $_.Item -match $Pattern }) }

$envUrl = $env:HUB_SPEEDTEST_URL
try {
    $env:HUB_SPEEDTEST_URL = ""
    Write-Host "`n  Checagem por teste selecionado" -ForegroundColor Cyan

    $script:tools = $okTools.Clone()
    $f = Get-F @($tCpu)
    $p = Find-Item $f 'wpaProfile'
    Assert-Condition ($p.Count -eq 1 -and $p[0].Nivel -eq "Impede") "modulo 1 sem .wpaProfile -> Impede"
    Assert-Condition ($p.Count -eq 1 -and $p[0].Acao -match '1_cpu_memo' -and $p[0].Testes -contains "1_automacao_performance.py") "acao indica a pasta e o teste afetado"

    Set-Content -LiteralPath (Join-Path $testsRoot "1_cpu_memo\Agentes_SI_Profile.wpaProfile.xml") -Value "<x/>"
    $f = Get-F @($tCpu)
    Assert-Condition ((Find-Item $f 'wpaProfile').Count -eq 0) "profile .wpaProfile.xml presente -> sem achado"

    $script:tools.Remove("wpaexporter")
    $f = Get-F @($tCpu)
    Assert-Condition ((Find-Item $f 'wpaexporter').Count -eq 1) "wpaexporter ausente -> Impede"
    $script:tools = $okTools.Clone()

    $f = Get-F @($tDisk)
    Assert-Condition ($f.Count -eq 0) "teste nao relacionado (disco) nao herda achados do modulo 1"
    $b5 = Find-Item (Get-F @($tBat)) 'Agentes_SI_Bateria_Profile'
    Assert-Condition ($b5.Count -eq 1 -and $b5[0].Nivel -eq "Impede" -and $b5[0].Testes -contains "5_teste_bateria.py") "modulo 5 sem o profile de bateria -> Impede"
    Set-Content -LiteralPath (Join-Path $testsRoot "5_bateria\Agentes_SI_Bateria_Profile.wpaProfile") -Value "<x/>"
    Assert-Condition ((Get-F @($tBat)).Count -eq 0) "profile de bateria presente -> sem achado"

    $f = Get-F @($tRede)
    Assert-Condition ((Find-Item $f 'speedtest').Count -eq 1) "teste 3 sem URL do speedtest -> Impede"
    Set-Content -LiteralPath (Join-Path $hub "config.local.json") -Value '{"SpeedtestUrl":"https://10.0.0.1/"}'
    Assert-Condition ((Find-Item (Get-F @($tRede)) 'speedtest').Count -eq 0) "SpeedtestUrl no config.local.json -> sem achado"
    Remove-Item -LiteralPath (Join-Path $hub "config.local.json")
    $env:HUB_SPEEDTEST_URL = "https://10.0.0.1/"
    Assert-Condition ((Find-Item (Get-F @($tRede)) 'speedtest').Count -eq 0) "HUB_SPEEDTEST_URL -> sem achado"
    $env:HUB_SPEEDTEST_URL = ""

    Write-Host "`n  Ferramentas de dev (cargas.json)" -ForegroundColor Cyan
    Assert-Condition ((Get-F @($tGo)).Count -eq 0) "go e git na versao -> sem achado"
    $script:tools["go"] = "go version go1.19.1 windows/amd64"
    $g = Find-Item (Get-F @($tGo)) "'go'"
    Assert-Condition ($g.Count -eq 1 -and $g[0].Nivel -eq "Impede" -and $g[0].Item -match 'minima 1\.21' -and $g[0].Acao -match 'Setup 7') "go abaixo da minima -> Impede, manda rodar o Setup 7"
    $script:tools["go"] = $null
    Assert-Condition ((Find-Item (Get-F @($tGo)) "'go' nao encontrado").Count -eq 1) "go ausente -> Impede"
    $script:tools = $okTools.Clone()
    $script:tools["git"] = $null
    Assert-Condition ((Find-Item (Get-F @($tGo)) "'git'").Count -eq 1) "git implicito (repos) ausente -> Impede"
    $script:tools = $okTools.Clone()
    $script:tools["podman"] = $null
    $pd = Find-Item (Get-F @($tPod)) "'podman'"
    Assert-Condition ($pd.Count -eq 1 -and $pd[0].Acao -match 'Setup 10') "podman ausente -> Impede, manda rodar o Setup 10"
    $script:tools = $okTools.Clone()
    $script:podman = [PSCustomObject]@{ Available = $true; Containers = @(); MachineRunning = $false }
    $pm = Find-Item (Get-F @($tPod)) 'podman machine'
    Assert-Condition ($pm.Count -eq 1 -and $pm[0].Nivel -eq "Impede" -and $pm[0].Acao -match 'machine start') "modulo 10 com a podman machine desligada -> Impede"
    $script:podman = [PSCustomObject]@{ Available = $true; Containers = @(); MachineRunning = $true }
    Assert-Condition ((Find-Item (Get-F @($tPod)) 'podman machine').Count -eq 0) "podman machine ligada -> sem achado"
    Assert-Condition ((Find-Item (Get-F @($tGo)) 'podman machine').Count -eq 0) "sem o modulo 10 na fila, a machine nao e checada"
    $script:podman = [PSCustomObject]@{ Available = $false; Containers = @(); MachineRunning = $false }

    Write-Host "`n  Tomada, internet e disco" -ForegroundColor Cyan
    $script:power = "Battery"
    $f = Get-F @($tGo, $tDisk, $tBat)
    $bi = @($f | Where-Object { $_.Item -match 'bateria' -and $_.Nivel -eq 'Impede' })
    $ba = @($f | Where-Object { $_.Item -match 'bateria' -and $_.Nivel -eq 'Atencao' })
    Assert-Condition ($bi.Count -eq 1 -and $bi[0].Testes -contains "8_dev_go.py") "bateria -> Impede para as cargas de dev"
    Assert-Condition ($ba.Count -eq 1 -and $ba[0].Testes -contains "2_teste_disco.py" -and $ba[0].Testes -notcontains "5_teste_bateria.py") "bateria -> Atencao nos demais, nunca no teste 5"
    Assert-Condition ((Get-F @($tBat)).Count -eq 0) "so o teste 5 na bateria -> sem achado"
    $script:power = "AC"

    $script:internet = $false
    $n = Find-Item (Get-F @($tGo)) 'internet'
    Assert-Condition ($n.Count -eq 1 -and $n[0].Nivel -eq "Atencao") "sem internet com carga de dev -> Atencao"
    Assert-Condition ((Find-Item (Get-F @($tDisk)) 'internet').Count -eq 0) "sem internet com teste de disco -> sem achado"
    $script:internet = $true

    $script:freeGB = 5
    $d = Find-Item (Get-F @($tDisk)) 'espaco livre'
    Assert-Condition ($d.Count -eq 1 -and $d[0].Nivel -eq "Atencao") "disco abaixo do minimo -> Atencao"
    $script:freeGB = 100

    Write-Host "`n  Remove-BlockedTests" -ForegroundColor Cyan
    $script:tools["go"] = $null
    $queue = @($tGo, $tDisk)
    $left = @(Remove-BlockedTests -Tests $queue -Findings (Get-F $queue))
    Assert-Condition ($left.Count -eq 1 -and $left[0].Name -eq "2_teste_disco") "[R] tira so o teste com Impede"
    $script:tools = $okTools.Clone()

    Write-Host "`n  Sobras de teste" -ForegroundColor Cyan
    $script:wpr = [PSCustomObject]@{ ExitCode = 0; Output = "Microsoft Windows Performance Recorder`nWPR is not recording" }
    Assert-Condition (-not (Test-WprRecording $script:wpr)) "wpr -status 'not recording' (en) -> parado"
    Assert-Condition (-not (Test-WprRecording ([PSCustomObject]@{ ExitCode = 0; Output = "O WPR nao esta gravando" }))) "wpr -status pt-BR parado -> parado"
    Assert-Condition (Test-WprRecording ([PSCustomObject]@{ ExitCode = 0; Output = "WPR recording is in progress..." })) "wpr -status gravando (en) -> ativo"
    Assert-Condition (Test-WprRecording ([PSCustomObject]@{ ExitCode = 0; Output = "A gravacao do WPR esta em andamento: gravando" })) "wpr -status gravando (pt) -> ativo"
    Assert-Condition (-not (Test-WprRecording $null)) "sem wpr -> parado"

    $script:wpr = [PSCustomObject]@{ ExitCode = 0; Output = "WPR recording is in progress..." }
    $script:procs = @(
        [PSCustomObject]@{ Name = "msedge.exe"; ProcessId = 10; ParentProcessId = 1; CommandLine = '"msedge.exe" --profile-directory=Default' },
        [PSCustomObject]@{ Name = "msedge.exe"; ProcessId = 11; ParentProcessId = 1; CommandLine = '"msedge.exe" --enable-automation --remote-debugging-port=0' },
        [PSCustomObject]@{ Name = "msedgedriver.exe"; ProcessId = 12; ParentProcessId = 1; CommandLine = 'msedgedriver.exe --port=1' },
        [PSCustomObject]@{ Name = "msedge.exe"; ProcessId = 13; ParentProcessId = 12; CommandLine = '"msedge.exe" --remote-debugging-port=0 --user-data-dir=C:\tmp\x' },
        [PSCustomObject]@{ Name = "msedge.exe"; ProcessId = 14; ParentProcessId = 1; CommandLine = '"msedge.exe" --remote-debugging-port=9222' },
        [PSCustomObject]@{ Name = "python.exe"; ProcessId = 22; ParentProcessId = 1; CommandLine = "python.exe `"$($testsRoot)_old\x.py`"" },
        [PSCustomObject]@{ Name = "python.exe"; ProcessId = 20; ParentProcessId = 1; CommandLine = "python.exe C:\outro\script.py" },
        [PSCustomObject]@{ Name = "python.exe"; ProcessId = 21; ParentProcessId = 1; CommandLine = "python.exe -u `"$testsRoot\2_disco\2_teste_disco.py`"" },
        [PSCustomObject]@{ Name = "diskspd.exe"; ProcessId = 30; ParentProcessId = 21; CommandLine = "diskspd.exe -c1G" },
        [PSCustomObject]@{ Name = "dotnet.exe"; ProcessId = 40; ParentProcessId = 1; CommandLine = 'dotnet.exe "C:\sdk\MSBuild.dll" /nodemode:1 /nodeReuse:true' },
        [PSCustomObject]@{ Name = "dotnet.exe"; ProcessId = 41; ParentProcessId = 1; CommandLine = 'dotnet.exe run --project app' },
        [PSCustomObject]@{ Name = "VBCSCompiler.exe"; ProcessId = 42; ParentProcessId = 1; CommandLine = 'VBCSCompiler.exe' }
    )
    $script:podman = [PSCustomObject]@{ Available = $true; Containers = @("wintestehub-database"); MachineRunning = $true }

    $pf = Get-PreflightFindings -Tests @($tDisk) -TestsRoot $testsRoot -HubRoot $hub -Settings $settings
    $bsf = @($pf | Where-Object { $_.Item -match 'Build servers' })
    Assert-Condition ($bsf.Count -eq 1 -and $null -eq $bsf[0].Sobra) "antes da fila, build servers do .NET so como aviso (sem [F]: podem ser do Visual Studio)"
    Assert-Condition (@($pf | Where-Object { $null -ne $_.Sobra -and $_.Sobra.Id -eq "wpr" }).Count -eq 1) "antes da fila, sessao WPR vem com [F]"

    $all = Get-TestLeftovers -TestsRoot $testsRoot
    $ids = @($all | ForEach-Object { $_.Id })
    Assert-Condition ($ids -contains "wpr") "sessao WPR ativa detectada"
    $edge = @($all | Where-Object { $_.Id -eq "edge" })
    Assert-Condition ($edge.Count -eq 1 -and $edge[0].Pids -contains 11 -and $edge[0].Pids -contains 12 -and $edge[0].Pids -contains 13 -and $edge[0].Pids -notcontains 10) "Edge da automacao (flag ou filho do driver) detectado; Edge do usuario fica"
    Assert-Condition ($edge[0].Pids -notcontains 14) "Edge do usuario so com --remote-debugging-port (VS Code/DevTools) fica"
    $py = @($all | Where-Object { $_.Id -eq "python" })
    Assert-Condition ($py.Count -eq 1 -and $py[0].Pids -contains 21 -and $py[0].Pids -notcontains 20 -and $py[0].Pids -notcontains 22) "Python de Testes\ detectado; Python de fora (e de Testes_old\) fica"
    $ign = @(Get-TestLeftovers -TestsRoot $testsRoot -IgnorePids @(40, 42) | Where-Object { $_.Id -eq "dotnet" })
    Assert-Condition ($ign.Count -eq 0) "processos que ja existiam antes do teste (IgnorePids) nao sao sobra"
    $edge5 = @(Get-TestLeftovers -TestsRoot $testsRoot -Folders @("5_bateria") | ForEach-Object { $_.Id })
    Assert-Condition ($edge5 -contains "edge") "Edge da automacao tambem e limpo depois do teste 5"

    # Stop-TestLeftovers real, com stubs dos comandos externos
    $script:calls = @()
    function wpr { $script:calls += "wpr $($args -join ' ')" }
    function podman { $script:calls += "podman $($args -join ' ')" }
    function dotnet { $script:calls += "dotnet $($args -join ' ')" }
    function taskkill.exe { $script:calls += "taskkill $($args -join ' ')" }
    function Test-CommandAvailable { param($Cmd) $true }
    $toStop = @($all | Where-Object { @("wpr", "compose", "podman-machine", "diskspd") -contains $_.Id })
    $null = Stop-TestLeftovers -Leftovers $toStop -TestsRoot $testsRoot
    Assert-Condition ($script:calls -contains "wpr -cancel") "sessao WPR encerrada com wpr -cancel"
    Assert-Condition (@($script:calls | Where-Object { $_ -match '^podman compose -f .*compose\.yml down -v$' }).Count -eq 1) "stack derrubada com podman compose down -v"
    Assert-Condition ($script:calls -contains "podman machine stop") "podman machine parada com podman machine stop"
    Assert-Condition ($script:calls -contains "taskkill /T /F /PID 30") "diskspd encerrado com taskkill /T"
    Assert-Condition ($ids -contains "diskspd") "diskspd detectado"
    $bs = @($all | Where-Object { $_.Id -eq "dotnet" })
    Assert-Condition ($bs.Count -eq 1 -and $bs[0].Pids -contains 40 -and $bs[0].Pids -contains 42 -and $bs[0].Pids -notcontains 41) "build servers do .NET detectados; dotnet comum fica"
    Assert-Condition ($ids -contains "compose" -and $ids -contains "podman-machine") "stack do modulo 10 e podman machine detectadas"
    $keep = @(Get-TestLeftovers -TestsRoot $testsRoot -KeepPodmanMachine | ForEach-Object { $_.Id })
    Assert-Condition ($keep -notcontains "podman-machine") "podman machine mantida quando a fila ainda usa o modulo 10"

    $only1 = @(Get-TestLeftovers -TestsRoot $testsRoot -Folders @("1_cpu_memo") | ForEach-Object { $_.Id })
    Assert-Condition (($only1 -contains "wpr") -and ($only1 -contains "edge") -and ($only1 -contains "python") -and ($only1 -notcontains "diskspd") -and ($only1 -notcontains "compose")) "filtro por teste: depois do modulo 1 so as sobras dele (+ Python de teste)"

    # Clear-TestLeftovers encerra (Stop-TestLeftovers substituido) e registra
    $script:stopped = @()
    function Stop-TestLeftovers { param($Leftovers, $TestsRoot) $script:stopped += @($Leftovers | ForEach-Object { $_.Id }); return ,@($Leftovers | ForEach-Object { $_.Nome }) }
    $log = Join-Path $hub "run.log"
    $done = Clear-TestLeftovers -After $tPod -Remaining @($tGo) -TestsRoot $testsRoot -LogFile $log
    Assert-Condition (($script:stopped -contains "compose") -and ($script:stopped -contains "podman-machine") -and $done.Count -ge 2) "depois do modulo 10 (sem 10 adiante): derruba a stack e a podman machine"
    Assert-Condition ((Get-Content -LiteralPath $log -Raw) -match 'Sobra de 10_dev_containers encerrada') "encerramento entre testes vai para o log"
    $script:stopped = @()
    $null = Clear-TestLeftovers -After $tPod -Remaining @($tPod) -TestsRoot $testsRoot -LogFile $log
    Assert-Condition ($script:stopped -notcontains "podman-machine") "com outro teste do 10 adiante, a podman machine fica"
    $script:procs = @(); $script:wpr = $null; $script:podman = [PSCustomObject]@{ Available = $false; Containers = @(); MachineRunning = $false }
    $done = Clear-TestLeftovers -After $tDisk -Remaining @() -TestsRoot $testsRoot -LogFile $log
    Assert-Condition ($done.Count -eq 0) "sem sobras -> nada encerrado"
}
finally {
    $env:HUB_SPEEDTEST_URL = $envUrl
    Remove-Item -LiteralPath $hub -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "  $($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "  Todas as verificacoes passaram." -ForegroundColor Green
exit 0
