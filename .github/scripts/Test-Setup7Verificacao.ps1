# =============================================================================
#  Teste de regressao: verificacao do plano B do Setup 7 (instalador oficial)
#
#  O Setup 7 so executa um instalador baixado direto do fabricante se a
#  assinatura Authenticode for valida E do fabricante esperado, ou (uv,
#  docker-compose, que nao assinam) se o SHA256 bater com o publicado.
#  Sem rede: usa binarios do proprio Windows e arquivos temporarios.
#  Executado pelo CI no Windows PowerShell 5.1.
# =============================================================================
param([string]$SetupPath = (Join-Path $PSScriptRoot "..\..\Setup\environment\7_install_devtools_dev.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$setup = (Resolve-Path -LiteralPath $SetupPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($setup, [ref]$null, [ref]$null)
# Padroes de assinante ($Assinante*) sao atribuicoes no nivel do script
foreach ($as in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -like '$Assinante*' }, $false)) {
    . ([scriptblock]::Create($as.Extent.Text))
}
foreach ($nome in "Test-ArquivoAssinado", "Test-ArquivoSha256", "Install-Direto", "Get-StatusInstalacao", "Add-PathMaquina",
                "New-PastaDownload", "Save-Download", "Get-GithubLatestAsset") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $setup" }
    . ([scriptblock]::Create($fn.Extent.Text))
}

$script:falhas = 0
function Assert-Condition {
    param([bool]$Condition, [string]$Description)
    if ($Condition) {
        Write-Host "  OK      $Description" -ForegroundColor Green
    } else {
        Write-Host "  FALHOU  $Description" -ForegroundColor Red
        $script:falhas++
    }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("setup7test " + [guid]::NewGuid().ToString('N') + " [x]")
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    Write-Host "`n  Assinatura (Authenticode)" -ForegroundColor Cyan
    # Um executavel assinado do proprio Windows (embutido ou por catalogo)
    $signed = @("$env:SystemRoot\System32\cmd.exe", "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe") |
        Where-Object { (Test-Path -LiteralPath $_) -and (Get-AuthenticodeSignature -LiteralPath $_).Status -eq 'Valid' } | Select-Object -First 1
    if ($signed) {
        Assert-Condition (Test-ArquivoAssinado -Path $signed -SubjectPattern 'Microsoft') "binario assinado pela Microsoft -> aceito"
        Assert-Condition (-not (Test-ArquivoAssinado -Path $signed -SubjectPattern 'Johannes Schindelin')) "assinatura valida de OUTRO fabricante -> recusado"
    } else {
        Write-Host "  (sem binario assinado verificavel nesta imagem; casos de assinatura valida pulados)" -ForegroundColor DarkGray
    }
    $unsigned = Join-Path $tmp "instalador.exe"
    [System.IO.File]::WriteAllBytes($unsigned, [byte[]](77, 90, 0, 0, 1, 2, 3))
    Assert-Condition (-not (Test-ArquivoAssinado -Path $unsigned -SubjectPattern 'Microsoft')) "arquivo sem assinatura -> recusado"
    Assert-Condition (-not (Test-ArquivoAssinado -Path (Join-Path $tmp "nao_existe.exe") -SubjectPattern '.')) "arquivo inexistente -> recusado"

    Write-Host "`n  SHA256 publicado" -ForegroundColor Cyan
    $bin = Join-Path $tmp "uv.zip"
    [System.IO.File]::WriteAllBytes($bin, [System.Text.Encoding]::ASCII.GetBytes("conteudo de teste"))
    $hash = (Get-FileHash -LiteralPath $bin -Algorithm SHA256).Hash
    Assert-Condition (Test-ArquivoSha256 -Path $bin -Esperado $hash) "hash igual -> aceito"
    Assert-Condition (Test-ArquivoSha256 -Path $bin -Esperado ("$($hash.ToLower())  uv-x86_64-pc-windows-msvc.zip`n")) "formato '<hash>  <nome>' do .sha256 (minusculo) -> aceito"
    $outro = ("0" * 63) + "1"
    Assert-Condition (-not (Test-ArquivoSha256 -Path $bin -Esperado $outro)) "hash diferente -> recusado"
    Assert-Condition (-not (Test-ArquivoSha256 -Path $bin -Esperado "")) "hash vazio -> recusado"
    Assert-Condition (-not (Test-ArquivoSha256 -Path $bin -Esperado "nao-e-hash")) "texto que nao e hash -> recusado"

    Write-Host "`n  Assinantes ancorados" -ForegroundColor Cyan
    Assert-Condition ("CN=Johannes Schindelin, O=Johannes Schindelin, S=Nordrhein-Westfalen, C=DE" -match $AssinanteGit) "Subject do Git for Windows casa"
    Assert-Condition (-not ("CN=Not Johannes Schindelin Fake, O=X" -match $AssinanteGit)) "Subject que so contem o nome nao casa"
    Assert-Condition ("CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US" -match $AssinanteMS) "Subject da Microsoft casa"
    Assert-Condition (-not ("CN=Evil, O=Microsoft Corporation Fake Ltd" -match $AssinanteMS)) "O= parecido com Microsoft nao casa"
    Assert-Condition (("CN=Google LLC, O=Google LLC, L=Mountain View, S=California, C=US" -match $AssinanteGoogle) -and -not ("CN=x, O=Googleplex Inc" -match $AssinanteGoogle)) "Subject do Google: so O=Google LLC"

    Write-Host "`n  Status da tabela final" -ForegroundColor Cyan
    Assert-Condition ((Get-StatusInstalacao -Presente $true -Codigo 0) -eq "OK (instalado)") "presente, codigo 0 -> OK (instalado)"
    Assert-Condition ((Get-StatusInstalacao -Presente $true -Codigo 3010) -eq "OK (reinicio pendente)") "presente, 3010 -> reinicio pendente"
    Assert-Condition ((Get-StatusInstalacao -Presente $false -Codigo "assinatura") -eq "FALHA (assinatura)") "verificacao recusou -> FALHA (assinatura)"
    Assert-Condition ((Get-StatusInstalacao -Presente $false -Codigo $null) -eq "FALHA (nao executou)") "nao executou -> FALHA (nao executou)"
    Assert-Condition ((Get-StatusInstalacao -Presente $false -Codigo 1603) -eq "FALHA (codigo 1603)") "codigo de erro -> FALHA (codigo N)"

    Write-Host "`n  PATH pelo registro (REG_EXPAND_SZ preservado)" -ForegroundColor Cyan
    $hk = [Microsoft.Win32.Registry]::CurrentUser
    $sub = "Software\WinTestHubTest_$([guid]::NewGuid().ToString('N'))"
    $k = $hk.CreateSubKey($sub)
    $k.SetValue("Path", "%SystemRoot%\system32;C:\Tools\", [Microsoft.Win32.RegistryValueKind]::ExpandString); $k.Close()
    try {
        $r1 = Add-PathMaquina -Pasta "C:\Program Files\uv" -Raiz $hk -RegKey $sub
        $r2 = Add-PathMaquina -Pasta "C:\Program Files\uv\" -Raiz $hk -RegKey $sub
        $r3 = Add-PathMaquina -Pasta "C:\Tools" -Raiz $hk -RegKey $sub
        $k = $hk.OpenSubKey($sub)
        $raw  = $k.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $kind = $k.GetValueKind("Path"); $k.Close()
        Assert-Condition ($r1 -and -not $r2 -and -not $r3) "acrescenta uma vez; barra final e entrada existente nao duplicam"
        Assert-Condition ($raw -eq "%SystemRoot%\system32;C:\Tools\;C:\Program Files\uv") "valor NAO expandido preservado (%SystemRoot%)"
        Assert-Condition ($kind -eq [Microsoft.Win32.RegistryValueKind]::ExpandString) "tipo REG_EXPAND_SZ preservado"
    } finally { $hk.DeleteSubKeyTree($sub, $false) }

    Write-Host "`n  Install-Direto com download sem assinatura (ponta a ponta, sem rede)" -ForegroundColor Cyan
    function Invoke-RestMethod { param($Uri, $Headers, [switch]$UseBasicParsing, $ErrorAction)
        [PSCustomObject]@{ tag_name = "v9.9.9"; assets = @([PSCustomObject]@{ name = "Git-9.9.9-64-bit.exe"; browser_download_url = "https://example.invalid/Git-9.9.9-64-bit.exe" }) } }
    function Invoke-WebRequest { param($Uri, $OutFile, [switch]$UseBasicParsing, $ErrorAction)
        [System.IO.File]::WriteAllBytes($OutFile, [byte[]](77, 90, 0, 0, 9, 9)) }
    $script:executou = $false
    function Start-Process { $script:executou = $true; throw "nao deveria executar instalador" }
    $r = Install-Direto "git" 6>$null
    Assert-Condition ($r -eq "assinatura" -and -not $script:executou) "instalador sem assinatura valida -> 'assinatura', nada executado"
    Assert-Condition ((Get-StatusInstalacao -Presente $false -Codigo $r) -eq "FALHA (assinatura)") "... e a tabela mostra FALHA (assinatura)"

    Write-Host "`n  Install-Direto sem rede" -ForegroundColor Cyan
    # Sem acesso a rede o plano B nao executa nada e devolve $null (vira "FALHA (nao executou)")
    function Invoke-RestMethod { throw "sem rede (teste)" }
    function Invoke-WebRequest { throw "sem rede (teste)" }
    function Start-Process { throw "nao deveria executar instalador" }
    foreach ($q in "git", "dotnet", "go", "uv", "compose") {
        $r = Install-Direto $q 6>$null
        Assert-Condition ($null -eq $r) "$q sem rede -> nada executado"
    }
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "  $($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "  Todas as verificacoes passaram." -ForegroundColor Green
exit 0
