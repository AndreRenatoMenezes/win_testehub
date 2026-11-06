# =============================================================================
# Script de Preparacao: Instalar Python e Corrigir Alias da MS Store
# =============================================================================

$pythonVersion      = "3.12.2"
$pythonMinorVersion = "3.12"   # Usado para localizar o executavel apos a instalacao
$installerPath      = Join-Path $env:TEMP "python_installer_$pythonVersion.exe"
$downloadUrl        = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"

# =============================================================================
# FUNCAO: Atualiza o PATH da sessao atual sem precisar reabrir o terminal
# =============================================================================
function Update-SessionPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# =============================================================================
# FUNCAO: Retorna o objeto de comando do Python real (ignora alias da Store)
# =============================================================================
function Get-RealPythonCommand {
    # Pega todos os 'python.exe' no PATH e filtra o alias fantasma da MS Store
    $cmds = Get-Command python.exe -All -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notmatch "WindowsApps" }
    return $cmds | Select-Object -First 1
}

# =============================================================================
# FUNCAO: Verifica se a versao instalada atende ao minimo exigido
# =============================================================================
function Test-PythonVersion {
    param([string]$PythonExe)
    try {
        $ver = & $PythonExe --version 2>&1  # Ex: "Python 3.12.2"
        if ($ver -match "Python (\d+\.\d+)") {
            $installed = [version]$Matches[1]
            $required  = [version]$pythonMinorVersion
            return $installed -ge $required
        }
    } catch {}
    return $false
}

# =============================================================================
# ETAPA 1 — Detectar e neutralizar alias da Microsoft Store
# =============================================================================
Write-Host ""
Write-Host "  [1/4] Verificando alias da Microsoft Store..." -ForegroundColor Cyan

$windowsApps = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$storeAliases = @(
    (Join-Path $windowsApps "python.exe"),
    (Join-Path $windowsApps "python3.exe")
)

$aliasRemovido = $false
foreach ($alias in $storeAliases) {
    if (Test-Path $alias) {
        Remove-Item $alias -Force -ErrorAction SilentlyContinue
        Write-Host "       [-] Alias removido: $alias" -ForegroundColor DarkGray
        $aliasRemovido = $true
    }
}

if (-not $aliasRemovido) {
    Write-Host "       Nenhum alias da Store encontrado." -ForegroundColor DarkGray
} else {
    # Atualiza PATH para a remocao ter efeito imediato
    Update-SessionPath
}

# =============================================================================
# ETAPA 2 — Verificar se Python real ja esta instalado e atualizado
# =============================================================================
Write-Host ""
Write-Host "  [2/4] Verificando instalacao do Python..." -ForegroundColor Cyan

$pythonCmd    = Get-RealPythonCommand
$needsInstall = $true

if ($pythonCmd) {
    if (Test-PythonVersion -PythonExe $pythonCmd.Source) {
        $verAtual = & $pythonCmd.Source --version 2>&1
        Write-Host "       [OK] $verAtual ja instalado e compativel." -ForegroundColor Green
        Write-Host "       Caminho: $($pythonCmd.Source)" -ForegroundColor DarkGray
        $needsInstall = $false
    } else {
        $verAtual = & $pythonCmd.Source --version 2>&1
        Write-Host "       [!] $verAtual encontrado, mas versao minima exigida e $pythonMinorVersion." -ForegroundColor Yellow
        Write-Host "       Prosseguindo com a instalacao da versao $pythonVersion..." -ForegroundColor Yellow
    }
} else {
    Write-Host "       [!] Python nao encontrado no sistema." -ForegroundColor Yellow
}

# =============================================================================
# ETAPA 3 — Baixar e instalar o Python (somente se necessario)
# =============================================================================
if ($needsInstall) {
    Write-Host ""
    Write-Host "  [3/4] Baixando Python v$pythonVersion oficial..." -ForegroundColor Cyan

    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
    } catch {
        Write-Host "       [ERRO] Falha ao baixar o instalador. Verifique a conexao com a internet." -ForegroundColor Red
        exit 1
    }

    Write-Host "       Instalando Python (pode levar de 1 a 3 minutos)..." -ForegroundColor Cyan
    # PrependPath=1: coloca o Python na frente do PATH, garantindo prioridade sobre versoes antigas
    $installArgs = "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"
    $process     = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru

    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    if ($process.ExitCode -ne 0) {
        Write-Host "       [ERRO] Instalacao falhou com codigo: $($process.ExitCode)" -ForegroundColor Red
        exit 1
    }

    Write-Host "       [OK] Python $pythonVersion instalado com sucesso!" -ForegroundColor Green
    Update-SessionPath

    # Re-verifica o comando apos a instalacao
    $pythonCmd = Get-RealPythonCommand
    if (-not $pythonCmd) {
        Write-Host "       [ERRO] Python nao encontrado no PATH apos a instalacao." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "  [3/4] Instalacao ignorada (Python compativel ja presente)." -ForegroundColor DarkGray
}

# =============================================================================
# ETAPA 4 — Configuracoes pos-instalacao (sempre executadas)
# =============================================================================
Write-Host ""
Write-Host "  [4/4] Aplicando configuracoes pos-instalacao..." -ForegroundColor Cyan

$pythonExe = $pythonCmd.Source
$pipExe    = Join-Path (Split-Path $pythonExe) "Scripts\pip.exe"

# 4a. Atualizar o pip para a versao mais recente
Write-Host "       Atualizando pip..." -ForegroundColor DarkGray
try {
    & $pythonExe -m pip install --upgrade pip --quiet
    $pipVer = & $pythonExe -m pip --version 2>&1
    Write-Host "       [OK] $pipVer" -ForegroundColor Green
} catch {
    Write-Host "       [!] Nao foi possivel atualizar o pip: $_" -ForegroundColor Yellow
}

# 4b. Garantir que 'wheel' e 'setuptools' estejam atualizados (evita erros em pacotes C-extension)
Write-Host "       Atualizando wheel e setuptools..." -ForegroundColor DarkGray
try {
    & $pythonExe -m pip install --upgrade wheel setuptools --quiet
    Write-Host "       [OK] wheel e setuptools atualizados." -ForegroundColor Green
} catch {
    Write-Host "       [!] Nao foi possivel atualizar wheel/setuptools: $_" -ForegroundColor Yellow
}

# =============================================================================
# Resumo final
# =============================================================================
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "   Ambiente Python pronto!" -ForegroundColor Green
Write-Host "   Executavel: $pythonExe" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
exit 0