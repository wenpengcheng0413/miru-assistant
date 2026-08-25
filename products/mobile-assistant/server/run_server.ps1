param(
    [int]$Port = 8765
)

# Long-running guardian used by Task Scheduler. It waits for drive/network
# readiness, starts Miru, and brings it back after an unexpected exit.
$ErrorActionPreference = 'Continue'
$server = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $server '..\..\..')).Path
$pythonCandidates = @(
    (Join-Path $server '.venv\Scripts\python.exe'),
    (Join-Path $repoRoot 'venv\Scripts\python.exe')
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { $python = $pythonCandidates[0] }
$logDir = Join-Path $server 'data\logs'
$guardianLog = Join-Path $logDir 'guardian.log'
$stdoutLog = Join-Path $logDir 'server.stdout.log'
$stderrLog = Join-Path $logDir 'server.stderr.log'

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-GuardianLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    Add-Content -LiteralPath $guardianLog -Value $line -Encoding UTF8
}

# Prevent a manual launch and the scheduled task from racing each other.
$lockPath = Join-Path $logDir 'guardian.lock'
try {
    $script:lock = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    Write-GuardianLog 'Another Miru guardian is already running; exiting'
    exit 0
}

Write-GuardianLog "Guardian started; target port $Port"
$lastPortOwner = $null

while ($true) {
    if (-not (Test-Path -LiteralPath $python)) {
        Write-GuardianLog "Python not found: $python; retrying in 30 seconds"
        Start-Sleep -Seconds 30
        continue
    }

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        if ($lastPortOwner -ne $listener.OwningProcess) {
            $lastPortOwner = $listener.OwningProcess
            Write-GuardianLog "Port $Port is owned by PID $lastPortOwner; waiting"
        }
        Start-Sleep -Seconds 10
        continue
    }
    $lastPortOwner = $null

    try {
        Write-GuardianLog 'Starting Miru Server'
        # WorkingDirectory is the server directory, so the default config/settings.yaml
        # is resolved deterministically without quoting a path that contains spaces.
        $arguments = "-m miru_server --host 0.0.0.0 --port $Port"
        $process = Start-Process `
            -FilePath $python `
            -ArgumentList $arguments `
            -WorkingDirectory $server `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -Wait `
            -PassThru
        $exitCode = $process.ExitCode
        Write-GuardianLog "Miru Server exited with code $exitCode; restarting in 5 seconds"
    } catch {
        Write-GuardianLog "Launch failed: $($_.Exception.Message); retrying in 5 seconds"
    }
    Start-Sleep -Seconds 5
}
