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
            ResultadosDir = "Resultados"
            ExecucoesDir  = "Execucoes"
        }
        Settings = @{
            PythonVenvName  = ".venv"
            HtmlReportTitle = "Hardware Test Hub - Relatorio Final"
        }
    }
    $defaultConfig | ConvertTo-Json -Depth 5 | Set-Content $configFile -Encoding UTF8
}

$config = Get-Content $configFile | ConvertFrom-Json

$SetupRoot     = Join-Path $PSScriptRoot $config.Paths.SetupRoot
$TestsRoot     = Join-Path $PSScriptRoot $config.Paths.TestsRoot
$ResultadosDir = Join-Path $PSScriptRoot $config.Paths.ResultadosDir
$ExecucoesDir  = Join-Path $PSScriptRoot $config.Paths.ExecucoesDir
$SkipSetup     = $config.SkipSetup
$VenvPath      = Join-Path $PSScriptRoot $config.Settings.PythonVenvName

# ---- Banner ------------------------------------------------------------------

function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host "  |         HARDWARE  TEST  HUB              |" -ForegroundColor Cyan
    Write-Host "  |  .ps1 + .py  |  multi-select  |  log     |" -ForegroundColor DarkCyan
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host ""
}

# ---- Descoberta de scripts ---------------------------------------------------

function Get-Scripts {
    param([string]$Root, [string]$Kind)
    $scripts = [System.Collections.Generic.List[PSCustomObject]]::new()

    if (-not (Test-Path $Root)) {
        Write-Host "  [!] Pasta '$Root' nao encontrada -- criando estrutura..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $Root -Force | Out-Null
    }

    $files = Get-ChildItem -Path $Root -Recurse -Include "*.ps1","*.py" -Exclude "boot_shutdown_duration.ps1" -ErrorAction SilentlyContinue | Sort-Object Name

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
    param([string]$Scenario, [string]$Machine)
    return [PSCustomObject]@{
        scenario  = $Scenario
        machine   = $Machine
        createdAt = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        lastRunAt = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        runs      = @()
    }
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

function Show-ScenarioMenu {
    param([string]$ExecucoesDir)
    $scenarios = Get-ExistingScenarios -ExecucoesDir $ExecucoesDir

    if ($scenarios.Count -eq 0) {
        $nome = Read-Host "  >> Digite o Nome do Teste (Ex: ImagemLimpa, PosUpdate) [Enter para: Execucao]"
        if ([string]::IsNullOrWhiteSpace($nome)) { $nome = "Execucao" }
        return [PSCustomObject]@{ Mode = "new"; Name = $nome; Path = $null; State = $null }
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
    Write-Host "  [E] Exportar cenario para ZIP" -ForegroundColor DarkCyan
    Write-Host ""

    while ($true) {
        $choice = Read-Host "  >> Escolha"
        if ($choice -eq 'N' -or $choice -eq 'n') {
            $nome = Read-Host "  >> Digite o Nome do Teste (Ex: ImagemLimpa, PosUpdate) [Enter para: Execucao]"
            if ([string]::IsNullOrWhiteSpace($nome)) { $nome = "Execucao" }
            return [PSCustomObject]@{ Mode = "new"; Name = $nome; Path = $null; State = $null }
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
    }

    Safe-SetCursorPosition -X 0 -Y $savedPos
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
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; color: #343a40; margin: 40px; }
            h1 { color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 10px; }
            .summary { background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .summary p { margin: 5px 0; font-size: 1.1em; }
            table { width: 100%; border-collapse: collapse; background: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            th, td { padding: 12px 15px; border-bottom: 1px solid #dee2e6; text-align: left; }
            th { background-color: #0056b3; color: white; font-weight: bold; }
            tr:hover { background-color: #f1f3f5; }
            .badge { padding: 5px 10px; border-radius: 12px; font-weight: bold; font-size: 0.9em; color: white; }
            .bg-PASS { background-color: #28a745; }
            .bg-FAIL { background-color: #dc3545; }
            .bg-ERROR { background-color: #fd7e14; }
        </style>
    </head>
    <body>
        <h1>$htmlTitle</h1>
        <div class="summary">
            <p><strong>Maquina (Host):</strong> $env:COMPUTERNAME</p>
            <p><strong>Utilizador:</strong> $env:USERNAME</p>
            <p><strong>Inicio da Execucao:</strong> $($jsonObj.RunTimestamp)</p>
            <p><strong>Tempo Total:</strong> $([Math]::Round($TotalSec,2))s</p>
            <p><strong>Estatisticas:</strong> Total: $($Results.Count) | <span style="color:#28a745;font-weight:bold;">Aprovados: $pass</span> | <span style="color:#dc3545;font-weight:bold;">Falhados: $fail</span> | <span style="color:#fd7e14;font-weight:bold;">Erros: $err</span></p>
        </div>
        <table>
            <tr><th>Fase</th><th>Nome do Teste</th><th>Tipo</th><th>Status</th><th>Duracao</th><th>Traces Gerados</th></tr>
            $($Results | ForEach-Object {
                $errRow = ""
                if ($_.Status -ne "PASS" -and $_.ErrorSnippet) {
                    $safeSnippet = $_.ErrorSnippet -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;' -replace "`n","<br>"
                    $errRow = "<tr><td colspan='6' style='background:#fff5f5;color:#dc3545;padding-left:30px;font-family:Consolas,monospace;font-size:0.85em;border-left:3px solid #dc3545;'>$safeSnippet</td></tr>"
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
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; color: #343a40; margin: 40px; }
            h1 { color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 10px; }
            .summary { background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .summary p { margin: 5px 0; font-size: 1.1em; }
            table { width: 100%; border-collapse: collapse; background: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            th, td { padding: 12px 15px; border-bottom: 1px solid #dee2e6; text-align: left; }
            th { background-color: #0056b3; color: white; font-weight: bold; }
            tr:hover { background-color: #f1f3f5; }
            .badge { padding: 5px 10px; border-radius: 12px; font-weight: bold; font-size: 0.9em; color: white; }
            .bg-PASS { background-color: #28a745; }
            .bg-FAIL { background-color: #dc3545; }
            .bg-ERROR { background-color: #fd7e14; }
        </style>
    </head>
    <body>
        <h1>$htmlTitle - Relatorio Consolidado</h1>
        <div class="summary">
            <p><strong>Cenario:</strong> $($State.scenario)</p>
            <p><strong>Maquina:</strong> $($State.machine)</p>
            <p><strong>Criado em:</strong> $($State.createdAt)</p>
            <p><strong>Ultima execucao:</strong> $($State.lastRunAt)</p>
            <p><strong>Total de runs:</strong> $totalRuns</p>
            <p><strong>Estatisticas:</strong> Total: $total | <span style="color:#28a745;font-weight:bold;">Aprovados: $pass</span> | <span style="color:#dc3545;font-weight:bold;">Falhados: $fail</span> | <span style="color:#fd7e14;font-weight:bold;">Erros: $err</span></p>
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
    param([string]$OutputDir)

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
        "Data da Coleta,`"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`""
    )
    Set-Content -Path $csvPath -Value $csvLines -Encoding UTF8
    Write-Host "  [OK] maquina.csv gerado em $OutputDir" -ForegroundColor Green
}

# ---- Copia de CSVs Tematicos para Resultados ---------------------------------

function Copy-ThematicCSVs {
    param(
        [string]$TraceRunDir,
        [string]$ResultadosDir,
        [string]$LogFile
    )

    Write-Host "`n  Copiando CSVs tematicos para Resultados..." -ForegroundColor DarkCyan

    $expectedCSVs = @{
        "1_cpu_memo"       = "cpu_memoria.csv"
        "2_disco"          = "disco.csv"
        "3_rede"           = "rede.csv"
        "3_rede_internet"  = "rede_internet.csv"
        "4_boot_shutdown"  = "boot_shutdown.csv"
        "5_bateria"        = "bateria.csv"
        "6_wifi_fast_transition" = "wifi_ft.csv"
    }

    # CSVs das variantes DLP/USB (1-1 e 2-1): opcionais -- copiados quando
    # existirem, sem aviso quando ausentes. Caminho relativo a TraceRunDir.
    $variantCSVs = [ordered]@{
        "1_cpu_memo/dlp_usb/cpu_memoria_dlp.csv" = "cpu_memoria_dlp.csv"
        "2_disco/disco_usb.csv"                  = "disco_usb.csv"
    }

    $copied  = 0
    $missing = 0

    foreach ($folder in ($expectedCSVs.Keys | Sort-Object)) {
        $csvName = $expectedCSVs[$folder]
        $sourcePath = Join-Path $TraceRunDir (Join-Path $folder $csvName)

        if (Test-Path $sourcePath) {
            $destPath = Join-Path $ResultadosDir $csvName
            Copy-Item -Path $sourcePath -Destination $destPath -Force
            Write-Host "  [OK] $csvName copiado" -ForegroundColor Green
            $copied++
        } else {
            $testFolder = Join-Path $TraceRunDir $folder
            if (Test-Path $testFolder) {
                Write-Host "  [!] $csvName nao encontrado -- teste executado mas CSV nao foi gerado" -ForegroundColor Yellow
                Add-Content -Path $LogFile -Value "[AVISO] CSV tematico '$csvName' nao gerado pelo teste em '$folder'" -Encoding UTF8
            } else {
                Write-Host "  [--] $csvName -- teste pendente `($folder nao executado`)" -ForegroundColor DarkGray
                Add-Content -Path $LogFile -Value "[INFO] CSV tematico '$csvName' pendente -- teste '$folder' nao executado" -Encoding UTF8
            }
            $missing++
        }
    }

    foreach ($relPath in $variantCSVs.Keys) {
        $sourcePath = Join-Path $TraceRunDir $relPath
        if (Test-Path $sourcePath) {
            $csvName = $variantCSVs[$relPath]
            Copy-Item -Path $sourcePath -Destination (Join-Path $ResultadosDir $csvName) -Force
            Write-Host "  [OK] $csvName copiado" -ForegroundColor Green
            $copied++
        }
    }

    if ($missing -gt 0) { $resultColor = "Yellow" } else { $resultColor = "Green" }
    Write-Host "  Resultado: ${copied} copiado`(s`), ${missing} pendente`(s`)/ausente`(s`)" -ForegroundColor $resultColor
}

# ---- Exportacao de Cenario para ZIP ------------------------------------------

function Export-ScenarioZip {
    param([string]$ExecucoesDir)

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
            Compress-And-Validate -ScenarioPath $selected.Path -ExecucoesDir $ExecucoesDir
            return
        }
        Write-Host "  [!] Opcao invalida." -ForegroundColor Red
    }
}

function Compress-And-Validate {
    param(
        [string]$ScenarioPath,
        [string]$ExecucoesDir
    )

    $scenarioName = Split-Path $ScenarioPath -Leaf
    $zipPath = Join-Path $ExecucoesDir "$scenarioName.zip"

    Write-Host "`n  Compactando cenario '$scenarioName'..." -ForegroundColor Cyan

    $originalFiles = @(Get-ChildItem -Path $ScenarioPath -Recurse -File -ErrorAction SilentlyContinue)
    $originalCount = $originalFiles.Count

    if ($originalCount -eq 0) {
        Write-Host "  [!] Pasta do cenario esta vazia. Nada para compactar." -ForegroundColor Yellow
        return
    }

    if (Test-Path $zipPath) { Remove-Item -Path $zipPath -Force }
    Compress-Archive -Path "$ScenarioPath\*" -DestinationPath $zipPath -Force

    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
        $zipFileCount = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') }).Count
        $zip.Dispose()

        if ($zipFileCount -eq 0) {
            Write-Host "  [!] ZIP gerado esta vazio!" -ForegroundColor Red
            $retry = Read-Host "  Deseja gerar o ZIP novamente? (S/N)"
            if ($retry -eq 'S' -or $retry -eq 's') {
                Remove-Item -Path $zipPath -Force
                Compress-And-Validate -ScenarioPath $ScenarioPath -ExecucoesDir $ExecucoesDir
            }
            return
        }

        if ($zipFileCount -ne $originalCount) {
            Write-Host "  [!] ZIP incompleto: $originalCount arquivos na pasta, $zipFileCount no ZIP" -ForegroundColor Red
            $retry = Read-Host "  Deseja gerar o ZIP novamente? (S/N)"
            if ($retry -eq 'S' -or $retry -eq 's') {
                Remove-Item -Path $zipPath -Force
                Compress-And-Validate -ScenarioPath $ScenarioPath -ExecucoesDir $ExecucoesDir
            }
            return
        }

        Remove-Item -Path $ScenarioPath -Recurse -Force
        Write-Host "  [OK] ZIP gerado e validado. Pasta original removida." -ForegroundColor Green
        Write-Host "  Arquivo: $zipPath `($zipFileCount arquivos`)" -ForegroundColor DarkCyan

    } catch {
        Write-Host "  [!] Erro ao validar ZIP: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Pasta original mantida: $ScenarioPath" -ForegroundColor Yellow
    }
}

# ---- Geracao de cenario.csv (Resultados) -------------------------------------

function Build-ScenarioCSV {
    param(
        [string]$ResultadosDir,
        [PSCustomObject]$State
    )

    Write-Host "  Gerando cenario.csv..." -ForegroundColor DarkCyan

    $csvPath = Join-Path $ResultadosDir "cenario.csv"
    $csvHeader = "Nome do Cenario,Hostname,Nome do Teste,Categoria,Status,Duracao (s),Exit Code,Run,Data da Execucao"
    $csvLines = @($csvHeader)

    # Usar resultado consolidado (ultimo status de cada teste)
    $latest = Get-LatestTestResults -State $State
    foreach ($key in ($latest.Keys | Sort-Object)) {
        $r = $latest[$key]
        # Encontrar o timestamp da run correspondente
        $runTimestamp = ""
        foreach ($run in $State.runs) {
            if ($run.runId -eq $r.runId) { $runTimestamp = $run.timestamp; break }
        }
        $csvLines += "`"$($State.scenario)`",`"$($State.machine)`",`"$key`",`"$($r.folder)`",$($r.status),$($r.duration),$($r.runId),$($r.runId),`"$runTimestamp`""
    }

    Set-Content -Path $csvPath -Value $csvLines -Encoding UTF8
    Write-Host "  [OK] cenario.csv gerado" -ForegroundColor Green
}

# ---- MAIN -------------------------------------------------------------------

Write-Header

Write-Host "  [!] Removendo bloqueios de seguranca (Unblock-File)..." -ForegroundColor DarkGray
Get-ChildItem -Path $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

foreach ($dir in @($ResultadosDir, $ExecucoesDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

Write-Host ""

# ---- Selecao de cenario -----------------------------------------------------
$scenarioChoice = Show-ScenarioMenu -ExecucoesDir $ExecucoesDir

$previousResults = @{}
$currentRunId    = 1

# Tratar modo "export" (opcao [E])
if ($scenarioChoice.Mode -eq "export") {
    Export-ScenarioZip -ExecucoesDir $ExecucoesDir
    exit 0
}

if ($scenarioChoice.Mode -eq "continue") {
    $scenarioDir     = $scenarioChoice.Path
    $traceRunDir     = Join-Path $scenarioDir "Traces"
    $logRunDir       = Join-Path $scenarioDir "Logs"
    if (-not (Test-Path $logRunDir)) { New-Item -ItemType Directory -Path $logRunDir -Force | Out-Null }
    $stateObj        = $scenarioChoice.State
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

    $stateObj = New-StateObject -Scenario $scenarioChoice.Name -Machine $env:COMPUTERNAME
    Write-StateFile -TraceRunDir $traceRunDir -State $stateObj
    Write-Host "`n  Novo cenario criado: $(Split-Path $scenarioDir -Leaf)" -ForegroundColor Cyan
}

# Diretorio de resultados estruturados
$resultadosCenarioDir = Join-Path $ResultadosDir (Split-Path $scenarioDir -Leaf)
if (-not (Test-Path $resultadosCenarioDir)) {
    New-Item -ItemType Directory -Path $resultadosCenarioDir -Force | Out-Null
}

$logFile     = Join-Path $logRunDir "run_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$resultsFile = Join-Path $logRunDir "run_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

$allResults    = [System.Collections.Generic.List[PSCustomObject]]::new()
$setupResults  = [System.Collections.Generic.List[PSCustomObject]]::new()
$runStart      = Get-Date

$logHeader = "HARDWARE TEST HUB -- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`nHost: $env:COMPUTERNAME | User: $env:USERNAME`nCenario: $(Split-Path $scenarioDir -Leaf) | Run: #$currentRunId`nSetupRoot: $SetupRoot`nTestsRoot: $TestsRoot`nTracesDir: $traceRunDir`nLogsDir: $logRunDir`nResultados: $resultadosCenarioDir`n$('-'*62)"
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

    if ($res.Status -ne "PASS") {
        Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 1)
        Write-Host "  [!] Teste falhou. Deseja continuar? (S para continuar)" -ForegroundColor Yellow
        $confirm = [Console]::ReadKey($true)
        if ($confirm.KeyChar -ne 's' -and $confirm.KeyChar -ne 'S') {
            Write-Host "`n  Execucao abortada.`n" -ForegroundColor Red
            break
        }
    }
}

# Posicionar cursor abaixo do painel
Safe-SetCursorPosition -X 0 -Y ($progressY + 2 + $toRun.Count + 2)

# Atualizar state file (setup + testes combinados)
$combinedResults = @($setupResults.ToArray()) + @($testResults.ToArray())
$stateObj = Add-RunToState -State $stateObj -Results $combinedResults
Write-StateFile -TraceRunDir $traceRunDir -State $stateObj

# Relatorio por run (Logs/)
Show-Summary -Results $allResults.ToArray() -LogFile $logFile -ResultsFile $resultsFile -TotalSec ((Get-Date) - $runStart).TotalSeconds

# Relatorio consolidado (Traces/cenario/)
Build-ConsolidatedReport -TraceRunDir $traceRunDir -State $stateObj

# ---- Resultados Estruturados ------------------------------------------------
Collect-MachineInfo -OutputDir $resultadosCenarioDir
Build-ScenarioCSV -ResultadosDir $resultadosCenarioDir -State $stateObj
Copy-ThematicCSVs -TraceRunDir $traceRunDir -ResultadosDir $resultadosCenarioDir -LogFile $logFile

Write-Host "`n  Resultados estruturados salvos em: $resultadosCenarioDir" -ForegroundColor Magenta

# ---- Pergunta de Exportacao ZIP ---------------------------------------------
Write-Host ""
$exportChoice = Read-Host "  Deseja exportar este cenario para ZIP? (S/N)"
if ($exportChoice -eq 'S' -or $exportChoice -eq 's') {
    Compress-And-Validate -ScenarioPath $scenarioDir -ExecucoesDir $ExecucoesDir
}