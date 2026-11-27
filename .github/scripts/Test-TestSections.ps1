# =============================================================================
#  Teste de regressao: secoes do menu da Fase 2 (hub.ps1, spec 003)
#
#  Agrupamento Escritorio / Dev / Opcional por nome do script, fallback de
#  script novo, pre-selecao (cenario novo e continuacao), tecla P (Fase 2 x
#  Fase 1), alternancia de secao, ordem da fila e config.json sem TestSections.
#  Executado pelo CI no Windows PowerShell 5.1 (runtime do hub).
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Extrai so as funcoes necessarias do hub.ps1 (carregar o script inteiro executaria o hub)
$hubPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..\hub.ps1")).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile($hubPath, [ref]$null, [ref]$null)
$funcoes = "Get-NaturalSortKey", "Get-DefaultTestSections", "Get-TestSectionsConfig", "Resolve-TestSection",
    "ConvertTo-AsciiText", "Build-MenuItems", "Get-SectionSelectionState", "Invoke-ToggleSectionSelection",
    "Invoke-SelectPendingItems"
foreach ($nome in $funcoes) {
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

# Scripts como Get-Scripts devolve (ordenacao natural global)
function New-ScriptList {
    param([string[]]$RelPaths)
    $list = [System.Collections.Generic.List[PSCustomObject]]::new()
    foreach ($rel in ($RelPaths | Sort-Object { Get-NaturalSortKey (Split-Path $_ -Leaf) })) {
        $folder = Split-Path $rel -Parent
        $leaf   = Split-Path $rel -Leaf
        $list.Add([PSCustomObject]@{
            Display      = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
            Name         = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
            Path         = "C:\hub\Testes\$rel"
            Type         = [System.IO.Path]::GetExtension($leaf).TrimStart('.')
            Kind         = "test"
            ParentFolder = $folder
            Selected     = $false
        })
    }
    return ,$list
}

function Get-TestNames {
    param($Items, [string]$SectionId = "")
    return @($Items | Where-Object { $_.IsTestItem -and ($SectionId -eq "" -or $_.SectionId -eq $SectionId) } | ForEach-Object { $_.Name })
}

function Get-SelectedNames {
    param($Items)
    return @($Items | Where-Object { $_.IsTestItem -and $_.Selected } | ForEach-Object { $_.Name })
}

function New-Prev {
    param([string[]]$FileNames)
    $h = @{}
    foreach ($f in $FileNames) { $h[$f] = [PSCustomObject]@{ status = "PASS"; duration = 10.0; runId = 1 } }
    return $h
}

$reais = @(
    "0_consumo_basal\0_teste_consumo_basal.py",
    "1_cpu_memo\1_automacao_performance.py",
    "1_cpu_memo\1-1_automacao_performance_dlp.py",
    "2_disco\2_teste_disco.py",
    "2_disco\2-1_teste_disco_dlp.py",
    "3_rede\3_teste_rede.py",
    "4_boot_shutdown\4_boot_shutdown_auto.py",
    "5_bateria\5_teste_bateria.py",
    "6_wifi_fast_transition\6_teste_fast_transition.py",
    "7_dev_dotnet\7_dev_dotnet.py",
    "8_dev_go\8_dev_go.py",
    "9_dev_python\9_dev_python.py",
    "10_dev_containers\10_dev_containers.py",
    "11_dev_git_arquivos\11_dev_git_arquivos.py"
)
$escritorio = @("0_teste_consumo_basal", "1_automacao_performance", "2_teste_disco", "3_teste_rede", "4_boot_shutdown_auto", "5_teste_bateria")
$dev        = @("7_dev_dotnet", "8_dev_go", "9_dev_python", "10_dev_containers", "11_dev_git_arquivos")
$opcional   = @("1-1_automacao_performance_dlp", "2-1_teste_disco_dlp", "6_teste_fast_transition")

$secoes = @(Get-DefaultTestSections)

# --- 1. Agrupamento dos 14 scripts reais -------------------------------------
Write-Host "`n[1] agrupamento 6/5/3 e cabecalhos"
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults @{} -TestSections $secoes
$headers = @($items | Where-Object { $_.IsSectionHeader })
Assert-Condition ($headers.Count -eq 3) "3 cabecalhos de secao"
Assert-Condition ((@($headers | ForEach-Object { $_.SectionId }) -join ",") -eq "escritorio,dev,opcional") "ordem dos cabecalhos: escritorio, dev, opcional"
Assert-Condition ((@($headers | ForEach-Object { $_.SectionKey }) -join ",") -eq "1,2,3") "atalhos 1, 2, 3"
Assert-Condition (@($items | Where-Object { $_.IsSeparator }).Count -eq 0) "sem separadores por pasta na Fase 2"
Assert-Condition (@($headers | Where-Object { $_.IsTestItem }).Count -eq 0) "cabecalho nao e item de teste"
Assert-Condition (@($headers | Where-Object { -not $_.Selectable }).Count -eq 0) "cabecalho recebe foco (Selectable)"
Assert-Condition ((Get-TestNames $items "escritorio") -join "," -eq ($escritorio -join ",")) "Escritorio = 0..5 (6)"
Assert-Condition ((Get-TestNames $items "dev") -join "," -eq ($dev -join ",")) "Dev = 7..11 (5), ordem natural"
Assert-Condition ((Get-TestNames $items "opcional") -join "," -eq ($opcional -join ",")) "Opcional = 1-1, 2-1, 6 (3)"
Assert-Condition (@(Get-TestNames $items).Count -eq 14) "14 itens de teste no total"
Assert-Condition ($items[0].IsSectionHeader -and $items[0].SectionId -eq "escritorio") "menu abre no cabecalho de Escritorio"
Assert-Condition (@($items | Where-Object { $_.Name -eq "0_teste_consumo_basal" })[0].SectionLabel -eq "Escritorio") "item de teste carrega SectionLabel (Escritorio)"
Assert-Condition (@($items | Where-Object { $_.Name -eq "7_dev_dotnet" })[0].SectionLabel -eq "Dev") "item de teste carrega SectionLabel (Dev)"
Assert-Condition (@($items | Where-Object { $_.Name -eq "6_teste_fast_transition" })[0].SectionLabel -eq "Opcional") "item de teste carrega SectionLabel (Opcional)"

# --- 2. Script novo nao mapeado ----------------------------------------------
Write-Host "`n[2] script novo cai em Opcional (desmarcado)"
$items = Build-MenuItems -Scripts (New-ScriptList ($reais + "12_gpu\12_gpu_bench.py")) -PreviousResults @{} -TestSections $secoes
$gpu = @($items | Where-Object { $_.Name -eq "12_gpu_bench" })
Assert-Condition ($gpu.Count -eq 1 -and $gpu[0].SectionId -eq "opcional") "12_gpu_bench na secao opcional"
Assert-Condition ($gpu.Count -eq 1 -and -not $gpu[0].Selected) "12_gpu_bench desmarcado"
Assert-Condition (@(Get-TestNames $items "opcional")[-1] -eq "12_gpu_bench") "12_gpu_bench depois do 6 (ordem natural)"
$semFallback = @(Get-DefaultTestSections | ForEach-Object { $_.Fallback = $false; $_ })
Assert-Condition ((Resolve-TestSection -ScriptName "12_gpu_bench" -Sections $semFallback).Id -eq "opcional") "sem Fallback: vai para a ultima secao"
Assert-Condition ((Resolve-TestSection -ScriptName "7_DEV_DOTNET" -Sections $secoes).Id -eq "dev") "casamento case-insensitive"

# --- 3. Duplicata no config ---------------------------------------------------
Write-Host "`n[3] script em duas secoes: a primeira vence"
$dup = @(Get-DefaultTestSections)
$dup[1].Scripts = @($dup[1].Scripts) + "3_teste_rede"
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults @{} -TestSections $dup
$rede = @($items | Where-Object { $_.Name -eq "3_teste_rede" })
Assert-Condition ($rede.Count -eq 1) "3_teste_rede aparece uma vez"
Assert-Condition ($rede.Count -eq 1 -and $rede[0].SectionId -eq "escritorio") "3_teste_rede fica em Escritorio"

# --- 4. Cenario novo ----------------------------------------------------------
Write-Host "`n[4] cenario novo: so Escritorio marcado"
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults @{} -TestSections $secoes
Assert-Condition ((Get-SelectedNames $items) -join "," -eq ($escritorio -join ",")) "6 de Escritorio marcados, Dev/Opcional nao"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "escritorio").Box -eq "[X]") "Escritorio [X]"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "dev").Box -eq "[ ]") "Dev [ ]"
$st = Get-SectionSelectionState -Items $items -SectionId "escritorio"
Assert-Condition ($st.SelectedCount -eq 6 -and $st.TotalCount -eq 6) "contador Escritorio 6/6"

# --- 5. Continuacao de cenario ------------------------------------------------
Write-Host "`n[5] continuacao: so pendentes de Escritorio"
$prev = New-Prev @("0_teste_consumo_basal.py", "1_automacao_performance.py", "7_dev_dotnet.py")
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults $prev -TestSections $secoes
Assert-Condition ((Get-SelectedNames $items) -join "," -eq "2_teste_disco,3_teste_rede,4_boot_shutdown_auto,5_teste_bateria") "pendentes de Escritorio marcados (2..5)"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "escritorio").Box -eq "[-]") "Escritorio [-] (parcial)"
$prevTodos = New-Prev ($escritorio | ForEach-Object { "$_.py" })
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults $prevTodos -TestSections $secoes
Assert-Condition (@(Get-SelectedNames $items).Count -eq 0) "Escritorio todo executado: 0 marcados"

# --- 6. Tecla P ---------------------------------------------------------------
Write-Host "`n[6] tecla P: Fase 2 (secoes) x Fase 1 (Setup)"
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults $prev -TestSections $secoes
foreach ($t in @($items | Where-Object { $_.IsTestItem })) { $t.Selected = $true }
Invoke-SelectPendingItems -Items $items -DefaultSectionsOnly
Assert-Condition ((Get-SelectedNames $items) -join "," -eq "2_teste_disco,3_teste_rede,4_boot_shutdown_auto,5_teste_bateria") "P (Fase 2): so pendentes de Escritorio"

$setup = [System.Collections.Generic.List[PSCustomObject]]::new()
foreach ($n in "1_winget", "2_python", "3_drivers") {
    $setup.Add([PSCustomObject]@{ Display = $n; Name = $n; Path = "C:\hub\Setup\environment\$n.ps1"; Type = "ps1"; Kind = "setup"; ParentFolder = "environment"; Selected = $false })
}
$setupPrev = New-Prev @("2_python.ps1")
$sItems = Build-MenuItems -Scripts $setup -PreviousResults $setupPrev
Assert-Condition (@($sItems | Where-Object { $_.IsSeparator }).Count -eq 1) "Fase 1 mantem separador por pasta"
Assert-Condition (@($sItems | Where-Object { $_.IsSectionHeader }).Count -eq 0) "Fase 1 sem cabecalho de secao"
Assert-Condition ((Get-SelectedNames $sItems) -join "," -eq "1_winget,3_drivers") "Fase 1 abre com todos os pendentes marcados"
foreach ($t in @($sItems | Where-Object { $_.IsTestItem })) { $t.Selected = $false }
Invoke-SelectPendingItems -Items $sItems
Assert-Condition ((Get-SelectedNames $sItems) -join "," -eq "1_winget,3_drivers") "P (Fase 1): todos os setups pendentes"
Assert-Condition (@($sItems | Where-Object { $_.IsTestItem -and $_.SectionLabel -ne "" }).Count -eq 0) "Fase 1 com SectionLabel vazio"

# --- 7. Alternancia de secao --------------------------------------------------
Write-Host "`n[7] alternancia de secao e estado [X]/[-]/[ ]"
$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults @{} -TestSections $secoes
Invoke-ToggleSectionSelection -Items $items -SectionId "dev"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "dev").Box -eq "[X]") "Dev: nenhum -> todos [X]"
Invoke-ToggleSectionSelection -Items $items -SectionId "dev"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "dev").Box -eq "[ ]") "Dev: todos -> nenhum [ ]"
@($items | Where-Object { $_.Name -eq "8_dev_go" })[0].Selected = $true
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "dev").Box -eq "[-]") "Dev parcial [-]"
Invoke-ToggleSectionSelection -Items $items -SectionId "dev"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "dev").State -eq "all") "Dev: parcial -> todos"
Assert-Condition ((Get-SectionSelectionState -Items $items -SectionId "escritorio").SelectedCount -eq 6) "alternar Dev nao mexe em Escritorio"

# --- 8. Ordem da fila ---------------------------------------------------------
Write-Host "`n[8] ordem da fila: Escritorio -> Dev -> Opcional"
foreach ($t in @($items | Where-Object { $_.IsTestItem })) { $t.Selected = $true }
$toRun = @($items | Where-Object { $_.IsTestItem -and $_.Selected })
Assert-Condition (($toRun | ForEach-Object { $_.Name }) -join "," -eq (($escritorio + $dev + $opcional) -join ",")) "fila na ordem das secoes"
Assert-Condition (@($toRun | Where-Object { $_.IsSectionHeader }).Count -eq 0) "fila sem cabecalhos"

# --- 9. config.json com e sem TestSections ------------------------------------
Write-Host "`n[9] Get-TestSectionsConfig"
$antigo = '{ "SkipSetup": false, "Paths": { "TestsRoot": "Testes" } }' | ConvertFrom-Json
$cfg = @(Get-TestSectionsConfig -Config $antigo)
Assert-Condition ((@($cfg | ForEach-Object { $_.Id }) -join ",") -eq "escritorio,dev,opcional") "config antigo: fallback padrao"
$vazio = '{ "TestSections": [] }' | ConvertFrom-Json
Assert-Condition (@(Get-TestSectionsConfig -Config $vazio).Count -eq 3) "TestSections vazio: fallback padrao"

$cfgPath = Join-Path $PSScriptRoot "..\..\config.json"
$real = Get-Content -LiteralPath $cfgPath -Encoding UTF8 | ConvertFrom-Json
$cfg = @(Get-TestSectionsConfig -Config $real)
Assert-Condition ($cfg.Count -eq 3) "config.json versionado: 3 secoes"
Assert-Condition ($cfg[0].DefaultSelected -and -not $cfg[1].DefaultSelected -and -not $cfg[2].DefaultSelected) "config.json: so Escritorio DefaultSelected"
Assert-Condition ($cfg[2].Fallback -and -not $cfg[0].Fallback) "config.json: Opcional e o Fallback"
$padrao = @(Get-DefaultTestSections)
$iguais = $true
for ($i = 0; $i -lt 3; $i++) {
    if ($cfg[$i].Id -ne $padrao[$i].Id -or (@($cfg[$i].Scripts) -join ",") -ne (@($padrao[$i].Scripts) -join ",")) { $iguais = $false }
}
Assert-Condition $iguais "config.json e fallback do hub.ps1 com as mesmas secoes e scripts"
Assert-Condition ((ConvertTo-AsciiText $cfg[0].Label) -eq "Escritorio") "rotulo acentuado vira ASCII no console"

$parcial = '{ "TestSections": [ { "Id": "x", "Scripts": ["a"], "DefaultSelected": "true" }, { "Label": "Resto", "Fallback": "sim?" } ] }' | ConvertFrom-Json
$cfg = @(Get-TestSectionsConfig -Config $parcial)
Assert-Condition ($cfg.Count -eq 2 -and $cfg[0].DefaultSelected -and $cfg[0].Key -eq "1" -and $cfg[0].Label -eq "x") "entrada parcial normalizada (Key/Label padrao, DefaultSelected texto)"
Assert-Condition ($cfg[1].Id -eq "secao2" -and -not $cfg[1].Fallback -and @($cfg[1].Scripts).Count -eq 0) "entrada sem Id/Scripts e Fallback invalido"

$items = Build-MenuItems -Scripts (New-ScriptList $reais) -PreviousResults @{} -TestSections @(Get-TestSectionsConfig -Config $parcial)
Assert-Condition (@($items | Where-Object { $_.IsSectionHeader }).Count -eq 1) "secao vazia nao e renderizada"

Write-Host ""
if ($script:falhas -gt 0) {
    Write-Host "$script:falhas verificacao(oes) falharam." -ForegroundColor Red
    exit 1
}
Write-Host "Todas as verificacoes passaram." -ForegroundColor Green
exit 0
