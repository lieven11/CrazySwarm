[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $false)]
    [string]$CompatibilityChecker,

    [Parameter(Mandatory = $false)]
    [switch]$ConfirmAllOfficialChecksGreen
)

$ErrorActionPreference = "Stop"

function Invoke-NvidiaSmiQuery {
    param([string]$Query)
    $nvidiaSmi = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if ($null -eq $nvidiaSmi) {
        return $null
    }
    $value = & $nvidiaSmi.Source "--query-gpu=$Query" "--format=csv,noheader,nounits" 2>$null |
        Select-Object -First 1
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return "$value".Trim()
}

$computer = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$systemDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($os.SystemDrive)'"
$gpu = Get-CimInstance Win32_VideoController |
    Where-Object { $_.Name -match "NVIDIA" } |
    Select-Object -First 1

$gpuName = Invoke-NvidiaSmiQuery "name"
$vramMiB = Invoke-NvidiaSmiQuery "memory.total"
$driver = Invoke-NvidiaSmiQuery "driver_version"
$powerLimitW = Invoke-NvidiaSmiQuery "power.limit"
$temperatureC = Invoke-NvidiaSmiQuery "temperature.gpu"
$network = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq "Up" } |
    ForEach-Object { "$($_.Name):$($_.LinkSpeed)" }
$powerMode = (& powercfg.exe /getactivescheme 2>$null | Out-String).Trim()

$checker = [ordered]@{
    status = "NOT_RUN"
    package_version = $null
    command = $null
    exit_code = $null
    report_path = $null
    findings = @()
}

if ($CompatibilityChecker) {
    $resolvedChecker = (Resolve-Path -LiteralPath $CompatibilityChecker).Path
    $checkerLog = [System.IO.Path]::ChangeExtension(
        [System.IO.Path]::GetFullPath($OutputPath),
        ".compatibility-checker.log"
    )
    $checkerOutput = & $resolvedChecker "--/app/quitAfter=10" "--no-window" 2>&1
    $checkerExit = $LASTEXITCODE
    $checkerOutput | Set-Content -LiteralPath $checkerLog -Encoding UTF8
    $checker.status = if ($checkerExit -ne 0) {
        "FAILED"
    } elseif ($ConfirmAllOfficialChecksGreen) {
        "PASSED"
    } else {
        "REVIEW_REQUIRED"
    }
    $checker.package_version = (Split-Path (Split-Path $resolvedChecker -Parent) -Leaf)
    $checker.command = "$resolvedChecker --/app/quitAfter=10 --no-window"
    $checker.exit_code = $checkerExit
    $checker.report_path = $checkerLog
    $checker.findings = @(
        $checkerOutput |
            Where-Object { "$_" -match "(excellent|good|enough|unsupported|fail|warn|error)" } |
            ForEach-Object { "$_".Trim() }
    )
}

$inventory = [ordered]@{
    schema_version = 1
    inventory_id = "isaac-host-$($env:COMPUTERNAME.ToLowerInvariant())-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
    captured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    measurement_class = "MEASURED_HOST"
    host_name = $env:COMPUTERNAME
    manufacturer = $computer.Manufacturer
    model = $computer.Model
    sku = $computer.SystemSKUNumber
    operating_system = $os.Caption
    os_build = $os.BuildNumber
    cpu = $cpu.Name
    physical_cpu_cores = [int]$cpu.NumberOfCores
    logical_cpu_cores = [int]$cpu.NumberOfLogicalProcessors
    system_ram_bytes = [long]$computer.TotalPhysicalMemory
    gpu = if ($gpuName) { $gpuName } elseif ($gpu) { $gpu.Name } else { "NOT_DETECTED" }
    vram_bytes = if ($vramMiB) { [long]([double]$vramMiB * 1MB) } else { 0 }
    driver_version = if ($driver) { $driver } elseif ($gpu) { $gpu.DriverVersion } else { $null }
    gpu_tgp_w = if ($powerLimitW) { [double]$powerLimitW } else { $null }
    free_storage_bytes = [long]$systemDrive.FreeSpace
    power_mode = $powerMode
    gpu_temperature_c = if ($temperatureC) { [double]$temperatureC } else { $null }
    network_summary = ($network -join "; ")
    official_checker = $checker
}

$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path $outputFullPath -Parent
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$inventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputFullPath -Encoding UTF8
Write-Output $outputFullPath
