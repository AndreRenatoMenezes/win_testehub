# =============================================================================
#  Fix-BootDiagnostics.ps1
#  Configura o Windows para sempre registrar eventos 100 (Boot) e 200 (Shutdown)
#  no Microsoft-Windows-Diagnostics-Performance/Operational
# =============================================================================

Write-Host "Iniciando configuracao de Diagnosticos de Boot/Shutdown..." -ForegroundColor Cyan

# 1. Verifica se o script esta rodando como Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERRO] Este script precisa ser executado como Administrador!" -ForegroundColor Red
    Write-Host "Por favor, clique com o botao direito no PowerShell e selecione 'Executar como Administrador'." -ForegroundColor Yellow
    exit 1
}

$falhas = 0

# 2. Desativar Inicializacao Rapida (Fast Startup)
# Isso obriga o Windows a fazer um boot frio em vez de acordar de uma hibernacao parcial do kernel
Write-Host "Desativando Inicializacao Rapida (Fast Startup)..."
try {
    $powerPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power"
    Set-ItemProperty -Path $powerPath -Name HiberbootEnabled -Value 0 -ErrorAction Stop
    Write-Host "  -> [OK] Fast Startup desativado." -ForegroundColor Green
} catch {
    Write-Host "  -> [FALHA] Nao foi possivel alterar a chave de energia." -ForegroundColor Red
    $falhas++
}

# 3. Configurar e Iniciar Servicos Dependentes
# DPS (Servico de Diretiva de Diagnostico) e SysMain (Superfetch/Prefetch)
$servicos = @("DPS", "SysMain")

foreach ($svc in $servicos) {
    Write-Host "Configurando servico: $svc..."
    try {
        Set-Service -Name $svc -StartupType Automatic -ErrorAction Stop
        Start-Service -Name $svc -ErrorAction SilentlyContinue
        
        $status = (Get-Service -Name $svc).Status
        if ($status -eq "Running") {
            Write-Host "  -> [OK] $svc configurado como Automatico e em execucao." -ForegroundColor Green
        } else {
            Write-Host "  -> [AVISO] $svc configurado como Automatico, mas não esta rodando." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  -> [FALHA] Nao foi possivel configurar o servico $svc." -ForegroundColor Red
        $falhas++
    }
}

# 4. Forcar Diretiva de Diagnostico de Desempenho de Inicializacao (WDI)
# Garante que a infraestrutura de diagnostico registre ativamente o cenario de boot
Write-Host "Habilitando Politica WDI de Diagnostico de Boot..."
try {
    $wdiPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WDI\{71c2738d-f44a-4a2b-b873-653a73cc9a01}"
    if (-not (Test-Path $wdiPath)) { 
        New-Item -Path $wdiPath -Force | Out-Null 
    }
    Set-ItemProperty -Path $wdiPath -Name "ScenarioExecutionEnabled" -Value 1 -Type DWord -ErrorAction Stop
    Write-Host "  -> [OK] Politica WDI habilitada com sucesso." -ForegroundColor Green
} catch {
    Write-Host "  -> [FALHA] Nao foi possivel configurar a politica WDI." -ForegroundColor Red
    $falhas++
}

Write-Host ""
Write-Host "Configuracao concluida! E recomendado reiniciar o computador para que todas as alteracoes entrem em vigor." -ForegroundColor Cyan
Write-Host "Apos o reinicio, seu script original passara a capturar 100% dos eventos de Boot e Shutdown." -ForegroundColor Cyan

if ($falhas -gt 0) {
    Write-Host "[AVISO] $falhas operacao(oes) falharam." -ForegroundColor Red
    exit 1
}
exit 0