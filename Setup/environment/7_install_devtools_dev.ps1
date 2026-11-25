# =============================================================================
# Setup: ferramentas de desenvolvimento dos modulos 7 a 11 (cargas de dev)
#
# Instala, sem intervencao, o que as cargas exigem:
#   Git, .NET SDK 10, Go, uv e docker-compose (provider do "podman compose").
# Idempotente: pula o que ja esta instalado na versao minima exigida.
# O Podman e a podman machine ficam no 10_preparar_podman.ps1.
#
# Via 1: winget. Via 2 (plano B, como no hw-eval): quando o winget nao existe,
# nao executa nesta conta (sessao elevada com outra conta da "Acesso negado")
# ou nao resolve o item, baixa o instalador OFICIAL do fabricante e so executa
# se a verificacao passar:
#   - Git, .NET SDK e Go: assinatura Authenticode valida do fabricante
#     (o Go tambem confere o SHA256 publicado em go.dev/dl);
#   - uv e docker-compose: binarios sem assinatura -> SHA256 publicado pelo
#     proprio projeto no mesmo release do GitHub. Isso garante INTEGRIDADE
#     (download corrompido ou adulterado no caminho), nao autenticidade: um
#     release comprometido na origem passaria. Risco aceito: mesma fonte que o
#     winget usa para esses dois pacotes.
# Os downloads vao para uma pasta so de administradores (ProgramData) quando o
# setup roda elevado, para ninguem trocar o arquivo entre verificar e executar.
# Exit 0 so quando todas as ferramentas respondem no final.
#
# Parametros (para diagnostico): -ForceDirect pula o winget.
# =============================================================================
param([switch]$ForceDirect)

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"   # Invoke-WebRequest fica muito mais rapido no PS 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# Codigos de saida aceitos: 0 ok; 3010 ok com reinicio pendente;
# -1978335189 (0x8A15002B) winget "ja instalado / sem atualizacao".
$OkExitCodes = @(0, 3010, -1978335189)

# Ferramenta -> pacote winget, verificacao, versao minima e fonte oficial (plano B)
$ferramentas = @(
    @{ Nome = "Git";            Id = "Git.Git";                 Cmd = "git";            Args = @("--version");          Minima = "2.40"; Direto = "git" },
    @{ Nome = ".NET SDK 10";    Id = "Microsoft.DotNet.SDK.10"; Cmd = "dotnet";         Args = @("--version");          Minima = "10.0"; Direto = "dotnet" },
    @{ Nome = "Go";             Id = "GoLang.Go";               Cmd = "go";             Args = @("version");            Minima = "1.21"; Direto = "go" },
    @{ Nome = "uv";             Id = "astral-sh.uv";            Cmd = "uv";             Args = @("--version");          Minima = "0.5";  Direto = "uv" },
    @{ Nome = "docker-compose"; Id = "Docker.DockerCompose";    Cmd = "docker-compose"; Args = @("version", "--short"); Minima = "2.20"; Direto = "compose" }
)

function Update-SessionPath {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    # Pacotes "portable" do winget (uv, docker-compose) ficam em WinGet\Links
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    if ((Test-Path -LiteralPath $links) -and (($env:PATH -split ';') -notcontains $links)) { $env:PATH += ";$links" }
}

function Get-VersaoFerramenta {
    param([hashtable]$F)
    $cmd = Get-Command $F.Cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
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

# ---- winget: existe E executa nesta conta? -----------------------------------
function Test-WingetUsable {
    $w = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $w) { return $false }
    try {
        $null = & $w.Source --version 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# ---- Verificacao do download (plano B) ---------------------------------------

# Assinatura Authenticode valida e do fabricante esperado (regex no Subject).
function Test-ArquivoAssinado {
    param([string]$Path, [string]$SubjectPattern)
    try { $sig = Get-AuthenticodeSignature -LiteralPath $Path } catch { return $false }
    if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate) { return $false }
    return ($sig.SignerCertificate.Subject -match $SubjectPattern)
}

# Padroes de assinante ancorados (CN/O exatos, nao "contem a palavra")
$AssinanteGit    = '(^|, )CN=Johannes Schindelin(,|$)'
$AssinanteMS     = '(^|, )O=Microsoft Corporation(,|$)'
$AssinanteGoogle = '(^|, )O=Google LLC(,|$)'

# Status da tabela final a partir do resultado da instalacao
function Get-StatusInstalacao {
    param([bool]$Presente, $Codigo)
    if ($Presente) {
        if ($Codigo -is [int] -and $Codigo -eq 3010) { return "OK (reinicio pendente)" }
        return "OK (instalado)"
    }
    if ($Codigo -is [string] -and $Codigo -eq "assinatura") { return "FALHA (assinatura)" }
    if ($null -eq $Codigo) { return "FALHA (nao executou)" }
    return "FALHA (codigo $Codigo)"
}

# SHA256 do arquivo igual ao publicado. Aceita o conteudo de um arquivo
# .sha256 ("<hash>  <nome>" ou so o hash).
function Test-ArquivoSha256 {
    param([string]$Path, [string]$Esperado)
    if ([string]::IsNullOrWhiteSpace($Esperado)) { return $false }
    $hash = ($Esperado.Trim() -split '\s+')[0]
    if ($hash -notmatch '^[0-9a-fA-F]{64}$') { return $false }
    $atual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return ($atual -ieq $hash)
}

function Get-GithubLatestAsset {
    param([string]$Repo, [string]$AssetPattern)
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "WinTestHub-Setup" } -UseBasicParsing -ErrorAction Stop
    $asset = @($rel.assets | Where-Object { $_.name -match $AssetPattern }) | Select-Object -First 1
    if (-not $asset) { throw "asset '$AssetPattern' nao encontrado no release $($rel.tag_name) de $Repo" }
    $sha = @($rel.assets | Where-Object { $_.name -eq "$($asset.name).sha256" }) | Select-Object -First 1
    return [pscustomobject]@{ Name = $asset.name; Url = $asset.browser_download_url; Sha256Url = $(if ($sha) { $sha.browser_download_url } else { $null }) }
}

# Pasta de download: so administradores escrevem (quando elevado); senao TEMP.
function New-PastaDownload {
    $nome = "wintesthub-setup7-" + [guid]::NewGuid().ToString('N')
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) {
        # Direto na raiz do ProgramData (dono SYSTEM): uma pasta-mae propria
        # poderia ser criada antes por um usuario comum, que viraria o dono.
        $dir = Join-Path $env:ProgramData $nome
        New-Item -ItemType Directory -Path $dir -Force -ErrorAction Stop | Out-Null
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($sid in "S-1-5-32-544", "S-1-5-18") {   # Administradores, SYSTEM
            $id = New-Object System.Security.Principal.SecurityIdentifier($sid)
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($id, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
        }
        Set-Acl -LiteralPath $dir -AclObject $acl -ErrorAction Stop
        return $dir
    }
    $dir = Join-Path ([IO.Path]::GetTempPath()) $nome
    New-Item -ItemType Directory -Path $dir -Force -ErrorAction Stop | Out-Null
    return $dir
}

function Save-Download {
    param([string]$Url, [string]$FileName)
    $dir = New-PastaDownload
    $file = Join-Path $dir $FileName
    Write-Host "  baixando $Url" -ForegroundColor DarkGray
    Invoke-WebRequest -Uri $Url -OutFile $file -UseBasicParsing -ErrorAction Stop
    return $file
}

# Acrescenta uma pasta ao PATH da maquina pelo registro, preservando o valor
# NAO expandido (%SystemRoot%...) e o tipo REG_EXPAND_SZ. Environment.
# SetEnvironmentVariable gravaria o PATH expandido como REG_SZ (corrompe).
function Add-PathMaquina {
    param(
        [string]$Pasta,
        [Microsoft.Win32.RegistryKey]$Raiz = [Microsoft.Win32.Registry]::LocalMachine,
        [string]$RegKey = "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    )
    $key = $Raiz.OpenSubKey($RegKey, $true)
    if ($null -eq $key) { throw "chave de ambiente nao encontrada: $($Raiz.Name)\$RegKey" }
    try {
        $atual = [string]$key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $norm = $Pasta.TrimEnd('\')
        $existe = @($atual -split ';' | Where-Object { $_ -and ([Environment]::ExpandEnvironmentVariables($_)).TrimEnd('\') -ieq $norm }).Count -gt 0
        if ($existe) { return $false }
        $novo = if ($atual) { $atual.TrimEnd(';') + ";" + $Pasta } else { $Pasta }
        $key.SetValue("Path", $novo, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        return $true
    } finally { $key.Close() }
}

# Pasta de binarios avulsos (uv, docker-compose) no PATH da maquina
function Install-Binario {
    param([string]$Origem, [string]$PastaDestino, [string]$NomeFinal)
    New-Item -ItemType Directory -Path $PastaDestino -Force -ErrorAction Stop | Out-Null
    Copy-Item -LiteralPath $Origem -Destination (Join-Path $PastaDestino $NomeFinal) -Force -ErrorAction Stop
    $null = Add-PathMaquina -Pasta $PastaDestino
}

# Instala pelo instalador oficial. Devolve o codigo de saida, ou $null quando
# nao executou (download falhou ou a verificacao recusou o arquivo).
function Install-Direto {
    param([string]$Qual)
    $file = $null
    try {
        switch ($Qual) {
            "git" {
                $a = Get-GithubLatestAsset -Repo "git-for-windows/git" -AssetPattern '^Git-[\d.]+-64-bit\.exe$'
                $file = Save-Download -Url $a.Url -FileName $a.Name
                if (-not (Test-ArquivoAssinado -Path $file -SubjectPattern $AssinanteGit)) { Write-Host "  RECUSADO: assinatura invalida ($($a.Name))" -ForegroundColor Red; return "assinatura" }
                return (Start-Process -FilePath $file -ArgumentList '/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES' -Wait -PassThru).ExitCode
            }
            "dotnet" {
                $file = Save-Download -Url "https://aka.ms/dotnet/10.0/dotnet-sdk-win-x64.exe" -FileName "dotnet-sdk-10-win-x64.exe"
                if (-not (Test-ArquivoAssinado -Path $file -SubjectPattern $AssinanteMS)) { Write-Host "  RECUSADO: assinatura invalida (.NET SDK)" -ForegroundColor Red; return "assinatura" }
                return (Start-Process -FilePath $file -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru).ExitCode
            }
            "go" {
                $rel = @(Invoke-RestMethod -Uri "https://go.dev/dl/?mode=json" -UseBasicParsing -ErrorAction Stop) | Where-Object { $_.stable } | Select-Object -First 1
                $f = @($rel.files | Where-Object { $_.os -eq "windows" -and $_.arch -eq "amd64" -and $_.kind -eq "installer" }) | Select-Object -First 1
                if (-not $f) { throw "instalador Windows amd64 nao encontrado em go.dev/dl" }
                $file = Save-Download -Url "https://go.dev/dl/$($f.filename)" -FileName $f.filename
                if (-not (Test-ArquivoSha256 -Path $file -Esperado $f.sha256)) { Write-Host "  RECUSADO: SHA256 diferente do publicado ($($f.filename))" -ForegroundColor Red; return "assinatura" }
                if (-not (Test-ArquivoAssinado -Path $file -SubjectPattern $AssinanteGoogle)) { Write-Host "  RECUSADO: assinatura invalida ($($f.filename))" -ForegroundColor Red; return "assinatura" }
                return (Start-Process -FilePath "msiexec.exe" -ArgumentList '/i', "`"$file`"", '/qn', '/norestart' -Wait -PassThru).ExitCode
            }
            "uv" {
                $a = Get-GithubLatestAsset -Repo "astral-sh/uv" -AssetPattern '^uv-x86_64-pc-windows-msvc\.zip$'
                if (-not $a.Sha256Url) { throw "release do uv sem .sha256" }
                $file = Save-Download -Url $a.Url -FileName $a.Name
                $esperado = (Invoke-WebRequest -Uri $a.Sha256Url -UseBasicParsing -ErrorAction Stop).Content
                if ($esperado -is [byte[]]) { $esperado = [Text.Encoding]::ASCII.GetString($esperado) }
                if (-not (Test-ArquivoSha256 -Path $file -Esperado $esperado)) { Write-Host "  RECUSADO: SHA256 diferente do publicado ($($a.Name))" -ForegroundColor Red; return "assinatura" }
                $ext = Join-Path (Split-Path $file -Parent) "uv"
                Expand-Archive -LiteralPath $file -DestinationPath $ext -Force
                foreach ($exe in "uv.exe", "uvx.exe") {
                    $src = Get-ChildItem -LiteralPath $ext -Recurse -Filter $exe -File | Select-Object -First 1
                    if ($src) { Install-Binario -Origem $src.FullName -PastaDestino (Join-Path $env:ProgramFiles "uv") -NomeFinal $exe }
                }
                return 0
            }
            "compose" {
                $a = Get-GithubLatestAsset -Repo "docker/compose" -AssetPattern '^docker-compose-windows-x86_64\.exe$'
                if (-not $a.Sha256Url) { throw "release do docker-compose sem .sha256" }
                $file = Save-Download -Url $a.Url -FileName $a.Name
                $esperado = (Invoke-WebRequest -Uri $a.Sha256Url -UseBasicParsing -ErrorAction Stop).Content
                if ($esperado -is [byte[]]) { $esperado = [Text.Encoding]::ASCII.GetString($esperado) }
                if (-not (Test-ArquivoSha256 -Path $file -Esperado $esperado)) { Write-Host "  RECUSADO: SHA256 diferente do publicado ($($a.Name))" -ForegroundColor Red; return "assinatura" }
                Install-Binario -Origem $file -PastaDestino (Join-Path $env:ProgramFiles "docker-compose") -NomeFinal "docker-compose.exe"
                return 0
            }
        }
    } catch {
        Write-Host "  ERRO no instalador oficial: $($_.Exception.Message)" -ForegroundColor Red
        return $null
    } finally {
        if ($file) { Remove-Item -LiteralPath (Split-Path $file -Parent) -Recurse -Force -ErrorAction SilentlyContinue }
    }
    return $null
}

function Invoke-WingetInstall {
    param([hashtable]$F)
    # Escopo machine quando o pacote oferece; sem ele, o escopo padrao do pacote
    winget install --id $F.Id --exact --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
    $codigo = $LASTEXITCODE
    if ($OkExitCodes -notcontains $codigo) {
        Write-Host "  escopo machine indisponivel para $($F.Id) (codigo $codigo); usando o escopo padrao do pacote." -ForegroundColor DarkYellow
        winget install --id $F.Id --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
        $codigo = $LASTEXITCODE
    }
    return $codigo
}

# Corpo do setup (fora de funcao para a CI poder extrair so as funcoes acima)
if ($MyInvocation.InvocationName -ne '.') {
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

    # 2. winget (opcional: sem ele, so o plano B)
    $useWinget = (-not $ForceDirect) -and (Test-WingetUsable)
    if ($useWinget) {
        Write-Host "winget: OK" -ForegroundColor Green
    } else {
        Write-Host "winget indisponivel nesta conta$(if ($ForceDirect) { ' (-ForceDirect)' }): usando o instalador oficial de cada ferramenta (com verificacao)." -ForegroundColor Yellow
    }

    Update-SessionPath

    # 3. Instalacao
    $tabela = @()
    foreach ($f in $ferramentas) {
        Write-Host "`n[$($f.Nome)] " -ForegroundColor Cyan -NoNewline
        if (Test-Ferramenta $f) {
            $atual = ((Get-VersaoFerramenta $f).Texto -split "`n")[0]
            Write-Host "ja instalado ($atual)." -ForegroundColor Yellow
            $tabela += [pscustomobject]@{ Ferramenta = $f.Nome; Status = "OK (ja presente)"; Via = "-"; Versao = $atual }
            continue
        }
        $via = "-"; $codigo = $null
        if ($useWinget) {
            Write-Host "instalando $($f.Id) via winget..." -ForegroundColor Magenta
            $via = "winget"
            for ($tentativa = 1; $tentativa -le 2 -and -not (Test-Ferramenta $f); $tentativa++) {
                if ($tentativa -gt 1) { Write-Host "  tentativa $tentativa de 2..." -ForegroundColor DarkYellow; Start-Sleep -Seconds 3 }
                $codigo = Invoke-WingetInstall $f
                Update-SessionPath
            }
        }
        if (-not (Test-Ferramenta $f)) {
            if ($useWinget) { Write-Host "  o winget nao resolveu $($f.Nome); tentando o instalador oficial." -ForegroundColor Yellow }
            else { Write-Host "instalando pelo instalador oficial..." -ForegroundColor Magenta }
            $via = "instalador oficial"
            $codigo = Install-Direto $f.Direto
            Update-SessionPath
        }
        $v = Get-VersaoFerramenta $f
        $versao = if ($v) { ($v.Texto -split "`n")[0] } else { "-" }
        $status = Get-StatusInstalacao -Presente (Test-Ferramenta $f) -Codigo $codigo
        $color = if ($status -like "OK*") { "Green" } else { "Red" }
        Write-Host "  $status via $via" -ForegroundColor $color
        $tabela += [pscustomobject]@{ Ferramenta = $f.Nome; Status = $status; Via = $via; Versao = $versao }
    }

    # 4. Verificacao final (fonte de verdade: a ferramenta responde no PATH)
    Update-SessionPath
    Write-Host "`n--- Resultado ---" -ForegroundColor Green
    $tabela | Format-Table -AutoSize | Out-String -Width 160 | Write-Host
    $faltando = @($ferramentas | Where-Object { -not (Test-Ferramenta $_) })
    if ($faltando.Count -gt 0) {
        # Mesmo texto da checagem antes da fila do hub (Get-PreflightFindings)
        foreach ($f in $faltando) {
            $v = Get-VersaoFerramenta $f
            if ($null -eq $v) { $msg = "'$($f.Cmd)' nao encontrado" }
            else { $msg = "'$($f.Cmd)' abaixo da versao minima $($f.Minima): $(($v.Texto -split "`n")[0])" }
            Write-Host "  [FALTA] $msg" -ForegroundColor Red
        }
        Write-Host "`n$($faltando.Count) ferramenta(s) faltando. Os modulos que dependem delas vao reprovar (a checagem antes da fila tambem acusa)." -ForegroundColor Red
        exit 1
    }
    Write-Host "`nTodas as ferramentas prontas. Abra um novo terminal (ou reinicie o hub) para o PATH valer." -ForegroundColor Green
    exit 0
}
