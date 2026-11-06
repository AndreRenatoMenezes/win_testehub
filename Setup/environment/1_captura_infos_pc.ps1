# =============================================================
#  system_info.ps1 - Informacoes do sistema (CPU, RAM, Disco)
#  Compativel com Windows 10/11 e Windows Server
#  Salva resultado em CSV na pasta de evidencias
# =============================================================

# Integração com o Hardware Test Hub
$FileName = "informacoes_maquina.csv"

if ($env:HUB_TRACE_ROOT) {
    $FilePath = Join-Path $env:HUB_TRACE_ROOT $FileName
} elseif ($env:HUB_EVIDENCE_DIR) {
    $FilePath = Join-Path $env:HUB_EVIDENCE_DIR $FileName
} else {
    $Desktop  = [Environment]::GetFolderPath("Desktop")
    $FilePath = Join-Path $Desktop $FileName
}

function Format-Bytes {
    param([long]$Bytes)
    if     ($Bytes -ge 1TB) { "{0:N2} TB" -f ($Bytes / 1TB) }
    elseif ($Bytes -ge 1GB) { "{0:N2} GB" -f ($Bytes / 1GB) }
    elseif ($Bytes -ge 1MB) { "{0:N2} MB" -f ($Bytes / 1MB) }
    else                    { "{0:N2} KB" -f ($Bytes / 1KB) }
}

# Linhas CSV: Categoria;Propriedade;Valor
$csvLines = [System.Collections.Generic.List[string]]::new()
$csvLines.Add("Categoria;Propriedade;Valor")

try {

# -- CPU -------------------------------------------------------
Write-Host "[ CPU ]" -ForegroundColor Cyan

$cpu = Get-CimInstance -ClassName Win32_Processor

foreach ($c in $cpu) {
    $arch = switch ($c.Architecture) {
        0 { "x86" }
        5 { "ARM" }
        9 { "x64 (AMD64)" }
        default { "$($c.Architecture)" }
    }
    $freqGHz = [math]::Round($c.MaxClockSpeed / 1000, 2)
    $csvLines.Add("CPU;Modelo;$($c.Name.Trim())")
    $csvLines.Add("CPU;Fabricante;$($c.Manufacturer)")
    $csvLines.Add("CPU;Arquitetura;$arch")
    $csvLines.Add("CPU;Nucleos fisicos;$($c.NumberOfCores)")
    $csvLines.Add("CPU;Threads (logicos);$($c.NumberOfLogicalProcessors)")
    $csvLines.Add("CPU;Freq. maxima;$($c.MaxClockSpeed) MHz ($freqGHz GHz)")
    $csvLines.Add("CPU;Soquete;$($c.SocketDesignation)")
    $csvLines.Add("CPU;Cache L2;$(Format-Bytes ($c.L2CacheSize * 1KB))")
    $csvLines.Add("CPU;Cache L3;$(Format-Bytes ($c.L3CacheSize * 1KB))")

    Write-Host "  Modelo: $($c.Name.Trim())  |  Nucleos: $($c.NumberOfCores)  |  Threads: $($c.NumberOfLogicalProcessors)"
}

# -- Memoria RAM -----------------------------------------------
Write-Host "[ MEMORIA RAM ]" -ForegroundColor Cyan

$os  = Get-CimInstance -ClassName Win32_OperatingSystem
$cs  = Get-CimInstance -ClassName Win32_ComputerSystem
$ram = Get-CimInstance -ClassName Win32_PhysicalMemory

$totalInstalled = ($ram | Measure-Object -Property Capacity -Sum).Sum
$totalVisible   = $os.TotalVisibleMemorySize * 1KB
$freePhys       = $os.FreePhysicalMemory * 1KB
$usedPhys       = $totalVisible - $freePhys
$totalPage      = $os.TotalVirtualMemorySize * 1KB
$freePage       = $os.FreeVirtualMemory * 1KB

$csvLines.Add("RAM;Total instalado;$(Format-Bytes $totalInstalled)")
$csvLines.Add("RAM;Total visivel;$(Format-Bytes $totalVisible)")
$csvLines.Add("RAM;Em uso;$(Format-Bytes $usedPhys)")
$csvLines.Add("RAM;Disponivel;$(Format-Bytes $freePhys)")
$csvLines.Add("RAM;Mem. virtual total;$(Format-Bytes $totalPage)")
$csvLines.Add("RAM;Mem. virtual livre;$(Format-Bytes $freePage)")

Write-Host "  Total: $(Format-Bytes $totalInstalled)  |  Em uso: $(Format-Bytes $usedPhys)  |  Livre: $(Format-Bytes $freePhys)"

if ($ram) {
    $slot = 1
    foreach ($stick in $ram) {
        $cap  = Format-Bytes $stick.Capacity
        $freq = if ($stick.Speed) { "$($stick.Speed) MHz" } else { "N/A" }
        $type = switch ($stick.MemoryType) {
            20 { "DDR" }; 21 { "DDR2" }; 24 { "DDR3" }; 26 { "DDR4" }; 34 { "DDR5" }
            default { "Tipo $($stick.MemoryType)" }
        }
        $csvLines.Add("RAM;Slot $slot ($($stick.DeviceLocator));$cap / $freq / $type")
        Write-Host "  Slot ${slot}: $($stick.DeviceLocator) - $cap $freq $type"
        $slot++
    }
}

# -- Disco -----------------------------------------------------
Write-Host "[ DISCOS FISICOS ]" -ForegroundColor Cyan

$disks = Get-CimInstance -ClassName Win32_DiskDrive | Sort-Object Index
foreach ($d in $disks) {
    $csvLines.Add("Disco;Disco $($d.Index) Modelo;$($d.Model.Trim())")
    $csvLines.Add("Disco;Disco $($d.Index) Tamanho;$(Format-Bytes $d.Size)")
    $csvLines.Add("Disco;Disco $($d.Index) Interface;$($d.InterfaceType)")
    $csvLines.Add("Disco;Disco $($d.Index) Particoes;$($d.Partitions)")
    $csvLines.Add("Disco;Disco $($d.Index) Num. serie;$($d.SerialNumber.Trim())")
    Write-Host "  Disco $($d.Index): $($d.Model.Trim()) - $(Format-Bytes $d.Size) ($($d.InterfaceType))"
}

$vols = Get-CimInstance -ClassName Win32_LogicalDisk | Where-Object { $_.DriveType -in 3,4 }
foreach ($v in $vols) {
    if ($v.Size -gt 0) {
        $used = $v.Size - $v.FreeSpace
        $pct  = [math]::Round(($used / $v.Size) * 100, 1)
        $csvLines.Add("Volume;$($v.DeviceID) Total;$(Format-Bytes $v.Size)")
        $csvLines.Add("Volume;$($v.DeviceID) Usado;$(Format-Bytes $used)")
        $csvLines.Add("Volume;$($v.DeviceID) Livre;$(Format-Bytes $v.FreeSpace)")
        $csvLines.Add("Volume;$($v.DeviceID) Uso%;$pct%")
        $csvLines.Add("Volume;$($v.DeviceID) FileSystem;$($v.FileSystem)")
        Write-Host "  $($v.DeviceID) Total: $(Format-Bytes $v.Size) | Usado: $(Format-Bytes $used) ($pct%) | FS: $($v.FileSystem)"
    }
}

# -- Bateria ---------------------------------------------------
Write-Host "[ BATERIA ]" -ForegroundColor Cyan

$batteries  = Get-CimInstance -ClassName Win32_Battery
$battFull   = Get-CimInstance -ClassName BatteryFullChargedCapacity -Namespace root\wmi -ErrorAction SilentlyContinue
$battStatus = Get-CimInstance -ClassName BatteryStatus              -Namespace root\wmi -ErrorAction SilentlyContinue
$battCycle  = Get-CimInstance -ClassName BatteryCycleCount          -Namespace root\wmi -ErrorAction SilentlyContinue

$designCapPowercfg = $null
try {
    $reportPath = Join-Path $env:TEMP "battery_tmp.xml"
    $null = & powercfg /batteryreport /xml /output $reportPath 2>$null
    if (Test-Path $reportPath) {
        [xml]$xmlReport = Get-Content $reportPath -ErrorAction SilentlyContinue
        $designCapPowercfg = [long]$xmlReport.BatteryReport.Batteries.Battery.DesignCapacity
        Remove-Item $reportPath -Force -ErrorAction SilentlyContinue
    }
} catch { }

if (-not $batteries) {
    $csvLines.Add("Bateria;Status;Nenhuma bateria encontrada")
    Write-Host "  Nenhuma bateria encontrada (pode ser desktop ou driver ausente)."
} else {
    foreach ($b in $batteries) {
        $statusText = switch ($b.BatteryStatus) {
            1 { "Descarregando" }
            2 { "Plugado, carregando" }
            3 { "Carregamento completo" }
            4 { "Baixa carga" }
            5 { "Critica" }
            6 { "Carregando" }
            7 { "Carregando e alta" }
            8 { "Carregando e baixa" }
            9 { "Carregando e critica" }
            default { "Desconhecido ($($b.BatteryStatus))" }
        }
        $chemText = switch ($b.Chemistry) {
            1 { "Outro" }; 2 { "Desconhecido" }; 3 { "Chumbo-acido" }
            4 { "Niquel-Cadmio" }; 5 { "Niquel-Metal Hidreto" }
            6 { "Litio-Ion" }; 7 { "Zinco-Ar" }; 8 { "Litio-Polimero" }
            default { "Desconhecido" }
        }

        $csvLines.Add("Bateria;Nome;$($b.Name)")
        $csvLines.Add("Bateria;Status;$statusText")
        $csvLines.Add("Bateria;Carga atual;$($b.EstimatedChargeRemaining)%")
        $csvLines.Add("Bateria;Quimica;$chemText")
        $csvLines.Add("Bateria;Voltagem;$($b.DesignVoltage) mV")
        Write-Host "  $($b.Name) | Status: $statusText | Carga: $($b.EstimatedChargeRemaining)%"
    }

    $fullCap   = if ($battFull) { $battFull.FullChargedCapacity } else { $null }
    $designCap = if ($designCapPowercfg -and $designCapPowercfg -gt 0) { $designCapPowercfg } else { $null }

    if ($fullCap -and $designCap -and $designCap -gt 0) {
        $designCapAjustado = $designCap * 0.9
        $saude = [math]::Round(($fullCap / $designCapAjustado) * 100, 1)
        if ($saude -gt 100) { $saude = 100 }

        $saudeTexto = if ($saude -ge 80)     { "Excellent (Excelente)" }
                elseif ($saude -ge 60) { "Good (Bom)" }
                elseif ($saude -ge 40) { "Fair (Aceitavel)" }
                elseif ($saude -gt  0) { "Poor (Ruim)" }
                else                   { "Unknown (Desconhecido)" }

        $csvLines.Add("Bateria;Capacidade design;$designCap mWh")
        $csvLines.Add("Bateria;Cap. design ajustada (Dell);$designCapAjustado mWh")
        $csvLines.Add("Bateria;Capacidade atual;$fullCap mWh")
        $csvLines.Add("Bateria;Saude;$saude% ($saudeTexto)")
        Write-Host "  Saude: $saude% ($saudeTexto)"
    } elseif ($fullCap) {
        $csvLines.Add("Bateria;Capacidade atual;$fullCap mWh")
        $csvLines.Add("Bateria;Saude;Desconhecido - Capacidade original nao encontrada")
    } else {
        $csvLines.Add("Bateria;Saude;Desconhecido - Falha no reconhecimento")
    }

    if ($battStatus) {
        $bs = $battStatus
        $csvLines.Add("Bateria;Carregando agora;$(if ($bs.Charging) { 'Sim' } else { 'Nao' })")
        $csvLines.Add("Bateria;Na tomada;$(if ($bs.PowerOnline) { 'Sim' } else { 'Nao' })")
        if ($bs.ChargeRate    -gt 0) { $csvLines.Add("Bateria;Taxa de carga;$($bs.ChargeRate) mW") }
        if ($bs.DischargeRate -gt 0) { $csvLines.Add("Bateria;Taxa de descarga;$($bs.DischargeRate) mW") }
        $csvLines.Add("Bateria;Carga restante;$($bs.RemainingCapacity) mWh")
        $csvLines.Add("Bateria;Voltagem atual;$($bs.Voltage) mV")
    }

    if ($battCycle) {
        $csvLines.Add("Bateria;Ciclos de carga;$($battCycle.CycleCount)")
    }
}

# -- Sistema Operacional ---------------------------------------
Write-Host "[ SISTEMA OPERACIONAL ]" -ForegroundColor Cyan

$bios   = Get-CimInstance -ClassName Win32_BIOS
$mb     = Get-CimInstance -ClassName Win32_BaseBoard
$uptime = (Get-Date) - $os.LastBootUpTime

$csvLines.Add("SO;Sistema operacional;$($os.Caption)")
$csvLines.Add("SO;Versao;$($os.Version) (Build $($os.BuildNumber))")
$csvLines.Add("SO;Arquitetura;$($os.OSArchitecture)")
$csvLines.Add("SO;Hostname;$($env:COMPUTERNAME)")
$csvLines.Add("SO;Dominio/Grupo;$($cs.Domain)")
$csvLines.Add("SO;Usuario atual;$($env:USERNAME)")
$csvLines.Add("SO;Instalado em;$($os.InstallDate.ToString('dd/MM/yyyy'))")
$csvLines.Add("SO;Ultimo boot;$($os.LastBootUpTime.ToString('dd/MM/yyyy HH:mm:ss'))")
$csvLines.Add("SO;Uptime;$([int]$uptime.TotalDays)d $($uptime.Hours)h $($uptime.Minutes)min")
$csvLines.Add("SO;BIOS;$($bios.Manufacturer) - $($bios.SMBIOSBIOSVersion)")
$csvLines.Add("SO;Placa-mae;$($mb.Manufacturer) $($mb.Product)")
$csvLines.Add("Coleta;Data/Hora;$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')")

Write-Host "  $($os.Caption) | Build $($os.BuildNumber) | $($os.OSArchitecture)"
Write-Host "  Hostname: $($env:COMPUTERNAME) | BIOS: $($bios.SMBIOSBIOSVersion)"

# -- Salvar CSV e exibir confirmacao ---------------------------
    $csvLines | Set-Content -Path $FilePath -Encoding UTF8

    Write-Host ""
    Write-Host "Arquivo salvo em: $FilePath" -ForegroundColor Green
    exit 0

} catch {
    Write-Host "[ERRO] Falha ao coletar informacoes do sistema: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}