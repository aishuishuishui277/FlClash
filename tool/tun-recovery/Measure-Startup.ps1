#requires -Version 7.4
param(
    [string]$AppDirectory = $PSScriptRoot,
    [ValidateSet('Automatic', 'Wlan')][string]$Mode = 'Automatic',
    [string]$InterfaceName = 'WLAN',
    [string]$NodeIP = '156.231.115.34',
    [string]$Url = 'https://1.1.1.1/cdn-cgi/trace',
    [int]$Port = 7890,
    [ValidateRange(75, 300)][int]$DurationSeconds = 90,
    [switch]$ObserveOnly
)
$ErrorActionPreference = 'Stop'
$app = Join-Path (Resolve-Path -LiteralPath $AppDirectory).Path 'FlClash.exe'
if (-not (Test-Path -LiteralPath $app)) { throw "Missing application: $app" }
if (-not $ObserveOnly -and (Get-Process -Name FlClash,FlClashCore -ErrorAction SilentlyContinue)) {
    throw 'Exit FlClash from its tray first. This script never stops an existing application.'
}
if ($ObserveOnly) {
    $running = @(Get-Process -Name FlClash -ErrorAction SilentlyContinue)
    if ($running.Count -ne 1 -or $running[0].Path -ine $app) {
        throw 'ObserveOnly must target the directory of the one running FlClash instance.'
    }
}
if ($Mode -eq 'Wlan') {
    $nic = Get-NetAdapter -Name $InterfaceName
    if ($nic.Status -ne 'Up' -or -not (Get-NetRoute -InterfaceIndex $nic.ifIndex -DestinationPrefix '0.0.0.0/0')) {
        throw 'The selected physical interface must be up and have an IPv4 default gateway.'
    }
}
$folder = Join-Path $PSScriptRoot ('measurements\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $Mode)
New-Item -ItemType Directory -Path $folder | Out-Null
$writer = [IO.StreamWriter]::new((Join-Path $folder 'events.jsonl'), $false, [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$clock = [Diagnostics.Stopwatch]::StartNew()
function Record($kind, $value) {
    $writer.WriteLine((@{utc=[DateTime]::UtcNow.ToString('o'); elapsedMs=$clock.ElapsedMilliseconds; event=$kind; value=$value} | ConvertTo-Json -Depth 5 -Compress))
}
$jobs = @()
$lastState = ''
$nextProbe = 0
$probeIndex = 0
$configPath = Join-Path $env:APPDATA 'com.follow\clash\config.yaml'
try {
    Record 'MeasurementStarted' @{mode=$Mode; observeOnly=[bool]$ObserveOnly; url=$Url; nodeIP=$NodeIP; duration=$DurationSeconds; timezone=(Get-TimeZone).Id; appSha256=(Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash}
    Get-NetAdapter | Select-Object Name,ifIndex,InterfaceGuid,Status,InterfaceDescription | ConvertTo-Json | Set-Content (Join-Path $folder 'adapters.json')
    if (-not $ObserveOnly) {
        $selected = if ($Mode -eq 'Wlan') { $InterfaceName } else { $null }
        $process = Start-Process -FilePath $app -WorkingDirectory $AppDirectory -PassThru -WindowStyle Normal -Environment @{FLCLASH_TUN_INTERFACE=$selected} -RedirectStandardOutput (Join-Path $folder 'app-out.log') -RedirectStandardError (Join-Path $folder 'app-err.log')
        Record 'ApplicationLaunched' @{pid=$process.Id; interface=$selected}
    }
    while ($clock.Elapsed.TotalSeconds -lt $DurationSeconds) {
        $cores = @(Get-CimInstance Win32_Process -Filter "Name='FlClashCore.exe'" | Select-Object ProcessId,CreationDate,ExecutablePath)
        $coreIds = @($cores.ProcessId)
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess)
        $adapters = @(Get-NetAdapter | Where-Object {$_.Name -in @($InterfaceName,'FlClash')} | Select-Object Name,ifIndex,Status)
        $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Select-Object InterfaceAlias,InterfaceIndex,NextHop,RouteMetric)
        $udp = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -in $coreIds} | Select-Object LocalAddress,LocalPort,OwningProcess)
        $tcp = @(Get-NetTCPConnection -RemoteAddress $NodeIP -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -in $coreIds} | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess)
        $config = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw } else { '' }
        $interface = [regex]::Match($config, '(?m)^interface-name:.*$').Value
        $withoutInterface = [regex]::Replace($config, '(?m)^interface-name:.*$', 'interface-name: <comparison>')
        $configHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($withoutInterface)))
        $state = @{cores=$cores; mixedListeners=$listeners; adapters=$adapters; defaultRoutes=$routes; nodeTcp=$tcp; coreUdp=$udp; generatedInterface=$interface; configHashExceptInterface=$configHash}
        $encoded = $state | ConvertTo-Json -Depth 5 -Compress
        if ($encoded -ne $lastState) { Record 'ObservedState' $state; $lastState=$encoded }
        if ($clock.Elapsed.TotalSeconds -ge $nextProbe) {
            $nextProbe = $clock.Elapsed.TotalSeconds + 4
            $probeIndex++
            $jobs += Start-ThreadJob -ArgumentList $folder,$probeIndex,$Url,$Port -ScriptBlock {
                param($folder,$index,$url,$port)
                $PSNativeCommandUseErrorActionPreference = $false
                $start = [DateTime]::UtcNow.ToString('o')
                $trace = Join-Path $folder ("curl-$index.trace")
                $errFile = Join-Path $folder ("curl-$index.err")
                $raw = & curl.exe --silent --show-error --output NUL --proxy "http://127.0.0.1:$port" --noproxy '' --connect-timeout 4 --max-time 8 --trace-time --trace-ascii $trace --write-out '%{json}' $url 2> $errFile
                $code = $LASTEXITCODE
                try { $metrics = $raw | ConvertFrom-Json } catch { $metrics = @{raw=$raw} }
                @{index=$index; startedUtc=$start; completedUtc=[DateTime]::UtcNow.ToString('o'); exitCode=$code; metrics=$metrics}
            }
        }
        foreach ($job in @($jobs | Where-Object {$_.State -in @('Completed','Failed')})) {
            Record 'HttpsProbeCompleted' (Receive-Job -Job $job)
            Remove-Job -Job $job
            $jobs = @($jobs | Where-Object {$_.Id -ne $job.Id})
        }
        Start-Sleep -Milliseconds 500
    }
    foreach ($job in $jobs) {
        $null = Wait-Job -Job $job -Timeout 15
        if ($job.State -eq 'Running') { Stop-Job -Job $job }
        Record 'HttpsProbeCompleted' (Receive-Job -Job $job)
        Remove-Job -Job $job
    }
    Record 'MeasurementFinished' @{applicationLeftRunning=$true}
} finally {
    foreach ($job in $jobs) {
        if ($job.State -eq 'Running') { Stop-Job -Job $job }
        Remove-Job -Job $job -ErrorAction SilentlyContinue
    }
    $writer.Dispose()
}
Write-Host "Evidence: $folder"
