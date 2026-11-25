# =============================================================================
# Setup (opcional): CA corporativa para os modulos 9 e 10
#
# Em rede com inspecao TLS (proxy que reassina o HTTPS), ferramentas que nao
# usam a loja de certificados do Windows (pip/requests, curl, OpenSSL, a VM do
# Podman) recusam as conexoes. Este script:
#   1. Testa se ha inspecao TLS (git com OpenSSL, que ignora a loja do Windows).
#   2. Sem inspecao (ex.: rede do laboratorio): nao altera nada e sai PASS.
#   3. Com inspecao: exporta as raizes e intermediarias em que o Windows JA
#      confia para um PEM no perfil do usuario, define as variaveis de CA,
#      instala o PEM na podman machine (se existir) e testa de novo.
# Nao confia em nada novo e nao grava certificado no repositorio.
# =============================================================================

$ErrorActionPreference = "Continue"
$urlTeste = "https://github.com/git/git"
$bundle = Join-Path $env:USERPROFILE "certs-corporativos\bundle.pem"
$variaveis = @("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "PIP_CERT", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")

function Test-TlsOpenSsl {
    param([string]$CaFile)
    $gitArgs = @("-c", "http.sslBackend=openssl")
    if ($CaFile) { $gitArgs += @("-c", "http.sslCAInfo=$CaFile") }
    $gitArgs += @("ls-remote", $urlTeste, "HEAD")
    & git @gitArgs *> $null
    return ($LASTEXITCODE -eq 0)
}

Write-Host "--- CA corporativa (opcional) ---" -ForegroundColor Green

# O git pode ter acabado de ser instalado pelo Setup 7: rele o PATH do registro
# e, se ainda faltar, usa o caminho padrao do instalador.
$env:PATH = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $gitCmd = Join-Path $env:ProgramFiles "Git\cmd"
    if (Test-Path (Join-Path $gitCmd "git.exe")) { $env:PATH += ";$gitCmd" }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git nao encontrado: rode antes o 7_install_devtools_dev.ps1." -ForegroundColor Red
    exit 1
}

# Precisa de rede para o teste fazer sentido. Forca o schannel (loja do Windows): o Git
# instalado pelo winget usa OpenSSL por padrao, que falharia justamente sob inspecao TLS.
& git -c http.sslBackend=schannel ls-remote $urlTeste HEAD *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Sem acesso ao GitHub nem pela loja do Windows: verifique a rede antes de continuar." -ForegroundColor Red
    exit 1
}

Write-Host "Testando TLS sem a loja do Windows (OpenSSL)... " -NoNewline
if (Test-TlsOpenSsl) {
    Write-Host "OK" -ForegroundColor Green
    Write-Host "Sem inspecao TLS nesta rede: nada a configurar." -ForegroundColor Green
    exit 0
}
Write-Host "FALHOU" -ForegroundColor Yellow
Write-Host "Ha inspecao TLS: exportando a cadeia confiavel do Windows." -ForegroundColor Yellow

# Raizes validas + intermediarias validas da maquina
$agora = Get-Date
$certs = @(Get-ChildItem Cert:\LocalMachine\Root) + @(Get-ChildItem Cert:\LocalMachine\CA) |
    Where-Object { $_.NotBefore -le $agora -and $_.NotAfter -gt $agora } |
    Sort-Object Thumbprint -Unique

New-Item -ItemType Directory -Path (Split-Path $bundle) -Force | Out-Null
$linhas = New-Object System.Collections.Generic.List[string]
foreach ($c in $certs) {
    $b64 = [Convert]::ToBase64String($c.RawData)
    $linhas.Add("# $($c.Subject)")
    $linhas.Add("-----BEGIN CERTIFICATE-----")
    for ($i = 0; $i -lt $b64.Length; $i += 64) { $linhas.Add($b64.Substring($i, [Math]::Min(64, $b64.Length - $i))) }
    $linhas.Add("-----END CERTIFICATE-----")
}
[System.IO.File]::WriteAllLines($bundle, $linhas.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  PEM gravado: $bundle ($($certs.Count) certificados)"

if (-not (Test-TlsOpenSsl -CaFile $bundle)) {
    Write-Host "O PEM exportado NAO validou a conexao. Variaveis nao foram definidas; fale com o time de rede." -ForegroundColor Red
    exit 1
}
Write-Host "  PEM validado com OpenSSL." -ForegroundColor Green

foreach ($v in $variaveis) {
    [System.Environment]::SetEnvironmentVariable($v, $bundle, "User")
    Set-Item -Path "env:$v" -Value $bundle
}
Write-Host "  Variaveis de usuario definidas: $($variaveis -join ', ')" -ForegroundColor Green

# podman machine (WSL): o C: fica montado em /mnt/c dentro da VM
if (Get-Command podman -ErrorAction SilentlyContinue) {
    $estado = (podman machine inspect --format "{{.State}}" 2>$null | Select-Object -First 1)
    if ($estado -eq "running") {
        $caminhoVm = "/mnt/" + $bundle.Substring(0, 1).ToLower() + ($bundle.Substring(2) -replace '\\', '/')
        podman machine ssh "sudo cp '$caminhoVm' /etc/pki/ca-trust/source/anchors/wintestehub-corp.pem && sudo update-ca-trust"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  PEM instalado na podman machine." -ForegroundColor Green
        } else {
            Write-Host "  Falha ao instalar o PEM na podman machine (codigo $LASTEXITCODE)." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "  podman machine nao esta rodando: rode este script de novo apos o 10_preparar_podman.ps1." -ForegroundColor Yellow
    }
}

Write-Host "`nCA corporativa configurada. Abra um novo terminal (ou reinicie o hub) para as variaveis valerem." -ForegroundColor Green
exit 0
