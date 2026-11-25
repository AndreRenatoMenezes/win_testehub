Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# ---- Carregar Configuracoes (JSON) -------------------------------------------
$configFile = Join-Path $PSScriptRoot "config.json"

if (-not (Test-Path $configFile)) {
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
    }
    $defaultConfig | ConvertTo-Json -Depth 5 | Set-Content $configFile -Encoding UTF8
}

$config = Get-Content $configFile | ConvertFrom-Json

$SetupRoot     = Join-Path $PSScriptRoot $config.Paths.SetupRoot
$TestsRoot     = Join-Path $PSScriptRoot $config.Paths.TestsRoot
# ExportarDir: config.json antigo (com ResultadosDir) nao tem a chave -> padrao "Exportar"
$exportarRel   = if ($config.Paths.PSObject.Properties['ExportarDir']) { $config.Paths.ExportarDir } else { "Exportar" }
$ExportarDir   = Join-Path $PSScriptRoot $exportarRel
$ExecucoesDir  = Join-Path $PSScriptRoot $config.Paths.ExecucoesDir
$SkipSetup     = $config.SkipSetup
$VenvPath      = Join-Path $PSScriptRoot $config.Settings.PythonVenvName

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

    if (-not (Test-Path $Root)) {
        Write-Host "  [!] Pasta '$Root' nao encontrada -- criando estrutura..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
    }

    # Ordenacao natural: numeros com zeros a esquerda na chave, para "10_x" vir
    # depois de "9_x" (Sort-Object Name puro colocaria "10_" antes de "1_").
    # dev_cargas.py e a biblioteca comum dos modulos 7 a 11, nao um teste.
    $files = Get-ChildItem -Path $Root -Recurse -Include "*.ps1","*.py" -Exclude "boot_shutdown_duration.ps1","dev_cargas.py" -ErrorAction SilentlyContinue |
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
    if (Test-Path $stateFile) {
        try {
            return (Get-Content $stateFile -Raw | ConvertFrom-Json)
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
    $State | ConvertTo-Json -Depth 10 | Set-Content $stateFile -Encoding UTF8
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
    if (-not (Test-Path $ExecucoesDir)) { return ,$scenarios }

    $dirs = Get-ChildItem -Path $ExecucoesDir -Directory -ErrorAction SilentlyContinue
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

function Build-MenuItems {
    param(
        [System.Collections.Generic.List[PSCustomObject]]$Scripts,
        [hashtable]$PreviousResults
    )
    $items = [System.Collections.Generic.List[PSCustomObject]]::new()
    $lastFolder = ""

    foreach ($s in $Scripts) {
        if ($s.ParentFolder -ne $lastFolder) {
            $label = ($s.ParentFolder -replace '^\d+_', '' -replace '_', ' ')
            $label = (Get-Culture).TextInfo.ToTitleCase($label)
            $items.Add([PSCustomObject]@{
                IsSeparator  = $true
                Display      = $label
                Name         = ""
                Selected     = $false
                Selectable   = $false
                PrevStatus   = $null
                PrevDuration = 0
                PrevRunId    = 0
            })
            $lastFolder = $s.ParentFolder
        }

        $fileName = "$($s.Name).$($s.Type)"
        $prev = if ($null -ne $PreviousResults -and $PreviousResults.ContainsKey($fileName)) { $PreviousResults[$fileName] } else { $null }
        $isPending = ($null -eq $prev)

        $items.Add([PSCustomObject]@{
            IsSeparator  = $false
            Display      = $s.Display
            Name         = $s.Name
            Path         = $s.Path
            Type         = $s.Type
            Kind         = $s.Kind
            ParentFolder = $s.ParentFolder
            Selected     = $isPending
            Selectable   = $true
            PrevStatus   = if ($prev) { $prev.status } else { $null }
            PrevDuration = if ($prev) { $prev.duration } else { 0 }
            PrevRunId    = if ($prev) { $prev.runId } else { 0 }
        })
    }
    return ,$items
}

function Show-CheckboxMenu {
    param([System.Collections.Generic.List[PSCustomObject]]$Items)

    $selectableIdx = [System.Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Items.Count; $i++) {
        if ($Items[$i].Selectable) { $selectableIdx.Add($i) }
    }
    if ($selectableIdx.Count -eq 0) { return $Items }

    $cursorPos  = 0
    $maxVisible = [Math]::Min(20, [Console]::WindowHeight - 12)
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
            $selCount = @($Items | Where-Object { $_.Selected }).Count
            $totalSel = $selectableIdx.Count

            Safe-SetCursorPosition -X 0 -Y $startY
            Write-PaddedLine -Text "  Selecionados: $selCount/$totalSel  |  setas Navegar  ESPACO Selecionar  A Todos  P Pendentes  ENTER Confirmar  ESC Cancelar" -Color DarkGray -Width $width
            Write-PaddedLine -Width $width

            for ($slot = 0; $slot -lt $maxSlots; $slot++) {
                $i = $scrollOff + $slot
                if ($i -lt $Items.Count) {
                    $it = $Items[$i]
                    if ($it.IsSeparator) {
                        $sepLine = "  -- $($it.Display) $('-' * [Math]::Max(1, 40 - $it.Display.Length))"
                        Write-PaddedLine -Text $sepLine -Color Cyan -Width $width
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

                        Write-Host $fullPadded.Substring(0, $linePadded.Length) -NoNewline -ForegroundColor $clr
                        Write-Host $fullPadded.Substring($linePadded.Length) -ForegroundColor $statusClr
                    }
                } else { Write-PaddedLine -Width $width }
            }

            Write-PaddedLine -Width $width
            Write-PaddedLine -Width $width

            $key = [Console]::ReadKey($true)
            switch ($key.Key) {
                "UpArrow"   { $cursorPos = [Math]::Max(0, $cursorPos - 1) }
                "DownArrow" { $cursorPos = [Math]::Min($selectableIdx.Count - 1, $cursorPos + 1) }
                "Spacebar"  { $Items[$actualIdx].Selected = -not $Items[$actualIdx].Selected }
                "A" {
                    $allSel = (@($Items | Where-Object { $_.Selectable -and -not $_.Selected }).Count -eq 0)
                    $Items | Where-Object { $_.Selectable } | ForEach-Object { $_.Selected = -not $allSel }
                }
                "P" {
                    $Items | Where-Object { $_.Selectable } | ForEach-Object {
                        $_.Selected = ($null -eq $_.PrevStatus)
                    }
                }
                "Enter"  { return $Items }
                "Escape" {
                    $Items | Where-Object { $_.Selectable } | ForEach-Object { $_.Selected = $false }
                    return $Items
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

    if (-not (Test-Path $ScriptTraceDir)) { return }

    $files = Get-ChildItem -Path $ScriptTraceDir -File -ErrorAction SilentlyContinue
    $dirs  = Get-ChildItem -Path $ScriptTraceDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "_anterior" }

    if (($files | Measure-Object).Count -eq 0 -and ($dirs | Measure-Object).Count -eq 0) { return }

    $ts = Get-Date -Format "yyyy-MM-ddTHH-mm-ss"
    $anteriorDir = Join-Path $ScriptTraceDir "_anterior"
    $runBackup   = Join-Path $anteriorDir "run${RunId}_$ts"
    New-Item -ItemType Directory -Path $runBackup -Force | Out-Null

    foreach ($f in $files) {
        Move-Item -Path $f.FullName -Destination $runBackup -Force
    }
    foreach ($d in $dirs) {
        Move-Item -Path $d.FullName -Destination $runBackup -Force
    }
}

# ---- Resumo pre-execucao ----------------------------------------------------

function Show-PreExecutionSummary {
    param(
        [array]$TestsToRun,
        [string]$ScenarioName,
        [string]$TraceRunDir,
        [int]$RunId,
        [hashtable]$PreviousResults
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

    Write-Host ""
    Write-Host "  Pressione ENTER para iniciar ou ESC para voltar" -ForegroundColor DarkGray

    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq "Enter") { return $true }
        if ($key.Key -eq "Escape") { return $false }
    }
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

# ---- Execucao de cada script -------------------------------------------------

function Invoke-TestScript {
    param([PSCustomObject]$Test, [string]$LogFile, [string]$TraceRunDir, [switch]$Silent)

    $scriptTraceDir = Join-Path $TraceRunDir "$($Test.ParentFolder)"
    New-Item -ItemType Directory -Path $scriptTraceDir -Force | Out-Null
    
    $env:HUB_EVIDENCE_DIR = $scriptTraceDir 
    $env:HUB_TRACE_DIR    = $scriptTraceDir
    $env:HUB_TRACE_ROOT   = $TraceRunDir

    $startTime = Get-Date
    $status    = "PASS"
    $output    = ""
    $exitCode  = 0

    try {
        $capturedOut = [System.Collections.Generic.List[string]]::new()
        
        if ($Test.Type -eq "ps1") {
            & powershell.exe -NonInteractive -NoProfile -ExecutionPolicy Bypass -File $Test.Path 2>&1 | ForEach-Object {
                $line = $_.ToString()
                $capturedOut.Add($line)
                if (-not $Silent) { Write-Host "      | $line" -ForegroundColor DarkGray }
            }
            $exitCode = $LASTEXITCODE
        }
        elseif ($Test.Type -eq "py") {
            # Logica de detecao do Virtual Environment (.venv)
            $venvExe = Join-Path $VenvPath "Scripts\python.exe"
            if (Test-Path $venvExe) {
                $pyExe = $venvExe
            } else {
                $pyExe = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }
            }

            & $pyExe -u $Test.Path 2>&1 | ForEach-Object {
                $line = $_.ToString()
                $capturedOut.Add($line)
                if (-not $Silent) { Write-Host "      | $line" -ForegroundColor DarkGray }
            }
            $exitCode = $LASTEXITCODE
        }

        $output = ($capturedOut -join "`n").Trim()
        if ($exitCode -ne 0) { $status = "FAIL" }
    }
    catch {
        $status   = "ERROR"
        $output   = $_.Exception.Message
        $exitCode = -1
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

    $traceFiles = @(Get-ChildItem -Path $scriptTraceDir -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*\_anterior\*" })
    $traceCount = $traceFiles.Count

    $logEntry = "`n$('-'*62)`n[$ts]  $($Test.Kind.ToUpper()) | $($Test.Name)  [$($Test.Type.ToUpper())]`nSTATUS    : $status`nDURATION  : $([Math]::Round($duration,3))s`nEXIT CODE : $exitCode`nTRACES    : $traceCount arquivo(s) em $scriptTraceDir`nOUTPUT    :`n$output"
    Add-Content -Path $LogFile -Value $logEntry -Encoding UTF8

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
    Set-Content -Path $csvPath -Value $csvLines -Encoding UTF8

    # ---- Exporta JSON
    $jsonPath = "$ResultsFile.json"
    $jsonObj  = [PSCustomObject]@{ RunTimestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); Host = $env:COMPUTERNAME; TotalScripts = $Results.Count; Pass = $pass; Fail = $fail; Error = $err; TotalDuration = [Math]::Round($TotalSec,3); TotalTraces = $totalTraces; Scripts = $Results }
    $jsonObj | ConvertTo-Json -Depth 5 | Set-Content -Path $jsonPath -Encoding UTF8

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
    Set-Content -Path $htmlPath -Value $html -Encoding UTF8

    # Appenda resumo no log
    $summaryLog = "`n$('-'*62)`nRESUMO FINAL`nTotal: $($Results.Count) | PASS: $pass | FAIL: $fail | ERROR: $err`nTempo total: $([Math]::Round($TotalSec,2))s`nTraces: $totalTraces arquivo(s)`nHTML Gerado em: $htmlPath`n$('-'*62)"
    Add-Content -Path $LogFile -Value $summaryLog -Encoding UTF8
    
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
    Set-Content -Path $csvPath -Value $csvLines -Encoding UTF8

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
    }
    $jsonObj | ConvertTo-Json -Depth 5 | Set-Content -Path $jsonPath -Encoding UTF8

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
    </body>
    </html>
"@
    Set-Content -Path $htmlPath -Value $html -Encoding UTF8

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
    Set-Content -Path $csvPath -Value $csvLines -Encoding UTF8
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
        "1_cpu_memo"       = "cpu_memoria.csv"
        "2_disco"          = "disco.csv"
        "3_rede"           = "rede.csv"
        "3_rede_internet"  = "rede_internet.csv"
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

    foreach ($folder in ($expectedCSVs.Keys | Sort-Object { Get-NaturalSortKey $_ })) {
        $csvName = $expectedCSVs[$folder]
        $sourcePath = Join-Path $TraceRunDir (Join-Path $folder $csvName)

        if (Test-Path $sourcePath) {
            Write-Host "  [OK] $csvName" -ForegroundColor Green
            $found++
        } else {
            $testFolder = Join-Path $TraceRunDir $folder
            if (Test-Path $testFolder) {
                Write-Host "  [!] $csvName nao encontrado -- teste executado mas CSV nao foi gerado" -ForegroundColor Yellow
                Add-Content -Path $LogFile -Value "[AVISO] CSV tematico '$csvName' nao gerado pelo teste em '$folder'" -Encoding UTF8
                $missing++
            } else {
                Write-Host "  [--] $csvName -- teste pendente `($folder nao executado`)" -ForegroundColor DarkGray
                Add-Content -Path $LogFile -Value "[INFO] CSV tematico '$csvName' pendente -- teste '$folder' nao executado" -Encoding UTF8
            }
        }
    }

    foreach ($relPath in $variantCSVs.Keys) {
        if (Test-Path (Join-Path $TraceRunDir $relPath)) {
            Write-Host "  [OK] $($variantCSVs[$relPath])" -ForegroundColor Green
            $found++
        }
    }

    if ($missing -gt 0) { $resultColor = "Yellow" } else { $resultColor = "Green" }
    Write-Host "  Resultado: ${found} encontrado`(s`), ${missing} ausente`(s`)" -ForegroundColor $resultColor
    return [PSCustomObject]@{ Found = $found; Missing = $missing }
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
            if ($LogFile) { Add-Content -Path $LogFile -Value "[ERRO] Exportacao anterior nao pode ser removida: $dest" -Encoding UTF8 }
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
        if ($LogFile) { Add-Content -Path $LogFile -Value "[ERRO] Exportacao falhou (robocopy exit $rc): $dest" -Encoding UTF8 }
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

    # Modulos que tinham arquivos em Traces/ mas sumiram da exportacao (so .etl/logs):
    # ex.: 1_cpu_memo sem o .wpaProfile grava os .etl e pula os CSVs do WPA.
    # Pastas de 1o nivel com arquivos na origem (reaproveita $srcFiles); 'logs' e
    # excluida de proposito pelo robocopy, entao nao conta como modulo vazio.
    $srcModules = @($srcFiles | ForEach-Object {
        $rel = $_.FullName.Substring($traceRoot.Length).TrimStart('\')
        if ($rel.Contains('\')) { $rel.Split('\')[0] }
    } | Select-Object -Unique)
    $emptyModules = @()
    foreach ($m in $srcModules) {
        if ($m -ieq 'logs') { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $dest $m))) { $emptyModules += $m }
    }

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
        Add-Content -Path $LogFile -Value "[INFO] Exportacao: $dest | $($summary.Files) arquivo(s), $($summary.SizeMB) MB | excluidos: $($summary.ExcludedFiles) ($($summary.ExcludedEtl) .etl), $($summary.ExcludedMB) MB" -Encoding UTF8
    }
    foreach ($m in $emptyModules) {
        Write-Host "  [!] $m ficou fora da exportacao: so tinha .etl, .log ou pastas logs/. As evidencias estao apenas em Execucoes/ (verifique o teste, ex.: .wpaProfile ausente)." -ForegroundColor Yellow
        if ($LogFile) { Add-Content -Path $LogFile -Value "[AVISO] Modulo '$m' sem nenhum arquivo na exportacao (so .etl/logs em Traces)" -Encoding UTF8 }
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

# ---- MAIN -------------------------------------------------------------------

Write-Header

Write-Host "  [!] Removendo bloqueios de seguranca (Unblock-File)..." -ForegroundColor DarkGray
Get-ChildItem -Path $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

foreach ($dir in @($ExportarDir, $ExecucoesDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
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
    if (-not (Test-Path $logRunDir)) { New-Item -ItemType Directory -Path $logRunDir -Force | Out-Null }
    $stateObj        = Ensure-MachineIdentity -State $scenarioChoice.State -TraceRunDir $traceRunDir
    $previousResults = Get-LatestTestResults -State $stateObj
    $currentRunId    = ($stateObj.runs | Measure-Object).Count + 1
    Write-Host "`n  Continuando cenario: $(Split-Path $scenarioDir -Leaf) `(run #$currentRunId`)" -ForegroundColor Cyan
} else {
    $runStamp           = Get-Date -Format "yyyy-MM-dd"
    $scenarioFolderName = "$($scenarioChoice.Name)_$($env:COMPUTERNAME)_$runStamp"
    $scenarioDir        = Join-Path $ExecucoesDir $scenarioFolderName

    if (Test-Path $scenarioDir) {
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
Add-Content -Path $logFile -Value $logHeader -Encoding UTF8

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
        $setupToRun = @($afterSetup | Where-Object { $_.Selectable -and $_.Selected })

        if ($setupToRun.Count -gt 0) {
            Add-Content -Path $logFile -Value "`n-- PREPARACAO ($($setupToRun.Count) script(s)) --" -Encoding UTF8
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
    $testMenuItems = Build-MenuItems -Scripts $allTests -PreviousResults $previousResults
    Write-Host "`n  $($allTests.Count) teste(s) encontrado(s):`n" -ForegroundColor White

    $afterMenu = Show-CheckboxMenu -Items $testMenuItems
    $toRun     = @($afterMenu | Where-Object { $_.Selectable -and $_.Selected })

    if ($toRun.Count -eq 0) {
        if ($allResults.Count -gt 0) {
            Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds
        }
        exit 0
    }

    # Resumo pre-execucao
    $confirmed = Show-PreExecutionSummary -TestsToRun $toRun -ScenarioName $scenarioChoice.Name -TraceRunDir $traceRunDir -RunId $currentRunId -PreviousResults $previousResults
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

Add-Content -Path $logFile -Value "`n-- TESTES ($($toRun.Count) script(s)) --" -Encoding UTF8

# Painel de progresso
$progressY = Show-ExecutionProgress -TestsToRun $toRun -RunId $currentRunId

$stopFile = Join-Path $env:TEMP "wintesthub_parada_$PID.flag"
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
$env:HUB_STOP_FILE = $stopFile

for ($idx = 0; $idx -lt $toRun.Count; $idx++) {
    $test = $toRun[$idx]
    Update-ProgressLine -Y $progressY -TestIndex $idx -Name $test.Name -Type $test.Type -Status "running" -Detail "" -Current ($idx + 1) -Total $toRun.Count

    $res = Invoke-TestScript -Test $test -LogFile $logFile -TraceRunDir $traceRunDir -Silent
    $allResults.Add($res)
    $testResults.Add($res)

    $detail = "$([Math]::Round($res.Duration, 1))s"
    if ($res.ErrorSnippet) {
        $lastErrLine = ($res.ErrorSnippet -split "`n")[-1].Trim()
        if ($lastErrLine.Length -gt 60) { $lastErrLine = $lastErrLine.Substring(0, 57) + "..." }
        $detail += "  >>  $lastErrLine"
    }
    Update-ProgressLine -Y $progressY -TestIndex $idx -Name $test.Name -Type $test.Type -Status $res.Status -Detail $detail -Current ($idx + 1) -Total $toRun.Count

    if (Test-StopSignal -StopFile $stopFile) {
        for ($j = $idx + 1; $j -lt $toRun.Count; $j++) {
            Update-ProgressLine -Y $progressY -TestIndex $j -Name $toRun[$j].Name -Type $toRun[$j].Type -Status "CANCEL" -Detail "(Ctrl+Q)" -Current ($idx + 1) -Total $toRun.Count
        }
        $restantes = $toRun.Count - $idx - 1
        Add-Content -Path $logFile -Value "`n[!] Fila interrompida pelo operador (Ctrl+Q) em $($test.Name). $restantes teste(s) nao executado(s)." -Encoding UTF8
        Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 1)
        Write-Host "  [!] Ctrl+Q: fila interrompida em $($test.Name). $restantes teste(s) cancelado(s)." -ForegroundColor Yellow
        Clear-KeyBuffer
        break
    }

    if ($res.Status -ne "PASS") {
        Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 1)
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

# Posicionar cursor abaixo do painel
Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 2)

# Atualizar state file (setup + testes combinados)
$combinedResults = @($setupResults.ToArray()) + @($testResults.ToArray())
$stateObj = Add-RunToState -State $stateObj -Results $combinedResults
Write-StateFile -TraceRunDir $traceRunDir -State $stateObj

# Relatorio por run (Logs/)
Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds

# ---- Inventario da maquina, relatorio consolidado e CSVs tematicos ----------
Collect-MachineInfo -OutputDir $traceRunDir -State $stateObj
Build-ConsolidatedReport -TraceRunDir $traceRunDir -State $stateObj
Test-ThematicCSVs -TraceRunDir $traceRunDir -LogFile $logFile | Out-Null

# ---- Pasta de exportacao (Traces sem .etl, logs e pastas vazias) ------------
$exportSummary = Export-ScenarioTraces -TraceRunDir $traceRunDir -ExportarDir $ExportarDir -State $stateObj -LogFile $logFile

# ---- Pergunta de ZIP (da pasta exportada) -----------------------------------
if ($null -ne $exportSummary) { Request-ExportZip -ExportPath $exportSummary.Path }