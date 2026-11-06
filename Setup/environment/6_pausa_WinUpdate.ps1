
param (
    [ValidateRange(1, 35)]
    [int]$DiasParaPausar = 35
)

# 1. Validação de Privilégios (Crucial para automação)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Error "[ERRO] Este script requer privilégios de Administrador."
    exit 1 # Retorna código de erro para o Hub
}

# 2. Execução das Mudanças
try {
    # Formata as datas em UTC para o padrão ISO 8601 (exigido pelo registro do WU)
    $pausaInicio = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $pausaFim = (Get-Date).AddDays($DiasParaPausar).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    $registryPath = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"

    # Cria a chave pai caso ela não exista (cenários de máquinas recém-formatadas)
    if (-not (Test-Path $registryPath)) {
        New-Item -Path $registryPath -Force | Out-Null
    }

    # Aplica as configurações silenciosamente
    Set-ItemProperty -Path $registryPath -Name "PauseUpdatesExpiryTime" -Value $pausaFim -ErrorAction Stop
    Set-ItemProperty -Path $registryPath -Name "PauseFeatureUpdatesStartTime" -Value $pausaInicio -ErrorAction Stop
    Set-ItemProperty -Path $registryPath -Name "PauseFeatureUpdatesExpiryTime" -Value $pausaFim -ErrorAction Stop
    Set-ItemProperty -Path $registryPath -Name "PauseQualityUpdatesStartTime" -Value $pausaInicio -ErrorAction Stop
    Set-ItemProperty -Path $registryPath -Name "PauseQualityUpdatesExpiryTime" -Value $pausaFim -ErrorAction Stop

    # Opcional: Reinicia o serviço de update para garantir que o sistema leia o registro imediatamente
    Restart-Service -Name "wuauserv" -Force -ErrorAction SilentlyContinue

    Write-Output "[SUCESSO] Windows Update pausado por $DiasParaPausar dias (Expira em: $pausaFim UTC)."
    exit 0 # Retorna código de sucesso para o Hub

} catch {
    Write-Error "[FALHA] Erro crítico ao tentar pausar o Windows Update. Detalhes: $($_.Exception.Message)"
    exit 1 # Retorna código de erro para o Hub
}