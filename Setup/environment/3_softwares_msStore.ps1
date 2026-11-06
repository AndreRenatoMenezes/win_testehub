# ---------------------------------------------------------------- objective
# Script: Instalação Automatizada (Admin)
# Apps: CrystalDiskMark, CrystalDiskInfo e Windows ADK
# Integração: Validação HTTP, Retry Loop e Clean Output
# --------------------------------------------------------------------------

# 1. Verificação de Administrador (Apenas se NÃO estiver rodando pelo Hub)
$isHub = -not [string]::IsNullOrWhiteSpace($env:HUB_TRACE_DIR)

if (-not $isHub) {
    if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
        Write-Host "Solicitando permissoes de administrador (Execucao Avulsa)..." -ForegroundColor Yellow
        Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
        exit
    }
}

Write-Host "--- Iniciando Setup de Softwares ---" -ForegroundColor Green

# 2. Verificar Conexão com a Internet (Metodo HTTP - Anti-Firewall)
Write-Host "Verificando conexao com a internet... " -NoNewline
try {
    $req = Invoke-WebRequest -Uri "http://www.msftconnecttest.com/connecttest.txt" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($req.Content -match "Microsoft Connect Test") {
        Write-Host "OK!" -ForegroundColor Green
    } else {
        throw "Conteudo da resposta inesperado."
    }
} catch {
    Write-Host "FALHA!" -ForegroundColor Red
    Write-Error "Erro: Sem conexao com a internet ou bloqueio de rede detectado."
    exit 1
}

# 3. Verificar se o Winget está instalado
if (!(Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error "Erro: Winget nao encontrado. Atualize o 'Instalador de Aplicativos' na Microsoft Store."
    exit 1
}

# 4. Lista de pacotes
$apps = @(
    "Microsoft.WindowsADK",
    "CrystalDewWorld.CrystalDiskMark",
    "CrystalDewWorld.CrystalDiskInfo"
)

# 5. Loop de Instalação com Verificação, Retry e Log Limpo
foreach ($app in $apps) {
    Write-Host "`n[Processando]: $app" -ForegroundColor Cyan
    Write-Host "Verificando o status de instalacao... " -NoNewline

    $listOutput = winget list --id $app --exact --disable-interactivity --accept-source-agreements 2>&1

    if ($listOutput -match $app) {
        Write-Host "Ja Instalado!" -ForegroundColor Yellow
        Write-Host "-> Pulando download/instalacao de $app." -ForegroundColor DarkGray
    } else {
        Write-Host "Nao encontrado. Iniciando download e instalacao..." -ForegroundColor Magenta

        $maxTentativas = 3
        $tentativaAtual = 0
        $instaladoSucesso = $false

        while ($tentativaAtual -lt $maxTentativas -and -not $instaladoSucesso) {
            $tentativaAtual++

            if ($tentativaAtual -gt 1) {
                Write-Host "  -> Tentativa $tentativaAtual de $maxTentativas..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds 3
            }

            winget install --id $app --silent --disable-interactivity --accept-package-agreements --accept-source-agreements

            if ($LASTEXITCODE -eq 0) {
                $instaladoSucesso = $true
            }
        }

        if ($instaladoSucesso) {
            Write-Host "OK: $app instalado com sucesso." -ForegroundColor Green
        } else {
            Write-Warning "Nota: Falha na instalacao de $app apos $maxTentativas tentativas. (Ultimo Codigo: $LASTEXITCODE)"
        }
    }
}

Write-Host "`n--- Operacao Concluida ---" -ForegroundColor Green
