Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Verificacao de Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "[ERRO] Este script requer privilegios de Administrador."
    exit 1
}

Write-Host "--- Removendo bloatwares Appx ---" -ForegroundColor Cyan

# Padroes de nome (-like) dos pacotes Appx alvo
$padroes = @(
    "*LinkedIn*",
    "*Xbox*", "*GamingApp*",
    "*WhatsApp*",
    "*MicrosoftSolitaireCollection*",
    "*Microsoft.Copilot*", "*Windows.Ai.Copilot*",
    "*MicrosoftOfficeHub*",
    "*BingNews*", "*Microsoft.News*",
    "*MicrosoftTeams*", "*Teams*",
    "*Microsoft.Todos*"
)

$houveErro = $false

# HRESULTs benignos (nao sao falha real -- app ja ausente ou componente do Windows):
#   0x80073CFA = pacote e parte do Windows e nao pode ser removido
#   0x80070032 = operacao nao suportada (app de sistema protegido)
#   0x80070002 = arquivo nao encontrado (provisionado ja ausente)
#   0x80070003 = caminho nao encontrado (provisionado ja ausente)
$errosBenignos = "0x80073CFA|0x80070032|0x80070002|0x80070003"

# Cache da lista de pacotes provisionados (consulta cara; constante por execucao)
$provisionados = Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue

foreach ($padrao in $padroes) {
    Write-Host "`n[Appx] $padrao" -ForegroundColor Cyan

    # 1. Pacotes instalados (todos os usuarios)
    $pkgs = Get-AppxPackage -AllUsers -Name $padrao -ErrorAction SilentlyContinue
    if (-not $pkgs) {
        Write-Host "  -> Nenhum pacote instalado encontrado." -ForegroundColor Yellow
    } else {
        foreach ($pkg in $pkgs) {
            try {
                Remove-AppxPackage -Package $pkg.PackageFullName -AllUsers -ErrorAction Stop
                Write-Host "  OK: removido $($pkg.Name)" -ForegroundColor Green
            } catch {
                if ($_.Exception.Message -match $errosBenignos) {
                    Write-Host "  -> $($pkg.Name) ja ausente ou componente do Windows (ignorado)." -ForegroundColor Yellow
                } else {
                    Write-Warning "  Falha ao remover $($pkg.Name): $($_.Exception.Message)"
                    $houveErro = $true
                }
            }
        }
    }

    # 2. Pacotes provisionados na imagem
    $prov = $provisionados | Where-Object { ($_.DisplayName -like $padrao) -or ($_.PackageName -like $padrao) }
    if (-not $prov) {
        Write-Host "  -> Nenhum pacote provisionado encontrado." -ForegroundColor Yellow
    } else {
        foreach ($p in $prov) {
            try {
                Remove-AppxProvisionedPackage -Online -PackageName $p.PackageName -ErrorAction Stop | Out-Null
                Write-Host "  OK: provisionado removido $($p.DisplayName)" -ForegroundColor Green
            } catch {
                if ($_.Exception.Message -match $errosBenignos) {
                    Write-Host "  -> Provisionado $($p.DisplayName) ja ausente (ignorado)." -ForegroundColor Yellow
                } else {
                    Write-Warning "  Falha ao remover provisionado $($p.DisplayName): $($_.Exception.Message)"
                    $houveErro = $true
                }
            }
        }
    }
}

# 3. Teams corporativo classico (Win32/MSI - "Teams Machine-Wide Installer")
Write-Host "`n[Win32] Teams Machine-Wide Installer" -ForegroundColor Cyan
$teamsRemovido = $false
if (Get-Command winget -ErrorAction SilentlyContinue) {
    try {
        winget uninstall --id "Microsoft.Teams" --silent --accept-source-agreements 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK: Teams desinstalado via winget." -ForegroundColor Green
            $teamsRemovido = $true
        }
    } catch {
        # winget e apenas um atalho; o fallback MSI segue mesmo se ele falhar
        Write-Warning "  Falha ao invocar winget: $($_.Exception.Message)"
    }
}
if (-not $teamsRemovido) {
    # Fallback: localizar produto MSI via registro de uninstall
    $uninstallKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $teams = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
        Where-Object { ($_.PSObject.Properties.Name -contains "DisplayName") -and ($_.DisplayName -like "*Teams Machine-Wide Installer*") }
    if (-not $teams) {
        Write-Host "  -> Teams Machine-Wide Installer nao encontrado." -ForegroundColor Yellow
    } else {
        foreach ($t in $teams) {
            try {
                if (($t.PSObject.Properties.Name -contains "UninstallString") -and ($t.UninstallString -match "\{[0-9A-Fa-f\-]+\}")) {
                    $guid = $matches[0]
                    $proc = Start-Process "msiexec.exe" -ArgumentList "/x $guid /qn /norestart" -Wait -NoNewWindow -PassThru
                    if ($proc.ExitCode -eq 0) {
                        Write-Host "  OK: Teams MSI removido ($guid)." -ForegroundColor Green
                    } else {
                        Write-Warning "  Falha ao remover Teams MSI (codigo $($proc.ExitCode))."
                        $houveErro = $true
                    }
                } else {
                    Write-Host "  -> Entrada Teams sem UninstallString MSI valida." -ForegroundColor Yellow
                }
            } catch {
                Write-Warning "  Falha ao remover Teams MSI: $($_.Exception.Message)"
                $houveErro = $true
            }
        }
    }
}

if ($houveErro) {
    Write-Error "`n[FALHA] Um ou mais pacotes nao puderam ser removidos."
    exit 1
}

Write-Host "`n--- Remocao de bloatwares concluida ---" -ForegroundColor Green
exit 0
