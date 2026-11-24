# =============================================================================
#  Teste de regressao: Export-ScenarioTraces (hub.ps1)
#
#  Garante que a pasta Exportar/<cenario>/<modelo> - <patrimonio> recebe o
#  conteudo de Traces/ sem .etl, sem logs (.log e pastas logs/) e sem pastas
#  vazias; que Traces/ nao e alterada; e que a etapa e idempotente.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
#  Fica fora de Setup/ e Testes/ para nao aparecer no menu do hub.
# =============================================================================
param([string]$HubPath = (Join-Path $PSScriptRoot "..\..\hub.ps1"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Extrai so as funcoes necessarias do hub.ps1 (carregar o script inteiro executaria o hub)
$hubPath = (Resolve-Path $HubPath).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
foreach ($nome in "ConvertTo-SafeFolderName", "Get-StateField", "Get-ExportPath", "Export-ScenarioTraces",
                "Request-ExportZip", "Compress-And-Validate") {
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $nome
    }, $true) | Select-Object -First 1
    if (-not $fn) { throw "Funcao $nome nao encontrada em $hubPath" }
    . ([scriptblock]::Create($fn.Extent.Text))
}
function Write-Host { }   # silencia o console das funcoes testadas
$script:answers = [System.Collections.Queue]::new()
function Read-Host { param($Prompt) if ($script:answers.Count) { $script:answers.Dequeue() } else { "N" } }

$script:falhas = 0
function Assert-Condition {
    param([bool]$Condition, [string]$Description)
    if ($Condition) {
        Microsoft.PowerShell.Utility\Write-Host "  OK      $Description" -ForegroundColor Green
    } else {
        Microsoft.PowerShell.Utility\Write-Host "  FALHOU  $Description" -ForegroundColor Red
        $script:falhas++
    }
}

# Listagem relativa (pastas e arquivos com tamanho), ordenada
function Get-Tree {
    param([string]$Root)
    $base = (Resolve-Path -LiteralPath $Root).ProviderPath.TrimEnd('\')
    return @(Get-ChildItem -LiteralPath $Root -Recurse -Force | ForEach-Object {
        $rel = $_.FullName.Substring($base.Length + 1)
        if ($_.PSIsContainer) { "D $rel" } else { "F $rel $($_.Length)" }
    } | Sort-Object)
}

# Caminho com espaco e colchetes de proposito: espaco como nas pastas reais do
# Drive; '[x]' viraria curinga se algum cmdlet usasse -Path em vez de -LiteralPath
# e casaria com a pasta vizinha "... x", que precisa sobreviver intacta.
$guid     = [guid]::NewGuid().ToString('N')
$tmp      = [System.IO.Path]::GetTempPath()
$root     = Join-Path $tmp "hubtest export $guid [x]"
$neighbor = Join-Path $tmp "hubtest export $guid x"
$traces = Join-Path $root "Execucoes\cen_HOST_2026-11-24\Traces"
$exportar = Join-Path $root "Exportar"

$files = [ordered]@{
    "_state.json"                                   = "{}"
    "_relatorio.csv"                                = "r"
    "maquina.csv"                                   = "m"
    "1_cpu_memo\Trace_20261103_Run1.etl"            = ("x" * 4096)
    "1_cpu_memo\automacao_20261103.log"             = "log"
    "1_cpu_memo\cpu_memoria.csv"                    = "cpu"
    "1_cpu_memo\CSV_20261103_Run1\CPU_GLOBAL.csv"   = "g"
    "5_bateria\Trace_Bateria_Ociosa_1.etl"          = ("y" * 2048)
    "5_bateria\CSV_Ociosa_1\BATERIA_DISCO.csv"      = "d"
    "5_bateria\bateria.csv"                         = "b"
    "7_dev_dotnet\dev_dotnet.csv"                   = "n"
    "7_dev_dotnet\logs\A4a-dotnet-build-limpo.log"  = "l"
    "7_dev_dotnet\Logs\extra.txt"                   = "t"
    "2_disco\_anterior\run1_2026\disco.csv"         = "old"
    "2_disco\_anterior\run1_2026\trace.etl"         = "e"
    "2_disco\disco.csv"                             = "new"
    "3_rede\sub\so.log"                             = "s"
    "6_wifi_fast_transition\Trace_Wifi.etl"         = "w"
}
foreach ($rel in $files.Keys) {
    $p = Join-Path $traces $rel
    New-Item -ItemType Directory -Path (Split-Path $p) -Force | Out-Null
    Set-Content -LiteralPath $p -Value $files[$rel] -Encoding ASCII -NoNewline
}
New-Item -ItemType Directory -Path (Join-Path $traces "environment") -Force | Out-Null

$state = [PSCustomObject]@{ scenario = "SDWAN 108.11.4.734 - Stack"; machine = "HOST"; modelo = "3440"; patrimonio = "050221" }
$tracesBefore = (Get-Tree $traces) -join "`n"

$neighborFile = Join-Path $neighbor "Exportar\SDWAN 108.11.4.734 - Stack\3440 - 050221\vizinho.txt"
New-Item -ItemType Directory -Path (Split-Path $neighborFile) -Force | Out-Null
Set-Content -LiteralPath $neighborFile -Value "nao apagar"

try {
    Microsoft.PowerShell.Utility\Write-Host "`nExportacao de um cenario com .etl, logs, _anterior e pastas vazias"
    $r = Export-ScenarioTraces -TraceRunDir $traces -ExportarDir $exportar -State $state
    $expectedDest = Join-Path $exportar "SDWAN 108.11.4.734 - Stack\3440 - 050221"

    Assert-Condition ($null -ne $r) "devolve um resumo"
    Assert-Condition ($r.Path -eq $expectedDest) "destino Exportar/<cenario>/<modelo> - <patrimonio>"
    Assert-Condition (Test-Path -LiteralPath $expectedDest) "pasta de destino criada"

    $out = Get-Tree $expectedDest
    $outText = $out -join "`n"
    Assert-Condition (-not ($outText -match '\.etl')) "nenhum .etl (inclusive em _anterior)"
    Assert-Condition (-not ($outText -match '\.log')) "nenhum .log"
    Assert-Condition (-not ($out | Where-Object { $_ -match '(?i)(^D |\\)logs($|\\)' })) "nenhuma pasta logs/ (qualquer caixa)"
    Assert-Condition (-not ($out | Where-Object { $_ -match '^D (environment|3_rede)' })) "pastas vazias removidas (inclusive as que esvaziaram)"
    foreach ($keep in "_state.json", "_relatorio.csv", "maquina.csv", "1_cpu_memo\cpu_memoria.csv",
                      "1_cpu_memo\CSV_20261103_Run1\CPU_GLOBAL.csv", "5_bateria\CSV_Ociosa_1\BATERIA_DISCO.csv",
                      "5_bateria\bateria.csv", "7_dev_dotnet\dev_dotnet.csv",
                      "2_disco\disco.csv", "2_disco\_anterior\run1_2026\disco.csv") {
        Assert-Condition (Test-Path -LiteralPath (Join-Path $expectedDest $keep)) "mantem $keep"
    }
    Assert-Condition ($r.Files -eq 10) "resumo conta 10 arquivos exportados (obtido: $($r.Files))"
    Assert-Condition ($r.ExcludedEtl -eq 4) "resumo conta 4 .etl fora (obtido: $($r.ExcludedEtl))"
    Assert-Condition ($r.ExcludedFiles -eq 8) "resumo conta 8 arquivos fora (obtido: $($r.ExcludedFiles))"
    $em = (@($r.EmptyModules) | Sort-Object) -join ","
    Assert-Condition ($em -eq "3_rede,6_wifi_fast_transition") "modulos so com .etl/logs avisados; environment (vazia) e modulos com CSV nao (obtido: $em)"
    Assert-Condition (((Get-Tree $traces) -join "`n") -eq $tracesBefore) "Traces/ nao foi alterada"

    Microsoft.PowerShell.Utility\Write-Host "`nIdempotencia: segunda execucao com lixo no destino"
    Set-Content -LiteralPath (Join-Path $expectedDest "lixo.txt") -Value "x"
    $r2 = Export-ScenarioTraces -TraceRunDir $traces -ExportarDir $exportar -State $state
    Assert-Condition ($null -ne $r2) "segunda execucao devolve resumo"
    Assert-Condition (((Get-Tree $expectedDest) -join "`n") -eq $outText) "mesma arvore da primeira execucao, sem sobras"

    Assert-Condition (Test-Path -LiteralPath $neighborFile) "exportacao de outra pasta (curinga '[x]') nao foi apagada"

    Microsoft.PowerShell.Utility\Write-Host "`nZIP da pasta exportada"
    $zipPath = "$expectedDest.zip"
    $script:answers.Enqueue("N")
    Request-ExportZip -ExportPath $expectedDest
    Assert-Condition (-not (Test-Path -LiteralPath $zipPath)) "resposta N nao gera ZIP"
    $script:answers.Enqueue("S")
    Request-ExportZip -ExportPath $expectedDest
    Assert-Condition (Test-Path -LiteralPath $zipPath) "resposta S gera <modelo> - <patrimonio>.zip ao lado da pasta"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $entries = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') } | ForEach-Object { $_.FullName })
    $zip.Dispose()
    Assert-Condition ($entries.Count -eq 10) "ZIP tem os 10 arquivos exportados (obtido: $($entries.Count))"
    Assert-Condition (@($entries | Where-Object { -not $_.StartsWith("3440 - 050221") }).Count -eq 0) "a pasta da maquina e a raiz do ZIP"
    Assert-Condition (Test-Path -LiteralPath $expectedDest) "pasta exportada continua existindo depois do ZIP"
    Assert-Condition (((Get-Tree $traces) -join "`n") -eq $tracesBefore) "Traces/ continua intacta depois do ZIP"

    Microsoft.PowerShell.Utility\Write-Host "`nNova exportacao remove ZIP desatualizado"
    $rz = Export-ScenarioTraces -TraceRunDir $traces -ExportarDir $exportar -State $state
    Assert-Condition ($null -ne $rz -and -not (Test-Path -LiteralPath $zipPath)) "ZIP anterior removido ao regerar"

    Microsoft.PowerShell.Utility\Write-Host "`nTraces inexistente"
    $otherState = [PSCustomObject]@{ scenario = "Outro"; modelo = "M"; patrimonio = "P" }
    $r3 = Export-ScenarioTraces -TraceRunDir (Join-Path $root "naoexiste") -ExportarDir $exportar -State $otherState
    Assert-Condition ($null -eq $r3) "devolve `$null"
    Assert-Condition (-not (Test-Path -LiteralPath (Join-Path $exportar "Outro"))) "nao cria pasta de destino"

    Microsoft.PowerShell.Utility\Write-Host "`nTraces sem nenhum arquivo excluido (StrictMode + soma vazia)"
    $cleanTraces = Join-Path $root "limpo\Traces"
    New-Item -ItemType Directory -Path $cleanTraces -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $cleanTraces "_state.json") -Value "{}"
    $r5 = Export-ScenarioTraces -TraceRunDir $cleanTraces -ExportarDir $exportar -State $otherState
    Assert-Condition ($null -ne $r5 -and $r5.Files -eq 1 -and $r5.ExcludedFiles -eq 0 -and $r5.ExcludedMB -eq 0) "exporta 1 arquivo, 0 excluidos, sem erro"
    Assert-Condition (@($r5.EmptyModules).Count -eq 0) "sem modulos vazios quando nada e excluido"

    Microsoft.PowerShell.Utility\Write-Host "`nTraces vazia"
    $emptyTraces = Join-Path $root "vazio\Traces"
    New-Item -ItemType Directory -Path $emptyTraces -Force | Out-Null
    $r6 = Export-ScenarioTraces -TraceRunDir $emptyTraces -ExportarDir $exportar -State $otherState
    Assert-Condition ($null -ne $r6 -and $r6.Files -eq 0 -and $r6.SizeMB -eq 0) "exporta 0 arquivos sem erro"

    Microsoft.PowerShell.Utility\Write-Host "`nDestino sempre dentro de Exportar"
    $evil = [PSCustomObject]@{ scenario = "..\.."; modelo = ""; patrimonio = "\..\.." }
    $p = Get-ExportPath -ExportarDir $exportar -State $evil
    $full = [System.IO.Path]::GetFullPath($p)
    Assert-Condition ($full.StartsWith([System.IO.Path]::GetFullPath($exportar) + "\")) "partes com '..' e '' nao escapam de Exportar ($p)"
    Assert-Condition ((Split-Path $p -Leaf) -eq "SemModelo - SemPatrimonio") "modelo vazio e patrimonio so com '\..' viram padrao"

    Microsoft.PowerShell.Utility\Write-Host "`nArquivo aberto na exportacao anterior"
    $lockFile = Join-Path $expectedDest "_state.json"
    $fs = [System.IO.File]::Open($lockFile, 'Open', 'Read', 'None')
    try {
        $r7 = Export-ScenarioTraces -TraceRunDir $traces -ExportarDir $exportar -State $state
    } finally { $fs.Dispose() }
    Assert-Condition ($null -eq $r7) "devolve `$null em vez de misturar exportacao antiga e nova"

    Microsoft.PowerShell.Utility\Write-Host "`nFalha do robocopy (exit >= 8)"
    function robocopy.exe { $global:LASTEXITCODE = 8 }   # funcao tem precedencia sobre o .exe
    $r4 = Export-ScenarioTraces -TraceRunDir $traces -ExportarDir $exportar -State $state
    Remove-Item Function:\robocopy.exe
    Assert-Condition ($null -eq $r4) "devolve `$null"
    Assert-Condition (-not (Test-Path -LiteralPath $expectedDest)) "nao deixa pasta parcial"
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $neighbor -Recurse -Force -ErrorAction SilentlyContinue
}

Microsoft.PowerShell.Utility\Write-Host ""
if ($script:falhas -gt 0) {
    Microsoft.PowerShell.Utility\Write-Host "$($script:falhas) verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Microsoft.PowerShell.Utility\Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
