Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Verificacao de Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "[ERRO] Este script requer privilegios de Administrador."
    exit 1
}

Write-Host "--- Removendo OneDrive ---" -ForegroundColor Cyan

try {
    # 1. Encerrar processo
    Write-Host "[1/5] Encerrando processo OneDrive..." -ForegroundColor Cyan
    Get-Process -Name OneDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "  OK." -ForegroundColor Green

    # 2. Desinstalador oficial (32 e 64 bits)
    Write-Host "[2/5] Executando desinstalador oficial..." -ForegroundColor Cyan
    $setupPaths = @(
        "$env:SystemRoot\SysWOW64\OneDriveSetup.exe",
        "$env:SystemRoot\System32\OneDriveSetup.exe"
    )
    $rodou = $false
    foreach ($sp in $setupPaths) {
        if (Test-Path $sp) {
            $proc = Start-Process $sp -ArgumentList "/uninstall" -Wait -NoNewWindow -PassThru
            if ($proc.ExitCode -eq 0) {
                Write-Host "  OK: $sp /uninstall" -ForegroundColor Green
            } else {
                Write-Warning "  Desinstalador retornou codigo $($proc.ExitCode) (prosseguindo; etapas seguintes neutralizam o OneDrive)."
            }
            $rodou = $true
        }
    }
    if (-not $rodou) { Write-Host "  -> OneDriveSetup.exe nao encontrado (ja removido)." -ForegroundColor Yellow }

    # 3. Remover entrada do Explorer (CLSID OneDrive)
    Write-Host "[3/5] Removendo entrada do Explorer..." -ForegroundColor Cyan
    $clsidPaths = @(
        "Registry::HKEY_CLASSES_ROOT\CLSID\{018D5C66-4533-4307-9B53-224DE2ED1FE6}",
        "Registry::HKEY_CLASSES_ROOT\Wow6432Node\CLSID\{018D5C66-4533-4307-9B53-224DE2ED1FE6}"
    )
    foreach ($cp in $clsidPaths) {
        if (Test-Path $cp) {
            Set-ItemProperty -Path $cp -Name "System.IsPinnedToNameSpaceTree" -Value 0 -Type DWord -ErrorAction SilentlyContinue
        }
    }
    Write-Host "  OK." -ForegroundColor Green

    # 4. Remover tarefas agendadas
    Write-Host "[4/5] Removendo tarefas agendadas..." -ForegroundColor Cyan
    Get-ScheduledTask -TaskName "OneDrive*" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  OK." -ForegroundColor Green

    # 5. Bloquear reinstalacao/sincronizacao via politica
    Write-Host "[5/5] Bloqueando reinstalacao (GPO)..." -ForegroundColor Cyan
    $polPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive"
    if (-not (Test-Path $polPath)) { New-Item -Path $polPath -Force | Out-Null }
    Set-ItemProperty -Path $polPath -Name "DisableFileSyncNGSC" -Value 1 -Type DWord
    Write-Host "  OK." -ForegroundColor Green

    Write-Host "`n--- OneDrive removido com sucesso ---" -ForegroundColor Green
    exit 0
} catch {
    Write-Error "[FALHA] Erro ao remover OneDrive: $($_.Exception.Message)"
    exit 1
}
