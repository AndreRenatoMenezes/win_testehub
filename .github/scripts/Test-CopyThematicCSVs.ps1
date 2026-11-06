# =============================================================================
#  Teste de regressao: Copy-ThematicCSVs (hub.ps1)
#
#  Garante que os CSVs tematicos e os das variantes DLP/USB chegam a
#  Resultados/ com nomes proprios, sem que um teste passe pelo outro.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
#  Fica fora de Setup/ e Testes/ para nao aparecer no menu do hub.
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Extrai so a funcao do hub.ps1 (carregar o script inteiro executaria o hub)
$hubPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..\hub.ps1")).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
$fn = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "Copy-ThematicCSVs"
}, $true) | Select-Object -First 1
if (-not $fn) { throw "Funcao Copy-ThematicCSVs nao encontrada em $hubPath" }
. ([scriptblock]::Create($fn.Extent.Text))

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

# Cria um cenario falso: chaves = caminho relativo em Traces, valores = conteudo
function Invoke-Scenario {
    param([string]$Name, [hashtable]$TraceFiles)
    $root = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest_${Name}_$([guid]::NewGuid().ToString('N'))"
    $traces = Join-Path $root "Traces"
    $resultados = Join-Path $root "Resultados"
    New-Item -ItemType Directory -Path $traces, $resultados -Force | Out-Null
    foreach ($rel in $TraceFiles.Keys) {
        $path = Join-Path $traces $rel
        New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
        Set-Content -Path $path -Value $TraceFiles[$rel] -Encoding UTF8
    }
    $log = Join-Path $root "run.log"
    Copy-ThematicCSVs -TraceRunDir $traces -ResultadosDir $resultados -LogFile $log | Out-Null
    return $resultados
}

function Get-ResultContent {
    param([string]$Dir, [string]$Name)
    $path = Join-Path $Dir $Name
    if (-not (Test-Path $path)) { return $null }
    return (Get-Content $path -Raw).Trim()
}

function Get-ResultNames {
    param([string]$Dir)
    return @(Get-ChildItem -Path $Dir -File | Sort-Object Name | ForEach-Object { $_.Name })
}

Write-Host "`nCenario 1: Modulo 1, variante 1-1 e variante 2-1 na mesma execucao"
$r = Invoke-Scenario -Name "todos" -TraceFiles @{
    "1_cpu_memo\cpu_memoria.csv"             = "modulo1"
    "1_cpu_memo\dlp_usb\cpu_memoria_dlp.csv" = "dlp"
    "2_disco\disco_usb.csv"                  = "usb"
}
Assert-Condition ((Get-ResultContent $r "cpu_memoria.csv") -eq "modulo1") "cpu_memoria.csv e o do Modulo 1"
Assert-Condition ((Get-ResultContent $r "cpu_memoria_dlp.csv") -eq "dlp") "cpu_memoria_dlp.csv e o da variante 1-1"
Assert-Condition ((Get-ResultContent $r "disco_usb.csv") -eq "usb") "disco_usb.csv e o da variante 2-1"
Assert-Condition (((Get-ResultNames $r) -join ",") -eq "cpu_memoria.csv,cpu_memoria_dlp.csv,disco_usb.csv") "nenhum arquivo extra em Resultados"

Write-Host "`nCenario 2: so a variante 1-1 rodou"
$r = Invoke-Scenario -Name "so_dlp" -TraceFiles @{
    "1_cpu_memo\dlp_usb\cpu_memoria_dlp.csv" = "dlp"
}
Assert-Condition ($null -eq (Get-ResultContent $r "cpu_memoria.csv")) "a variante nao aparece como cpu_memoria.csv do Modulo 1"
Assert-Condition ((Get-ResultContent $r "cpu_memoria_dlp.csv") -eq "dlp") "cpu_memoria_dlp.csv copiado"

Write-Host "`nCenario 3: sem variantes"
$r = Invoke-Scenario -Name "sem_variantes" -TraceFiles @{
    "1_cpu_memo\cpu_memoria.csv" = "modulo1"
}
Assert-Condition (((Get-ResultNames $r) -join ",") -eq "cpu_memoria.csv") "so o CSV do Modulo 1, sem erro pelas variantes ausentes"

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
