# =============================================================================
# Instalação Isolada de Dependências Python (Virtual Environment)
# =============================================================================
# O hub roda cada script em um powershell.exe filho que herda o PATH do hub.
# Quando o Setup 4 acabou de instalar o Python, esse PATH ainda é o antigo,
# por isso o PATH é relido do registro e o Python é procurado também nos
# caminhos padrão de instalação.

# Descobre a raiz do projeto (voltando 2 pastas: environment -> Setup -> raiz)
$RootPath = (Resolve-Path "$PSScriptRoot\..\..").Path
$VenvName = ".venv" # Deve ser o mesmo nome definido no config.json
$VenvPath = Join-Path $RootPath $VenvName
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

# Liste aqui os pacotes Python que os seus testes necessitam
$Pacotes = @("psutil", "speedtest-cli", "requests", "selenium", "pandas", "pyautogui", "pyperclip", "pynput")

function Update-SessionPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# Retorna o caminho de um python.exe real (ignora o alias da MS Store) ou $null
function Find-RealPython {
    Update-SessionPath

    $candidatos = @()
    $candidatos += Get-Command python.exe, python3.exe -All -ErrorAction SilentlyContinue |
                   Where-Object { $_.Source -notmatch "WindowsApps" } |
                   ForEach-Object { $_.Source }

    # Caminhos padrão do instalador oficial (InstallAllUsers=1 e por usuário)
    foreach ($base in @($env:ProgramFiles, "$env:LOCALAPPDATA\Programs\Python")) {
        if ($base -and (Test-Path $base)) {
            $candidatos += Get-ChildItem -Path $base -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
                           Sort-Object Name -Descending |
                           ForEach-Object { Join-Path $_.FullName "python.exe" }
        }
    }

    foreach ($c in $candidatos) {
        if (-not (Test-Path $c)) { continue }
        $ver = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$ver" -match "Python 3\.") { return $c }
    }
    return $null
}

Write-Host "  >> Verificando ambiente virtual Python em: $VenvPath" -ForegroundColor Cyan

# Um .venv sem python.exe funcional (criação interrompida) é recriado
if (Test-Path $VenvPath) {
    $ok = $false
    if (Test-Path $VenvPython) {
        $null = & $VenvPython --version 2>&1
        $ok = ($LASTEXITCODE -eq 0)
    }
    if ($ok) {
        Write-Host "  >> Ambiente virtual já existe." -ForegroundColor Green
    } else {
        Write-Host "  [!] Ambiente virtual incompleto, recriando..." -ForegroundColor Yellow
        Remove-Item $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $VenvPath)) {
    $pyExe = Find-RealPython
    if (-not $pyExe) {
        Write-Host "  [!] Python não encontrado. Rode o Setup 4 (install_python) antes deste." -ForegroundColor Red
        exit 1
    }

    Write-Host "  >> Criando novo ambiente virtual (.venv) com $pyExe..." -ForegroundColor Yellow
    & $pyExe -m venv $VenvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        Write-Host "  [!] Erro ao criar o ambiente virtual. Verifique a instalação do Python." -ForegroundColor Red
        Remove-Item $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

Write-Host "  >> Atualizando o PIP no ambiente virtual..." -ForegroundColor DarkGray
& $VenvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!] Não foi possível atualizar o pip (seguindo com a versão atual)." -ForegroundColor Yellow
}

Write-Host "  >> Instalando pacotes ($($Pacotes -join ', '))..." -ForegroundColor Yellow
$falhas = @()
foreach ($pacote in $Pacotes) {
    $saida = & $VenvPython -m pip install $pacote --disable-pip-version-check 2>&1
    if ($LASTEXITCODE -ne 0) {
        # Uma nova tentativa cobre falhas transitórias de rede/índice
        Write-Host "     [!] $pacote falhou, tentando de novo..." -ForegroundColor Yellow
        $saida = & $VenvPython -m pip install $pacote --disable-pip-version-check 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        $falhas += $pacote
        Write-Host "     [ERRO] $pacote :" -ForegroundColor Red
        $saida | Select-Object -Last 5 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    } else {
        Write-Host "     [OK] $pacote" -ForegroundColor DarkGray
    }
}

if ($falhas.Count -gt 0) {
    Write-Host "  [!] Pacotes com falha: $($falhas -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] Dependências Python isoladas configuradas com sucesso." -ForegroundColor Green
exit 0
