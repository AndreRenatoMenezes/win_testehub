# =============================================================================
# Setup: ferramentas de desenvolvimento dos modulos 7 a 11 (cargas de dev)
#
# Instala via winget, sem intervencao, o que as cargas exigem:
#   Git, .NET SDK 10, Go, uv e docker-compose (provider do "podman compose").
# Idempotente: pula o que ja esta instalado na versao minima exigida.
# O Podman e a podman machine ficam no 10_preparar_podman.ps1.
# Exit 0 so quando todas as ferramentas respondem no final.
# =============================================================================

$ErrorActionPreference = "Continue"

# Ferramenta -> pacote winget, comando de verificacao e versao minima
$ferramentas = @(
    @{ Nome = "Git";            Id = "Git.Git";                  Cmd = "git";            Args = @("--version");            Minima = "2.40" },
    @{ Nome = ".NET SDK 10";    Id = "Microsoft.DotNet.SDK.10";  Cmd = "dotnet";         Args = @("--version");            Minima = "10.0" },
    @{ Nome = "Go";             Id = "GoLang.Go";                Cmd = "go";             Args = @("version");              Minima = "1.21" },
    @{ Nome = "uv";             Id = "astral-sh.uv";             Cmd = "uv";             Args = @("--version");            Minima = "0.5" },
    @{ Nome = "docker-compose"; Id = "Docker.DockerCompose";     Cmd = "docker-compose"; Args = @("version", "--short");   Minima = "2.20" }
)

function Update-SessionPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    # Pacotes "portable" do winget (uv, docker-compose) ficam em WinGet\Links
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    if ((Test-Path $links) -and (($env:PATH -split ';') -notcontains $links)) { $env:PATH += ";$links" }
}

function Get-VersaoFerramenta {
    param([hashtable]$F)
    $cmd = Get-Command $F.Cmd -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return $null }
    try {
        $saida = (& $cmd.Source @($F.Args) 2>&1 | Out-String).Trim()
    } catch {
        return $null
    }
    if ($saida -match '(\d+)\.(\d+)(\.(\d+))?') { return [pscustomobject]@{ Texto = $saida; Versao = [version]"$($Matches[1]).$($Matches[2])" } }
    return $null
}

function Test-Ferramenta {
    param([hashtable]$F)
    $v = Get-VersaoFerramenta $F
    if (-not $v) { return $false }
    return ($v.Versao -ge [version]$F.Minima)
}

Write-Host "--- Ferramentas de desenvolvimento (modulos 7 a 11) ---" -ForegroundColor Green

# 1. Internet
Write-Host "Verificando conexao com a internet... " -NoNewline
try {
    $req = Invoke-WebRequest -Uri "http://www.msftconnecttest.com/connecttest.txt" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($req.Content -notmatch "Microsoft Connect Test") { throw "resposta inesperada" }
    Write-Host "OK" -ForegroundColor Green
} catch {
    Write-Host "FALHA" -ForegroundColor Red
    Write-Host "Sem internet: nao e possivel instalar as ferramentas." -ForegroundColor Red
    exit 1
}

# 2. winget
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget nao encontrado. Atualize o 'Instalador de Aplicativos' na Microsoft Store." -ForegroundColor Red
    exit 1
}

Update-SessionPath

# 3. Instalacao
foreach ($f in $ferramentas) {
    Write-Host "`n[$($f.Nome)] " -ForegroundColor Cyan -NoNewline
    if (Test-Ferramenta $f) {
        $atual = ((Get-VersaoFerramenta $f).Texto -split "`n")[0]
        Write-Host "ja instalado ($atual)." -ForegroundColor Yellow
        continue
    }
    Write-Host "instalando $($f.Id)..." -ForegroundColor Magenta
    $ok = $false
    for ($tentativa = 1; $tentativa -le 3 -and -not $ok; $tentativa++) {
        if ($tentativa -gt 1) { Write-Host "  tentativa $tentativa de 3..." -ForegroundColor DarkYellow; Start-Sleep -Seconds 3 }
        # Escopo machine quando o pacote oferece; sem ele, o winget usa o escopo padrao do pacote
        winget install --id $f.Id --exact --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
        $codigoWinget = $LASTEXITCODE
        $escopo = "machine"
        if ($codigoWinget -ne 0) {
            Write-Host "  escopo machine indisponivel para $($f.Id) (codigo $codigoWinget); usando o escopo padrao do pacote." -ForegroundColor DarkYellow
            winget install --id $f.Id --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
            $codigoWinget = $LASTEXITCODE
            $escopo = "padrao do pacote"
        }
        Update-SessionPath
        $ok = Test-Ferramenta $f
    }
    if ($ok) {
        Write-Host "  OK: $($f.Nome) instalado (escopo: $escopo)." -ForegroundColor Green
    } else {
        Write-Host "  FALHA: $($f.Nome) nao respondeu apos a instalacao (codigo winget: $codigoWinget)." -ForegroundColor Red
    }
}

# 4. Verificacao final (fonte de verdade: a ferramenta responde no PATH)
Update-SessionPath
Write-Host "`n--- Verificacao ---" -ForegroundColor Green
$faltando = 0
foreach ($f in $ferramentas) {
    $v = Get-VersaoFerramenta $f
    if ($v -and $v.Versao -ge [version]$f.Minima) {
        Write-Host ("  [OK]    {0,-15} {1}" -f $f.Nome, ($v.Texto -split "`n" | Select-Object -First 1)) -ForegroundColor Green
    } else {
        Write-Host ("  [FALTA] {0,-15} minima {1}" -f $f.Nome, $f.Minima) -ForegroundColor Red
        $faltando++
    }
}

if ($faltando -gt 0) {
    Write-Host "`n$faltando ferramenta(s) faltando. Os modulos que dependem delas vao reprovar." -ForegroundColor Red
    exit 1
}
Write-Host "`nTodas as ferramentas prontas. Abra um novo terminal (ou reinicie o hub) para o PATH valer." -ForegroundColor Green
exit 0
