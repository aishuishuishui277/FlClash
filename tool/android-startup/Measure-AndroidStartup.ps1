param(
    [string]$Adb = 'adb',
    [string]$Serial = '',
    [ValidateRange(30, 300)][int]$Seconds = 150,
    [ValidateRange(1, 65535)][int]$PhonePort = 7890,
    [ValidateRange(1024, 65535)][int]$LocalPort = 17990,
    [string]$Output = (Join-Path $PWD ('android-startup-' + (Get-Date -Format yyyyMMdd-HHmmss)))
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required' }
$adbPath = (Get-Command $Adb -ErrorAction Stop).Source
$curlPath = (Get-Command curl.exe -ErrorAction Stop).Source
$adbArgs = if ($Serial) { @('-s', $Serial) } else { @() }
function Invoke-Adb([string[]]$Arguments) {
    $result = & $adbPath @adbArgs @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('ADB failed: ' + ($result -join ' ')) }
    return $result
}
function Start-CapturedProcess([string]$File, [string[]]$Arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new($File)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void]$process.Start()
    return @{
        Process = $process
        Stdout = $process.StandardOutput.ReadToEndAsync()
        Stderr = $process.StandardError.ReadToEndAsync()
    }
}
function Write-Event([hashtable]$Data) {
    $Data.time_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    Add-Content -LiteralPath (Join-Path $Output 'probes.jsonl') -Value ($Data | ConvertTo-Json -Compress) -Encoding utf8
}

[void](Invoke-Adb @('get-state'))
$forwards = Invoke-Adb @('forward', '--list')
if (($forwards -join "`n") -match "\btcp:$LocalPort\s") { throw "ADB local port $LocalPort already has a forward; choose another LocalPort" }
if (Test-Path -LiteralPath $Output) { throw 'Output directory already exists; choose a new directory' }
[void](New-Item -ItemType Directory -Path $Output)
$previous = (Invoke-Adb @('shell', 'getprop', 'log.tag.FlClashStartup')) -join ''
$logger = $null
$probe = $null
$ownsForward = $false
try {
    [void](Invoke-Adb @('shell', 'setprop', 'log.tag.FlClashStartup', 'DEBUG'))
    if (((Invoke-Adb @('shell', 'getprop', 'log.tag.FlClashStartup')) -join '').Trim() -ne 'DEBUG') {
        throw 'Device did not enable diagnostic logging; no root workaround is attempted'
    }
    [void](Invoke-Adb @('forward', "tcp:$LocalPort", "tcp:$PhonePort"))
    $ownsForward = $true
    $logger = Start-CapturedProcess $adbPath ($adbArgs + @('logcat', '-T', '1', '-v', 'epoch', 'FlClashStartup:D', '*:S'))
    Write-Host 'Keep the same node, DNS and rules. Manually exit and reopen the diagnostic app now.'
    Write-Host 'S = mark first VPN tap; C = mark recovery tap; T = mark network/toggle action; Q = stop.'
    Write-Host 'Each key is only a timestamp marker. This script never toggles or stops the VPN.'
    Write-Host "Recording for $Seconds seconds. Keep this PowerShell window focused."
    Write-Event @{ event = 'capture_begin'; duration_seconds = $Seconds; phone_port = $PhonePort }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $nextProbe = 0L
    $stopping = $false
    while ($clock.Elapsed.TotalSeconds -lt $Seconds -and !$stopping) {
        while ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true).Key.ToString()
            if ($key -in @('S', 'C', 'T')) {
                Write-Event @{ event = 'manual_' + $key.ToLowerInvariant() }
                Write-Host "Marked $key at $([Math]::Round($clock.Elapsed.TotalSeconds, 1)) s"
            }
            if ($key -eq 'Q') { $stopping = $true }
        }
        if ($logger.Process.HasExited) { throw 'Filtered logcat ended; check the USB connection and device authorization' }
        if (!$probe -and $clock.ElapsedMilliseconds -ge $nextProbe) {
            $probeStarted = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $probe = Start-CapturedProcess $curlPath @(
                '--silent', '--proxy', "http://127.0.0.1:$LocalPort", '--noproxy', '',
                '--connect-timeout', '4', '--max-time', '8', '--output', 'NUL',
                '--write-out', '%{json}', 'https://1.1.1.1/cdn-cgi/trace'
            )
        }
        if ($probe -and $probe.Process.HasExited) {
            $raw = $probe.Stdout.GetAwaiter().GetResult()
            $stats = $raw | ConvertFrom-Json
            Write-Event @{
                event = 'https_proxy_probe'; started_ms = $probeStarted; exit_code = $probe.Process.ExitCode
                connect_code = $stats.http_connect; http_code = $stats.http_code
                time_connect = $stats.time_connect; time_appconnect = $stats.time_appconnect; time_total = $stats.time_total
                success = ($probe.Process.ExitCode -eq 0 -and $stats.http_connect -eq 200 -and $stats.http_code -eq 200)
            }
            $probe.Process.Dispose()
            $probe = $null
            $nextProbe = $clock.ElapsedMilliseconds + 2000
        }
        Start-Sleep -Milliseconds 100
    }
    Write-Event @{ event = 'capture_end' }
} finally {
    foreach ($owned in @($probe, $logger)) {
        if ($owned -and !$owned.Process.HasExited) { $owned.Process.Kill(); $owned.Process.WaitForExit() }
    }
    if ($logger) {
        [IO.File]::WriteAllText((Join-Path $Output 'startup-logcat.txt'), $logger.Stdout.GetAwaiter().GetResult())
        $logger.Process.Dispose()
    }
    if ($probe) { $probe.Process.Dispose() }
    if ($ownsForward) { [void](Invoke-Adb @('forward', '--remove', "tcp:$LocalPort")) }
    $restore = if ($previous.Trim()) { $previous.Trim() } else { 'SILENT' }
    [void](Invoke-Adb @('shell', 'setprop', 'log.tag.FlClashStartup', $restore))
    Write-Host "Saved filtered diagnostics to $Output. Reopen the app after capture to fully disable the Go relay."
}
