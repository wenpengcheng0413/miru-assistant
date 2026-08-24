param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$server = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $server 'run_server.ps1'
$taskName = 'MiruServer'

function Test-MiruPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(1000)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-MiruPort) {
    Write-Host "Miru Server is already running at http://0.0.0.0:$Port"
    exit 0
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Start-ScheduledTask -TaskName $taskName
} else {
    $arguments = @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $runner + '"'), '-Port', $Port
    ) -join ' '
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden
}

$deadline = (Get-Date).AddSeconds(25)
do {
    Start-Sleep -Milliseconds 500
    $ready = Test-MiruPort
} until ($ready -or (Get-Date) -ge $deadline)

if (-not $ready) {
    Write-Host "[ERROR] Miru did not start in 25 seconds. See server\data\logs\guardian.log" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Miru Server started at http://0.0.0.0:$Port" -ForegroundColor Green
exit 0
