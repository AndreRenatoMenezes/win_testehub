Write-Host "Iniciando a configuracao de energia..." -ForegroundColor Cyan

$falhas = 0

# 1. Forca o plano Equilibrado de energia
powercfg /S 381b4222-f694-41f0-9685-ff5bb260df2e
if ($LASTEXITCODE -ne 0) { Write-Host "  [FALHA] Nao foi possivel alterar o plano de energia." -ForegroundColor Red; $falhas++ }
else { Write-Host "- Plano alterado para Equilibrado." -ForegroundColor Yellow }

# 2. Define a suspensao de atividade para "NUNCA" (0 minutos)
powercfg /change standby-timeout-ac 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
powercfg /change standby-timeout-dc 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
Write-Host "- Suspensao desativada (Tomada e Bateria)." -ForegroundColor Yellow

# 3. Define o desligamento do video para "NUNCA" (0 minutos)
powercfg /change monitor-timeout-ac 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
powercfg /change monitor-timeout-dc 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
Write-Host "- Desligamento do video desativado (Tomada e Bateria)." -ForegroundColor Yellow

# 4. Define a acao de fechar a tampa para "Nada a fazer" (0)
powercfg /setacvalueindex scheme_current sub_buttons lidaction 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
powercfg /setdcvalueindex scheme_current sub_buttons lidaction 0
if ($LASTEXITCODE -ne 0) { $falhas++ }
Write-Host "- Acao de fechar a tampa definida como 'Nada a fazer'." -ForegroundColor Yellow

# 5. Aplica as alteracoes definitivamente no plano atual
powercfg /setactive scheme_current
if ($LASTEXITCODE -ne 0) { $falhas++ }

if ($falhas -gt 0) {
    Write-Host "[AVISO] $falhas comando(s) powercfg falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Configuracoes aplicadas com sucesso!" -ForegroundColor Green
exit 0
