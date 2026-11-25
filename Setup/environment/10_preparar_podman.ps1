# =============================================================================
# Setup: Podman e WSL2 para o modulo 10 (containers)
#
# 1. Confere a virtualizacao (BIOS/hipervisor).
# 2. Ativa o WSL2 se faltar. Se o Windows precisar reiniciar, sai com 3010
#    (reinicio necessario): o hub mostra REINICIAR, oferece reiniciar agora e
#    retoma a fila no proximo logon.
# 3. Instala o Podman CLI via winget (machine).
# 4. Cria a podman machine rootful (se nao existir) e liga.
# 5. Confere com "podman info" e "podman compose version".
# Idempotente: com tudo pronto, sai PASS sem alterar nada.
# Roda elevado (o hub roda como administrador).
# =============================================================================

$ErrorActionPreference = "Continue"

function Update-SessionPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    if ((Test-Path $links) -and (($env:PATH -split ';') -notcontains $links)) { $env:PATH += ";$links" }
    $podmanDir = Join-Path $env:ProgramFiles "RedHat\Podman"
    if ((Test-Path $podmanDir) -and (($env:PATH -split ';') -notcontains $podmanDir)) { $env:PATH += ";$podmanDir" }
}

function Exit-Falha {
    param([string]$Mensagem)
    Write-Host "`n[FALHA] $Mensagem" -ForegroundColor Red
    exit 1
}

# Codigo padrao do Windows para "reinicio necessario"; o hub trata como REINICIAR.
function Exit-Reinicio {
    param([string]$Mensagem)
    Write-Host "`n[REINICIAR] $Mensagem" -ForegroundColor Yellow
    exit 3010
}

Write-Host "--- Podman + WSL2 (modulo 10) ---" -ForegroundColor Green
Update-SessionPath

# 1. Virtualizacao ------------------------------------------------------------
Write-Host "`n[1/5] Virtualizacao... " -NoNewline
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
if ($cs.HypervisorPresent -or $cpu.VirtualizationFirmwareEnabled) {
    Write-Host "OK" -ForegroundColor Green
} else {
    Write-Host "DESLIGADA" -ForegroundColor Red
    Exit-Falha "Habilite a virtualizacao (Intel VT-x / AMD-V) na BIOS/UEFI e rode este script de novo."
}

# 2. WSL2 ---------------------------------------------------------------------
Write-Host "[2/5] WSL2... " -NoNewline
# O "podman machine init" (provedor WSL) exige os DOIS recursos opcionais: o
# VirtualMachinePlatform e o legado Microsoft-Windows-Subsystem-Linux. Se faltar
# algum, o proprio Podman o ativa e REINICIA o Windows sem aviso. Por isso o
# script ativa os dois aqui, sem reiniciar, e sai pedindo o reinicio.
$recursos = @("VirtualMachinePlatform", "Microsoft-Windows-Subsystem-Linux")
$pendentes = @()
foreach ($r in $recursos) {
    $estadoRecurso = "$((Get-WindowsOptionalFeature -Online -FeatureName $r -ErrorAction SilentlyContinue).State)"
    if ($estadoRecurso -eq "EnablePending") {
        $pendentes += $r
    } elseif ($estadoRecurso -ne "Enabled") {
        Write-Host "ativando $r ($estadoRecurso)... " -ForegroundColor Magenta -NoNewline
        $res = Enable-WindowsOptionalFeature -Online -FeatureName $r -All -NoRestart -ErrorAction SilentlyContinue
        if (-not $res) { Exit-Falha "nao foi possivel ativar o recurso $r." }
        if ($res.RestartNeeded) { $pendentes += $r }
    }
}
if ($pendentes.Count -gt 0) {
    Exit-Reinicio "Recursos ativados aguardando reinicio ($($pendentes -join ', ')). Reinicie o Windows e rode este script de novo."
}
wsl.exe --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "instalando o pacote do WSL... " -ForegroundColor Magenta -NoNewline
    wsl.exe --install --no-distribution
    if ($LASTEXITCODE -ne 0) { Exit-Falha "wsl --install falhou (codigo $LASTEXITCODE). Confira a rede e rode de novo." }
    wsl.exe --version *> $null
    if ($LASTEXITCODE -ne 0) { Exit-Reinicio "WSL instalado mas sem responder. Reinicie o Windows e rode este script de novo." }
}
Write-Host "OK" -ForegroundColor Green

# 3. Podman CLI ---------------------------------------------------------------
Write-Host "[3/5] Podman CLI... " -NoNewline
if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
    Write-Host "instalando Podman.CLI..." -ForegroundColor Magenta
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Exit-Falha "winget nao encontrado." }
    winget install --id Podman.CLI --exact --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
    $codigoWinget = $LASTEXITCODE
    if ($codigoWinget -ne 0) {
        # O MSI do Podman nao declara escopo no manifesto: sem --scope o winget o encontra
        Write-Host "  escopo machine indisponivel (codigo $codigoWinget); usando o escopo padrao do pacote." -ForegroundColor DarkYellow
        winget install --id Podman.CLI --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
        $codigoWinget = $LASTEXITCODE
    }
    Update-SessionPath
    if (-not (Get-Command podman -ErrorAction SilentlyContinue)) { Exit-Falha "podman nao encontrado apos a instalacao (codigo winget: $codigoWinget)." }
}
Write-Host ((podman --version) -join ' ') -ForegroundColor Green

# 4. podman machine -----------------------------------------------------------
Write-Host "[4/5] podman machine... " -NoNewline
$maquinas = @(podman machine list --format "{{.Name}}" 2>$null | Where-Object { $_ })
if ($maquinas.Count -eq 0) {
    Write-Host "criando (rootful)..." -ForegroundColor Magenta
    # Processo oculto separado (como o start abaixo): o init provisiona a distro pelo wsl.exe,
    # que pode deixar wslhost/wslrelay vivos herdando o pipe do hub.
    $procInit = Start-Process -FilePath (Get-Command podman).Source -ArgumentList "machine", "init", "--rootful" -WindowStyle Hidden -PassThru
    $procInit.WaitForExit()
    if ($procInit.ExitCode -ne 0) { Exit-Falha "podman machine init falhou (codigo $($procInit.ExitCode)). Rode 'podman machine init --rootful' a mao para ver o erro." }
}
$rootful = (podman machine inspect --format "{{.Rootful}}" 2>$null | Select-Object -First 1)
if ("$rootful" -ne "true") {
    Write-Host "passando a machine existente para rootful..." -ForegroundColor Magenta
    podman machine stop *> $null
    podman machine set --rootful
    if ($LASTEXITCODE -ne 0) { Exit-Falha "podman machine set --rootful falhou (codigo $LASTEXITCODE)." }
}
$estado = (podman machine inspect --format "{{.State}}" 2>$null | Select-Object -First 1)
if ($estado -ne "running") {
    Write-Host "ligando..." -ForegroundColor Magenta
    # Processo separado e oculto: o "machine start" deixa wslrelay/wslhost vivos, e se eles
    # herdassem a saida capturada pelo hub (pipe), o hub esperaria para sempre. WaitForExit
    # espera so o podman, nao os processos que ele deixa rodando.
    $podmanExe = (Get-Command podman).Source
    $proc = Start-Process -FilePath $podmanExe -ArgumentList "machine", "start" -WindowStyle Hidden -PassThru
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) { Exit-Falha "podman machine start falhou (codigo $($proc.ExitCode)). Rode 'podman machine start' a mao para ver o erro." }
}
Write-Host "OK (rodando)" -ForegroundColor Green

# 5. Verificacao --------------------------------------------------------------
Write-Host "[5/5] Verificacao..."
$info = podman info --format "{{.Host.MemTotal}} {{.Host.CPUs}}" 2>$null
if ($LASTEXITCODE -ne 0) { Exit-Falha "podman info falhou: a VM nao responde." }
$partes = "$info" -split ' '
Write-Host ("  VM: {0:N1} GiB, {1} CPUs" -f ([double]$partes[0] / 1GB), $partes[1]) -ForegroundColor Green
$env:PODMAN_COMPOSE_WARNING_LOGS = "false"   # sem o aviso ">>>> Executing external compose provider"
podman compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Exit-Falha "'podman compose' sem provider: rode o setup 7_install_devtools_dev.ps1 (docker-compose)."
}
Write-Host "  podman compose: OK" -ForegroundColor Green

Write-Host "`nPodman pronto para o modulo 10." -ForegroundColor Green
exit 0
