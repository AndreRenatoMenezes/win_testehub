# =============================================================================
#  Teste de regressao: parada da fila por Ctrl+Q (hub.ps1 + testes)
#
#  Garante que Test-StopSignal detecta e consome o arquivo-sinal, e que todo
#  teste com Ctrl+Q grava HUB_STOP_FILE ao receber a tecla (senao o hub segue
#  para o proximo teste em vez de parar a fila).
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$raiz    = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$hubPath = Join-Path $raiz "hub.ps1"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Test-StopSignal", "Clear-KeyBuffer") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $hubPath" }
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

Write-Host "Test-StopSignal"
$sinal = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest_parada_$([guid]::NewGuid().ToString('N')).flag"
try {
    Assert-Condition (-not (Test-StopSignal -StopFile $sinal)) "sem arquivo-sinal: a fila continua"
    Assert-Condition (-not (Test-StopSignal -StopFile "")) "caminho vazio: a fila continua"
    Set-Content -LiteralPath $sinal -Value "ctrl+q"
    Assert-Condition (Test-StopSignal -StopFile $sinal) "com arquivo-sinal: a fila para"
    Assert-Condition (-not (Test-Path -LiteralPath $sinal)) "o arquivo-sinal e consumido"
    Assert-Condition (-not (Test-StopSignal -StopFile $sinal)) "depois de consumido, nao dispara de novo"
} finally {
    Remove-Item -LiteralPath $sinal -Force -ErrorAction SilentlyContinue
}

Write-Host "Testes com Ctrl+Q sinalizam o hub"
$comCtrlQ = @(Get-ChildItem -Path (Join-Path $raiz "Testes") -Recurse -Filter *.py |
    Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match "def _on_key_press|def _iniciar_ctrl_q" })
Assert-Condition ($comCtrlQ.Count -ge 5) "encontrados $($comCtrlQ.Count) arquivo(s) com listener de Ctrl+Q"
foreach ($f in $comCtrlQ) {
    $txt = Get-Content -LiteralPath $f.FullName -Raw
    $rel = $f.FullName.Substring($raiz.Length + 1)
    $ok = ($txt -match 'os\.environ\.get\("HUB_STOP_FILE"\)') -and
          ([regex]::Matches($txt, "_sinalizar_parada_hub\(\)").Count -ge 2)
    Assert-Condition $ok "$rel grava HUB_STOP_FILE no Ctrl+Q"
}

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
