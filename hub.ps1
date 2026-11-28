Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# ---- Carregar Configuracoes (JSON) -------------------------------------------
$configFile = Join-Path $PSScriptRoot "config.json"

function Get-DefaultTestSections {
    return @(
        [PSCustomObject]@{
            Id = "escritorio"; Label = "Escritorio"; Key = "1"; DefaultSelected = $true; Fallback = $false
            Scripts = @("0_teste_consumo_basal", "1_automacao_performance", "2_teste_disco", "3_teste_rede", "4_boot_shutdown_auto", "5_teste_bateria")
        },
        [PSCustomObject]@{
            Id = "dev"; Label = "Dev"; Key = "2"; DefaultSelected = $false; Fallback = $false
            Scripts = @("7_dev_dotnet", "8_dev_go", "9_dev_python", "10_dev_containers", "11_dev_git_arquivos")
        },
        [PSCustomObject]@{
            Id = "opcional"; Label = "Opcional"; Key = "3"; DefaultSelected = $false; Fallback = $true
            Scripts = @("1-1_automacao_performance_dlp", "2-1_teste_disco_dlp", "6_teste_fast_transition")
        }
    )
}

if (-not (Test-Path -LiteralPath $configFile)) {
    Write-Host "  [!] config.json nao encontrado. Criando um com os valores padrao..." -ForegroundColor Yellow
    $defaultConfig = @{
        SkipSetup = $false
        Paths = @{
            SetupRoot     = "Setup"
            TestsRoot     = "Testes"
            ExportarDir   = "Exportar"
            ExecucoesDir  = "Execucoes"
        }
        Settings = @{
            PythonVenvName  = ".venv"
            HtmlReportTitle = "WinTestHub - Relatorio Final"
        }
        Preflight = @{
            MinFreeGB    = 20
            CpuAlertPct  = 10
            InternetHost = "www.msftconnecttest.com"
        }
        CpuSampler = @{
            Enabled          = $true
            IntervalSec      = 5
            ThrottleAlertPct = 20
            LoadMinPct       = 50
            SkipFolders      = @("0_consumo_basal", "5_bateria")
        }
        LiveMonitor = @{
            Enabled              = $true
            RefreshHz            = 1
            LogTailLines         = 8
            TelemetryIntervalSec = 2
            LowImpactFolders     = @("0_consumo_basal", "5_bateria")
        }
        TestSections = @(Get-DefaultTestSections)
    }
    $defaultConfig | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configFile -Encoding UTF8
}

# -Encoding UTF8: o config.json e UTF-8 sem BOM (rotulos acentuados); o padrao do PS 5.1 leria como ANSI
$config = Get-Content -LiteralPath $configFile -Encoding UTF8 | ConvertFrom-Json

$SetupRoot     = Join-Path $PSScriptRoot $config.Paths.SetupRoot
$TestsRoot     = Join-Path $PSScriptRoot $config.Paths.TestsRoot
# ExportarDir: config.json antigo (com ResultadosDir) nao tem a chave -> padrao "Exportar"
$exportarRel   = if ($config.Paths.PSObject.Properties['ExportarDir']) { $config.Paths.ExportarDir } else { "Exportar" }
$ExportarDir   = Join-Path $PSScriptRoot $exportarRel
$ExecucoesDir  = Join-Path $PSScriptRoot $config.Paths.ExecucoesDir
$SkipSetup     = $config.SkipSetup
$VenvPath      = Join-Path $PSScriptRoot $config.Settings.PythonVenvName

# Secoes opcionais do config.json: um config antigo, sem a secao, usa os padroes.
function Merge-ConfigSection {
    param([PSCustomObject]$Config, [string]$Name, [hashtable]$Defaults)
    $merged = New-Object PSObject -Property $Defaults
    $sec = $Config.PSObject.Properties[$Name]
    if ($null -ne $sec -and $null -ne $sec.Value) {
        foreach ($p in $sec.Value.PSObject.Properties) {
            $merged | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force
        }
    }
    return $merged
}
$PreflightSettings  = Merge-ConfigSection $config "Preflight"  @{ MinFreeGB = 20; CpuAlertPct = 10; InternetHost = "www.msftconnecttest.com" }
$CpuSamplerSettings = Merge-ConfigSection $config "CpuSampler" @{ Enabled = $true; IntervalSec = 5; ThrottleAlertPct = 20; LoadMinPct = 50; SkipFolders = @("0_consumo_basal", "5_bateria") }
# "Enabled": "false" (com aspas) tambem desliga
try { $CpuSamplerSettings.Enabled = [System.Convert]::ToBoolean([string]$CpuSamplerSettings.Enabled) } catch { $CpuSamplerSettings.Enabled = $true }
# Monitor ao vivo da Fase 2 (TUI rich, Spec 004). Enabled=false ou .venv sem rich -> painel classico.
$LiveMonitorSettings = Merge-ConfigSection $config "LiveMonitor" @{ Enabled = $true; RefreshHz = 1; LogTailLines = 8; TelemetryIntervalSec = 2; LowImpactFolders = @("0_consumo_basal", "5_bateria") }
try { $LiveMonitorSettings.Enabled = [System.Convert]::ToBoolean([string]$LiveMonitorSettings.Enabled) } catch { $LiveMonitorSettings.Enabled = $true }
$LiveMonitorScript = Join-Path $PSScriptRoot "Testes\_lib\live_monitor.py"

# ---- Secoes do menu da Fase 2 (TestSections) ---------------------------------
# Agrupamento logico por nome do script (sem extensao); as pastas de Testes/ nao mudam.

# Normaliza TestSections do config.json; config antigo (sem a chave) usa o padrao.
function Get-TestSectionsConfig {
    param($Config)
    $prop = $null
    if ($null -ne $Config) { $prop = $Config.PSObject.Properties['TestSections'] }
    if ($null -eq $prop -or $null -eq $prop.Value -or @($prop.Value).Count -eq 0) { return @(Get-DefaultTestSections) }

    $sections = [System.Collections.Generic.List[PSCustomObject]]::new()
    $n = 0
    foreach ($raw in @($prop.Value)) {
        if ($null -eq $raw) { continue }
        $n++
        $vals = @{}
        foreach ($name in "Id", "Label", "Key", "DefaultSelected", "Fallback", "Scripts") {
            $p = $raw.PSObject.Properties[$name]
            $vals[$name] = if ($null -ne $p) { $p.Value } else { $null }
        }
        $id    = if ([string]::IsNullOrWhiteSpace([string]$vals.Id)) { "secao$n" } else { [string]$vals.Id }
        $label = if ([string]::IsNullOrWhiteSpace([string]$vals.Label)) { $id } else { [string]$vals.Label }
        $key   = if ($null -eq $vals.Key) { "$n" } else { [string]$vals.Key }
        $defSel = $false
        if ($null -ne $vals.DefaultSelected) { try { $defSel = [System.Convert]::ToBoolean([string]$vals.DefaultSelected) } catch { $defSel = $false } }
        $fallback = $false
        if ($null -ne $vals.Fallback) { try { $fallback = [System.Convert]::ToBoolean([string]$vals.Fallback) } catch { $fallback = $false } }
        $scripts = @(@($vals.Scripts) | Where-Object { $null -ne $_ -and [string]$_ -ne "" } | ForEach-Object { [string]$_ })
        $sections.Add([PSCustomObject]@{
            Id = $id; Label = $label; Key = $key; DefaultSelected = $defSel; Fallback = $fallback; Scripts = $scripts
        })
    }
    if ($sections.Count -eq 0) { return @(Get-DefaultTestSections) }
    return @($sections)
}

# Secao de um script: primeira secao que o lista (case-insensitive); senao a
# primeira com Fallback; senao a ultima configurada.
function Resolve-TestSection {
    param([string]$ScriptName, [object[]]$Sections)
    foreach ($sec in $Sections) {
        foreach ($s in @($sec.Scripts)) {
            if ([string]::Equals([string]$s, $ScriptName, [System.StringComparison]::OrdinalIgnoreCase)) { return $sec }
        }
    }
    foreach ($sec in $Sections) { if ($sec.Fallback) { return $sec } }
    return @($Sections)[-1]
}

$TestSectionsConfig = Get-TestSectionsConfig -Config $config

# ---- Banner ------------------------------------------------------------------

function Write-Header {
    # Logo WinTestHub (janela + check) em ASCII; arquivos da marca em docs/assets/brand/
    Clear-Host
    Write-Host ""
    Write-Host "   +----------+" -ForegroundColor Gray
    Write-Host "   |==========|   " -ForegroundColor Gray -NoNewline
    Write-Host "Win" -ForegroundColor White -NoNewline
    Write-Host "Test" -ForegroundColor Green -NoNewline
    Write-Host "Hub" -ForegroundColor White
    Write-Host "   |       " -ForegroundColor Gray -NoNewline
    Write-Host "/" -ForegroundColor Green -NoNewline
    Write-Host "  |   " -ForegroundColor Gray -NoNewline
    Write-Host "HARDWARE / TEST / HUB" -ForegroundColor DarkGray
    Write-Host "   |   " -ForegroundColor Gray -NoNewline
    Write-Host "\  /" -ForegroundColor Green -NoNewline
    Write-Host "   |   " -ForegroundColor Gray -NoNewline
    Write-Host ".ps1 + .py  |  multi-select  |  log" -ForegroundColor DarkGray
    Write-Host "   |    " -ForegroundColor Gray -NoNewline
    Write-Host "\/" -ForegroundColor Green -NoNewline
    Write-Host "    |" -ForegroundColor Gray
    Write-Host "   +----------+" -ForegroundColor Gray
    Write-Host ""
}

# ---- Identidade visual dos relatorios HTML -----------------------------------
# Mesmas cores do logo (docs/assets/brand/): grafite #0B0F14 e verde #2E7C35.

$BrandFavicon = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0OCIgaGVpZ2h0PSI0OCIgdmlld0JveD0iMCAwIDQ4IDQ4IiByb2xlPSJpbWciIGFyaWEtbGFiZWw9IldpblRlc3RIdWIiPjx0aXRsZT5XaW5UZXN0SHViPC90aXRsZT48cmVjdCB3aWR0aD0iNDgiIGhlaWdodD0iNDgiIHJ4PSI4LjYiIGZpbGw9IiMwNTA4MEMiLz48ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSg4LjY0IDguNjQpIHNjYWxlKDAuNjQwMDApIiBmaWxsPSJub25lIj48cmVjdCB4PSI0IiB5PSI1IiB3aWR0aD0iNDAiIGhlaWdodD0iMzgiIHJ4PSIyIiBzdHJva2U9IiNFRUVCRTIiIHN0cm9rZS13aWR0aD0iNSIvPjxwYXRoIGQ9Ik0xNC41IDI4IEwyMSAzNC41IEwzMy41IDIxLjUiIHN0cm9rZT0iIzYxQzU2OCIgc3Ryb2tlLXdpZHRoPSI2IiBzdHJva2UtbGluZWNhcD0ic3F1YXJlIi8+PC9nPjwvc3ZnPg==">'
$BrandHeader  = '<svg class="brand-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true"><rect x="4" y="5" width="40" height="38" rx="2" stroke="#0B0F14" stroke-width="2.5"/><line x1="4" y1="13" x2="44" y2="13" stroke="#0B0F14" stroke-width="2.5"/><path d="M14.5 28 L21 34.5 L33.5 21.5" stroke="#2E7C35" stroke-width="3.5" stroke-linecap="square"/></svg>'
$BrandCss = @'
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; color: #0b0f14; margin: 40px; }
            .brand { display: flex; align-items: center; gap: 14px; border-bottom: 2px solid #2e7c35; padding-bottom: 14px; margin-bottom: 24px; }
            .brand-mark { width: 44px; height: 44px; flex: none; }
            .brand-name { font-family: Consolas, 'Courier New', monospace; font-size: 0.75em; letter-spacing: 0.2em; text-transform: uppercase; color: #5b636d; margin-bottom: 4px; }
            .brand-name b { color: #2e7c35; font-weight: normal; }
            h1 { margin: 0; font-size: 1.6em; font-weight: 600; color: #0b0f14; }
            .summary { background: #ffffff; padding: 20px; border-radius: 4px; border: 1px solid #dfe3e8; margin-bottom: 20px; }
            .summary p { margin: 5px 0; font-size: 1.1em; }
            table { width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #dfe3e8; }
            th, td { padding: 12px 15px; border-bottom: 1px solid #dfe3e8; text-align: left; }
            th { background-color: #0b0f14; color: #eeebe2; font-weight: 600; }
            tr:hover { background-color: #f1f3f5; }
            .badge { padding: 5px 10px; border-radius: 999px; font-weight: bold; font-size: 0.9em; color: white; }
            .bg-PASS { background-color: #2e7c35; }
            .bg-FAIL { background-color: #c53030; }
            .bg-ERROR { background-color: #b45309; }
'@

# ---- Descoberta de scripts ---------------------------------------------------

function Get-NaturalSortKey {
    param([string]$Name)
    return [regex]::Replace($Name, '\d+', { param($m) $m.Value.PadLeft(8, '0') })
}

function Get-Scripts {
    param([string]$Root, [string]$Kind)
    $scripts = [System.Collections.Generic.List[PSCustomObject]]::new()

    if (-not (Test-Path -LiteralPath $Root)) {
        Write-Host "  [!] Pasta '$Root' nao encontrada -- criando estrutura..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
    }

    # Ordenacao natural: numeros com zeros a esquerda na chave, para "10_x" vir
    # depois de "9_x" (Sort-Object Name puro colocaria "10_" antes de "1_").
    # dev_cargas.py e a biblioteca comum dos modulos 7 a 11 e rede_calc.py a do
    # teste 3 (pasta _lib): bibliotecas, nao testes.
    # -LiteralPath (colchetes no caminho do hub) + filtro por extensao no lugar do -Include
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { ($_.Extension -eq ".ps1" -or $_.Extension -eq ".py") -and $_.Directory.Name -ne "_lib" -and @("boot_shutdown_duration.ps1", "dev_cargas.py") -notcontains $_.Name } |
        Sort-Object { Get-NaturalSortKey $_.Name }

    foreach ($f in $files) {
        $scripts.Add([PSCustomObject]@{
            Display      = $f.BaseName
            Name         = $f.BaseName
            Path         = $f.FullName
            Type         = $f.Extension.TrimStart('.')
            Kind         = $Kind
            ParentFolder = $f.Directory.Name
            Selected     = $false
        })
    }
    return ,$scripts
}

# ---- State File (persistencia de cenario) ------------------------------------

function Read-StateFile {
    param([string]$TraceRunDir)
    $stateFile = Join-Path $TraceRunDir "_state.json"
    if (Test-Path -LiteralPath $stateFile) {
        try {
            return (Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)
        } catch {
            Write-Host "  [!] State file corrompido: $stateFile" -ForegroundColor Yellow
            return $null
        }
    }
    return $null
}

function Write-StateFile {
    param([string]$TraceRunDir, [PSCustomObject]$State)
    $stateFile = Join-Path $TraceRunDir "_state.json"
    $State | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

function New-StateObject {
    param([string]$Scenario, [string]$Machine, [string]$Modelo, [string]$Patrimonio)
    return [PSCustomObject]@{
        scenario   = $Scenario
        machine    = $Machine
        modelo     = $Modelo
        patrimonio = $Patrimonio
        createdAt  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        lastRunAt  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        runs       = @()
    }
}

# ---- Identificacao da maquina (modelo / patrimonio) --------------------------

# Remove caracteres invalidos em nome de pasta e espacos nas pontas.
# '[' e ']' tambem saem: sao curinga para os cmdlets com -Path do PowerShell.
function ConvertTo-SafeFolderName {
    param([string]$Text)
    if ($null -eq $Text) { return "" }
    $invalid = [System.IO.Path]::GetInvalidFileNameChars() + [char[]]'[]'
    $clean = -join ($Text.ToCharArray() | Where-Object { $invalid -notcontains $_ })
    # Windows nao aceita nome de pasta terminado em ponto ou espaco
    return $clean.Trim().TrimEnd('.', ' ').Trim()
}

# Pergunta um valor obrigatorio (repete enquanto vier vazio apos a limpeza).
function Read-RequiredValue {
    param([string]$Prompt)
    while ($true) {
        $value = ConvertTo-SafeFolderName (Read-Host $Prompt)
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        Write-Host "  [!] Valor obrigatorio." -ForegroundColor Red
    }
}

function Read-MachineIdentity {
    $modelo     = Read-RequiredValue "  >> Modelo da maquina (Ex: 3440, Pro 14 i5)"
    $patrimonio = Read-RequiredValue "  >> Patrimonio/serial (Ex: 050221)"
    return [PSCustomObject]@{ Modelo = $modelo; Patrimonio = $patrimonio }
}

# Le um campo do state sem quebrar no StrictMode quando ele nao existe.
function Get-StateField {
    param([PSCustomObject]$State, [string]$Name)
    $prop = $State.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) { return "" }
    return [string]$prop.Value
}

# Cenarios antigos nao tem modelo/patrimonio: pergunta uma vez e grava no state.
function Ensure-MachineIdentity {
    param([PSCustomObject]$State, [string]$TraceRunDir)
    if ((Get-StateField $State "modelo") -and (Get-StateField $State "patrimonio")) { return $State }

    Write-Host "`n  Este cenario nao tem modelo/patrimonio registrados." -ForegroundColor Yellow
    $id = Read-MachineIdentity
    $State | Add-Member -NotePropertyName modelo     -NotePropertyValue $id.Modelo     -Force
    $State | Add-Member -NotePropertyName patrimonio -NotePropertyValue $id.Patrimonio -Force
    Write-StateFile -TraceRunDir $TraceRunDir -State $State
    return $State
}

function Add-RunToState {
    param([PSCustomObject]$State, [array]$Results)
    $runId = ($State.runs | Measure-Object).Count + 1
    $testEntries = @()
    foreach ($r in $Results) {
        $testEntries += [PSCustomObject]@{
            name       = "$($r.Name).$($r.Type)"
            folder     = $r.TraceDir | Split-Path -Leaf
            kind       = $r.Kind
            status     = $r.Status
            exitCode   = $r.ExitCode
            duration   = [Math]::Round($r.Duration, 3)
            traceCount = $r.TraceCount
        }
    }
    $newRun = [PSCustomObject]@{
        runId     = $runId
        timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        tests     = $testEntries
    }
    $State.lastRunAt = $newRun.timestamp
    $State.runs = @($State.runs) + @($newRun)
    return $State
}

function Get-LatestTestResults {
    param([PSCustomObject]$State)
    $latest = @{}
    foreach ($run in $State.runs) {
        foreach ($t in $run.tests) {
            $latest[$t.name] = [PSCustomObject]@{
                status   = $t.status
                duration = $t.duration
                runId    = $run.runId
                folder   = $t.folder
            }
        }
    }
    return $latest
}

# ---- Selecao de Cenario ------------------------------------------------------

function Get-ExistingScenarios {
    param([string]$ExecucoesDir)
    $scenarios = [System.Collections.Generic.List[PSCustomObject]]::new()
    if (-not (Test-Path -LiteralPath $ExecucoesDir)) { return ,$scenarios }

    $dirs = Get-ChildItem -LiteralPath $ExecucoesDir -Directory -ErrorAction SilentlyContinue
    foreach ($d in $dirs) {
        $tracesSubDir = Join-Path $d.FullName "Traces"
        $state = Read-StateFile -TraceRunDir $tracesSubDir
        if ($null -ne $state) {
            $latest = Get-LatestTestResults -State $state
            $total  = $latest.Count
            $pass   = @($latest.Values | Where-Object { $_.status -eq "PASS" }).Count
            $fail   = @($latest.Values | Where-Object { $_.status -eq "FAIL" }).Count

            $scenarios.Add([PSCustomObject]@{
                Name      = $d.Name
                Path      = $d.FullName
                State     = $state
                LastRunAt = $state.lastRunAt
                Total     = $total
                Pass      = $pass
                Fail      = $fail
            })
        }
    }

    $sorted = $scenarios | Sort-Object { [datetime]$_.LastRunAt } -Descending
    return ,@($sorted | Select-Object -First 5)
}

# Perguntas da criacao de cenario: nome, modelo e patrimonio/serial.
function Read-NewScenario {
    $nome = ConvertTo-SafeFolderName (Read-Host "  >> Nome do cenario (Ex: SDWAN 108.11.4.734 - Stack) [Enter para: Execucao]")
    if ([string]::IsNullOrWhiteSpace($nome)) { $nome = "Execucao" }
    $id = Read-MachineIdentity
    return [PSCustomObject]@{ Mode = "new"; Name = $nome; Modelo = $id.Modelo; Patrimonio = $id.Patrimonio; Path = $null; State = $null }
}

function Show-ScenarioMenu {
    param([string]$ExecucoesDir)
    $scenarios = Get-ExistingScenarios -ExecucoesDir $ExecucoesDir

    if ($scenarios.Count -eq 0) {
        return (Read-NewScenario)
    }

    Write-Host "  Cenarios recentes:" -ForegroundColor Cyan
    Write-Host "  ------------------" -ForegroundColor DarkCyan

    for ($i = 0; $i -lt $scenarios.Count; $i++) {
        $s = $scenarios[$i]
        $idx = $i + 1
        $statusClr = if ($s.Fail -gt 0) { "Yellow" } else { "Green" }
        Write-Host "  $idx. $($s.Name)" -ForegroundColor White
        $summary = "     $($s.Total) teste(s)  |  $($s.Pass) PASS"
        if ($s.Fail -gt 0) { $summary += ", $($s.Fail) FAIL" }
        Write-Host $summary -ForegroundColor $statusClr
    }

    Write-Host ""
    Write-Host "  [N] Criar novo cenario" -ForegroundColor DarkCyan
    Write-Host "  [1-$($scenarios.Count)] Continuar cenario existente" -ForegroundColor DarkCyan
    Write-Host "  [E] Exportar cenario (gerar pasta Exportar / ZIP)" -ForegroundColor DarkCyan
    Write-Host ""

    while ($true) {
        $choice = Read-Host "  >> Escolha"
        if ($choice -eq 'N' -or $choice -eq 'n') {
            return (Read-NewScenario)
        }
        if ($choice -eq 'E' -or $choice -eq 'e') {
            return [PSCustomObject]@{ Mode = "export"; Name = $null; Path = $null; State = $null }
        }
        $num = 0
        if ([int]::TryParse($choice, [ref]$num) -and $num -ge 1 -and $num -le $scenarios.Count) {
            $selected = $scenarios[$num - 1]
            return [PSCustomObject]@{
                Mode  = "continue"
                Name  = $selected.State.scenario
                Path  = $selected.Path
                State = $selected.State
            }
        }
        Write-Host "  [!] Opcao invalida. Tente novamente." -ForegroundColor Red
    }
}

# ---- UI de checkbox ----------------------------------------------------------

function Write-PaddedLine {
    param([string]$Text = "", [string]$Color = "White", [int]$Width)
    $padded = $Text.PadRight($Width - 1).Substring(0, $Width - 1)
    Write-Host $padded -ForegroundColor $Color
}

# Rotulo vindo do config.json (pode ter acento) em ASCII para o console CP850.
function ConvertTo-AsciiText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return "" }
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $Text.Normalize([System.Text.NormalizationForm]::FormD).ToCharArray()) {
        if ([System.Globalization.CharUnicodeInfo]::GetUnicodeCategory($ch) -eq [System.Globalization.UnicodeCategory]::NonSpacingMark) { continue }
        if ([int]$ch -lt 128) { [void]$sb.Append($ch) } else { [void]$sb.Append('?') }
    }
    return $sb.ToString()
}

# Sem -TestSections (Fase 1, Setup/): separadores por pasta e todos os pendentes
# marcados. Com -TestSections (Fase 2, Testes/): cabecalhos de secao na ordem
# declarada, ordenacao natural dentro da secao e so os pendentes das secoes
# DefaultSelected marcados.
function Build-MenuItems {
    param(
        [System.Collections.Generic.List[PSCustomObject]]$Scripts,
        [hashtable]$PreviousResults,
        [object[]]$TestSections
    )
    $items = [System.Collections.Generic.List[PSCustomObject]]::new()

    function New-ScriptMenuItem {
        param($Script, [string]$SectionId, [string]$SectionLabel, [bool]$DefaultSelected)
        $fileName = "$($Script.Name).$($Script.Type)"
        $prev = if ($null -ne $PreviousResults -and $PreviousResults.ContainsKey($fileName)) { $PreviousResults[$fileName] } else { $null }
        return [PSCustomObject]@{
            IsSeparator     = $false
            IsSectionHeader = $false
            IsTestItem      = $true
            Display         = $Script.Display
            Name            = $Script.Name
            Path            = $Script.Path
            Type            = $Script.Type
            Kind            = $Script.Kind
            ParentFolder    = $Script.ParentFolder
            SectionId       = $SectionId
            SectionLabel    = $SectionLabel
            SectionKey      = ""
            DefaultSelected = $DefaultSelected
            Selected        = ($DefaultSelected -and $null -eq $prev)
            Selectable      = $true
            PrevStatus      = if ($prev) { $prev.status } else { $null }
            PrevDuration    = if ($prev) { $prev.duration } else { 0 }
            PrevRunId       = if ($prev) { $prev.runId } else { 0 }
        }
    }

    if ($null -eq $TestSections -or @($TestSections).Count -eq 0) {
        $lastFolder = ""
        foreach ($s in $Scripts) {
            if ($s.ParentFolder -ne $lastFolder) {
                $label = ($s.ParentFolder -replace '^\d+_', '' -replace '_', ' ')
                $label = (Get-Culture).TextInfo.ToTitleCase($label)
                $items.Add([PSCustomObject]@{
                    IsSeparator     = $true
                    IsSectionHeader = $false
                    IsTestItem      = $false
                    Display         = $label
                    Name            = ""
                    SectionId       = ""
                    SectionLabel    = ""
                    SectionKey      = ""
                    DefaultSelected = $false
                    Selected        = $false
                    Selectable      = $false
                    PrevStatus      = $null
                    PrevDuration    = 0
                    PrevRunId       = 0
                })
                $lastFolder = $s.ParentFolder
            }
            $items.Add((New-ScriptMenuItem -Script $s -SectionId "" -SectionLabel "" -DefaultSelected $true))
        }
        return ,$items
    }

    # Baldes por secao, na ordem declarada (Id repetido: vale a primeira)
    $order   = [System.Collections.Generic.List[PSCustomObject]]::new()
    $buckets = @{}
    foreach ($sec in $TestSections) {
        if ($buckets.ContainsKey($sec.Id)) { continue }
        $buckets[$sec.Id] = [System.Collections.Generic.List[PSCustomObject]]::new()
        $order.Add($sec)
    }
    foreach ($s in $Scripts) {
        $sec = Resolve-TestSection -ScriptName $s.Name -Sections @($order)
        $buckets[$sec.Id].Add($s)
    }

    foreach ($sec in $order) {
        $bucket = $buckets[$sec.Id]
        if ($bucket.Count -eq 0) { continue }   # secao vazia nao aparece
        $secLabel = ConvertTo-AsciiText $sec.Label
        $items.Add([PSCustomObject]@{
            IsSeparator     = $false
            IsSectionHeader = $true
            IsTestItem      = $false
            Display         = $secLabel
            Name            = ""
            SectionId       = $sec.Id
            SectionLabel    = $secLabel
            SectionKey      = [string]$sec.Key
            DefaultSelected = [bool]$sec.DefaultSelected
            Selected        = $false
            Selectable      = $true
            PrevStatus      = $null
            PrevDuration    = 0
            PrevRunId       = 0
        })
        foreach ($s in @($bucket | Sort-Object { Get-NaturalSortKey $_.Name })) {
            $items.Add((New-ScriptMenuItem -Script $s -SectionId $sec.Id -SectionLabel $secLabel -DefaultSelected ([bool]$sec.DefaultSelected)))
        }
    }
    return ,$items
}

# Estado agregado de uma secao: [X] todos, [-] parte, [ ] nenhum.
function Get-SectionSelectionState {
    param([System.Collections.Generic.List[PSCustomObject]]$Items, [string]$SectionId)
    $tests = @($Items | Where-Object { $_.IsTestItem -and $_.SectionId -eq $SectionId })
    $sel   = @($tests | Where-Object { $_.Selected }).Count
    if ($tests.Count -gt 0 -and $sel -eq $tests.Count) { $state = "all"; $box = "[X]" }
    elseif ($sel -gt 0) { $state = "partial"; $box = "[-]" }
    else { $state = "none"; $box = "[ ]" }
    return [PSCustomObject]@{ SelectedCount = $sel; TotalCount = $tests.Count; State = $state; Box = $box }
}

# Todos marcados -> desmarca a secao; parcial ou nenhum -> marca a secao.
function Invoke-ToggleSectionSelection {
    param([System.Collections.Generic.List[PSCustomObject]]$Items, [string]$SectionId)
    $tests = @($Items | Where-Object { $_.IsTestItem -and $_.SectionId -eq $SectionId })
    if ($tests.Count -eq 0) { return }
    $allSel = (@($tests | Where-Object { -not $_.Selected }).Count -eq 0)
    foreach ($t in $tests) { $t.Selected = -not $allSel }
}

# Tecla P: pendentes. Com -DefaultSectionsOnly (Fase 2) so os pendentes das
# secoes DefaultSelected (Escritorio); sem o switch (Fase 1) todos os pendentes.
function Invoke-SelectPendingItems {
    param([System.Collections.Generic.List[PSCustomObject]]$Items, [switch]$DefaultSectionsOnly)
    foreach ($it in @($Items | Where-Object { $_.IsTestItem })) {
        $pending = ($null -eq $it.PrevStatus)
        $it.Selected = if ($DefaultSectionsOnly) { ([bool]$it.DefaultSelected -and $pending) } else { $pending }
    }
}

function Show-CheckboxMenu {
    param([System.Collections.Generic.List[PSCustomObject]]$Items)

    $selectableIdx = [System.Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Items.Count; $i++) {
        if ($Items[$i].Selectable) { $selectableIdx.Add($i) }
    }
    if ($selectableIdx.Count -eq 0) { return $Items }

    $headers     = @($Items | Where-Object { $_.IsSectionHeader })
    $hasSections = ($headers.Count -gt 0)
    $totalTests  = @($Items | Where-Object { $_.IsTestItem }).Count
    if ($hasSections) {
        $keys = @($headers | Where-Object { $_.SectionKey -match '^[1-9]$' } | ForEach-Object { $_.SectionKey })
        $keyHint = ""
        if ($keys.Count -eq 1) {
            $keyHint = "$($keys[0]) Secao  "
        } elseif ($keys.Count -gt 1) {
            $contiguous = $true
            for ($ki = 1; $ki -lt $keys.Count; $ki++) {
                if ([int]$keys[$ki] -ne ([int]$keys[$ki - 1] + 1)) { $contiguous = $false; break }
            }
            $keyHint = if ($contiguous) { "$($keys[0])-$($keys[-1]) Secao  " } else { "$($keys -join '/') Secao  " }
        }
        $defLabels = @($headers | Where-Object { $_.DefaultSelected } | ForEach-Object { $_.Display })
        $pHint = if ($defLabels.Count -gt 0) { "P Pendentes ($($defLabels -join ', '))" } else { "P Pendentes" }
        # Sem "setas Navegar" para caber em 120 colunas com o rotulo do P
        $helpLine = "ESPACO Marcar  $($keyHint)A Todos  $pHint  ENTER Confirmar  ESC Cancelar"
    } else {
        $helpLine = "setas Navegar  ESPACO Selecionar  A Todos  P Pendentes  ENTER Confirmar  ESC Cancelar"
    }

    $cursorPos  = 0
    $maxVisible = [Math]::Max(1, [Math]::Min(20, [Console]::WindowHeight - 12))
    $scrollOff  = 0
    $width      = [Console]::WindowWidth

    [Console]::CursorVisible = $false
    $maxSlots  = [Math]::Min($maxVisible, $Items.Count)
    $frameLines = 5 + $maxSlots
    for ($i = 0; $i -lt $frameLines; $i++) { Write-Host "" }
    $startY = [Console]::CursorTop - $frameLines

    try {
        while ($true) {
            $actualIdx = $selectableIdx[$cursorPos]
            if ($actualIdx -lt $scrollOff) { $scrollOff = $actualIdx }
            if ($actualIdx -ge ($scrollOff + $maxVisible)) { $scrollOff = $actualIdx - $maxVisible + 1 }
            $selCount = @($Items | Where-Object { $_.IsTestItem -and $_.Selected }).Count

            Safe-SetCursorPosition -X 0 -Y $startY
            Write-PaddedLine -Text "  Selecionados: $selCount/$totalTests  |  $helpLine" -Color DarkGray -Width $width
            Write-PaddedLine -Width $width

            for ($slot = 0; $slot -lt $maxSlots; $slot++) {
                $i = $scrollOff + $slot
                if ($i -lt $Items.Count) {
                    $it = $Items[$i]
                    if ($it.IsSeparator) {
                        $sepLine = "  -- $($it.Display) $('-' * [Math]::Max(1, 40 - $it.Display.Length))"
                        Write-PaddedLine -Text $sepLine -Color Cyan -Width $width
                    } elseif ($it.IsSectionHeader) {
                        $isCur  = ($i -eq $actualIdx)
                        $st     = Get-SectionSelectionState -Items $Items -SectionId $it.SectionId
                        $prefix = if ($isCur) { "  >> " } else { "     " }
                        $keyTag = if ($it.SectionKey -ne "") { "[$($it.SectionKey)] " } else { "" }
                        $head   = "$prefix$($st.Box) == $keyTag$($it.Display) ($($st.SelectedCount)/$($st.TotalCount)) "
                        $line   = $head + ('=' * [Math]::Max(3, 62 - $head.Length))
                        $clr    = if ($isCur) { "Yellow" } elseif ($st.State -eq "all") { "Green" } else { "Cyan" }
                        Write-PaddedLine -Text $line -Color $clr -Width $width
                    } else {
                        $isCur  = ($i -eq $actualIdx)
                        $box    = if ($it.Selected) { "[X]" } else { "[ ]" }
                        $prefix = if ($isCur) { "  >> " } else { "     " }
                        $typeTag = "  [$($it.Type.ToUpper())]"

                        $statusTag = ""
                        $statusClr = "DarkGray"
                        if ($null -ne $it.PrevStatus) {
                            $dur = "$([Math]::Round($it.PrevDuration, 1))s"
                            if ($it.PrevStatus -eq "PASS") {
                                $statusTag = "  PASS  ($dur)"
                                $statusClr = "Green"
                            } elseif ($it.PrevStatus -eq "FAIL") {
                                $statusTag = "  FAIL  ($dur)"
                                $statusClr = "Red"
                            } else {
                                $statusTag = "  $($it.PrevStatus)  ($dur)"
                                $statusClr = "Yellow"
                            }
                        } else {
                            $statusTag = "  pendente"
                            $statusClr = "DarkGray"
                        }

                        $line = "$prefix$box $($it.Display)$typeTag"
                        $padLen = [Math]::Max(1, 50 - $line.Length)
                        $linePadded = $line + (' ' * $padLen)

                        $clr = if ($isCur) { "Yellow" } elseif ($it.Selected) { "Green" } else { "White" }
                        $fullLine = "$linePadded$statusTag"
                        $fullPadded = $fullLine.PadRight($width - 1)
                        if ($fullPadded.Length -gt $width - 1) { $fullPadded = $fullPadded.Substring(0, $width - 1) }
                        $cut = [Math]::Min($linePadded.Length, $fullPadded.Length)

                        Write-Host $fullPadded.Substring(0, $cut) -NoNewline -ForegroundColor $clr
                        Write-Host $fullPadded.Substring($cut) -ForegroundColor $statusClr
                    }
                } else { Write-PaddedLine -Width $width }
            }

            Write-PaddedLine -Width $width
            Write-PaddedLine -Width $width

            $key = [Console]::ReadKey($true)
            $keyName = [string]$key.Key
            switch ($keyName) {
                "UpArrow"   { $cursorPos = [Math]::Max(0, $cursorPos - 1) }
                "DownArrow" { $cursorPos = [Math]::Min($selectableIdx.Count - 1, $cursorPos + 1) }
                "Spacebar"  {
                    if ($Items[$actualIdx].IsSectionHeader) {
                        Invoke-ToggleSectionSelection -Items $Items -SectionId $Items[$actualIdx].SectionId
                    } else {
                        $Items[$actualIdx].Selected = -not $Items[$actualIdx].Selected
                    }
                }
                "A" {
                    $tests  = @($Items | Where-Object { $_.IsTestItem })
                    $allSel = (@($tests | Where-Object { -not $_.Selected }).Count -eq 0)
                    foreach ($t in $tests) { $t.Selected = -not $allSel }
                }
                "P"      { Invoke-SelectPendingItems -Items $Items -DefaultSectionsOnly:$hasSections }
                "Enter"  { return $Items }
                "Escape" {
                    foreach ($t in @($Items | Where-Object { $_.IsTestItem })) { $t.Selected = $false }
                    return $Items
                }
                default {
                    # 1..9 (fileira superior ou teclado numerico): alterna a secao com essa Key
                    if ($hasSections -and $keyName -match '^(?:D|NumPad)([1-9])$') {
                        $digit = $Matches[1]
                        $hdr = @($headers | Where-Object { $_.SectionKey -eq $digit }) | Select-Object -First 1
                        if ($null -ne $hdr) { Invoke-ToggleSectionSelection -Items $Items -SectionId $hdr.SectionId }
                    }
                }
            }
        }
    }
    finally {
        Safe-SetCursorPosition -X 0 -Y ($startY + $frameLines)
        [Console]::CursorVisible = $true
    }
}

# ---- Preservacao de evidencias -----------------------------------------------

function Move-EvidenceToAnterior {
    param([string]$ScriptTraceDir, [int]$RunId)

    if (-not (Test-Path -LiteralPath $ScriptTraceDir)) { return }

    $files = Get-ChildItem -LiteralPath $ScriptTraceDir -File -ErrorAction SilentlyContinue
    $dirs  = Get-ChildItem -LiteralPath $ScriptTraceDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "_anterior" }

    if (($files | Measure-Object).Count -eq 0 -and ($dirs | Measure-Object).Count -eq 0) { return }

    $ts = Get-Date -Format "yyyy-MM-ddTHH-mm-ss"
    $anteriorDir = Join-Path $ScriptTraceDir "_anterior"
    $runBackup   = Join-Path $anteriorDir "run${RunId}_$ts"
    New-Item -ItemType Directory -Path $runBackup -Force | Out-Null

    foreach ($f in $files) {
        Move-Item -LiteralPath $f.FullName -Destination $runBackup -Force
    }
    foreach ($d in $dirs) {
        Move-Item -LiteralPath $d.FullName -Destination $runBackup -Force
    }
}

# ---- Resumo pre-execucao ----------------------------------------------------

function Show-PreExecutionSummary {
    param(
        [array]$TestsToRun,
        [string]$ScenarioName,
        [string]$TraceRunDir,
        [int]$RunId,
        [hashtable]$PreviousResults,
        [array]$Findings = @()
    )

    Write-Host ""
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |   RESUMO PRE-EXECUCAO                    |" -ForegroundColor Cyan
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Cenario : $(Split-Path $TraceRunDir -Leaf)" -ForegroundColor White

    if ($RunId -gt 1) {
        Write-Host "  Modo    : Continuacao (run #$RunId)" -ForegroundColor DarkCyan
    } else {
        Write-Host "  Modo    : Nova execucao (run #1)" -ForegroundColor DarkCyan
    }

    Write-Host ""
    Write-Host "  Testes selecionados ($($TestsToRun.Count)):" -ForegroundColor White

    $hasRerun = $false
    foreach ($t in $TestsToRun) {
        $fileName = "$($t.Name).$($t.Type)"
        $isRerun = ($null -ne $PreviousResults -and $PreviousResults.ContainsKey($fileName))
        if ($isRerun) {
            Write-Host "    ~ $fileName" -NoNewline -ForegroundColor Yellow
            Write-Host "  [$($t.Type.ToUpper())]  re-execucao" -ForegroundColor DarkGray
            $hasRerun = $true
        } else {
            Write-Host "    * $fileName" -NoNewline -ForegroundColor Green
            Write-Host "  [$($t.Type.ToUpper())]  primeira execucao" -ForegroundColor DarkGray
        }
    }

    if ($hasRerun) {
        Write-Host ""
        Write-Host "  Evidencias anteriores serao preservadas em _anterior/" -ForegroundColor DarkYellow
    }

    # Achados da checagem (Get-PreflightFindings)
    $blocking  = @($Findings | Where-Object { $_.Nivel -eq "Impede" })
    $attention = @($Findings | Where-Object { $_.Nivel -ne "Impede" })
    $hasSobra  = @($Findings | Where-Object { $null -ne $_.Sobra }).Count -gt 0

    Write-Host ""
    if ($Findings.Count -eq 0) {
        Write-Host "  Checagem: [OK] nenhum problema encontrado" -ForegroundColor Green
    } else {
        Write-Host "  Checagem:" -ForegroundColor White
        foreach ($f in $blocking) {
            Write-Host "    [X] $($f.Item)" -ForegroundColor Red
            Write-Host "        -> $($f.Acao)  `($(($f.Testes) -join ', ')`)" -ForegroundColor DarkGray
        }
        foreach ($f in $attention) {
            Write-Host "    [!] $($f.Item)" -ForegroundColor Yellow
            Write-Host "        -> $($f.Acao)" -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    $keys = @()
    if ($blocking.Count -gt 0) {
        $keys += "R = tirar da fila os testes com [X]"
        $keys += "C = continuar mesmo assim"
    } else {
        $keys += "ENTER = iniciar"
    }
    if ($hasSobra) { $keys += "F = encerrar as sobras de teste" }
    $keys += "ESC = voltar"
    Write-Host "  $($keys -join '  |  ')" -ForegroundColor DarkGray

    # Devolve a escolha: start | continue | remove | kill | back
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq "Escape") { return "back" }
        if ($key.Key -eq "Enter") {
            if ($blocking.Count -eq 0) { return "start" }
            Write-Host "  [!] Ha itens que impedem testes da fila: escolha R, C ou ESC." -ForegroundColor Yellow
            continue
        }
        if ($blocking.Count -gt 0 -and $key.Key -eq "R") { return "remove" }
        if ($blocking.Count -gt 0 -and $key.Key -eq "C") { return "continue" }
        if ($hasSobra -and $key.Key -eq "F") { return "kill" }
    }
}

# Tira da fila os testes citados em achados 'Impede'.
function Remove-BlockedTests {
    param([array]$Tests, [array]$Findings)
    $blocked = @($Findings | Where-Object { $_.Nivel -eq "Impede" } | ForEach-Object { $_.Testes })
    return @($Tests | Where-Object { $blocked -notcontains "$($_.Name).$($_.Type)" })
}

# Motivo(s) que tiraram um teste da fila: os itens dos achados 'Impede' que o citam.
function Get-BlockReason {
    param([string]$TestName, [array]$Findings)
    $items = @($Findings | Where-Object { $_.Nivel -eq "Impede" -and @($_.Testes) -contains $TestName } |
        ForEach-Object { $_.Item } | Select-Object -Unique)
    return ($items -join "; ")
}

# ---- Progresso em tempo real -------------------------------------------------

function Show-ExecutionProgress {
    param([array]$TestsToRun, [int]$RunId)

    Write-Host ""
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    $headerText = "  |  EXECUCAO EM ANDAMENTO -- run #$RunId"
    $pad = 45 - $headerText.Length
    Write-Host "$headerText$(' ' * [Math]::Max(0,$pad))|" -ForegroundColor Cyan
    Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""

    $headerY = [Console]::CursorTop
    $width   = [Console]::WindowWidth

    Write-PaddedLine -Text "" -Width $width
    Write-PaddedLine -Text "" -Width $width

    foreach ($t in $TestsToRun) {
        Write-PaddedLine -Text "  ..  $($t.Name).$($t.Type)  [$($t.Type.ToUpper())]    aguardando" -Color DarkGray -Width $width
    }

    Write-Host ""
    return $headerY
}

function Safe-SetCursorPosition {
    param([int]$X, [int]$Y)
    $maxY = [Console]::BufferHeight - 1
    if ($Y -gt $maxY) {
        $linesToAdd = $Y - [Console]::CursorTop
        for ($i = 0; $i -lt $linesToAdd; $i++) { Write-Host "" }
        $Y = [Math]::Min([Console]::CursorTop, $maxY)
    }
    if ($Y -lt 0) { $Y = 0 }
    [Console]::SetCursorPosition($X, $Y)
}

function Update-ProgressLine {
    param([int]$Y, [int]$TestIndex, [string]$Name, [string]$Type, [string]$Status, [string]$Detail, [int]$Current, [int]$Total)

    $width = [Console]::WindowWidth
    $savedPos = [Console]::CursorTop

    Safe-SetCursorPosition -X 0 -Y $Y
    $headerText = "  [$Current/$Total]  > $Name.$Type"
    Write-PaddedLine -Text $headerText -Color Cyan -Width $width

    $lineY = $Y + 2 + $TestIndex
    Safe-SetCursorPosition -X 0 -Y $lineY

    switch ($Status) {
        "running" {
            $line = "  >>  $Name.$Type  [$($Type.ToUpper())]    executando... $Detail"
            Write-PaddedLine -Text $line -Color Cyan -Width $width
        }
        "PASS" {
            $line = "  OK  $Name.$Type  [$($Type.ToUpper())]    PASS    $Detail"
            Write-PaddedLine -Text $line -Color Green -Width $width
        }
        "FAIL" {
            $line = "  XX  $Name.$Type  [$($Type.ToUpper())]    FAIL    $Detail"
            Write-PaddedLine -Text $line -Color Red -Width $width
        }
        "ERROR" {
            $line = "  !!  $Name.$Type  [$($Type.ToUpper())]    ERROR   $Detail"
            Write-PaddedLine -Text $line -Color Yellow -Width $width
        }
        "CANCEL" {
            $line = "  --  $Name.$Type  [$($Type.ToUpper())]    cancelado $Detail"
            Write-PaddedLine -Text $line -Color DarkGray -Width $width
        }
    }

    Safe-SetCursorPosition -X 0 -Y $savedPos
}

# ---- Parada da fila (Ctrl+Q) -------------------------------------------------
# Os testes com Ctrl+Q gravam o arquivo HUB_STOP_FILE ao receber a tecla; o hub
# confere o arquivo ao fim de cada teste e, se existir, para a fila inteira.

function Test-StopSignal {
    param([string]$StopFile)
    if ([string]::IsNullOrEmpty($StopFile) -or -not (Test-Path -LiteralPath $StopFile)) { return $false }
    Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue
    return $true
}

# Descarta teclas que ficaram no buffer do console durante o teste (ex.: o proprio
# Ctrl+Q), para que nao respondam sozinhas a proxima pergunta do hub.
function Clear-KeyBuffer {
    try { while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) } } catch {}
}

# ---- Monitor ao vivo (TUI rich, Spec 004) ------------------------------------
# O hub continua dono da orquestracao; Testes/_lib/live_monitor.py so executa o
# teste mostrando o painel ao vivo e devolve o resultado em JSON.

# Python do .venv (ou o do PATH, se o .venv ainda nao existir).
function Resolve-PythonExe {
    param([string]$VenvPath)
    $venvExe = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path -LiteralPath $venvExe) { return $venvExe }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return "python3" }
    return "python"
}

# $true so se LiveMonitor.Enabled, o live_monitor.py existe e o Python importa rich.
# Reason explica o motivo do fallback para o painel classico.
function Test-LiveMonitorAvailable {
    param([PSCustomObject]$Settings, [string]$PythonExe, [string]$MonitorScript)
    $r = [PSCustomObject]@{ Available = $false; Reason = "" }
    if ($null -eq $Settings -or -not $Settings.Enabled) { $r.Reason = "LiveMonitor.Enabled = false"; return $r }
    if ([string]::IsNullOrEmpty($MonitorScript) -or -not (Test-Path -LiteralPath $MonitorScript)) { $r.Reason = "live_monitor.py nao encontrado"; return $r }
    $ok = $false
    try {
        & $PythonExe -c "import rich" 2>$null | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
    } catch { $ok = $false }
    if (-not $ok) { $r.Reason = "Python do .venv sem o pacote rich (rode o Setup 5)"; return $r }
    $r.Available = $true
    return $r
}

# Testes sensiveis (LowImpactFolders): painel sem timer e sem telemetria.
function Test-LiveMonitorLowImpact {
    param([PSCustomObject]$Test, [PSCustomObject]$Settings)
    if ($null -eq $Settings -or -not $Settings.PSObject.Properties['LowImpactFolders']) { return $false }
    return (@($Settings.LowImpactFolders) -contains $Test.ParentFolder)
}

# Objeto do --state do live_monitor.py (contrato na spec 004, secao 4).
function New-LiveMonitorStatePayload {
    param(
        [PSCustomObject]$State,
        [int]$RunId,
        [datetime]$RunStart,
        [array]$Tests,
        [array]$Results = @(),
        [int]$CurrentIndex,
        [PSCustomObject]$Settings,
        [PSCustomObject]$Sampler
    )
    $queue = @()
    for ($i = 0; $i -lt @($Tests).Count; $i++) {
        $t = @($Tests)[$i]
        $status = "pending"; $duration = 0.0
        if ($i -lt @($Results).Count) {
            $status = [string]@($Results)[$i].Status
            $duration = [Math]::Round([double]@($Results)[$i].Duration, 3)
        } elseif ($i -eq $CurrentIndex) {
            $status = "running"
        }
        $section = ""
        if ($t.PSObject.Properties['SectionLabel'] -and $t.SectionLabel) { $section = [string]$t.SectionLabel }
        $queue += [PSCustomObject]@{ name = $t.Name; type = $t.Type; section = $section; status = $status; duration = $duration }
    }
    $warnings = @(Get-RunWarnings -State $State | Where-Object { $_.run -eq $RunId } |
        ForEach-Object { [PSCustomObject]@{ fonte = [string]$_.fonte; texto = [string]$_.texto } })
    $epoch = ([DateTimeOffset]$RunStart).ToUnixTimeMilliseconds() / 1000.0
    $throttle = 20; $loadMin = 50
    if ($null -ne $Sampler) {
        if ($Sampler.PSObject.Properties['ThrottleAlertPct']) { $throttle = [double]$Sampler.ThrottleAlertPct }
        if ($Sampler.PSObject.Properties['LoadMinPct'])       { $loadMin  = [double]$Sampler.LoadMinPct }
    }
    return [PSCustomObject]@{
        scenario             = [string](Get-StateField $State "scenario")
        machine              = [string](Get-StateField $State "machine")
        modelo               = [string](Get-StateField $State "modelo")
        patrimonio           = [string](Get-StateField $State "patrimonio")
        runId                = $RunId
        runStartEpoch        = $epoch
        currentIndex         = $CurrentIndex
        refreshHz            = [double]$Settings.RefreshHz
        logTailLines         = [int]$Settings.LogTailLines
        telemetryIntervalSec = [double]$Settings.TelemetryIntervalSec
        throttleAlertPct     = $throttle
        loadMinPct           = $loadMin
        warnings             = $warnings
        queue                = $queue
    }
}

# Argumento de linha de comando com as regras de aspas do Windows (CommandLineToArgvW).
function ConvertTo-ProcessArgument {
    param([string]$Value)
    if ($Value -ne "" -and $Value -notmatch '[\s"]') { return $Value }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $bs = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq '\') { $bs++; continue }
        if ($ch -eq '"') { [void]$sb.Append([char]'\', 2 * $bs + 1); [void]$sb.Append('"'); $bs = 0; continue }
        if ($bs -gt 0) { [void]$sb.Append([char]'\', $bs); $bs = 0 }
        [void]$sb.Append($ch)
    }
    if ($bs -gt 0) { [void]$sb.Append([char]'\', 2 * $bs) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

# Executa o live_monitor.py herdando o console (sem redirecionar o stdout, para o
# rich desenhar no terminal real). Devolve ExitCode, a saida capturada do teste e
# o JSON de resultado (ou $null se ausente/invalido).
function Invoke-LiveMonitorProcess {
    param([string]$PythonExe, [string]$MonitorScript, [PSCustomObject]$Payload, [string[]]$Command, [string]$FreqCsv = "", [switch]$LowImpact)
    $tag = [guid]::NewGuid().ToString('N')
    $stateFile   = Join-Path $env:TEMP "wintesthub_live_state_$tag.json"
    $resultFile  = Join-Path $env:TEMP "wintesthub_live_result_$tag.json"
    $captureFile = Join-Path $env:TEMP "wintesthub_live_stdout_$tag.txt"
    $out = [PSCustomObject]@{ ExitCode = -1; Lines = @(); Result = $null; Error = "" }
    try {
        $json = $Payload | ConvertTo-Json -Depth 6
        [System.IO.File]::WriteAllText($stateFile, $json, (New-Object System.Text.UTF8Encoding($false)))
        $argv = @("-u", $MonitorScript, "--state", $stateFile, "--result", $resultFile, "--log-capture", $captureFile)
        if ($FreqCsv) { $argv += @("--freq-csv", $FreqCsv) }
        if ($LowImpact) { $argv += "--low-impact" }
        $argv += "--"
        $argv += $Command
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $PythonExe
        $psi.Arguments = (@($argv | ForEach-Object { ConvertTo-ProcessArgument ([string]$_) }) -join " ")
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.WaitForExit()
        $out.ExitCode = $proc.ExitCode
        if (Test-Path -LiteralPath $captureFile) {
            $out.Lines = @([System.IO.File]::ReadAllLines($captureFile, [System.Text.Encoding]::UTF8))
        }
        if (Test-Path -LiteralPath $resultFile) {
            try {
                $out.Result = [System.IO.File]::ReadAllText($resultFile, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
                if ($null -eq $out.Result -or -not $out.Result.PSObject.Properties['exitCode']) {
                    $out.Result = $null; $out.Error = "JSON de resultado do live_monitor.py invalido"
                }
            } catch { $out.Result = $null; $out.Error = "JSON de resultado do live_monitor.py invalido: $($_.Exception.Message)" }
        } else {
            $out.Error = "live_monitor.py terminou (exit $($out.ExitCode)) sem gravar o JSON de resultado"
        }
    } catch {
        $out.Error = "Falha ao executar live_monitor.py: $($_.Exception.Message)"
    } finally {
        foreach ($f in $stateFile, $resultFile, "$resultFile.tmp", $captureFile) {
            Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
        }
    }
    return $out
}

# ---- Execucao de cada script -------------------------------------------------

function Invoke-TestScript {
    param([PSCustomObject]$Test, [string]$LogFile, [string]$TraceRunDir, [switch]$Silent, [PSCustomObject]$LivePayload = $null)

    $scriptTraceDir = Join-Path $TraceRunDir "$($Test.ParentFolder)"
    New-Item -ItemType Directory -Path $scriptTraceDir -Force | Out-Null
    
    $env:HUB_EVIDENCE_DIR = $scriptTraceDir 
    $env:HUB_TRACE_DIR    = $scriptTraceDir
    $env:HUB_TRACE_ROOT   = $TraceRunDir

    $startTime = Get-Date
    $status    = "PASS"
    $output    = ""
    $exitCode  = 0

    # Frequencia da CPU durante o teste (so testes, nao setups)
    $sampling = Test-CpuSamplingEnabled -Test $Test -Settings $CpuSamplerSettings
    if ($sampling) {
        Start-CpuSampler -OutFile (Join-Path $scriptTraceDir "frequencia_cpu.csv") -IntervalSec ([int]$CpuSamplerSettings.IntervalSec)
    }

    try {
        $capturedOut = [System.Collections.Generic.List[string]]::new()
        
        if ($null -ne $LivePayload -and $Test.Kind -eq "test") {
            # Monitor ao vivo: live_monitor.py executa o teste e desenha a TUI
            $pyExe = Resolve-PythonExe -VenvPath $VenvPath
            if ($Test.Type -eq "ps1") {
                $cmd = @("powershell.exe", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Test.Path)
            } else {
                $cmd = @($pyExe, "-u", $Test.Path)
            }
            $freqCsv = if ($sampling) { Join-Path $scriptTraceDir "frequencia_cpu.csv" } else { "" }
            $lowImpact = Test-LiveMonitorLowImpact -Test $Test -Settings $LiveMonitorSettings
            $live = Invoke-LiveMonitorProcess -PythonExe $pyExe -MonitorScript $LiveMonitorScript -Payload $LivePayload -Command $cmd -FreqCsv $freqCsv -LowImpact:$lowImpact
            foreach ($l in $live.Lines) { $capturedOut.Add([string]$l) }
            if ($null -ne $live.Result) {
                $exitCode = [int]$live.Result.exitCode
                if ($exitCode -eq -1) { $status = "ERROR" }
            } else {
                $status   = "ERROR"
                $exitCode = -1
                $capturedOut.Add("[ERRO] [live_monitor] $($live.Error)")
            }
        }
        elseif ($Test.Type -eq "ps1") {
            & powershell.exe -NonInteractive -NoProfile -ExecutionPolicy Bypass -File $Test.Path 2>&1 | ForEach-Object {
                $line = $_.ToString()
                $capturedOut.Add($line)
                if (-not $Silent) { Write-Host "      | $line" -ForegroundColor DarkGray }
            }
            $exitCode = $LASTEXITCODE
        }
        elseif ($Test.Type -eq "py") {
            # Logica de detecao do Virtual Environment (.venv)
            $pyExe = Resolve-PythonExe -VenvPath $VenvPath

            & $pyExe -u $Test.Path 2>&1 | ForEach-Object {
                $line = $_.ToString()
                $capturedOut.Add($line)
                if (-not $Silent) { Write-Host "      | $line" -ForegroundColor DarkGray }
            }
            $exitCode = $LASTEXITCODE
        }

        $output = ($capturedOut -join "`n").Trim()
        if ($exitCode -ne 0 -and $status -eq "PASS") { $status = "FAIL" }
    }
    catch {
        $status   = "ERROR"
        $output   = $_.Exception.Message
        $exitCode = -1
    }
    finally {
        if ($sampling) { Stop-CpuSampler }
    }

    # Extrair snippet de erro (ultimas linhas relevantes do output)
    $errorSnippet = ""
    if ($status -ne "PASS") {
        $relevantLines = @($capturedOut | Where-Object {
            $_ -match '\S' -and $_ -match '(?i)(erro|fail|falha|exception|critical|traceback|error|\[ERRO\])'
        })
        if ($relevantLines.Count -eq 0) {
            $relevantLines = @($capturedOut | Where-Object { $_ -match '\S' }) | Select-Object -Last 3
        } else {
            $relevantLines = $relevantLines | Select-Object -Last 3
        }
        $errorSnippet = ($relevantLines -join "`n").Trim()
    }

    $env:HUB_EVIDENCE_DIR = ""
    $env:HUB_TRACE_DIR    = ""
    $env:HUB_TRACE_ROOT   = ""

    $endTime  = Get-Date
    $duration = ($endTime - $startTime).TotalSeconds
    $ts       = $startTime.ToString("yyyy-MM-dd HH:mm:ss")

    $traceFiles = @(Get-ChildItem -LiteralPath $scriptTraceDir -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*\_anterior\*" -and $_.Name -ne "frequencia_cpu.csv" })
    $traceCount = $traceFiles.Count

    $logEntry = "`n$('-'*62)`n[$ts]  $($Test.Kind.ToUpper()) | $($Test.Name)  [$($Test.Type.ToUpper())]`nSTATUS    : $status`nDURATION  : $([Math]::Round($duration,3))s`nEXIT CODE : $exitCode`nTRACES    : $traceCount arquivo(s) em $scriptTraceDir`nOUTPUT    :`n$output"
    Add-Content -LiteralPath $LogFile -Value $logEntry -Encoding UTF8

    return [PSCustomObject]@{
        Display        = $Test.Display
        Name           = $Test.Name
        Type           = $Test.Type
        Kind           = $Test.Kind
        Status         = $status
        Duration       = $duration
        Timestamp      = $ts
        ExitCode       = $exitCode
        TraceDir       = $scriptTraceDir
        TraceCount     = $traceCount
        ErrorSnippet   = $errorSnippet
    }
}

# ---- Resumo final e Relatorio HTML -------------------------------------------

function Show-Summary {
    param([array]$Results, [string]$LogFile, [string]$ResultsFile, [double]$TotalSec)

    $setupResults = @($Results | Where-Object { $_.Kind -eq "setup" })
    $testResults  = @($Results | Where-Object { $_.Kind -ne "setup" })
    $pass  = @($Results | Where-Object { $_.Status -eq "PASS"  }).Count
    $fail  = @($Results | Where-Object { $_.Status -eq "FAIL"  }).Count
    $err   = @($Results | Where-Object { $_.Status -eq "ERROR" }).Count
    $totalTraces = ($Results | Measure-Object -Property TraceCount -Sum).Sum

    Write-Host "`n  +==========================================+" -ForegroundColor Cyan
    Write-Host "  |          RESUMO DA EXECUCAO              |" -ForegroundColor Cyan
    Write-Host "  +==========================================+" -ForegroundColor Cyan

    # Print Console (Setup + Tests)
    foreach ($group in @(@("PREPARACAO DA MAQUINA", "DarkYellow", $setupResults), @("TESTES DE HARDWARE", "DarkCyan", $testResults))) {
        if ($group[2].Count -gt 0) {
            Write-Host "`n  -- $($group[0]) $( '-' * (26 - $group[0].Length) )" -ForegroundColor $group[1]
            foreach ($r in $group[2]) {
                $clr  = if ($r.Status -eq "PASS") { "Green" } elseif ($r.Status -eq "FAIL") { "Red" } else { "Yellow" }
                $icon = if ($r.Status -eq "PASS") { "[OK]" } elseif ($r.Status -eq "FAIL") { "[FAIL]" } else { "[ERR]" }
                Write-Host "  $icon " -NoNewline -ForegroundColor $clr
                Write-Host $r.Display -NoNewline -ForegroundColor White
                Write-Host "  $([Math]::Round($r.Duration,2))s  @ $($r.Timestamp)" -NoNewline -ForegroundColor DarkGray
                if ($r.TraceCount -gt 0) { Write-Host "  [TRACES: $($r.TraceCount)]" -ForegroundColor DarkYellow } else { Write-Host "" }

                # Mostrar snippet de erro para testes que falharam
                if ($r.Status -ne "PASS" -and $r.ErrorSnippet) {
                    foreach ($errLine in ($r.ErrorSnippet -split "`n")) {
                        Write-Host "        > $errLine" -ForegroundColor DarkRed
                    }
                }
            }
        }
    }

    Write-Host "`n  --------------------------------------------" -ForegroundColor DarkGray
    Write-Host "  Total : $($Results.Count)   PASS: $pass   FAIL: $fail   ERROR: $err" -ForegroundColor White
    Write-Host "  Tempo total  : $([Math]::Round($TotalSec,2))s" -ForegroundColor DarkGray
    Write-Host "  Traces salvos: $totalTraces arquivo(s)`n" -ForegroundColor DarkGray

    # ---- Exporta CSV 
    $csvPath = "$ResultsFile.csv"
    $csvHeader = "Timestamp,Kind,Name,Type,Status,Duration_s,ExitCode,TraceCount,TraceDir"
    $csvLines  = @($csvHeader)
    foreach ($r in $Results) { $csvLines += "$($r.Timestamp),$($r.Kind),$($r.Name),$($r.Type),$($r.Status),$([Math]::Round($r.Duration,3)),$($r.ExitCode),$($r.TraceCount),$($r.TraceDir)" }
    Set-Content -LiteralPath $csvPath -Value $csvLines -Encoding UTF8

    # ---- Exporta JSON
    $jsonPath = "$ResultsFile.json"
    $jsonObj  = [PSCustomObject]@{ RunTimestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); Host = $env:COMPUTERNAME; TotalScripts = $Results.Count; Pass = $pass; Fail = $fail; Error = $err; TotalDuration = [Math]::Round($TotalSec,3); TotalTraces = $totalTraces; Scripts = $Results }
    $jsonObj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    # ---- Exporta Relatorio HTML (NOVO)
    $htmlPath = "$ResultsFile.html"
    $htmlTitle = $config.Settings.HtmlReportTitle
    $html = @"
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>$htmlTitle</title>
        $BrandFavicon
        <style>
$BrandCss
        </style>
    </head>
    <body>
        <div class="brand">$BrandHeader<div><div class="brand-name">Win<b>Test</b>Hub</div><h1>$htmlTitle</h1></div></div>
        <div class="summary">
            <p><strong>Maquina (Host):</strong> $env:COMPUTERNAME</p>
            <p><strong>Utilizador:</strong> $env:USERNAME</p>
            <p><strong>Inicio da Execucao:</strong> $($jsonObj.RunTimestamp)</p>
            <p><strong>Tempo Total:</strong> $([Math]::Round($TotalSec,2))s</p>
            <p><strong>Estatisticas:</strong> Total: $($Results.Count) | <span style="color:#2e7c35;font-weight:bold;">Aprovados: $pass</span> | <span style="color:#c53030;font-weight:bold;">Falhados: $fail</span> | <span style="color:#b45309;font-weight:bold;">Erros: $err</span></p>
        </div>
        <table>
            <tr><th>Fase</th><th>Nome do Teste</th><th>Tipo</th><th>Status</th><th>Duracao</th><th>Traces Gerados</th></tr>
            $($Results | ForEach-Object {
                $errRow = ""
                if ($_.Status -ne "PASS" -and $_.ErrorSnippet) {
                    $safeSnippet = $_.ErrorSnippet -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;' -replace "`n","<br>"
                    $errRow = "<tr><td colspan='6' style='background:#fff5f5;color:#c53030;padding-left:30px;font-family:Consolas,monospace;font-size:0.85em;border-left:3px solid #c53030;'>$safeSnippet</td></tr>"
                }
                "<tr>
                    <td>$($_.Kind.ToUpper())</td>
                    <td><strong>$($_.Display)</strong></td>
                    <td>.$($_.Type)</td>
                    <td><span class='badge bg-$($_.Status)'>$($_.Status)</span></td>
                    <td>$([Math]::Round($_.Duration,2))s</td>
                    <td>$($_.TraceCount)</td>
                </tr>$errRow"
            })
        </table>
    </body>
    </html>
"@
    Set-Content -LiteralPath $htmlPath -Value $html -Encoding UTF8

    # Appenda resumo no log
    $summaryLog = "`n$('-'*62)`nRESUMO FINAL`nTotal: $($Results.Count) | PASS: $pass | FAIL: $fail | ERROR: $err`nTempo total: $([Math]::Round($TotalSec,2))s`nTraces: $totalTraces arquivo(s)`nHTML Gerado em: $htmlPath`n$('-'*62)"
    Add-Content -LiteralPath $LogFile -Value $summaryLog -Encoding UTF8
    
    Write-Host "  Relatorio HTML : $htmlPath" -ForegroundColor Magenta
    Write-Host "  Log, CSV, JSON salvos na pasta Logs." -ForegroundColor DarkCyan
    Write-Host ""
}

# ---- Relatorio Consolidado ---------------------------------------------------

function Build-ConsolidatedReport {
    param([string]$TraceRunDir, [PSCustomObject]$State)

    $latest = Get-LatestTestResults -State $State
    $results = @()
    foreach ($key in ($latest.Keys | Sort-Object)) {
        $r = $latest[$key]
        $results += [PSCustomObject]@{
            Name     = $key
            Status   = $r.status
            Duration = $r.duration
            RunId    = $r.runId
            Folder   = $r.folder
            IsRerun  = ($r.runId -gt 1)
        }
    }

    $pass  = @($results | Where-Object { $_.Status -eq "PASS" }).Count
    $fail  = @($results | Where-Object { $_.Status -eq "FAIL" }).Count
    $err   = @($results | Where-Object { $_.Status -eq "ERROR" }).Count
    $total = $results.Count
    $totalDuration = ($results | Measure-Object -Property Duration -Sum).Sum

    # CSV
    $csvPath = Join-Path $TraceRunDir "_relatorio.csv"
    $csvLines = @("Nome,Status,Duracao_s,Run,Reexecucao,Pasta")
    foreach ($r in $results) {
        $rerun = if ($r.IsRerun) { "sim" } else { "nao" }
        $csvLines += "$($r.Name),$($r.Status),$($r.Duration),$($r.RunId),$rerun,$($r.Folder)"
    }
    Set-Content -LiteralPath $csvPath -Value $csvLines -Encoding UTF8

    # Avisos da rodada (acumulados no _state.json) e frequencia da CPU por modulo
    # Sort-Object do PS 5.1 nao e estavel: desempata pela ordem em que foram gravados
    $rawWarnings = @(Get-RunWarnings -State $State)
    $warnings = @(0..($rawWarnings.Count - 1) | Where-Object { $rawWarnings.Count -gt 0 } |
        Sort-Object @{ e = { [int]$rawWarnings[$_].run } }, @{ e = { $_ } } | ForEach-Object { $rawWarnings[$_] })
    $freq = @()
    foreach ($folder in @($results | ForEach-Object { $_.Folder } | Select-Object -Unique)) {
        if (-not $folder) { continue }
        $fcsv = Join-Path (Join-Path $TraceRunDir $folder) "frequencia_cpu.csv"
        $fs = Get-CpuFrequencySummary -Csv $fcsv -IntervalSec ([int]$CpuSamplerSettings.IntervalSec) -LoadMinPct ([double]$CpuSamplerSettings.LoadMinPct)
        if ($null -ne $fs) {
            $freq += [PSCustomObject]@{
                Modulo    = $folder
                Amostras  = $fs.Samples
                MHzMedio  = $fs.AvgMHz
                MHzInicio = $fs.StartMHz
                MHzFim    = $fs.EndMHz
                QuedaPct  = $fs.DropPct
                TempMaxC  = $fs.MaxTempC
            }
        }
    }

    # JSON
    $jsonPath = Join-Path $TraceRunDir "_relatorio.json"
    $jsonObj = [PSCustomObject]@{
        Scenario      = $State.scenario
        Machine       = $State.machine
        Modelo        = (Get-StateField $State "modelo")
        Patrimonio    = (Get-StateField $State "patrimonio")
        CreatedAt     = $State.createdAt
        LastRunAt     = $State.lastRunAt
        TotalRuns     = ($State.runs | Measure-Object).Count
        TotalTests    = $total
        Pass          = $pass
        Fail          = $fail
        Error         = $err
        TotalDuration = [Math]::Round($totalDuration, 3)
        Tests         = $results
        Avisos        = @($warnings)
        FrequenciaCpu = @($freq)
    }
    $jsonObj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    # HTML
    $htmlPath  = Join-Path $TraceRunDir "_relatorio.html"
    $htmlTitle = $config.Settings.HtmlReportTitle
    $totalRuns = ($State.runs | Measure-Object).Count

    $tableRows = ""
    foreach ($r in $results) {
        $rerunTag = if ($r.IsRerun) { " (rerun)" } else { "" }
        $tableRows += @"
            <tr>
                <td><strong>$($r.Name)</strong></td>
                <td><span class='badge bg-$($r.Status)'>$($r.Status)</span></td>
                <td>$([Math]::Round($r.Duration, 2))s</td>
                <td>run #$($r.RunId)$rerunTag</td>
                <td>$($r.Folder)</td>
            </tr>
"@
    }

    $enc = { param($t) [System.Net.WebUtility]::HtmlEncode([string]$t) }
    if ($warnings.Count -gt 0) {
        $warnRows = ""
        foreach ($w in $warnings) {
            $warnRows += "            <tr><td>run #$($w.run)</td><td>$(& $enc $w.fonte)</td><td>$(& $enc $w.texto)</td></tr>`r`n"
        }
        $warnSection = @"
        <h2>Avisos da rodada ($($warnings.Count))</h2>
        <table>
            <tr><th>Run</th><th>Fonte</th><th>Aviso</th></tr>
$warnRows        </table>
"@
    } else {
        $warnSection = "        <h2>Avisos da rodada</h2>`r`n        <p>Nenhum aviso.</p>"
    }
    $freqSection = ""
    if ($freq.Count -gt 0) {
        $dash = { param($v, $suf) if ($null -eq $v -or "$v" -eq "") { "-" } else { "$v$suf" } }
        $freqRows = ""
        foreach ($f in $freq) {
            $freqRows += "            <tr><td>$(& $enc $f.Modulo)</td><td>$($f.Amostras)</td><td>$($f.MHzMedio)</td><td>$(& $dash $f.MHzInicio '') / $(& $dash $f.MHzFim '')</td><td>$(& $dash $f.QuedaPct '%')</td><td>$(& $dash $f.TempMaxC ' C')</td></tr>`r`n"
        }
        $freqSection = @"
        <h2>Frequencia da CPU por modulo</h2>
        <p>Inicio/fim e queda: mediana do 1o e do ultimo minuto com a CPU sob carga (uso &gt;= $($CpuSamplerSettings.LoadMinPct)%). Temperatura: maior zona termica ACPI, quando o firmware expoe.</p>
        <table>
            <tr><th>Modulo</th><th>Amostras</th><th>MHz medio</th><th>MHz inicio / fim</th><th>Queda</th><th>Temp. max.</th></tr>
$freqRows        </table>
"@
    }

    $html = @"
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>$htmlTitle - Consolidado</title>
        $BrandFavicon
        <style>
$BrandCss
        </style>
    </head>
    <body>
        <div class="brand">$BrandHeader<div><div class="brand-name">Win<b>Test</b>Hub</div><h1>$htmlTitle - Relatorio Consolidado</h1></div></div>
        <div class="summary">
            <p><strong>Cenario:</strong> $($State.scenario)</p>
            <p><strong>Maquina:</strong> $($State.machine)</p>
            <p><strong>Modelo / Patrimonio:</strong> $(Get-StateField $State "modelo") / $(Get-StateField $State "patrimonio")</p>
            <p><strong>Criado em:</strong> $($State.createdAt)</p>
            <p><strong>Ultima execucao:</strong> $($State.lastRunAt)</p>
            <p><strong>Total de runs:</strong> $totalRuns</p>
            <p><strong>Estatisticas:</strong> Total: $total | <span style="color:#2e7c35;font-weight:bold;">Aprovados: $pass</span> | <span style="color:#c53030;font-weight:bold;">Falhados: $fail</span> | <span style="color:#b45309;font-weight:bold;">Erros: $err</span></p>
        </div>
        <table>
            <tr><th>Teste</th><th>Status</th><th>Duracao</th><th>Run</th><th>Pasta</th></tr>
            $tableRows
        </table>
$warnSection
$freqSection
    </body>
    </html>
"@
    Set-Content -LiteralPath $htmlPath -Value $html -Encoding UTF8

    Write-Host "  Relatorio consolidado: $htmlPath" -ForegroundColor Magenta
}

# ---- Coleta de Informacoes da Maquina ----------------------------------------

function Collect-MachineInfo {
    param([string]$OutputDir, [PSCustomObject]$State)

    Write-Host "  Coletando informacoes da maquina..." -ForegroundColor DarkCyan

    $cs  = Get-CimInstance -ClassName Win32_ComputerSystem
    $bios = Get-CimInstance -ClassName Win32_BIOS
    $cpu = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1
    $disk = Get-CimInstance -ClassName Win32_DiskDrive | Select-Object -First 1
    $os  = Get-CimInstance -ClassName Win32_OperatingSystem

    $ramGB = [Math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
    $diskGB = if ($disk) { [Math]::Round($disk.Size / 1GB, 2) } else { "N/A" }

    $csvPath = Join-Path $OutputDir "maquina.csv"
    $csvHeader = "Campo,Valor"
    $csvLines = @(
        $csvHeader,
        "Hostname,`"$($env:COMPUTERNAME)`"",
        "Modelo,`"$($cs.Model)`"",
        "Fabricante,`"$($cs.Manufacturer)`"",
        "Numero de Serie,`"$($bios.SerialNumber)`"",
        "Processador,`"$($cpu.Name)`"",
        "Nucleos Fisicos,$($cpu.NumberOfCores)",
        "Nucleos Logicos,$($cpu.NumberOfLogicalProcessors)",
        "RAM Total (GB),$ramGB",
        "Disco Principal,`"$(if ($disk) { $disk.Model } else { 'N/A' })`"",
        "Disco Tamanho (GB),$diskGB",
        "Sistema Operacional,`"$($os.Caption)`"",
        "Build do SO,`"$($os.BuildNumber)`"",
        "Data da Coleta,`"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`"",
        "Modelo Informado,`"$(Get-StateField $State 'modelo')`"",
        "Patrimonio/Serial Informado,`"$(Get-StateField $State 'patrimonio')`""
    )
    Set-Content -LiteralPath $csvPath -Value $csvLines -Encoding UTF8
    Write-Host "  [OK] maquina.csv gerado em $OutputDir" -ForegroundColor Green
}

# ---- Verificacao de CSVs Tematicos ------------------------------------------

# Avisa quando um teste rodou mas nao gerou o CSV tematico esperado.
# Nao copia nada: os CSVs ficam em Traces/ e seguem na exportacao.
function Test-ThematicCSVs {
    param(
        [string]$TraceRunDir,
        [string]$LogFile
    )

    Write-Host "`n  Verificando CSVs tematicos..." -ForegroundColor DarkCyan

    $expectedCSVs = @{
        "0_consumo_basal"  = "consumo_basal.csv"
        "1_cpu_memo"       = "cpu_memoria.csv"
        "2_disco"          = "disco.csv"
        "3_rede"           = "rede.csv"
        "4_boot_shutdown"  = "boot_shutdown.csv"
        "5_bateria"        = "bateria.csv"
        "6_wifi_fast_transition" = "wifi_ft.csv"
        "7_dev_dotnet"           = "dev_dotnet.csv"
        "8_dev_go"               = "dev_go.csv"
        "9_dev_python"           = "dev_python.csv"
        "10_dev_containers"      = "dev_containers.csv"
        "11_dev_git_arquivos"    = "dev_git_arquivos.csv"
    }

    # CSVs das variantes DLP/USB (1-1 e 2-1): opcionais -- listados quando
    # existirem, sem aviso quando ausentes. Caminho relativo a TraceRunDir.
    $variantCSVs = [ordered]@{
        "1_cpu_memo/dlp_usb/cpu_memoria_dlp.csv" = "cpu_memoria_dlp.csv"
        "2_disco/disco_usb.csv"                  = "disco_usb.csv"
    }

    $found   = 0
    $missing = 0
    $missingFolders = @()

    foreach ($folder in ($expectedCSVs.Keys | Sort-Object { Get-NaturalSortKey $_ })) {
        $csvName = $expectedCSVs[$folder]
        $sourcePath = Join-Path $TraceRunDir (Join-Path $folder $csvName)

        if (Test-Path -LiteralPath $sourcePath) {
            Write-Host "  [OK] $csvName" -ForegroundColor Green
            $found++
        } else {
            $testFolder = Join-Path $TraceRunDir $folder
            if (Test-Path -LiteralPath $testFolder) {
                Write-Host "  [!] $csvName nao encontrado -- teste executado mas CSV nao foi gerado" -ForegroundColor Yellow
                Add-Content -LiteralPath $LogFile -Value "[AVISO] CSV tematico '$csvName' nao gerado pelo teste em '$folder'" -Encoding UTF8
                $missing++
                $missingFolders += $folder
            } else {
                Write-Host "  [--] $csvName -- teste pendente `($folder nao executado`)" -ForegroundColor DarkGray
                Add-Content -LiteralPath $LogFile -Value "[INFO] CSV tematico '$csvName' pendente -- teste '$folder' nao executado" -Encoding UTF8
            }
        }
    }

    foreach ($relPath in $variantCSVs.Keys) {
        if (Test-Path -LiteralPath (Join-Path $TraceRunDir $relPath)) {
            Write-Host "  [OK] $($variantCSVs[$relPath])" -ForegroundColor Green
            $found++
        }
    }

    if ($missing -gt 0) { $resultColor = "Yellow" } else { $resultColor = "Green" }
    Write-Host "  Resultado: ${found} encontrado`(s`), ${missing} ausente`(s`)" -ForegroundColor $resultColor
    return [PSCustomObject]@{ Found = $found; Missing = $missing; MissingFolders = $missingFolders }
}

# ---- Exportacao dos traces (pasta Exportar) ----------------------------------

# Destino da exportacao: Exportar/<cenario>/<modelo> - <patrimonio>.
# Cada parte passa pela limpeza de nome de pasta (sem '\', '/', ':'...), entao
# o destino nunca sai de ExportarDir, mesmo com _state.json editado a mao.
function Get-ExportPath {
    param([string]$ExportarDir, [PSCustomObject]$State)
    $cenario    = ConvertTo-SafeFolderName (Get-StateField $State "scenario")
    $modelo     = ConvertTo-SafeFolderName (Get-StateField $State "modelo")
    $patrimonio = ConvertTo-SafeFolderName (Get-StateField $State "patrimonio")
    if ([string]::IsNullOrWhiteSpace($cenario))    { $cenario    = "Execucao" }
    if ([string]::IsNullOrWhiteSpace($modelo))     { $modelo     = "SemModelo" }
    if ([string]::IsNullOrWhiteSpace($patrimonio)) { $patrimonio = "SemPatrimonio" }
    return (Join-Path (Join-Path $ExportarDir $cenario) "$modelo - $patrimonio")
}

# Copia Traces/ para a pasta de exportacao sem .etl, sem logs (.log e pastas
# logs/) e sem pastas vazias. Traces/ nao e alterada. Idempotente: o destino
# e recriado a cada chamada. Devolve um resumo ou $null em caso de erro.
# Usa sempre -LiteralPath: '[' e ']' sao validos em nome de pasta e, com
# -Path, virariam curinga (e poderiam apagar a exportacao de outro cenario).
function Export-ScenarioTraces {
    param(
        [string]$TraceRunDir,
        [string]$ExportarDir,
        [PSCustomObject]$State,
        [string]$LogFile
    )

    $dest = Get-ExportPath -ExportarDir $ExportarDir -State $State
    Write-Host "`n  Gerando pasta de exportacao..." -ForegroundColor DarkCyan

    if (-not (Test-Path -LiteralPath $TraceRunDir)) {
        Write-Host "  [!] Pasta Traces nao encontrada: $TraceRunDir" -ForegroundColor Red
        return $null
    }

    if (Test-Path -LiteralPath $dest) {
        Write-Host "  [i] Substituindo exportacao existente: $dest" -ForegroundColor DarkGray
        Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $dest) {
            Write-Host "  [!] Nao foi possivel limpar a exportacao anterior (arquivo aberto?). Feche os arquivos e use [E] para exportar de novo." -ForegroundColor Red
            if ($LogFile) { Add-Content -LiteralPath $LogFile -Value "[ERRO] Exportacao anterior nao pode ser removida: $dest" -Encoding UTF8 }
            return $null
        }
    }
    New-Item -ItemType Directory -Path $dest -Force | Out-Null

    # Um ZIP de uma exportacao anterior ficaria desatualizado: remove
    $staleZip = "$dest.zip"
    if (Test-Path -LiteralPath $staleZip) {
        Remove-Item -LiteralPath $staleZip -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $staleZip) {
            Write-Host "  [!] ZIP anterior (desatualizado) nao pode ser removido, esta aberto? $staleZip" -ForegroundColor Yellow
        } else {
            Write-Host "  [i] ZIP anterior removido (desatualizado): $staleZip" -ForegroundColor DarkGray
        }
    }

    # Contabiliza o que fica de fora (para o resumo). Soma sem Measure-Object:
    # no PS 5.1, Measure-Object de lista vazia nao tem .Sum (quebra no StrictMode).
    $srcFiles  = @(Get-ChildItem -LiteralPath $TraceRunDir -Recurse -File -Force -ErrorAction SilentlyContinue)
    $traceRoot = (Resolve-Path -LiteralPath $TraceRunDir).ProviderPath.TrimEnd('\')
    $excluded  = @($srcFiles | Where-Object {
        $rel = $_.FullName.Substring($traceRoot.Length)
        $_.Extension -eq '.etl' -or $_.Extension -eq '.log' -or $rel -match '(?i)\\logs\\'
    })
    $etlCount = @($excluded | Where-Object { $_.Extension -eq '.etl' }).Count
    [long]$excludedBytes = 0
    foreach ($f in $excluded) { $excludedBytes += $f.Length }

    # robocopy: /E subpastas; /XF e /XD exclusoes; exit code < 8 = sucesso.
    # Sem barra final: robocopy le '\"' como aspas escapadas em caminhos com espaco
    $null = & robocopy.exe $TraceRunDir.TrimEnd('\') $dest.TrimEnd('\') /E /XF *.etl *.log /XD logs /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        Write-Host "  [!] Falha ao copiar para a exportacao (robocopy exit $rc)." -ForegroundColor Red
        if ($LogFile) { Add-Content -LiteralPath $LogFile -Value "[ERRO] Exportacao falhou (robocopy exit $rc): $dest" -Encoding UTF8 }
        Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        return $null
    }

    # Remove pastas vazias, das mais profundas para as mais rasas
    Get-ChildItem -LiteralPath $dest -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { @(Get-ChildItem -LiteralPath $_.FullName -Force).Count -eq 0 } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

    $outFiles = @(Get-ChildItem -LiteralPath $dest -Recurse -File -Force -ErrorAction SilentlyContinue)
    [long]$outBytes = 0
    foreach ($f in $outFiles) { $outBytes += $f.Length }

    # Modulos que tinham arquivos em Traces/ mas so com .etl/logs (ex.: 1_cpu_memo
    # sem o .wpaProfile grava os .etl e pula os CSVs do WPA). Mesma regra dos
    # avisos da rodada; arquivos do proprio hub (frequencia_cpu.csv) nao contam.
    $emptyModules = @(Get-EmptyExportModules -TraceRunDir $TraceRunDir)

    $summary = [PSCustomObject]@{
        Path          = $dest
        Files         = $outFiles.Count
        SizeMB        = [Math]::Round($outBytes / 1MB, 1)
        ExcludedFiles = $excluded.Count
        ExcludedEtl   = $etlCount
        ExcludedMB    = [Math]::Round($excludedBytes / 1MB, 1)
        EmptyModules  = $emptyModules
    }

    Write-Host "  [OK] Exportacao pronta: $dest" -ForegroundColor Green
    Write-Host "       $($summary.Files) arquivo(s), $($summary.SizeMB) MB" -ForegroundColor DarkCyan
    Write-Host "       Fora da exportacao: $($summary.ExcludedFiles) arquivo(s) ($($summary.ExcludedEtl) .etl), $($summary.ExcludedMB) MB" -ForegroundColor DarkGray
    if ($LogFile) {
        Add-Content -LiteralPath $LogFile -Value "[INFO] Exportacao: $dest | $($summary.Files) arquivo(s), $($summary.SizeMB) MB | excluidos: $($summary.ExcludedFiles) ($($summary.ExcludedEtl) .etl), $($summary.ExcludedMB) MB" -Encoding UTF8
    }
    foreach ($m in $emptyModules) {
        Write-Host "  [!] $m sem evidencias do teste na exportacao: so tinha .etl, .log ou pastas logs/. Os originais estao apenas em Execucoes/ (verifique o teste, ex.: .wpaProfile ausente)." -ForegroundColor Yellow
        if ($LogFile) { Add-Content -LiteralPath $LogFile -Value "[AVISO] Modulo '$m' sem nenhum arquivo na exportacao (so .etl/logs em Traces)" -Encoding UTF8 }
    }
    return $summary
}

# ---- Exportacao de Cenario para ZIP ------------------------------------------

# Menu [E]: regera a pasta de exportacao de um cenario existente e oferece o ZIP.
function Export-ScenarioZip {
    param([string]$ExecucoesDir, [string]$ExportarDir)

    $scenarios = Get-ExistingScenarios -ExecucoesDir $ExecucoesDir

    if ($scenarios.Count -eq 0) {
        Write-Host "`n  [!] Nenhum cenario encontrado para exportar." -ForegroundColor Yellow
        return
    }

    Write-Host "`n  Cenarios disponiveis para exportacao:" -ForegroundColor Cyan
    for ($i = 0; $i -lt $scenarios.Count; $i++) {
        Write-Host "  $($i + 1). $($scenarios[$i].Name)" -ForegroundColor White
    }
    Write-Host ""

    while ($true) {
        $choice = Read-Host "  >> Escolha o cenario para exportar (ou Enter para voltar)"
        if ([string]::IsNullOrWhiteSpace($choice)) { return }
        $num = 0
        if ([int]::TryParse($choice, [ref]$num) -and $num -ge 1 -and $num -le $scenarios.Count) {
            $selected = $scenarios[$num - 1]
            $traceDir = Join-Path $selected.Path "Traces"
            $state    = Ensure-MachineIdentity -State $selected.State -TraceRunDir $traceDir
            $summary  = Export-ScenarioTraces -TraceRunDir $traceDir -ExportarDir $ExportarDir -State $state
            if ($null -ne $summary) { Request-ExportZip -ExportPath $summary.Path }
            return
        }
        Write-Host "  [!] Opcao invalida." -ForegroundColor Red
    }
}

# Pergunta se compacta a pasta exportada da maquina; o ZIP fica ao lado dela.
function Request-ExportZip {
    param([string]$ExportPath)
    Write-Host ""
    $zipChoice = Read-Host "  Deseja compactar a pasta exportada em ZIP? (S/N)"
    if ($zipChoice -eq 'S' -or $zipChoice -eq 's') {
        Compress-And-Validate -SourcePath $ExportPath -ZipPath "$ExportPath.zip"
    }
}

# Compacta SourcePath em ZipPath (com a pasta como raiz do ZIP) e valida pela
# contagem de arquivos. Nao apaga nada: Traces/ e a pasta exportada ficam.
function Compress-And-Validate {
    param(
        [string]$SourcePath,
        [string]$ZipPath
    )

    $name = Split-Path $SourcePath -Leaf
    Write-Host "`n  Compactando '$name'..." -ForegroundColor Cyan

    $originalCount = @(Get-ChildItem -LiteralPath $SourcePath -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    if ($originalCount -eq 0) {
        Write-Host "  [!] Pasta vazia. Nada para compactar." -ForegroundColor Yellow
        return
    }

    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
        # CreateFromDirectory: sem o limite de 2 GB do Compress-Archive no PS 5.1
        [System.IO.Compression.ZipFile]::CreateFromDirectory($SourcePath, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)

        $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            $zipFileCount = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') }).Count
        } finally {
            $zip.Dispose()
        }

        if ($zipFileCount -ne $originalCount) {
            Write-Host "  [!] ZIP incompleto: $originalCount arquivos na pasta, $zipFileCount no ZIP. ZIP descartado." -ForegroundColor Red
            Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
            $retry = Read-Host "  Deseja gerar o ZIP novamente? (S/N)"
            if ($retry -eq 'S' -or $retry -eq 's') {
                Compress-And-Validate -SourcePath $SourcePath -ZipPath $ZipPath
            }
            return
        }

        $zipMB = [Math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 1)
        Write-Host "  [OK] ZIP gerado e validado: $ZipPath `($zipFileCount arquivos, $zipMB MB`)" -ForegroundColor Green
    } catch {
        Write-Host "  [!] Erro ao gerar/validar ZIP: $($_.Exception.Message). ZIP descartado." -ForegroundColor Red
        # Nao deixa um ZIP parcial com o nome do ZIP valido
        Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    }
}

# ---- Avisos da rodada (_state.json -> _relatorio) ----------------------------

# Avisos ficam em $State.avisos ({ run, fonte, texto }), acumulados entre runs.
# Devolve os itens desenrolados: o chamador usa @() (convencao do hub).
# Fontes: checagem, sobra, modulo_vazio, csv_faltando, carga_dev, rede, throttling.
function Get-RunWarnings {
    param([PSCustomObject]$State)
    $prop = $State.PSObject.Properties['avisos']
    if ($null -eq $prop -or $null -eq $prop.Value) { return @() }
    return @($prop.Value)
}

function Add-RunWarning {
    param([PSCustomObject]$State, [int]$Run, [string]$Fonte, [string]$Texto)
    $list = Get-RunWarnings -State $State
    foreach ($w in $list) {
        if ($w.run -eq $Run -and $w.fonte -eq $Fonte -and $w.texto -eq $Texto) { return }
    }
    $list = @($list) + @([PSCustomObject]@{ run = $Run; fonte = $Fonte; texto = $Texto })
    $State | Add-Member -NotePropertyName avisos -NotePropertyValue $list -Force
}

# Modulos (pastas de 1o nivel de Traces) com arquivos, mas que ficariam vazios
# na exportacao: tudo neles e .etl, .log ou esta numa pasta logs/.
function Get-EmptyExportModules {
    param([string]$TraceRunDir)
    # Gerados pelo proprio hub em cada modulo: nao contam como evidencia do
    # teste (um modulo so com .etl + frequencia_cpu.csv continua "vazio").
    $hubGenerated = @("frequencia_cpu.csv")
    if (-not (Test-Path -LiteralPath $TraceRunDir)) { return @() }
    $root = (Resolve-Path -LiteralPath $TraceRunDir).ProviderPath.TrimEnd('\')
    $content = @{}
    foreach ($f in @(Get-ChildItem -LiteralPath $TraceRunDir -Recurse -File -Force -ErrorAction SilentlyContinue)) {
        $rel = $f.FullName.Substring($root.Length)
        $parts = $rel.TrimStart('\').Split('\')
        if ($parts.Count -lt 2) { continue }          # arquivo na raiz de Traces
        $m = $parts[0]
        if ($m -ieq 'logs') { continue }
        if (-not $content.ContainsKey($m)) { $content[$m] = $false }
        if ($hubGenerated -contains $f.Name) { continue }
        $excluded = ($f.Extension -eq '.etl' -or $f.Extension -eq '.log' -or $rel -match '(?i)\\logs\\')
        if (-not $excluded) { $content[$m] = $true }
    }
    return @($content.Keys | Where-Object { -not $content[$_] } | Sort-Object { Get-NaturalSortKey $_ })
}

# Cargas de dev (dev_*.csv) com status diferente de OK ou sensiveis a rede.
# Subpartes (carga:parte) ficam de fora.
function Get-DevCsvWarnings {
    param([string]$TraceRunDir, [string[]]$Folders)
    $out = [System.Collections.Generic.List[PSCustomObject]]::new()
    foreach ($folder in $Folders) {
        $dir = Join-Path $TraceRunDir $folder
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        foreach ($csv in @(Get-ChildItem -LiteralPath $dir -Filter "dev_*.csv" -File -ErrorAction SilentlyContinue)) {
            try { $rows = @(Import-Csv -LiteralPath $csv.FullName -Delimiter ';' -Encoding UTF8) } catch { continue }
            foreach ($r in $rows) {
                $carga = [string]$r.carga
                if (-not $carga -or $carga.Contains(':')) { continue }
                if ([string]$r.status -ne "OK") {
                    $motivo = if ($r.PSObject.Properties['motivo'] -and $r.motivo) { " -- $($r.motivo)" } else { "" }
                    $out.Add([PSCustomObject]@{ Fonte = "carga_dev"; Texto = "$folder/${carga}: $($r.status)$motivo" })
                }
                if ($r.PSObject.Properties['sensivel_rede'] -and [string]$r.sensivel_rede -eq "sim") {
                    $out.Add([PSCustomObject]@{ Fonte = "rede"; Texto = "$folder/${carga} depende da internet do lab (resultado sensivel a rede)" })
                }
            }
        }
    }
    return @($out)
}

# Teste 3 (rede.csv, Metrica,Valor,Unidade): fonte que nao terminou ok,
# medicao instavel (CV acima do limite), medicao no Wi-Fi e roaming.
function Get-NetworkWarnings {
    param([string]$TraceRunDir)
    $out = [System.Collections.Generic.List[PSCustomObject]]::new()
    $csv = Join-Path (Join-Path $TraceRunDir "3_rede") "rede.csv"
    if (-not (Test-Path -LiteralPath $csv)) { return @() }
    try { $rows = @(Import-Csv -LiteralPath $csv -Encoding UTF8) } catch { return @() }
    $v = @{}
    foreach ($r in $rows) { if ($r.PSObject.Properties['Metrica']) { $v[[string]$r.Metrica] = [string]$r.Valor } }
    if (-not $v.ContainsKey("Versao_Teste")) { return @() }   # rede.csv antigo (antes da unificacao)
    $rotulos = [ordered]@{ "Interno" = "speedtest interno"; "Internet" = "internet (fast.com)" }
    foreach ($p in $rotulos.Keys) {
        $st = $v["${p}_Status"]
        if ($st -and $st -ne "ok") {
            $motivo = if ($v["${p}_Motivo"] -and $v["${p}_Motivo"] -ne "N/A") { " -- $($v["${p}_Motivo"])" } else { "" }
            $out.Add([PSCustomObject]@{ Fonte = "rede"; Texto = "3_rede: $($rotulos[$p]) $st$motivo" })
        }
        if ($v["${p}_Estavel"] -eq "nao") {
            $out.Add([PSCustomObject]@{ Fonte = "rede"; Texto = "3_rede: $($rotulos[$p]) instavel (CV download $($v["${p}_Download_CV"])%, upload $($v["${p}_Upload_CV"])%)" })
        }
    }
    if ($v["Conexao_Tipo"] -eq "wifi" -or $v["Conexao_Tipo"] -eq "misto") {
        $out.Add([PSCustomObject]@{ Fonte = "rede"; Texto = "3_rede: medido com Wi-Fi ($($v["Conexao_Tipo"])) -- para comparar hardware, use cabo" })
    }
    if ($v["Roaming"] -eq "sim") {
        $onde = if ($v["Roaming_Rodadas"] -and $v["Roaming_Rodadas"] -ne "N/A") { " (antes de: $($v["Roaming_Rodadas"]))" } else { "" }
        $out.Add([PSCustomObject]@{ Fonte = "rede"; Texto = "3_rede: o Wi-Fi trocou de AP (BSSID) durante o teste$onde -- veja resultado_afericoes.csv" })
    }
    return @($out)
}

# ---- Frequencia da CPU durante os testes -------------------------------------

$script:CpuSamplerJob = $null

# O amostrador roda em testes (nao setups), exceto nas pastas de SkipFolders:
# no teste 5 (bateria) ele acordaria a CPU a cada poucos segundos por horas.
function Test-CpuSamplingEnabled {
    param([PSCustomObject]$Test, [PSCustomObject]$Settings)
    if ($Test.Kind -ne "test" -or -not $Settings.Enabled) { return $false }
    $skip = @()
    if ($Settings.PSObject.Properties['SkipFolders']) { $skip = @($Settings.SkipFolders) }
    return ($skip -notcontains $Test.ParentFolder)
}

function Start-CpuSampler {
    param([string]$OutFile, [int]$IntervalSec = 5)
    Stop-CpuSampler
    $IntervalSec = [Math]::Max(1, $IntervalSec)   # 0 viraria laco sem pausa
    # Amostrador em segundo plano (Start-Job): a cada IntervalSec grava uso, % de
    # desempenho (>100 = turbo), MHz efetivo e a maior zona termica ACPI. Usa CIM,
    # nao Get-Counter (nomes de contador sao localizados no Windows pt-BR).
    $sampler = {
        param([string]$OutFile, [int]$IntervalSec)
        $inv = [System.Globalization.CultureInfo]::InvariantCulture
        $cls = 'Win32_PerfFormattedData_Counters_ProcessorInformation'
        $tz  = 'Win32_PerfFormattedData_Counters_ThermalZoneInformation'
        $base = [double]((Get-CimInstance Win32_Processor | Select-Object -First 1).MaxClockSpeed)
        Set-Content -LiteralPath $OutFile -Value 'time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC' -Encoding ASCII
        $null = Get-CimInstance $cls -Filter "Name='_Total'"   # 1a leitura "formatted" vem zerada
        $thermal = $true
        while ($true) {
            Start-Sleep -Seconds $IntervalSec
            try {
                $p = Get-CimInstance $cls -Filter "Name='_Total'"
                $temp = ""
                if ($thermal) {
                    try {
                        $z = @(Get-CimInstance $tz -ErrorAction Stop)
                        if ($z.Count -eq 0) { $thermal = $false }
                        else {
                            $max = ($z | ForEach-Object { [double]$_.Temperature - 273.15 } | Measure-Object -Maximum).Maximum
                            $temp = ([Math]::Round($max, 1)).ToString($inv)
                        }
                    } catch { $thermal = $false }
                }
                $mhz = [Math]::Round($base * [double]$p.PercentProcessorPerformance / 100)
                $line = [string]::Format($inv, "{0},{1},{2},{3},{4}", (Get-Date -Format s), $p.PercentProcessorUtility, $p.PercentProcessorPerformance, $mhz, $temp)
                Add-Content -LiteralPath $OutFile -Value $line -Encoding ASCII
            } catch { }
        }
    }
    try {
        $script:CpuSamplerJob = Start-Job -ScriptBlock $sampler -ArgumentList $OutFile, $IntervalSec
    } catch {
        $script:CpuSamplerJob = $null
    }
}

function Stop-CpuSampler {
    # Get-Variable: no StrictMode, ler $script:CpuSamplerJob inexistente quebra
    $v = Get-Variable -Name CpuSamplerJob -Scope Script -ErrorAction SilentlyContinue
    if ($null -eq $v -or $null -eq $v.Value) { return }
    Stop-Job -Job $script:CpuSamplerJob -ErrorAction SilentlyContinue
    Remove-Job -Job $script:CpuSamplerJob -Force -ErrorAction SilentlyContinue
    $script:CpuSamplerJob = $null
}

function Get-Median {
    param([double[]]$Values)
    if ($null -eq $Values -or $Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $mid = [int][Math]::Floor($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 1) { return [double]$sorted[$mid] }
    return ([double]$sorted[$mid - 1] + [double]$sorted[$mid]) / 2
}

# Resumo de frequencia_cpu.csv. A queda (throttling) e medida so nas amostras
# sob carga (uso >= LoadMinPct): em ocioso o clock cai sem ser throttling.
# Compara a mediana do 1o minuto sob carga com a do ultimo minuto sob carga.
function Get-CpuFrequencySummary {
    param([string]$Csv, [int]$IntervalSec = 5, [double]$LoadMinPct = 50)
    if (-not (Test-Path -LiteralPath $Csv)) { return $null }
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $rows = @(Import-Csv -LiteralPath $Csv)
    if ($rows.Count -lt 3) { return $null }

    $mhz = [System.Collections.Generic.List[double]]::new()
    $loaded = [System.Collections.Generic.List[double]]::new()
    $temps = [System.Collections.Generic.List[double]]::new()
    foreach ($r in $rows) {
        $m = 0.0; $u = 0.0; $t = 0.0
        if (-not [double]::TryParse([string]$r.effectiveMHz, [System.Globalization.NumberStyles]::Float, $inv, [ref]$m)) { continue }
        $mhz.Add($m)
        if ([double]::TryParse([string]$r.cpuUtilPct, [System.Globalization.NumberStyles]::Float, $inv, [ref]$u) -and $u -ge $LoadMinPct) { $loaded.Add($m) }
        if ($r.PSObject.Properties['maxThermalC'] -and [double]::TryParse([string]$r.maxThermalC, [System.Globalization.NumberStyles]::Float, $inv, [ref]$t)) { $temps.Add($t) }
    }
    if ($mhz.Count -lt 3) { return $null }

    [double]$sum = 0
    foreach ($v in $mhz) { $sum += $v }
    $n = [Math]::Max(1, [int][Math]::Ceiling(60 / [Math]::Max(1, $IntervalSec)))
    $start = $null; $end = $null; $drop = $null
    if ($loaded.Count -ge 2 * $n) {
        $arr = $loaded.ToArray()
        $start = Get-Median -Values ($arr[0..($n - 1)])
        $end   = Get-Median -Values ($arr[($arr.Count - $n)..($arr.Count - 1)])
        if ($start -gt 0) { $drop = [Math]::Round((1 - $end / $start) * 100, 1) }
    }
    $maxTemp = $null
    if ($temps.Count -gt 0) { $maxTemp = ($temps | Measure-Object -Maximum).Maximum }

    return [PSCustomObject]@{
        Samples       = $mhz.Count
        LoadedSamples = $loaded.Count
        AvgMHz        = [Math]::Round($sum / $mhz.Count, 0)
        StartMHz      = $start
        EndMHz        = $end
        DropPct       = $drop
        MaxTempC      = $maxTemp
    }
}

# Avisos de fim de rodada, so para os modulos executados nesta run.
function Add-EndOfRunWarnings {
    param(
        [PSCustomObject]$State,
        [int]$Run,
        [string]$TraceRunDir,
        [string[]]$Folders,
        [string[]]$MissingCsvFolders = @(),
        [PSCustomObject]$Sampler
    )
    foreach ($m in (Get-EmptyExportModules -TraceRunDir $TraceRunDir)) {
        if ($Folders -contains $m) {
            Add-RunWarning -State $State -Run $Run -Fonte "modulo_vazio" -Texto "$m ficaria vazio na exportacao (so .etl/.log/logs): verifique o teste (ex.: .wpaProfile ausente)"
        }
    }
    foreach ($m in $MissingCsvFolders) {
        if ($Folders -contains $m) {
            Add-RunWarning -State $State -Run $Run -Fonte "csv_faltando" -Texto "$m executado, mas o CSV tematico nao foi gerado"
        }
    }
    foreach ($w in (Get-DevCsvWarnings -TraceRunDir $TraceRunDir -Folders $Folders)) {
        Add-RunWarning -State $State -Run $Run -Fonte $w.Fonte -Texto $w.Texto
    }
    if ($Folders -contains "3_rede") {
        foreach ($w in (Get-NetworkWarnings -TraceRunDir $TraceRunDir)) {
            Add-RunWarning -State $State -Run $Run -Fonte $w.Fonte -Texto $w.Texto
        }
    }
    if ($null -ne $Sampler -and $Sampler.Enabled) {
        foreach ($m in $Folders) {
            $s = Get-CpuFrequencySummary -Csv (Join-Path (Join-Path $TraceRunDir $m) "frequencia_cpu.csv") -IntervalSec ([int]$Sampler.IntervalSec) -LoadMinPct ([double]$Sampler.LoadMinPct)
            if ($null -ne $s -and $null -ne $s.DropPct -and $s.DropPct -ge [double]$Sampler.ThrottleAlertPct) {
                Add-RunWarning -State $State -Run $Run -Fonte "throttling" -Texto "${m}: clock sob carga caiu $($s.DropPct)% (de $($s.StartMHz) para $($s.EndMHz) MHz)"
            }
        }
    }
}

# ---- Checagem antes da fila (preflight) --------------------------------------

# Achado da checagem. Nivel: 'Impede' (o teste vai falhar) ou 'Atencao' (roda,
# mas a medicao pode sair comprometida). Sobra: objeto de Get-TestLeftovers
# quando o achado e um processo de teste que ficou aberto ([F] encerra).
function New-PreflightFinding {
    param([string]$Nivel, [string[]]$Testes, [string]$Item, [string]$Acao, $Sobra = $null)
    return [PSCustomObject]@{
        Nivel  = $Nivel
        Testes = @($Testes)
        Item   = $Item
        Acao   = $Acao
        Sobra  = $Sobra
    }
}

# Sondas do sistema: funcoes separadas para a CI poder substitui-las.
function Get-PowerSource {
    # 'AC' (na tomada), 'Battery' (na bateria) ou 'Desktop' (sem bateria)
    $bat = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
    if ($bat.Count -eq 0) { return "Desktop" }
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $line = [System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus
        if ("$line" -eq "Online") { return "AC" }
        if ("$line" -eq "Offline") { return "Battery" }
    } catch { }
    # Fallback: BatteryStatus 2 = na tomada (Win32_Battery)
    if ($bat[0].BatteryStatus -eq 2) { return "AC" }
    return "Battery"
}

function Test-InternetReachable {
    param([string]$HostName)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $ar = $client.BeginConnect($HostName, 443, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(3000) -and $client.Connected
        $client.Close()
        return [bool]$ok
    } catch { return $false }
}

function Get-FreeSpaceGB {
    param([string]$Path)
    try {
        $root = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $Path).ProviderPath)
        $drive = New-Object System.IO.DriveInfo($root)
        return [Math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    } catch { return $null }
}

# Versao de uma ferramenta: $null se o comando nao existe; Version $null se
# nao deu para ler. Mesma regex do Setup 7 e do dev_cargas.py.
function Get-ToolVersion {
    param([string]$Cmd, [string[]]$VersionArgs)
    $c = Get-Command $Cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    $out = ""
    try { $out = (& $c.Source @($VersionArgs) 2>&1 | Out-String).Trim() } catch { }
    $ver = $null
    if ($out -match '(\d+)\.(\d+)(\.(\d+))?') { $ver = [version]"$($Matches[1]).$($Matches[2])" }
    return [PSCustomObject]@{ Path = $c.Source; Output = $out; Version = $ver }
}

function Test-CommandAvailable {
    param([string]$Cmd)
    return [bool](Get-Command $Cmd -CommandType Application -ErrorAction SilentlyContinue)
}

function Test-LibreOfficeAvailable {
    if (-not [string]::IsNullOrWhiteSpace($env:HUB_LIBREOFFICE_PATH) -and (Test-Path -LiteralPath $env:HUB_LIBREOFFICE_PATH)) { return $true }
    if (Test-CommandAvailable -Cmd "soffice") { return $true }
    foreach ($p in @(
        "C:\Program Files\LibreOffice\program\soffice.exe",
        "C:\Program Files (x86)\LibreOffice\program\soffice.exe"
    )) {
        if (Test-Path -LiteralPath $p) { return $true }
    }
    return $false
}

function Test-SpeedtestConfigured {
    param([string]$HubRoot)
    if (-not [string]::IsNullOrWhiteSpace($env:HUB_SPEEDTEST_URL)) { return $true }
    $local = Join-Path $HubRoot "config.local.json"
    if (-not (Test-Path -LiteralPath $local)) { return $false }
    try {
        $j = Get-Content -LiteralPath $local -Raw | ConvertFrom-Json
        $p = $j.PSObject.Properties['SpeedtestUrl']
        return ($null -ne $p -and -not [string]::IsNullOrWhiteSpace([string]$p.Value))
    } catch { return $false }
}

# Ferramentas exigidas por um modulo de cargas de dev: cargas.json (+ o
# workloads.local.json, como no dev_cargas.py); git implicito quando ha repos.
function Get-DevModuleTools {
    param([string]$ModuleDir, [string]$HubRoot)
    $tools = [System.Collections.Generic.List[PSCustomObject]]::new()
    $file = Join-Path $ModuleDir "cargas.json"
    if (-not (Test-Path -LiteralPath $file)) { return ,$tools }
    try { $def = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return ,$tools }
    $hasRepos = $false
    $p = $def.PSObject.Properties['repos']
    if ($p -and @($p.Value).Count -gt 0) { $hasRepos = $true }
    $list = @()
    $p = $def.PSObject.Properties['ferramentas']
    if ($p) { $list = @($p.Value) }

    $localFile = Join-Path $HubRoot "workloads.local.json"
    if (Test-Path -LiteralPath $localFile) {
        try {
            $local = Get-Content -LiteralPath $localFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $mod = $local.PSObject.Properties[(Split-Path $ModuleDir -Leaf)]
            if ($mod) {
                $lp = $mod.Value.PSObject.Properties['ferramentas']
                if ($lp) {
                    foreach ($lt in @($lp.Value)) {
                        $list = @($list | Where-Object { $_.cmd -ne $lt.cmd }) + @($lt)
                    }
                }
                $lr = $mod.Value.PSObject.Properties['repos']
                if ($lr -and @($lr.Value).Count -gt 0) { $hasRepos = $true }
            }
        } catch { }
    }

    if ($hasRepos -and -not @($list | Where-Object { $_.cmd -eq 'git' })) {
        $tools.Add([PSCustomObject]@{ Cmd = "git"; VersionArgs = @("--version"); Minima = "" })
    }
    foreach ($t in $list) {
        $argsV = @("--version")
        $vp = $t.PSObject.Properties['versao']
        if ($vp -and @($vp.Value).Count -gt 1) { $argsV = @($vp.Value)[1..(@($vp.Value).Count - 1)] }
        $minima = ""
        $mp = $t.PSObject.Properties['minima']
        if ($mp) { $minima = [string]$mp.Value }
        $tools.Add([PSCustomObject]@{ Cmd = [string]$t.cmd; VersionArgs = $argsV; Minima = $minima })
    }
    return ,$tools
}

# Monta os achados da checagem so para os testes selecionados. Nao interage
# nem imprime nada (testavel na CI); a tela fica em Show-PreExecutionSummary.
function Get-PreflightFindings {
    param(
        [array]$Tests,
        [string]$TestsRoot,
        [string]$HubRoot,
        [PSCustomObject]$Settings,
        [switch]$SkipLeftovers
    )
    $findings = [System.Collections.Generic.List[PSCustomObject]]::new()
    $byFolder = [ordered]@{}
    foreach ($t in $Tests) {
        if (-not $byFolder.Contains($t.ParentFolder)) { $byFolder[$t.ParentFolder] = @() }
        $byFolder[$t.ParentFolder] += "$($t.Name).$($t.Type)"
    }
    $allNames = @($Tests | ForEach-Object { "$($_.Name).$($_.Type)" })

    # Modulos com captura WPR + exportacao WPA (0, 1 e 5): profile do WPA (nao
    # versionado; sem ele o modulo grava so .etl, horas depois) e o WPT no PATH.
    # O modulo 0 reutiliza o Agentes_SI_Profile.wpaProfile de 1_cpu_memo quando
    # nao ha copia propria em 0_consumo_basal.
    $wpaModules = [ordered]@{
        "0_consumo_basal" = @("Agentes_SI_Profile.wpaProfile", "1_cpu_memo")
        "1_cpu_memo"      = @("Agentes_SI_Profile.wpaProfile", $null)
        "5_bateria"       = @("Agentes_SI_Bateria_Profile.wpaProfile", $null)
    }
    foreach ($folder in $wpaModules.Keys) {
        if (-not $byFolder.Contains($folder)) { continue }
        $names = $byFolder[$folder]
        $profileName, $fallbackFolder = $wpaModules[$folder]
        $dir = Join-Path $TestsRoot $folder
        $searchDirs = @($dir)
        if ($fallbackFolder) { $searchDirs += (Join-Path $TestsRoot $fallbackFolder) }
        $foundProfile = $false
        foreach ($sd in $searchDirs) {
            $prof = Join-Path $sd $profileName
            if ((Test-Path -LiteralPath $prof) -or (Test-Path -LiteralPath "$prof.xml")) {
                $foundProfile = $true
                break
            }
        }
        if (-not $foundProfile) {
            $acao = if ($fallbackFolder) {
                "Copie o $profileName para $dir ou $(Join-Path $TestsRoot $fallbackFolder)"
            } else {
                "Copie o $profileName para $dir"
            }
            $findings.Add((New-PreflightFinding "Impede" $names "$profileName ausente (sem ele o modulo grava so .etl e nenhum CSV do WPA)" $acao))
        }
        foreach ($exe in "wpr", "wpaexporter") {
            if (-not (Test-CommandAvailable -Cmd $exe)) {
                $findings.Add((New-PreflightFinding "Impede" $names "$exe.exe nao encontrado no PATH ($folder)" "Instale o Windows Performance Toolkit (Windows ADK) e reabra o hub"))
            }
        }
    }

    # Modulos com carga no LibreOffice: 1 (ciclos Writer/Calc) e 5 (fase ativa da bateria v2.0)
    $loModules = [ordered]@{
        "1_cpu_memo" = '^1_automacao_performance\.'
        "5_bateria"  = '^5_teste_bateria\.'
    }
    $loDisponivel = $null
    foreach ($folder in $loModules.Keys) {
        if (-not $byFolder.Contains($folder)) { continue }
        $pattern = $loModules[$folder]
        $loNames = @($byFolder[$folder] | Where-Object { $_ -match $pattern })
        if ($loNames.Count -eq 0) { continue }
        if ($null -eq $loDisponivel) { $loDisponivel = [bool](Test-LibreOfficeAvailable) }
        if (-not $loDisponivel) {
            $findings.Add((New-PreflightFinding "Impede" $loNames "LibreOffice (soffice.exe) nao encontrado ($folder)" "Instale: rode o Setup 3_softwares_msStore"))
        }
    }

    # Cargas de dev (7-11): ferramentas na versao minima do cargas.json
    $devFolders = @($byFolder.Keys | Where-Object { Test-Path -LiteralPath (Join-Path (Join-Path $TestsRoot $_) "cargas.json") })
    foreach ($folder in $devFolders) {
        foreach ($tool in (Get-DevModuleTools -ModuleDir (Join-Path $TestsRoot $folder) -HubRoot $HubRoot)) {
            $setup = if ($tool.Cmd -eq "podman") { "rode o Setup 10_preparar_podman" } else { "rode o Setup 7_install_devtools_dev" }
            $v = Get-ToolVersion -Cmd $tool.Cmd -VersionArgs $tool.VersionArgs
            if ($null -eq $v) {
                $findings.Add((New-PreflightFinding "Impede" $byFolder[$folder] "'$($tool.Cmd)' nao encontrado ($folder)" "Instale: $setup"))
            } elseif ($tool.Minima -and ($null -eq $v.Version -or $v.Version -lt [version]$tool.Minima)) {
                $findings.Add((New-PreflightFinding "Impede" $byFolder[$folder] "'$($tool.Cmd)' abaixo da versao minima $($tool.Minima) ($folder): $(($v.Output -split "`n")[0])" "Atualize: $setup"))
            }
        }
    }

    # Modulo 10: a podman machine precisa estar ligada (o hub a desliga entre
    # testes quando a fila nao precisa mais dela, e o modulo nao a liga sozinho)
    if ($byFolder.Contains("10_dev_containers") -and (Test-CommandAvailable -Cmd "podman")) {
        $pod = Get-PodmanState
        if ($pod.Available -and -not $pod.MachineRunning) {
            $findings.Add((New-PreflightFinding "Impede" $byFolder["10_dev_containers"] "podman machine desligada (o modulo 10 precisa dela ligada)" "Rode 'podman machine start' ou o Setup 10_preparar_podman"))
        }
    }

    # Tomada: as cargas de dev dao FAIL na bateria; o teste 5 e o unico que
    # deve rodar na bateria; o resto mede pior (plano de energia muda).
    $power = Get-PowerSource
    if ($power -eq "Battery") {
        $devNames   = @($devFolders | ForEach-Object { $byFolder[$_] })
        $otherNames = @($byFolder.Keys | Where-Object { $_ -ne "5_bateria" -and $devFolders -notcontains $_ } | ForEach-Object { $byFolder[$_] })
        if ($devNames.Count -gt 0) {
            $findings.Add((New-PreflightFinding "Impede" $devNames "Notebook na bateria (as cargas de dev dao FAIL fora da tomada)" "Conecte o carregador"))
        }
        if ($otherNames.Count -gt 0) {
            $findings.Add((New-PreflightFinding "Atencao" $otherNames "Notebook na bateria (o plano de energia muda a medicao)" "Conecte o carregador"))
        }
    }

    # Internet: sondada uma vez, so quando um teste selecionado precisa dela
    $netNames = @($byFolder.Keys | Where-Object { $devFolders -contains $_ } | ForEach-Object { $byFolder[$_] })
    $internetOk = $true
    if ($netNames.Count -gt 0 -or $byFolder.Contains("3_rede")) {
        $internetOk = [bool](Test-InternetReachable -HostName $Settings.InternetHost)
    }

    # Teste 3 (rede): mede o speedtest interno (URL fora do repositorio) e o
    # fast.com. Uma fonte fora vira so aviso no teste; as duas fora = FAIL.
    if ($byFolder.Contains("3_rede")) {
        $semUrl = -not (Test-SpeedtestConfigured -HubRoot $HubRoot)
        $acaoUrl = "Defina HUB_SPEEDTEST_URL ou SpeedtestUrl no config.local.json (veja config.local.example.json)"
        if ($semUrl -and -not $internetOk) {
            $findings.Add((New-PreflightFinding "Impede" $byFolder["3_rede"] "Rede: URL do speedtest interno nao configurada e sem acesso a internet ($($Settings.InternetHost):443) -- nenhuma das duas fontes pode ser medida" $acaoUrl))
        } elseif ($semUrl) {
            $findings.Add((New-PreflightFinding "Atencao" $byFolder["3_rede"] "Rede: URL do speedtest interno nao configurada -- so a internet (fast.com) sera medida" $acaoUrl))
        } elseif (-not $internetOk) {
            $findings.Add((New-PreflightFinding "Atencao" $byFolder["3_rede"] "Rede: sem acesso a internet ($($Settings.InternetHost):443) -- so o speedtest interno sera medido" "Verifique a rede/proxy antes de iniciar"))
        }
    }

    # Cargas de dev (clones, pacotes, imagens)
    if ($netNames.Count -gt 0 -and -not $internetOk) {
        $findings.Add((New-PreflightFinding "Atencao" $netNames "Sem acesso a internet ($($Settings.InternetHost):443)" "Verifique a rede/proxy antes de iniciar"))
    }

    # Disco do hub: evidencias (.etl do WPR chegam a 400 MB cada)
    $free = Get-FreeSpaceGB -Path $HubRoot
    if ($null -ne $free -and $free -lt [double]$Settings.MinFreeGB) {
        $findings.Add((New-PreflightFinding "Atencao" $allNames "Pouco espaco livre no disco do hub: $free GB (minimo $($Settings.MinFreeGB) GB)" "Libere espaco (ex.: exporte e apague cenarios antigos em Execucoes)"))
    }

    if (-not $SkipLeftovers) {
        # A podman machine so e sobra se nenhum teste da fila precisa dela
        $needsPodman = @($byFolder.Keys | Where-Object { $_ -eq "10_dev_containers" }).Count -gt 0
        foreach ($l in (Get-TestLeftovers -TestsRoot $TestsRoot -KeepPodmanMachine:$needsPodman)) {
            if ($l.Id -eq "dotnet") {
                # Antes da fila nao da para saber se sao do teste 7 ou do Visual
                # Studio do usuario: so aviso, sem [F] (entre testes, o filtro por
                # PID garante que so os do teste sao encerrados).
                $findings.Add((New-PreflightFinding "Atencao" $allNames "Build servers do .NET ativos ($($l.Detalhe))" "Se forem de um teste anterior, rode 'dotnet build-server shutdown'; se forem do Visual Studio, ignore"))
                continue
            }
            $findings.Add((New-PreflightFinding "Atencao" $allNames "Sobra de teste: $($l.Nome) ($($l.Detalhe))" "[F] encerra" -Sobra $l))
        }
        foreach ($h in (Get-HighCpuProcesses -ThresholdPct ([double]$Settings.CpuAlertPct))) {
            $findings.Add((New-PreflightFinding "Atencao" $allNames "Processo usando CPU: $($h.Name) (PID $($h.Id), $($h.CpuPct)% de um nucleo)" "Feche-o se nao for necessario (o hub nao encerra processos que nao sao de teste)"))
        }
    }
    return ,$findings
}

# ---- Sobras de teste (processos que nao fecharam direito) --------------------

# Sondas (substituiveis na CI)
function Get-ProcessSnapshot {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object Name, ProcessId, ParentProcessId, CommandLine)
}

function Get-WprStatus {
    if (-not (Get-Command wpr -CommandType Application -ErrorAction SilentlyContinue)) { return $null }
    $out = (& wpr -status 2>&1 | Out-String)
    return [PSCustomObject]@{ ExitCode = $LASTEXITCODE; Output = $out }
}

function Get-PodmanState {
    $state = [PSCustomObject]@{ Available = $false; Containers = @(); MachineRunning = $false }
    if (-not (Get-Command podman -CommandType Application -ErrorAction SilentlyContinue)) { return $state }
    $state.Available = $true
    try {
        $m = (& podman machine inspect --format "{{.State}}" 2>$null | Out-String).Trim()
        $state.MachineRunning = ($m -match '(?i)running')
        if ($state.MachineRunning) {
            $state.Containers = @(& podman ps --filter "name=wintestehub-" --format "{{.Names}}" 2>$null | Where-Object { $_ -match '\S' })
        }
    } catch { }
    return $state
}

# WPR gravando? "WPR is not recording" (en) / "nao esta gravando" (pt) = parado.
function Test-WprRecording {
    param($Status)
    if ($null -eq $Status) { return $false }
    $o = [string]$Status.Output
    if ($o -match '(?i)not recording|n.o est. gravando|nenhuma grava') { return $false }
    return ($o -match '(?i)recording|gravando|grava..o em andamento')
}

# Processos abertos por testes do hub. Detecta pela linha de comando ou por
# flags de automacao, nunca so pelo nome (o Edge e o Python do usuario ficam).
# Testes: pastas de teste que costumam deixar a sobra (filtro entre testes).
function Get-TestLeftovers {
    param(
        [string]$TestsRoot,
        [string[]]$Folders = @(),
        [switch]$KeepPodmanMachine,
        [int[]]$IgnorePids = @()
    )
    $out = [System.Collections.Generic.List[PSCustomObject]]::new()
    $add = {
        param($Id, $Nome, $Detalhe, $Pids, $Testes)
        if ($Folders.Count -gt 0 -and $Testes -ne "*" -and -not @($Testes | Where-Object { $Folders -contains $_ })) { return }
        $out.Add([PSCustomObject]@{ Id = $Id; Nome = $Nome; Detalhe = $Detalhe; Pids = @($Pids) })
    }

    if (Test-WprRecording (Get-WprStatus)) {
        & $add "wpr" "sessao do WPR gravando" "wpr -status" @() @("0_consumo_basal", "1_cpu_memo", "5_bateria")
    }

    # IgnorePids: processos que ja existiam antes do teste (entre testes, so o
    # que o proprio teste abriu e sobra; o Visual Studio do usuario fica).
    $procs = @(Get-ProcessSnapshot | Where-Object { $IgnorePids -notcontains [int]$_.ProcessId })
    $testsRootNorm = $TestsRoot.TrimEnd('\') + '\'

    $byName = {
        param([string]$Pattern)
        @($procs | Where-Object { $_.Name -match $Pattern })
    }

    foreach ($exe in @(@{ N = "wpaexporter"; T = @("0_consumo_basal", "1_cpu_memo", "5_bateria") }, @{ N = "diskspd"; T = @("2_disco") })) {
        $p = @(& $byName ("^" + $exe.N + "\.exe$"))
        if ($p.Count -gt 0) { & $add $exe.N "$($exe.N).exe" "$($p.Count) processo(s)" @($p | ForEach-Object { $_.ProcessId }) $exe.T }
    }

    # Edge da automacao: msedgedriver, ou msedge com --enable-automation ou
    # aberto pelo driver. So --remote-debugging-port nao basta (VS Code/DevTools).
    $drv  = @(& $byName '^msedgedriver\.exe$')
    $drvPids = @($drv | ForEach-Object { [int]$_.ProcessId })
    $edge = @($procs | Where-Object { $_.Name -match '^msedge\.exe$' -and ([string]$_.CommandLine -match '--enable-automation' -or $drvPids -contains [int]$_.ParentProcessId) })
    $edgePids = @($drv | ForEach-Object { $_.ProcessId }) + @($edge | ForEach-Object { $_.ProcessId })
    if ($edgePids.Count -gt 0) {
        & $add "edge" "Edge da automacao" "$($drv.Count) msedgedriver, $($edge.Count) msedge" $edgePids @("3_rede", "6_wifi_fast_transition")
    }

    # LibreOffice da automacao: soffice.exe ou soffice.bin com subperfil wintesthub_lo_profile
    $lo = @($procs | Where-Object { $_.Name -match '^soffice\.(exe|bin)$' -and [string]$_.CommandLine -match '(?i)wintesthub_lo_profile' })
    $loPids = @($lo | ForEach-Object { $_.ProcessId })
    if ($loPids.Count -gt 0) {
        & $add "libreoffice" "LibreOffice da automacao" "$($lo.Count) processo(s)" $loPids @("1_cpu_memo", "5_bateria")
    }

    # Python rodando um script de Testes\ (o hub roda um teste por vez; fora
    # de um teste, qualquer um desses e sobra)
    $py = @($procs | Where-Object {
        $_.Name -match '^pythonw?(3)?(\.\d+)?\.exe$' -and [string]$_.CommandLine -and
        ([string]$_.CommandLine).IndexOf($testsRootNorm, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    if ($py.Count -gt 0) { & $add "python" "script Python de teste" "$($py.Count) processo(s)" @($py | ForEach-Object { $_.ProcessId }) "*" }

    # Build servers do .NET (node reuse do MSBuild e o compilador Roslyn)
    $bs = @($procs | Where-Object {
        $_.Name -match '^VBCSCompiler\.exe$' -or
        ($_.Name -match '^(MSBuild|dotnet)\.exe$' -and [string]$_.CommandLine -match '(?i)nodeReuse:true|MSBuild\.dll.*/nodemode|VBCSCompiler')
    })
    if ($bs.Count -gt 0) { & $add "dotnet" "build servers do .NET" "$($bs.Count) processo(s)" @($bs | ForEach-Object { $_.ProcessId }) @("7_dev_dotnet") }

    # Podman: stack do modulo 10 e a podman machine (WSL, vmmem ocupa RAM)
    $pod = Get-PodmanState
    if ($pod.Available) {
        if (@($pod.Containers).Count -gt 0) {
            & $add "compose" "stack do modulo 10 (podman compose)" ((@($pod.Containers)) -join ", ") @() @("10_dev_containers")
        }
        if ($pod.MachineRunning -and -not $KeepPodmanMachine) {
            & $add "podman-machine" "podman machine ligada" "ocupa RAM (vmmem)" @() @("10_dev_containers")
        }
    }
    return ,$out
}

# Encerra as sobras do jeito certo de cada uma. Devolve as descricoes do que
# foi encerrado (para log e avisos da rodada).
function Stop-TestLeftovers {
    param([array]$Leftovers, [string]$TestsRoot)
    $done = [System.Collections.Generic.List[string]]::new()
    foreach ($l in $Leftovers) {
        try {
            switch ($l.Id) {
                "wpr"            { & wpr -cancel 2>&1 | Out-Null }
                "dotnet"         {
                    # So os PIDs detectados (ja filtrados pelos que o teste abriu):
                    # 'dotnet build-server shutdown' derrubaria tambem os do Visual Studio
                    foreach ($p in $l.Pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
                }
                "compose"        {
                    $compose = Join-Path (Join-Path $TestsRoot "10_dev_containers") "compose.yml"
                    & podman compose -f $compose down -v 2>&1 | Out-Null
                }
                "podman-machine" { & podman machine stop 2>&1 | Out-Null }
                "libreoffice"    {
                    # Encerra apenas os PIDs do LibreOffice do teste (sem /T), preservando
                    # descendentes nao relacionados ou processos protegidos por IgnorePids.
                    $errosTk = [System.Collections.Generic.List[string]]::new()
                    foreach ($p in $l.Pids) {
                        $global:LASTEXITCODE = 0
                        try {
                            $tkOut = (& taskkill.exe /F /PID $p 2>&1 | Out-String).Trim()
                            if ($LASTEXITCODE -ne 0) {
                                $errosTk.Add("PID ${p}: codigo $LASTEXITCODE$(if ($tkOut) { " ($tkOut)" })")
                            }
                        } catch {
                            $errosTk.Add("PID ${p}: $($_.Exception.Message)")
                        }
                    }
                    if ($errosTk.Count -gt 0) { throw ($errosTk -join "; ") }
                }
                default          {
                    # taskkill /T leva junto os filhos (ex.: msedge aberto pelo driver)
                    $errosTk = [System.Collections.Generic.List[string]]::new()
                    foreach ($p in $l.Pids) {
                        $global:LASTEXITCODE = 0
                        try {
                            $tkOut = (& taskkill.exe /T /F /PID $p 2>&1 | Out-String).Trim()
                            if ($LASTEXITCODE -ne 0) {
                                $errosTk.Add("PID ${p}: codigo $LASTEXITCODE$(if ($tkOut) { " ($tkOut)" })")
                            }
                        } catch {
                            $errosTk.Add("PID ${p}: $($_.Exception.Message)")
                        }
                    }
                    if ($errosTk.Count -gt 0) { throw ($errosTk -join "; ") }
                }
            }
            $done.Add("$($l.Nome) ($($l.Detalhe))")
        } catch {
            $done.Add("$($l.Nome): falha ao encerrar ($($_.Exception.Message))")
        }
    }
    return ,$done
}

# Os processos que mais usaram CPU numa janela curta (% de UM nucleo).
# So aviso: o hub nao sabe se sao do usuario e nunca os encerra.
function Get-HighCpuProcesses {
    param([double]$ThresholdPct = 10, [int]$WindowSec = 3, [int]$Top = 5)
    $first = @{}
    foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
        try { if ($null -ne $p.CPU) { $first[$p.Id] = [double]$p.CPU } } catch { }
    }
    Start-Sleep -Seconds $WindowSec
    $rows = @()
    foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
        if ($p.Id -eq $PID -or $p.Id -eq 0 -or $p.Name -eq "Idle") { continue }
        if (-not $first.ContainsKey($p.Id)) { continue }
        try { $pct = (([double]$p.CPU - $first[$p.Id]) / $WindowSec) * 100 } catch { continue }
        if ($pct -ge $ThresholdPct) { $rows += [PSCustomObject]@{ Name = $p.Name; Id = $p.Id; CpuPct = [Math]::Round($pct, 0) } }
    }
    return @($rows | Sort-Object CpuPct -Descending | Select-Object -First $Top)
}

# Entre testes da fila: encerra, sem perguntar, as sobras do teste que acabou
# (a fila e desassistida). A podman machine fica se ainda vem teste do 10.
function Clear-TestLeftovers {
    param([PSCustomObject]$After, [array]$Remaining, [string]$TestsRoot, [string]$LogFile, [int[]]$PidsBefore = @())
    $needsPodman = @($Remaining | Where-Object { $_.ParentFolder -eq "10_dev_containers" }).Count -gt 0
    $left = Get-TestLeftovers -TestsRoot $TestsRoot -Folders @($After.ParentFolder) -KeepPodmanMachine:$needsPodman -IgnorePids $PidsBefore
    if ($left.Count -eq 0) { return ,@() }
    $done = Stop-TestLeftovers -Leftovers $left -TestsRoot $TestsRoot
    foreach ($d in $done) {
        if ($LogFile) { Add-Content -LiteralPath $LogFile -Value "[AVISO] Sobra de $($After.Name) encerrada antes do proximo teste: $d" -Encoding UTF8 }
    }
    return ,@($done)
}

# ---- MAIN -------------------------------------------------------------------

Write-Header

Write-Host "  [!] Removendo bloqueios de seguranca (Unblock-File)..." -ForegroundColor DarkGray
Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

foreach ($dir in @($ExportarDir, $ExecucoesDir)) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

Write-Host ""

# ---- Selecao de cenario -----------------------------------------------------
$scenarioChoice = Show-ScenarioMenu -ExecucoesDir $ExecucoesDir

$previousResults = @{}
$currentRunId    = 1

# Tratar modo "export" (opcao [E])
if ($scenarioChoice.Mode -eq "export") {
    Export-ScenarioZip -ExecucoesDir $ExecucoesDir -ExportarDir $ExportarDir
    exit 0
}

if ($scenarioChoice.Mode -eq "continue") {
    $scenarioDir     = $scenarioChoice.Path
    $traceRunDir     = Join-Path $scenarioDir "Traces"
    $logRunDir       = Join-Path $scenarioDir "Logs"
    if (-not (Test-Path -LiteralPath $logRunDir)) { New-Item -ItemType Directory -Path $logRunDir -Force | Out-Null }
    $stateObj        = Ensure-MachineIdentity -State $scenarioChoice.State -TraceRunDir $traceRunDir
    $previousResults = Get-LatestTestResults -State $stateObj
    $currentRunId    = ($stateObj.runs | Measure-Object).Count + 1
    Write-Host "`n  Continuando cenario: $(Split-Path $scenarioDir -Leaf) `(run #$currentRunId`)" -ForegroundColor Cyan
} else {
    $runStamp           = Get-Date -Format "yyyy-MM-dd"
    $scenarioFolderName = "$($scenarioChoice.Name)_$($env:COMPUTERNAME)_$runStamp"
    $scenarioDir        = Join-Path $ExecucoesDir $scenarioFolderName

    if (Test-Path -LiteralPath $scenarioDir) {
        $scenarioFolderName += "_" + (Get-Date -Format "HH-mm-ss")
        $scenarioDir = Join-Path $ExecucoesDir $scenarioFolderName
    }

    $traceRunDir = Join-Path $scenarioDir "Traces"
    $logRunDir   = Join-Path $scenarioDir "Logs"
    New-Item -ItemType Directory -Path $traceRunDir -Force | Out-Null
    New-Item -ItemType Directory -Path $logRunDir -Force | Out-Null

    $stateObj = New-StateObject -Scenario $scenarioChoice.Name -Machine $env:COMPUTERNAME -Modelo $scenarioChoice.Modelo -Patrimonio $scenarioChoice.Patrimonio
    Write-StateFile -TraceRunDir $traceRunDir -State $stateObj
    Write-Host "`n  Novo cenario criado: $(Split-Path $scenarioDir -Leaf)" -ForegroundColor Cyan
}

$logFile     = Join-Path $logRunDir "run_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$resultsFile = Join-Path $logRunDir "run_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

$allResults    = [System.Collections.Generic.List[PSCustomObject]]::new()
$setupResults  = [System.Collections.Generic.List[PSCustomObject]]::new()
$runStart      = Get-Date

$logHeader = "WINTESTHUB -- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`nHost: $env:COMPUTERNAME | User: $env:USERNAME`nCenario: $(Split-Path $scenarioDir -Leaf) | Run: #$currentRunId`nSetupRoot: $SetupRoot`nTestsRoot: $TestsRoot`nTracesDir: $traceRunDir`nLogsDir: $logRunDir`nExportar: $(Get-ExportPath -ExportarDir $ExportarDir -State $stateObj)`n$('-'*62)"
Add-Content -LiteralPath $logFile -Value $logHeader -Encoding UTF8

# ==== FASE 1: PREPARACAO =====================================================

if (-not $SkipSetup) {
    $allSetup = Get-Scripts -Root $SetupRoot -Kind "setup"
    if ($allSetup.Count -gt 0) {
        Write-Host ""
        Write-Host "  +------------------------------------------+" -ForegroundColor DarkYellow
        Write-Host "  |   FASE 1 -- PREPARACAO DA MAQUINA        |" -ForegroundColor DarkYellow
        Write-Host "  +------------------------------------------+" -ForegroundColor DarkYellow

        $setupMenuItems = Build-MenuItems -Scripts $allSetup -PreviousResults $previousResults
        Write-Host "`n  $($allSetup.Count) script(s) encontrados. Selecione os que deseja executar:`n" -ForegroundColor White

        $afterSetup = Show-CheckboxMenu -Items $setupMenuItems
        $setupToRun = @($afterSetup | Where-Object { $_.IsTestItem -and $_.Selected })

        if ($setupToRun.Count -gt 0) {
            Add-Content -LiteralPath $logFile -Value "`n-- PREPARACAO ($($setupToRun.Count) script(s)) --" -Encoding UTF8
            Write-Host "`n  Executando $($setupToRun.Count) script(s) de preparacao...`n" -ForegroundColor DarkYellow

            foreach ($s in $setupToRun) {
                Write-Host "  >> $($s.Display) [$($s.Type.ToUpper())] ..." -ForegroundColor DarkYellow
                $res = Invoke-TestScript -Test $s -LogFile $logFile -TraceRunDir $traceRunDir
                $allResults.Add($res)
                $setupResults.Add($res)

                $statusClr = if ($res.Status -eq "PASS") { "Green" } elseif ($res.Status -eq "FAIL") { "Red" } else { "Yellow" }
                Write-Host "  >> Resultado: $($res.Status) ($([Math]::Round($res.Duration,2))s)`n" -ForegroundColor $statusClr

                if ($res.Status -ne "PASS") {
                    Write-Host "  [!] Script de preparacao falhou. Deseja continuar? (S para continuar)" -ForegroundColor Yellow
                    Clear-KeyBuffer
                    $confirm = [Console]::ReadKey($true)
                    if ($confirm.KeyChar -ne 's' -and $confirm.KeyChar -ne 'S') {
                        Write-Host "`n  Execucao abortada.`n" -ForegroundColor Red
                        Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds
                        exit 1
                    }
                }
            }
        } else { Write-Host "`n  Nenhum setup selecionado.`n" -ForegroundColor DarkGray }
    }
}

$env:PATH = "$([System.Environment]::GetEnvironmentVariable('Path', 'Machine'));$([System.Environment]::GetEnvironmentVariable('Path', 'User'))"

# ==== FASE 2: TESTES =========================================================

Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |   FASE 2 -- TESTES DE HARDWARE           |" -ForegroundColor Cyan
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan

$allTests = Get-Scripts -Root $TestsRoot -Kind "test"
if ($allTests.Count -eq 0) { exit 0 }

$confirmed = $false
while (-not $confirmed) {
    $testMenuItems = Build-MenuItems -Scripts $allTests -PreviousResults $previousResults -TestSections $TestSectionsConfig
    Write-Host "`n  $($allTests.Count) teste(s) encontrado(s):`n" -ForegroundColor White

    $afterMenu = Show-CheckboxMenu -Items $testMenuItems
    # So itens de teste (nunca cabecalhos), na ordem do menu: Escritorio -> Dev -> Opcional
    $toRun     = @($afterMenu | Where-Object { $_.IsTestItem -and $_.Selected })

    if ($toRun.Count -eq 0) {
        if ($allResults.Count -gt 0) {
            Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds
        }
        exit 0
    }

    # Checagem + resumo pre-execucao. R/F refazem a checagem; ESC volta ao menu.
    $decided = $false
    while (-not $decided) {
        Write-Host "`n  Checando pre-requisitos e sobras de teste..." -ForegroundColor DarkCyan
        $findings = Get-PreflightFindings -Tests $toRun -TestsRoot $TestsRoot -HubRoot $PSScriptRoot -Settings $PreflightSettings
        $choice = Show-PreExecutionSummary -TestsToRun $toRun -ScenarioName $scenarioChoice.Name -TraceRunDir $traceRunDir -RunId $currentRunId -PreviousResults $previousResults -Findings $findings
        switch ($choice) {
            "back"   {
                foreach ($f in $findings) { Add-Content -LiteralPath $logFile -Value "[CHECAGEM] [$($f.Nivel)] $($f.Item) -- operador voltou ao menu" -Encoding UTF8 }
                $decided = $true
            }
            "kill"   {
                $sobras = @($findings | Where-Object { $null -ne $_.Sobra } | ForEach-Object { $_.Sobra })
                Write-Host "`n  Encerrar $($sobras.Count) sobra(s) de teste? (S/N)" -ForegroundColor Yellow
                Clear-KeyBuffer
                $k = [Console]::ReadKey($true)
                if ($k.KeyChar -ne 's' -and $k.KeyChar -ne 'S') {
                    Add-Content -LiteralPath $logFile -Value "[CHECAGEM] Operador recusou encerrar $($sobras.Count) sobra(s) de teste" -Encoding UTF8
                }
                if ($k.KeyChar -eq 's' -or $k.KeyChar -eq 'S') {
                    foreach ($d in (Stop-TestLeftovers -Leftovers $sobras -TestsRoot $TestsRoot)) {
                        Write-Host "  [OK] Encerrado: $d" -ForegroundColor Green
                        Add-Content -LiteralPath $logFile -Value "[INFO] Sobra encerrada antes da fila: $d" -Encoding UTF8
                        Add-RunWarning -State $stateObj -Run $currentRunId -Fonte "sobra" -Texto "Encerrada antes da fila: $d"
                    }
                }
            }
            "remove" {
                $removed = @($toRun | Where-Object { @(Remove-BlockedTests -Tests @($_) -Findings $findings).Count -eq 0 })
                $toRun = @(Remove-BlockedTests -Tests $toRun -Findings $findings)
                foreach ($r in $removed) {
                    $rName  = "$($r.Name).$($r.Type)"
                    $reason = Get-BlockReason -TestName $rName -Findings $findings
                    $rText  = if ($reason) { "$rName ($reason)" } else { $rName }
                    Add-Content -LiteralPath $logFile -Value "[AVISO] Teste tirado da fila pela checagem: $rText" -Encoding UTF8
                    Add-RunWarning -State $stateObj -Run $currentRunId -Fonte "checagem" -Texto "Tirado da fila pela checagem: $rText"
                }
                if ($toRun.Count -eq 0) {
                    Write-Host "`n  [!] Nenhum teste restou na fila." -ForegroundColor Yellow
                    $decided = $true
                }
            }
            default  {
                # start (sem impedimentos) ou continue (operador seguiu mesmo assim)
                foreach ($f in $findings) {
                    $txt = "[$($f.Nivel)] $($f.Item)"
                    if ($f.Nivel -eq "Impede") { $txt += " -- operador continuou mesmo assim ($(($f.Testes) -join ', '))" }
                    Add-Content -LiteralPath $logFile -Value "[CHECAGEM] $txt" -Encoding UTF8
                    Add-RunWarning -State $stateObj -Run $currentRunId -Fonte "checagem" -Texto $txt
                }
                $confirmed = $true
                $decided   = $true
            }
        }
    }
}

# Mover evidencias anteriores para testes que serao re-executados
$testResults = [System.Collections.Generic.List[PSCustomObject]]::new()

foreach ($t in $toRun) {
    $fileName = "$($t.Name).$($t.Type)"
    if ($null -ne $previousResults -and $previousResults.ContainsKey($fileName)) {
        $prevFolder = $previousResults[$fileName].folder
        $prevRunId  = $previousResults[$fileName].runId
        $scriptTraceDir = Join-Path $traceRunDir $prevFolder
        Move-EvidenceToAnterior -ScriptTraceDir $scriptTraceDir -RunId $prevRunId
    }
}

Add-Content -LiteralPath $logFile -Value "`n-- TESTES ($($toRun.Count) script(s)) --" -Encoding UTF8

# Painel de progresso: monitor ao vivo (rich) ou painel estatico classico
$liveCheck = Test-LiveMonitorAvailable -Settings $LiveMonitorSettings -PythonExe (Resolve-PythonExe -VenvPath $VenvPath) -MonitorScript $LiveMonitorScript
$useLiveMonitor = $liveCheck.Available
if ($useLiveMonitor) {
    Add-Content -LiteralPath $logFile -Value "[i] Monitor ao vivo (live_monitor.py) ativo nesta rodada." -Encoding UTF8
    $progressY = 0
} else {
    if ($LiveMonitorSettings.Enabled) {
        Add-Content -LiteralPath $logFile -Value "[!] Monitor ao vivo indisponivel ($($liveCheck.Reason)); usando o painel classico." -Encoding UTF8
        Write-Host "  [!] Monitor ao vivo indisponivel ($($liveCheck.Reason)); usando o painel classico." -ForegroundColor DarkYellow
    }
    $progressY = Show-ExecutionProgress -TestsToRun $toRun -RunId $currentRunId
}

$stopFile = Join-Path $env:TEMP "wintesthub_parada_$PID.flag"
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
$env:HUB_STOP_FILE = $stopFile

for ($idx = 0; $idx -lt $toRun.Count; $idx++) {
    $test = $toRun[$idx]
    $livePayload = $null
    if ($useLiveMonitor) {
        $livePayload = New-LiveMonitorStatePayload -State $stateObj -RunId $currentRunId -RunStart $runStart -Tests $toRun -Results @($testResults.ToArray()) -CurrentIndex $idx -Settings $LiveMonitorSettings -Sampler $CpuSamplerSettings
        Clear-Host
    } else {
        Update-ProgressLine -Y $progressY -TestIndex $idx -Name $test.Name -Type $test.Type -Status "running" -Detail "" -Current ($idx + 1) -Total $toRun.Count
    }

    $pidsBefore = @(Get-Process -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
    $res = Invoke-TestScript -Test $test -LogFile $logFile -TraceRunDir $traceRunDir -Silent -LivePayload $livePayload
    $allResults.Add($res)
    $testResults.Add($res)

    # Sobras do teste que acabou (WPR, Edge, build servers, stack do podman...)
    $remaining = @()
    if ($idx + 1 -lt $toRun.Count) { $remaining = @($toRun[($idx + 1)..($toRun.Count - 1)]) }
    foreach ($d in (Clear-TestLeftovers -After $test -Remaining $remaining -TestsRoot $TestsRoot -LogFile $logFile -PidsBefore $pidsBefore)) {
        Add-RunWarning -State $stateObj -Run $currentRunId -Fonte "sobra" -Texto "Encerrada apos $($test.Name).$($test.Type): $d"
    }

    $detail = "$([Math]::Round($res.Duration, 1))s"
    if ($res.ErrorSnippet) {
        $lastErrLine = ($res.ErrorSnippet -split "`n")[-1].Trim()
        if ($lastErrLine.Length -gt 60) { $lastErrLine = $lastErrLine.Substring(0, 57) + "..." }
        $detail += "  >>  $lastErrLine"
    }
    if ($useLiveMonitor) {
        $cor = if ($res.Status -eq "PASS") { "Green" } elseif ($res.Status -eq "FAIL") { "Red" } else { "Yellow" }
        Write-Host "  [$($idx + 1)/$($toRun.Count)] $($test.Name).$($test.Type): $($res.Status)  $detail" -ForegroundColor $cor
    } else {
        Update-ProgressLine -Y $progressY -TestIndex $idx -Name $test.Name -Type $test.Type -Status $res.Status -Detail $detail -Current ($idx + 1) -Total $toRun.Count
    }

    if (Test-StopSignal -StopFile $stopFile) {
        if (-not $useLiveMonitor) {
            for ($j = $idx + 1; $j -lt $toRun.Count; $j++) {
                Update-ProgressLine -Y $progressY -TestIndex $j -Name $toRun[$j].Name -Type $toRun[$j].Type -Status "CANCEL" -Detail "(Ctrl+Q)" -Current ($idx + 1) -Total $toRun.Count
            }
        }
        $restantes = $toRun.Count - $idx - 1
        Add-Content -LiteralPath $logFile -Value "`n[!] Fila interrompida pelo operador (Ctrl+Q) em $($test.Name). $restantes teste(s) nao executado(s)." -Encoding UTF8
        if (-not $useLiveMonitor) { Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 1) }
        Write-Host "  [!] Ctrl+Q: fila interrompida em $($test.Name). $restantes teste(s) cancelado(s)." -ForegroundColor Yellow
        Clear-KeyBuffer
        break
    }

    if ($res.Status -ne "PASS") {
        # No modo ao vivo o live_monitor.py ja fechou o Live: a pergunta sai abaixo do ultimo quadro
        if (-not $useLiveMonitor) { Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 1) }
        Write-Host "  [!] Teste falhou. Deseja continuar? (S para continuar)" -ForegroundColor Yellow
        Clear-KeyBuffer
        $confirm = [Console]::ReadKey($true)
        if ($confirm.KeyChar -ne 's' -and $confirm.KeyChar -ne 'S') {
            Write-Host "`n  Execucao abortada.`n" -ForegroundColor Red
            break
        }
    }
}

$env:HUB_STOP_FILE = ""
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

# Posicionar cursor abaixo do painel (o monitor ao vivo ja deixa o cursor no fim)
if (-not $useLiveMonitor) { Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 2) }

# Atualizar state file (setup + testes combinados)
$combinedResults = @($setupResults.ToArray()) + @($testResults.ToArray())
$stateObj = Add-RunToState -State $stateObj -Results $combinedResults
Write-StateFile -TraceRunDir $traceRunDir -State $stateObj

# Relatorio por run (Logs/)
Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds

# ---- Inventario da maquina, CSVs tematicos, avisos e relatorio consolidado --
Collect-MachineInfo -OutputDir $traceRunDir -State $stateObj
$thematic   = Test-ThematicCSVs -TraceRunDir $traceRunDir -LogFile $logFile
$runFolders = @($testResults | ForEach-Object { Split-Path $_.TraceDir -Leaf } | Select-Object -Unique)
Add-EndOfRunWarnings -State $stateObj -Run $currentRunId -TraceRunDir $traceRunDir -Folders $runFolders -MissingCsvFolders $thematic.MissingFolders -Sampler $CpuSamplerSettings
Write-StateFile -TraceRunDir $traceRunDir -State $stateObj
Build-ConsolidatedReport -TraceRunDir $traceRunDir -State $stateObj

# ---- Pasta de exportacao (Traces sem .etl, logs e pastas vazias) ------------
$exportSummary = Export-ScenarioTraces -TraceRunDir $traceRunDir -ExportarDir $ExportarDir -State $stateObj -LogFile $logFile

# ---- Pergunta de ZIP (da pasta exportada) -----------------------------------
if ($null -ne $exportSummary) { Request-ExportZip -ExportPath $exportSummary.Path }