# =============================================================================
#  boot_shutdown_duration.ps1
#  Teste de Hardware Hub -- categoria: misc
#
#  Mede a duracao real de boot e shutdown via log de diagnostico do Windows
#  (Microsoft-Windows-Diagnostics-Performance/Operational)
#
#  Eventos coletados:
#    100        -> Boot completo (BootTime = MainPathBootTime + BootPostBootTime)
#    101-110    -> Causas de degradacao de boot (app, driver, servico, prefetch...)
#    200        -> Shutdown completo
#    201-203    -> Causas de atraso no shutdown (app, device, servico)
#
#  Exit codes (Hub):
#    0 -> PASS  (nenhum evento critico hoje)
#    1 -> FAIL  (boot ou shutdown critico detectado hoje)
# =============================================================================

#region ── LIMITES (ms) ──────────────────────────────────────────────────────
$Limites = @{
    Boot_Aviso        = 30000     # >30s  -> aviso
    Boot_Critico      = 60000     # >60s  -> FAIL
    Shut_Aviso        = 20000     # >20s  -> aviso
    Shut_Critico      = 60000     # >60s  -> FAIL
    DiasHistorico     = 3         # hoje + ultimos N dias para exibir/salvar
    LogTamanhoMinimo  = 20971520  # 20MB
}
#endregion

#region ── HELPERS ───────────────────────────────────────────────────────────
function Out-Both {
    param([string]$Msg = "")
    Write-Output $Msg
}

function Format-Ms {
    param([long]$ms)
    if ($ms -le 0) { return "N/A" }
    $s = [Math]::Floor($ms / 1000)
    $m = [Math]::Floor($s / 60)
    $r = $s % 60
    if ($m -gt 0) { return "${m}m ${r}s (${ms}ms)" }
    return "${s}s (${ms}ms)"
}

function Get-XmlField {
    param($Event, [string]$Field)
    try {
        $xml  = [xml]$Event.ToXml()
        $ns   = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $ns.AddNamespace("e","http://schemas.microsoft.com/win/2004/08/events/event")
        $node = $xml.SelectSingleNode("//e:Data[@Name='$Field']", $ns)
        if ($node) { return $node.InnerText }
    } catch {}
    return $null
}

function Get-XmlFieldLong {
    param($Event, [string]$Field)
    $val = Get-XmlField -Event $Event -Field $Field
    if ($null -ne $val -and $val -ne "") {
        try { return [long]$val } catch {}
    }
    return 0
}

function Get-Avaliacao {
    param([long]$ms, [long]$aviso, [long]$critico)
    if     ($ms -le 0)        { return "SEM DADO" }
    elseif ($ms -gt $critico) { return "CRITICO"  }
    elseif ($ms -gt $aviso)   { return "AVISO"    }
    else                      { return "OK"       }
}

function Get-EventDesc {
    param([int]$Id)
    switch ($Id) {
        101 { return "App lenta no boot"           }
        102 { return "Driver lento no boot"        }
        103 { return "Servico lento no boot"       }
        104 { return "Sistema core lento"          }
        105 { return "Prefetch foreground lento"   }
        106 { return "Prefetch background lento"   }
        107 { return "Politica de maquina lenta"   }
        108 { return "Politica de usuario lenta"   }
        109 { return "Dispositivo lento no boot"   }
        110 { return "Session Manager lento"       }
        201 { return "App atrasou shutdown"        }
        202 { return "Dispositivo atrasou shutdown"}
        203 { return "Servico atrasou shutdown"    }
        default { return "Causa desconhecida"      }
    }
}
#endregion

#region ── CABECALHO ─────────────────────────────────────────────────────────
$logName    = "Microsoft-Windows-Diagnostics-Performance/Operational"
$hoje       = Get-Date -Format "yyyy-MM-dd"
$hojeDate   = [datetime]::Today
$dataInicio = $hojeDate.AddDays(-$Limites.DiasHistorico)
$falhas     = 0

Out-Both "Computador  : $env:COMPUTERNAME"
Out-Both "Usuario     : $env:USERNAME"
Out-Both "Data        : $hoje"
Out-Both "Periodo     : $($dataInicio.ToString('dd/MM/yy')) ate hoje"
Out-Both "Log fonte   : $logName"
Out-Both ("-" * 62)
#endregion

#region ── VERIFICA E CORRIGE TAMANHO DO LOG ─────────────────────────────────
$logInfo = Get-WinEvent -ListLog $logName -ErrorAction SilentlyContinue
if ($logInfo) {
    $tamanhoAtualMB = [Math]::Round($logInfo.MaximumSizeInBytes / 1MB, 1)
    $minimoMB       = [Math]::Round($Limites.LogTamanhoMinimo / 1MB, 0)
    Out-Both "Log size    : $tamanhoAtualMB MB (minimo recomendado: $minimoMB MB)"

    if ($logInfo.MaximumSizeInBytes -lt $Limites.LogTamanhoMinimo) {
        Out-Both "[AVISO] Log muito pequeno -- eventos podem estar sendo sobrescritos!"
        Out-Both "        Tentando expandir para $minimoMB MB..."
        try {
            wevtutil sl $logName /ms:$($Limites.LogTamanhoMinimo) 2>$null
            $logAtualizado = Get-WinEvent -ListLog $logName -ErrorAction SilentlyContinue
            $novoMB = [Math]::Round($logAtualizado.MaximumSizeInBytes / 1MB, 1)
            if ($logAtualizado.MaximumSizeInBytes -ge $Limites.LogTamanhoMinimo) {
                Out-Both "[OK] Log expandido para $novoMB MB. Proximas execucoes terao historico completo."
            } else {
                Out-Both "[FALHA] Nao foi possivel expandir. Execute o Hub como Administrador."
            }
        } catch {
            Out-Both "[FALHA] Sem permissao para alterar o log. Execute o Hub como Administrador."
        }
    } else {
        Out-Both "Log size    : OK"
    }
    Out-Both ("-" * 62)
}
#endregion

#region ── COLETA DE EVENTOS ─────────────────────────────────────────────────
$idsBootAll     = @(100,101,102,103,104,105,106,107,108,109,110)
$idsShutdownAll = @(200,201,202,203)

try {
    $evBootAll = @(Get-WinEvent -FilterHashtable @{
        LogName   = $logName
        Id        = $idsBootAll
        StartTime = $dataInicio
    } -ErrorAction Stop | Sort-Object TimeCreated -Descending)
} catch { $evBootAll = @() }

try {
    $evShutdownAll = @(Get-WinEvent -FilterHashtable @{
        LogName   = $logName
        Id        = $idsShutdownAll
        StartTime = $dataInicio
    } -ErrorAction Stop | Sort-Object TimeCreated -Descending)
} catch { $evShutdownAll = @() }

$evBoots      = @($evBootAll     | Where-Object { $_.Id -eq 100 })
$evBootCauses = @($evBootAll     | Where-Object { $_.Id -ne 100 })
$evShutdowns  = @($evShutdownAll | Where-Object { $_.Id -eq 200 })
$evShutCauses = @($evShutdownAll | Where-Object { $_.Id -ne 200 })

if ($evBoots.Count -eq 0 -and $evShutdowns.Count -eq 0) {
    Out-Both "[AVISO] Nenhum evento encontrado nos ultimos $($Limites.DiasHistorico) dias."
    exit 1
}
#endregion

#region ── CSV -- cabecalho ───────────────────────────────────────────────────
# BootTime      = tempo total (MainPathBootTime + BootPostBootTime)
# MainPath      = do logo Windows ate o desktop/logon aparecer
# PostBoot      = do desktop ate o sistema estar 80% idle (realmente utilizavel)
$linhasCSV = [System.Collections.Generic.List[string]]::new()
$linhasCSV.Add("Tipo,DataHora,BootTime_ms,MainPath_ms,PostBoot_ms," +
               "Kernel_ms,Driver_ms,Smss_ms,Explorer_ms," +
               "CritServices_ms,UserProfile_ms,NumStartupApps," +
               "IsDegradation,DuracaoFormatada,Avaliacao,Computador")
#endregion

#region ── PROCESSA BOOTS (Event 100 + causas 101-110) ───────────────────────
Out-Both ""
Out-Both "BOOTS -- ultimos $($Limites.DiasHistorico) dias ($($evBoots.Count) evento(s))"
Out-Both ("{0,-20} {1,-15} {2,-15} {3,-15} {4,-10} {5}" -f `
    "Data/Hora","BootTime","MainPath","PostBoot","Degradado","Avaliacao")
Out-Both ("-" * 85)

$somaBootMs = 0
$countBoot  = 0

foreach ($ev in $evBoots) {
    $bootTime      = Get-XmlFieldLong -Event $ev -Field "BootTime"
    $mainPathMs    = Get-XmlFieldLong -Event $ev -Field "MainPathBootTime"
    $postBootMs    = Get-XmlFieldLong -Event $ev -Field "BootPostBootTime"
    $kernelMs      = Get-XmlFieldLong -Event $ev -Field "BootKernelInitTime"
    $driverMs      = Get-XmlFieldLong -Event $ev -Field "BootDriverInitTime"
    $smssMs        = Get-XmlFieldLong -Event $ev -Field "BootSmssInitTime"
    $explorerMs    = Get-XmlFieldLong -Event $ev -Field "BootExplorerInitTime"
    $critServMs    = Get-XmlFieldLong -Event $ev -Field "BootCriticalServicesInitTime"
    $userProfMs    = Get-XmlFieldLong -Event $ev -Field "BootUserProfileProcessingTime"
    $numApps       = Get-XmlFieldLong -Event $ev -Field "BootNumStartupApps"
    $isDegradation = Get-XmlField     -Event $ev -Field "BootIsDegradation"

    # BootTime = MainPath + PostBoot (conforme documentacao)
    if ($bootTime -eq 0) { $bootTime = $mainPathMs + $postBootMs }

    $aval   = Get-Avaliacao -ms $bootTime -aviso $Limites.Boot_Aviso -critico $Limites.Boot_Critico
    $degStr = if ($isDegradation -in @("true","True","1")) { "SIM" } else { "nao" }
    $dtHora = $ev.TimeCreated.ToString("dd/MM/yy HH:mm:ss")

    Out-Both ("{0,-20} {1,-15} {2,-15} {3,-15} {4,-10} {5}" -f `
        $dtHora,
        (Format-Ms -ms $bootTime),
        (Format-Ms -ms $mainPathMs),
        (Format-Ms -ms $postBootMs),
        $degStr,
        $aval)

    # Causas de degradacao correlacionadas por proximidade de tempo (janela 2 min)
    $causas = @($evBootCauses | Where-Object {
        [Math]::Abs(($_.TimeCreated - $ev.TimeCreated).TotalMinutes) -le 2
    })
    foreach ($causa in $causas) {
        $nome    = Get-XmlField     -Event $causa -Field "FriendlyName"
        if (-not $nome) { $nome = Get-XmlField -Event $causa -Field "FileName" }
        if (-not $nome) { $nome = "desconhecido" }
        $totalMs = Get-XmlFieldLong -Event $causa -Field "TotalTime"
        $degradMs= Get-XmlFieldLong -Event $causa -Field "DegradationTime"
        Out-Both ("   >> [ID $($causa.Id)] $(Get-EventDesc $causa.Id): $nome" +
                      " | total: $(Format-Ms -ms $totalMs)  degradacao: $(Format-Ms -ms $degradMs)")
    }

    if ($aval -eq "CRITICO" -and $ev.TimeCreated -ge $hojeDate) { $falhas++ }
    if ($bootTime -gt 0) { $somaBootMs += $bootTime; $countBoot++ }

    $linhasCSV.Add(("Boot,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13}" -f `
        $ev.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss"),
        $bootTime, $mainPathMs, $postBootMs,
        $kernelMs, $driverMs, $smssMs, $explorerMs,
        $critServMs, $userProfMs, $numApps,
        $degStr, (Format-Ms -ms $bootTime), $aval))
}

if ($countBoot -gt 0) {
    $mediaBootMs = [long]($somaBootMs / $countBoot)
    Out-Both ("-" * 85)
    Out-Both ("Media BootTime : {0}   |   Aviso: {1}   Critico: {2}" -f `
        (Format-Ms -ms $mediaBootMs),
        (Format-Ms -ms $Limites.Boot_Aviso),
        (Format-Ms -ms $Limites.Boot_Critico))
}
#endregion

#region ── PROCESSA SHUTDOWNS (Event 200 + causas 201-203) ───────────────────
Out-Both ""
Out-Both "SHUTDOWNS -- ultimos $($Limites.DiasHistorico) dias ($($evShutdowns.Count) evento(s))"
Out-Both ("{0,-20} {1,-20} {2}" -f "Data/Hora","Duracao Shutdown","Avaliacao")
Out-Both ("-" * 55)

$somaShutMs = 0
$countShut  = 0

foreach ($ev in $evShutdowns) {
    $shutMs = Get-XmlFieldLong -Event $ev -Field "ShutdownTime"
    if ($shutMs -eq 0) { $shutMs = Get-XmlFieldLong -Event $ev -Field "MainPathShutdownTime" }

    $aval   = Get-Avaliacao -ms $shutMs -aviso $Limites.Shut_Aviso -critico $Limites.Shut_Critico
    $dtHora = $ev.TimeCreated.ToString("dd/MM/yy HH:mm:ss")

    Out-Both ("{0,-20} {1,-20} {2}" -f $dtHora, (Format-Ms -ms $shutMs), $aval)

    # Causas de atraso no shutdown (201-203)
    $causas = @($evShutCauses | Where-Object {
        [Math]::Abs(($_.TimeCreated - $ev.TimeCreated).TotalMinutes) -le 2
    })
    foreach ($causa in $causas) {
        $nome    = Get-XmlField     -Event $causa -Field "FriendlyName"
        if (-not $nome) { $nome = Get-XmlField -Event $causa -Field "FileName" }
        if (-not $nome) { $nome = "desconhecido" }
        $totalMs = Get-XmlFieldLong -Event $causa -Field "TotalTime"
        Out-Both ("   >> [ID $($causa.Id)] $(Get-EventDesc $causa.Id): $nome" +
                      " | total: $(Format-Ms -ms $totalMs)")
    }

    if ($aval -eq "CRITICO" -and $ev.TimeCreated -ge $hojeDate) { $falhas++ }
    if ($shutMs -gt 0) { $somaShutMs += $shutMs; $countShut++ }

    $linhasCSV.Add(("Shutdown,{0},{1},0,0,0,0,0,0,0,0,0,N/A,{2},{3}" -f `
        $ev.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss"),
        $shutMs, (Format-Ms -ms $shutMs), $aval))
}

if ($countShut -gt 0) {
    $mediaShutMs = [long]($somaShutMs / $countShut)
    Out-Both ("-" * 55)
    Out-Both ("Media Shutdown : {0}   |   Aviso: {1}   Critico: {2}" -f `
        (Format-Ms -ms $mediaShutMs),
        (Format-Ms -ms $Limites.Shut_Aviso),
        (Format-Ms -ms $Limites.Shut_Critico))
}
#endregion

#region ── SALVA CSV ─────────────────────────────────────────────────────────
$evidenceDir = if ($env:HUB_EVIDENCE_DIR -and (Test-Path $env:HUB_EVIDENCE_DIR)) {
    $env:HUB_EVIDENCE_DIR
} else {
    $PSScriptRoot
}

$csvPath = Join-Path $evidenceDir "BootShutdown_$hoje.csv"
$linhasCSV | Set-Content -Path $csvPath -Encoding UTF8

Out-Both ""
Out-Both ("-" * 62)
Out-Both "CSV salvo em : $csvPath"
Out-Both "Total linhas : $($linhasCSV.Count - 1) registros"
#endregion

#endregion

#region ── RESULTADO FINAL ───────────────────────────────────────────────────
Out-Both ""
Out-Both ("-" * 62)

if ($falhas -gt 0) {
    Out-Both "RESULTADO: FAIL -- $falhas evento(s) CRITICO(s) detectado(s) hoje ($hoje)"
    exit 1
} else {
    Out-Both "RESULTADO: PASS -- nenhum evento critico hoje ($hoje)"
    exit 0
}
#endregion