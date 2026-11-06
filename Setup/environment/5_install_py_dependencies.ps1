# =============================================================================
# Instalação Isolada de Dependências Python (Virtual Environment)
# =============================================================================

# Descobre a raiz do projeto (voltando 2 pastas: environment -> Setup -> raiz)
$RootPath = (Resolve-Path "$PSScriptRoot\..\..").Path
$VenvName = ".venv" # Deve ser o mesmo nome definido no config.json
$VenvPath = Join-Path $RootPath $VenvName

Write-Host "  >> Verificando ambiente virtual Python em: $VenvPath" -ForegroundColor Cyan

if (-not (Test-Path $VenvPath)) {
    Write-Host "  >> Criando novo ambiente virtual (.venv)..." -ForegroundColor Yellow
    
    # Tenta usar python3 ou python
    $pyExe = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }
    & $pyExe -m venv $VenvPath
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!] Erro ao criar o ambiente virtual. Verifique a instalação do Python." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  >> Ambiente virtual já existe." -ForegroundColor Green
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$VenvPip    = Join-Path $VenvPath "Scripts\pip.exe"

Write-Host "  >> Atualizando o PIP no ambiente virtual..." -ForegroundColor DarkGray
& $VenvPython -m pip install --upgrade pip | Out-Null

# Liste aqui os pacotes Python que os seus testes necessitam
$Pacotes = @("psutil", "speedtest-cli", "requests", "selenium", "pandas", "pyautogui", "pyperclip", "psutil", "pynput")

Write-Host "  >> Instalando pacotes ($($Pacotes -join ', '))..." -ForegroundColor Yellow
foreach ($pacote in $Pacotes) {
    & $VenvPip install $pacote | Out-Null
}

Write-Host "  [OK] Dependências Python isoladas configuradas com sucesso." -ForegroundColor Green
exit 0