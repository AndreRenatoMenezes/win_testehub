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
foreach ($nome in "New-PreflightFinding", "Get-DevModuleTools", "Test-SpeedtestConfigured", "Test-LibreOfficeAvailable", "Get-PreflightFindings",
                "Test-WprRecording", "Get-TestLeftovers", "Remove-BlockedTests", "Get-BlockReason", "Clear-TestLeftovers", "Stop-TestLeftovers") {
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
$realTestLibreOffice = ${function:Test-LibreOfficeAvailable}
function Test-LibreOfficeAvailable { Test-CommandAvailable -Cmd "soffice" }
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
foreach ($d in "0_consumo_basal", "1_cpu_memo", "3_rede", "5_bateria", "8_dev_go", "10_dev_containers", "2_disco") {
    New-Item -ItemType Directory -Path (Join-Path $testsRoot $d) -Force | Out-Null
}
Set-Content -LiteralPath (Join-Path $testsRoot "8_dev_go\cargas.json") -Encoding UTF8 -Value '{"ferramentas":[{"cmd":"go","versao":["go","version"],"minima":"1.21"}],"repos":[{"nome":"hugo"}]}'
Set-Content -LiteralPath (Join-Path $testsRoot "10_dev_containers\cargas.json") -Encoding UTF8 -Value '{"ferramentas":[{"cmd":"podman","versao":["podman","--version"],"minima":"5.0"}],"repos":[]}'

function New-T { param($Folder, $Name, $Type = "py") [PSCustomObject]@{ Name = $Name; Type = $Type; ParentFolder = $Folder } }
$tBasal = New-T "0_consumo_basal" "0_teste_consumo_basal"
$tCpu  = New-T "1_cpu_memo" "1_automacao_performance"
$tCpuDlp = New-T "1_cpu_memo" "1-1_automacao_performance_dlp"
$tRede = New-T "3_rede" "3_teste_rede"
$tBat  = New-T "5_bateria" "5_teste_bateria"
$tGo   = New-T "8_dev_go" "8_dev_go"
$tPod  = New-T "10_dev_containers" "10_dev_containers"
$tDisk = New-T "2_disco" "2_teste_disco"
$settings = [PSCustomObject]@{ MinFreeGB = 20; CpuAlertPct = 10; InternetHost = "example.invalid" }
$okTools = @{ wpr = "wpr"; wpaexporter = "wpa"; soffice = "LibreOffice 24.8"; go = "go version go1.22.3 windows/amd64"; git = "git version 2.45.1"; podman = "podman version 5.2.0" }

function Get-F { param($Tests) Get-PreflightFindings -Tests $Tests -TestsRoot $testsRoot -HubRoot $hub -Settings $settings -SkipLeftovers }
function Find-Item { param($F, $Pattern) return ,@($F | Where-Object { $_.Item -match $Pattern }) }

$envUrl = $env:HUB_SPEEDTEST_URL
try {
    $env:HUB_SPEEDTEST_URL = ""
    Write-Host "`n  Checagem por teste selecionado" -ForegroundColor Cyan

    $script:tools = $okTools.Clone()
    $f0 = Get-F @($tBasal)
    $p0 = Find-Item $f0 'wpaProfile'
    Assert-Condition ($p0.Count -eq 1 -and $p0[0].Nivel -eq "Impede" -and $p0[0].Testes -contains "0_teste_consumo_basal.py") "modulo 0 sem .wpaProfile em 0_consumo_basal nem 1_cpu_memo -> Impede"

    $f = Get-F @($tCpu)
    $p = Find-Item $f 'wpaProfile'
    Assert-Condition ($p.Count -eq 1 -and $p[0].Nivel -eq "Impede") "modulo 1 sem .wpaProfile -> Impede"
    Assert-Condition ($p.Count -eq 1 -and $p[0].Acao -match '1_cpu_memo' -and $p[0].Testes -contains "1_automacao_performance.py") "acao indica a pasta e o teste afetado"

    Set-Content -LiteralPath (Join-Path $testsRoot "1_cpu_memo\Agentes_SI_Profile.wpaProfile.xml") -Value "<x/>"
    $f = Get-F @($tCpu)
    Assert-Condition ((Find-Item $f 'wpaProfile').Count -eq 0) "profile .wpaProfile.xml presente -> sem achado"
    Assert-Condition ((Find-Item (Get-F @($tBasal)) 'wpaProfile').Count -eq 0) "modulo 0 reutiliza .wpaProfile de 1_cpu_memo -> sem achado"

    $script:tools.Remove("wpaexporter")
    $f = Get-F @($tCpu)
    Assert-Condition ((Find-Item $f 'wpaexporter').Count -eq 1) "wpaexporter ausente -> Impede"
    Assert-Condition ((Find-Item (Get-F @($tBasal)) 'wpaexporter').Count -eq 1) "modulo 0 sem wpaexporter -> Impede"
    $script:tools.Remove("wpr")
    Assert-Condition ((Find-Item (Get-F @($tBasal)) 'wpr\.exe').Count -eq 1) "modulo 0 sem wpr -> Impede"
    $script:tools = $okTools.Clone()

    $script:tools.Remove("soffice")
    $fLo = Find-Item (Get-F @($tCpu, $tCpuDlp)) 'LibreOffice'
    Assert-Condition ($fLo.Count -eq 1 -and $fLo[0].Nivel -eq "Impede" -and $fLo[0].Acao -match 'Setup 3_softwares_msStore') "1_automacao_performance sem LibreOffice -> Impede mandando rodar o Setup 3"
    Assert-Condition ($fLo.Count -eq 1 -and ($fLo[0].Testes -contains "1_automacao_performance.py") -and ($fLo[0].Testes -notcontains "1-1_automacao_performance_dlp.py")) "LibreOffice ausente bloqueia apenas 1_automacao_performance.py, nao 1-1_automacao_performance_dlp.py"
    Assert-Condition ((Find-Item (Get-F @($tCpuDlp)) 'LibreOffice').Count -eq 0) "1-1_automacao_performance_dlp isolado sem LibreOffice -> sem achado de LibreOffice"
    $fakeSoffice = Join-Path $hub "fake_soffice.exe"
    Set-Content -LiteralPath $fakeSoffice -Value "bin"
    $oldLoPath = $env:HUB_LIBREOFFICE_PATH
    try {
        $env:HUB_LIBREOFFICE_PATH = $fakeSoffice
        Assert-Condition ([bool](& $realTestLibreOffice)) "sonda real Test-LibreOfficeAvailable reconhece HUB_LIBREOFFICE_PATH existente"
    } finally {
        $env:HUB_LIBREOFFICE_PATH = $oldLoPath
    }
    $script:tools = $okTools.Clone()

    $f = Get-F @($tDisk)
    Assert-Condition ($f.Count -eq 0) "teste nao relacionado (disco) nao herda achados do modulo 1"
    $b5 = Find-Item (Get-F @($tBat)) 'Agentes_SI_Bateria_Profile'
    Assert-Condition ($b5.Count -eq 1 -and $b5[0].Nivel -eq "Impede" -and $b5[0].Testes -contains "5_teste_bateria.py") "modulo 5 sem o profile de bateria -> Impede"
    Set-Content -LiteralPath (Join-Path $testsRoot "5_bateria\Agentes_SI_Bateria_Profile.wpaProfile") -Value "<x/>"
    Assert-Condition ((Get-F @($tBat)).Count -eq 0) "profile de bateria presente -> sem achado"

    # Teste 3 unificado: uma fonte fora (URL interna ou internet) = Atencao; as duas = Impede
    $f = Find-Item (Get-F @($tRede)) 'Rede:'
    Assert-Condition ($f.Count -eq 1 -and $f[0].Nivel -eq "Atencao" -and $f[0].Item -match 'so a internet') "teste 3 sem URL do speedtest (com internet) -> Atencao, so a internet"
    $script:internet = $false
    $f = Find-Item (Get-F @($tRede)) 'Rede:'
    Assert-Condition ($f.Count -eq 1 -and $f[0].Nivel -eq "Impede" -and $f[0].Item -match 'nenhuma das duas') "teste 3 sem URL e sem internet -> Impede"
    Set-Content -LiteralPath (Join-Path $hub "config.local.json") -Value '{"SpeedtestUrl":"https://speedtest.example.invalid/"}'
    $f = Find-Item (Get-F @($tRede)) 'Rede:'
    Assert-Condition ($f.Count -eq 1 -and $f[0].Nivel -eq "Atencao" -and $f[0].Item -match 'so o speedtest interno') "teste 3 com URL e sem internet -> Atencao, so o interno"
    $script:internet = $true
    Assert-Condition ((Find-Item (Get-F @($tRede)) 'Rede:').Count -eq 0) "SpeedtestUrl no config.local.json e internet -> sem achado"
    Remove-Item -LiteralPath (Join-Path $hub "config.local.json")
    $env:HUB_SPEEDTEST_URL = "https://speedtest.example.invalid/"
    Assert-Condition ((Find-Item (Get-F @($tRede)) 'Rede:').Count -eq 0) "HUB_SPEEDTEST_URL -> sem achado"
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
    $fq = Get-F $queue      # Get-F devolve ,@(): sem @() em volta, senao aninha
    $goName = "$($tGo.Name).$($tGo.Type)"
    $why = Get-BlockReason -TestName $goName -Findings $fq
    $esperado = @($fq | Where-Object { $_.Nivel -eq "Impede" -and @($_.Testes) -contains $goName } | ForEach-Object { $_.Item })
    Assert-Condition ($why -and $esperado.Count -ge 1 -and $why -like "*$($esperado[0])*" -and $why -notmatch 'psobject|\{get;set;\}') "motivo do [R] = item do achado Impede ($why)"
    Assert-Condition ((Get-BlockReason -TestName "$($tDisk.Name).$($tDisk.Type)" -Findings $fq) -eq "") "teste sem Impede -> motivo vazio"
    $dup = @((New-PreflightFinding -Nivel "Impede" -Testes @("a.py") -Item "x"), (New-PreflightFinding -Nivel "Impede" -Testes @("a.py") -Item "x"),
             (New-PreflightFinding -Nivel "Impede" -Testes @("a.py") -Item "y"), (New-PreflightFinding -Nivel "Atencao" -Testes @("a.py") -Item "z"))
    Assert-Condition ((Get-BlockReason -TestName "a.py" -Findings $dup) -eq "x; y") "varios Impede: itens unicos separados por '; ', sem Atencao"
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
        [PSCustomObject]@{ Name = "VBCSCompiler.exe"; ProcessId = 42; ParentProcessId = 1; CommandLine = 'VBCSCompiler.exe' },
        [PSCustomObject]@{ Name = "soffice.bin"; ProcessId = 50; ParentProcessId = 1; CommandLine = '"soffice.bin" --writer C:\Users\user\doc.odt' },
        [PSCustomObject]@{ Name = "soffice.exe"; ProcessId = 51; ParentProcessId = 1; CommandLine = '"soffice.exe" -env:UserInstallation=file:///C:/Temp/wintesthub_lo_profile_writer --writer' },
        [PSCustomObject]@{ Name = "soffice.bin"; ProcessId = 52; ParentProcessId = 51; CommandLine = '"soffice.bin" -env:UserInstallation=file:///C:/Temp/wintesthub_lo_profile_writer --writer' },
        [PSCustomObject]@{ Name = "notepad.exe"; ProcessId = 53; ParentProcessId = 51; CommandLine = '"notepad.exe" C:\Users\user\notas.txt' },
        [PSCustomObject]@{ Name = "soffice.bin"; ProcessId = 54; ParentProcessId = 51; CommandLine = '"soffice.bin" -env:UserInstallation=file:///C:/Temp/wintesthub_lo_profile_calc --calc' },
        [PSCustomObject]@{ Name = "soffice.bin"; ProcessId = 55; ParentProcessId = 51; CommandLine = '"soffice.bin" --writer user.odt' },
        [PSCustomObject]@{ Name = "wpaexporter.exe"; ProcessId = 60; ParentProcessId = 1; CommandLine = 'wpaexporter.exe -i trace.etl' }
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
    $loLeft = @($all | Where-Object { $_.Id -eq "libreoffice" })
    Assert-Condition ($loLeft.Count -eq 1 -and ($loLeft[0].Pids -contains 51) -and ($loLeft[0].Pids -contains 52) -and ($loLeft[0].Pids -contains 54) -and ($loLeft[0].Pids -notcontains 50) -and ($loLeft[0].Pids -notcontains 53) -and ($loLeft[0].Pids -notcontains 55)) "LibreOffice da automacao exige wintesthub_lo_profile no CommandLine, ignorando LibreOffice do usuario (50), descendente nao relacionado (53) e filho soffice sem marcador (--writer user.odt, 55)"
    $allIgn = Get-TestLeftovers -TestsRoot $testsRoot -Folders @("1_cpu_memo") -IgnorePids @(54)
    $loIgn = @($allIgn | Where-Object { $_.Id -eq "libreoffice" })
    Assert-Condition ($loIgn.Count -eq 1 -and ($loIgn[0].Pids -contains 51) -and ($loIgn[0].Pids -contains 52) -and ($loIgn[0].Pids -notcontains 54) -and ($loIgn[0].Pids -notcontains 53) -and ($loIgn[0].Pids -notcontains 55)) "LibreOffice respeita IgnorePids (54 protegido) e preserva descendente nao relacionado (53) e filho soffice sem marcador (55)"

    # Stop-TestLeftovers real, com stubs dos comandos externos
    $script:calls = @()
    function wpr { $script:calls += "wpr $($args -join ' ')" }
    function podman { $script:calls += "podman $($args -join ' ')" }
    function dotnet { $script:calls += "dotnet $($args -join ' ')" }
    function taskkill.exe { $global:LASTEXITCODE = 0; $script:calls += "taskkill $($args -join ' ')" }
    function Test-CommandAvailable { param($Cmd) $true }
    $toStop = @($all | Where-Object { @("wpr", "compose", "podman-machine", "diskspd") -contains $_.Id }) + $loIgn
    $null = Stop-TestLeftovers -Leftovers $toStop -TestsRoot $testsRoot
    Assert-Condition ($script:calls -contains "wpr -cancel") "sessao WPR encerrada com wpr -cancel"
    Assert-Condition (@($script:calls | Where-Object { $_ -match '^podman compose -f .*compose\.yml down -v$' }).Count -eq 1) "stack derrubada com podman compose down -v"
    Assert-Condition ($script:calls -contains "podman machine stop") "podman machine parada com podman machine stop"
    Assert-Condition ($script:calls -contains "taskkill /T /F /PID 30") "diskspd encerrado com taskkill /T"
    Assert-Condition (($script:calls -contains "taskkill /F /PID 51") -and ($script:calls -contains "taskkill /F /PID 52") -and ($script:calls -notcontains "taskkill /T /F /PID 51") -and ($script:calls -notcontains "taskkill /F /PID 53") -and ($script:calls -notcontains "taskkill /F /PID 54") -and ($script:calls -notcontains "taskkill /F /PID 55")) "LibreOffice encerrado sem /T apenas nos PIDs com wintesthub_lo_profile (51, 52), preservando descendente nao relacionado (53), IgnorePids (54) e filho soffice sem marcador (55)"

    # Tratamento de falha do taskkill em Stop-TestLeftovers (continua nos demais PIDs e reporta falha)
    $script:callsFail = @()
    function taskkill.exe {
        $cmdStr = "taskkill $($args -join ' ')"
        $script:callsFail += $cmdStr
        if ($cmdStr -match 'PID 51$') {
            $global:LASTEXITCODE = 128
            Write-Output "ERRO: processo 51 nao encontrado"
            return
        }
        $global:LASTEXITCODE = 0
    }
    $resFail = @(Stop-TestLeftovers -Leftovers $loIgn -TestsRoot $testsRoot)
    Assert-Condition (($script:callsFail -contains "taskkill /F /PID 51") -and ($script:callsFail -contains "taskkill /F /PID 52")) "falha do taskkill no primeiro PID (51) ainda tenta encerrar os demais PIDs do teste (52)"
    Assert-Condition ($resFail.Count -eq 1 -and $resFail[0] -match 'LibreOffice da automacao: falha ao encerrar.*PID 51.*codigo 128') "Stop-TestLeftovers captura e relata falha do taskkill ($($resFail[0]))"
    Assert-Condition ($ids -contains "diskspd") "diskspd detectado"
    $bs = @($all | Where-Object { $_.Id -eq "dotnet" })
    Assert-Condition ($bs.Count -eq 1 -and $bs[0].Pids -contains 40 -and $bs[0].Pids -contains 42 -and $bs[0].Pids -notcontains 41) "build servers do .NET detectados; dotnet comum fica"
    Assert-Condition ($ids -contains "compose" -and $ids -contains "podman-machine") "stack do modulo 10 e podman machine detectadas"
    $keep = @(Get-TestLeftovers -TestsRoot $testsRoot -KeepPodmanMachine | ForEach-Object { $_.Id })
    Assert-Condition ($keep -notcontains "podman-machine") "podman machine mantida quando a fila ainda usa o modulo 10"

    $only1 = @(Get-TestLeftovers -TestsRoot $testsRoot -Folders @("1_cpu_memo") | ForEach-Object { $_.Id })
    Assert-Condition (($only1 -contains "wpr") -and ($only1 -contains "libreoffice") -and ($only1 -contains "python") -and ($only1 -notcontains "edge") -and ($only1 -notcontains "diskspd") -and ($only1 -notcontains "compose")) "filtro por teste: depois do modulo 1 so as sobras dele (wpr, libreoffice, python; sem edge)"
    $only0 = @(Get-TestLeftovers -TestsRoot $testsRoot -Folders @("0_consumo_basal") | ForEach-Object { $_.Id })
    Assert-Condition (($only0 -contains "wpr") -and ($only0 -contains "wpaexporter") -and ($only0 -contains "python") -and ($only0 -notcontains "libreoffice") -and ($only0 -notcontains "edge") -and ($only0 -notcontains "diskspd")) "filtro por teste: depois do modulo 0 so wpr, wpaexporter e python (sem libreoffice/edge/diskspd)"

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
