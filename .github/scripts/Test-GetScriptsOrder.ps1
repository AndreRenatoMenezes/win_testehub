# =============================================================================
#  Teste de regressao: Get-Scripts (hub.ps1)
#
#  Garante a ordenacao natural do menu ("10_" depois de "9_") e que a
#  bibliotecas da pasta _lib (dev_cargas.py, rede_calc.py, hub_progress.py, live_monitor.py) nao viram item do menu.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Extrai so as funcoes necessarias do hub.ps1 (carregar o script inteiro executaria o hub)
$hubPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..\hub.ps1")).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "Get-NaturalSortKey", "Get-Scripts") {
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

function New-Tree {
    param([string[]]$RelPaths)
    $root = Join-Path ([System.IO.Path]::GetTempPath()) "hubtest_order_$([guid]::NewGuid().ToString('N'))"
    foreach ($rel in $RelPaths) {
        $path = Join-Path $root $rel
        New-Item -ItemType Directory -Path (Split-Path $path) -Force | Out-Null
        Set-Content -Path $path -Value "# teste" -Encoding UTF8
    }
    return $root
}

Write-Host "`n[Testes/] ordenacao natural e exclusoes"
$testes = New-Tree @(
    "0_consumo_basal/0_teste_consumo_basal.py",
    "1_cpu_memo/1_automacao_performance.py",
    "1_cpu_memo/1-1_automacao_performance_dlp.py",
    "2_disco/2_teste_disco.py",
    "3_rede/3_teste_rede.py",
    "4_boot_shutdown/4_boot_shutdown_auto.py",
    "4_boot_shutdown/boot_shutdown_duration.ps1",
    "6_wifi_fast_transition/6_teste_fast_transition.py",
    "7_dev_dotnet/7_dev_dotnet.py",
    "8_dev_go/8_dev_go.py",
    "9_dev_python/9_dev_python.py",
    "10_dev_containers/10_dev_containers.py",
    "11_dev_git_arquivos/11_dev_git_arquivos.py",
    "_lib/dev_cargas.py",
    "_lib/rede_calc.py",
    "_lib/hub_progress.py",
    "_lib/live_monitor.py"
)
try {
    $nomes = @((Get-Scripts -Root $testes -Kind "test") | ForEach-Object { $_.Name })
    $esperado = @(
        # Mesma ordem de antes para os modulos 0 a 6 (o hub usa comparacao cultural: "1_" antes de "1-1_")
        "0_teste_consumo_basal", "1_automacao_performance", "1-1_automacao_performance_dlp", "2_teste_disco", "3_teste_rede",
        "4_boot_shutdown_auto", "6_teste_fast_transition", "7_dev_dotnet", "8_dev_go",
        "9_dev_python", "10_dev_containers", "11_dev_git_arquivos"
    )
    Assert-Condition (($nomes -join ",") -eq ($esperado -join ",")) "ordem: $($nomes -join ', ')"
    Assert-Condition (-not ($nomes -contains "dev_cargas")) "dev_cargas.py fora do menu"
    Assert-Condition (-not ($nomes -contains "rede_calc")) "rede_calc.py (biblioteca do teste 3) fora do menu"
    Assert-Condition (-not ($nomes -contains "hub_progress")) "hub_progress.py (protocolo do monitor ao vivo) fora do menu"
    Assert-Condition (-not ($nomes -contains "live_monitor")) "live_monitor.py (TUI do monitor ao vivo) fora do menu"
    Assert-Condition (-not ($nomes -contains "boot_shutdown_duration")) "boot_shutdown_duration.ps1 continua fora do menu"
} finally {
    Remove-Item $testes -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "`n[Setup/] ordenacao natural"
$setup = New-Tree @(
    "environment/12_remover_appx_bloatware.ps1",
    "environment/13_remover_onedrive.ps1",
    "environment/1_captura_infos_pc.ps1",
    "environment/2_opcoes_energia.ps1",
    "environment/7_install_devtools_dev.ps1",
    "environment/10_preparar_podman.ps1",
    "environment/11_ca_corporativa_dev.ps1",
    "environment/9_AdicionarTecladoUSInt.ps1"
)
try {
    $nomes = @((Get-Scripts -Root $setup -Kind "setup") | ForEach-Object { $_.Name })
    $esperado = @(
        "1_captura_infos_pc", "2_opcoes_energia", "7_install_devtools_dev", "9_AdicionarTecladoUSInt",
        "10_preparar_podman", "11_ca_corporativa_dev", "12_remover_appx_bloatware", "13_remover_onedrive"
    )
    Assert-Condition (($nomes -join ",") -eq ($esperado -join ",")) "ordem: $($nomes -join ', ')"
} finally {
    Remove-Item $setup -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
