# =============================================================================
#  Teste de regressao: Test-ThematicCSVs (hub.ps1)
#
#  Garante que a verificacao de CSVs tematicos acha os CSVs dos modulos e das
#  variantes DLP/USB em Traces/, avisa quando um teste rodou sem gerar o CSV
#  e nao copia nada para fora de Traces/.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
#  Fica fora de Setup/ e Testes/ para nao aparecer no menu do hub.
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Extrai so as funcoes necessarias do hub.ps1 (carregar o script inteiro executaria o hub)
$hubPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..\hub.ps1")).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Get-NaturalSortKey", "Test-ThematicCSVs") {
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

# Cria um cenario falso (chaves = caminho relativo em Traces; valor $null = pasta vazia),
# roda a verificacao e devolve resultado, log e listagem de Traces antes/depois.
function Invoke-Scenario {
    param([string]$Name, [hashtable]$TraceFiles)
    $root = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest_${Name}_$([guid]::NewGuid().ToString('N'))"
    $traces = Join-Path $root "Traces"
    New-Item -ItemType Directory -Path $traces -Force | Out-Null
    foreach ($rel in $TraceFiles.Keys) {
        $path = Join-Path $traces $rel
        if ($null -eq $TraceFiles[$rel]) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        } else {
            New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
            Set-Content -Path $path -Value $TraceFiles[$rel] -Encoding UTF8
        }
    }
    $log = Join-Path $root "run.log"
    Set-Content -Path $log -Value "" -Encoding UTF8
    $before = @(Get-ChildItem -Path $root -Recurse | ForEach-Object { $_.FullName }) -join "|"
    $res = Test-ThematicCSVs -TraceRunDir $traces -LogFile $log
    $after = @(Get-ChildItem -Path $root -Recurse | ForEach-Object { $_.FullName }) -join "|"
    $out = [PSCustomObject]@{
        Result    = $res
        Log       = (Get-Content $log -Raw)
        Unchanged = ($before -eq $after)
    }
    Remove-Item -Path $root -Recurse -Force
    return $out
}

Write-Host "`nCenario 1: Modulo 0, Modulo 1, variante 1-1 e variante 2-1 na mesma execucao"
$r = Invoke-Scenario -Name "todos" -TraceFiles @{
    "0_consumo_basal\consumo_basal.csv"      = "modulo0"
    "1_cpu_memo\cpu_memoria.csv"             = "modulo1"
    "1_cpu_memo\dlp_usb\cpu_memoria_dlp.csv" = "dlp"
    "2_disco\disco_usb.csv"                  = "usb"
}
Assert-Condition ($r.Result.Found -eq 4) "4 CSVs encontrados (modulo 0 + modulo 1 + as duas variantes)"
Assert-Condition ($r.Result.Missing -eq 1) "disco.csv ausente com 2_disco executado conta como ausente"
Assert-Condition ($r.Log -match "\[AVISO\] CSV tematico 'disco.csv' nao gerado") "aviso de disco.csv no log"
Assert-Condition $r.Unchanged "nenhum arquivo criado ou copiado"

Write-Host "`nCenario 2: modulos de dev (7-11)"
$r = Invoke-Scenario -Name "dev" -TraceFiles @{
    "7_dev_dotnet\dev_dotnet.csv"               = "a"
    "8_dev_go\dev_go.csv"                       = "b"
    "9_dev_python\dev_python.csv"               = "c"
    "10_dev_containers\dev_containers.csv"      = "d"
    "11_dev_git_arquivos\dev_git_arquivos.csv"  = "e"
}
Assert-Condition ($r.Result.Found -eq 5 -and $r.Result.Missing -eq 0) "os 5 CSVs de dev encontrados, sem ausentes"

Write-Host "`nCenario 3: teste executado sem CSV e teste nao executado"
$r = Invoke-Scenario -Name "ausente" -TraceFiles @{
    "5_bateria" = $null
}
Assert-Condition ($r.Result.Found -eq 0 -and $r.Result.Missing -eq 1) "bateria.csv ausente conta 1"
Assert-Condition ($r.Log -match "\[AVISO\] CSV tematico 'bateria.csv'") "aviso de bateria.csv no log"
Assert-Condition ($r.Log -match "\[INFO\] CSV tematico 'consumo_basal.csv' pendente") "modulo 0 nao executado fica como INFO"
Assert-Condition ($r.Log -match "\[INFO\] CSV tematico 'cpu_memoria.csv' pendente") "modulo nao executado fica como INFO"

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
