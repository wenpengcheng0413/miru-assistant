param(
    [int]$Port = 8765
)

# Installs a machine-start task plus tightly-scoped LAN firewall rules.
$ErrorActionPreference = 'Stop'
$server = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $server '..\..\..')).Path
$runner = Join-Path $server 'run_server.ps1'
$pythonCandidates = @(
    (Join-Path $server '.venv\Scripts\python.exe'),
    (Join-Path $repoRoot 'venv\Scripts\python.exe')
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { $python = $pythonCandidates[0] }
$taskName = 'MiruServer'
$tcpRule = 'Miru Server (LAN TCP)'
$mdnsRule = 'Miru Server (mDNS)'

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object System.Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principalCheck.IsInRole(
    [System.Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    throw 'Run this script from an Administrator PowerShell window.'
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Guardian script not found: $runner"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtualenv Python not found: $python"
}

$actionArgs = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-WindowStyle', 'Hidden', '-File', ('"' + $runner + '"'),
    '-Port', $Port
) -join ' '
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument $actionArgs `
    -WorkingDirectory $server

# AtStartup provides the requested "PC on = Miru available" behavior.
# AtLogOn is a recovery trigger for machines whose data drive mounted late.
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn)
)
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description 'Keeps Miru Server available on the home LAN.' `
    -Force | Out-Null

# TCP is limited to the local subnet and to Miru's Python executable.
# UDP/5353 is only for Bonjour discovery; neither rule opens Internet access.
Get-NetFirewallRule -DisplayName $tcpRule -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName $mdnsRule -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule `
    -DisplayName $tcpRule `
    -Direction Inbound `
    -Action Allow `
    -Program $python `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress LocalSubnet `
    -Profile Any | Out-Null
New-NetFirewallRule `
    -DisplayName $mdnsRule `
    -Direction Inbound `
    -Action Allow `
    -Program $python `
    -Protocol UDP `
    -LocalPort 5353 `
    -RemoteAddress LocalSubnet `
    -Profile Any | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "[OK] Installed startup guardian task: $taskName" -ForegroundColor Green
Write-Host "[OK] Allowed LAN TCP/$Port and mDNS UDP/5353" -ForegroundColor Green
Write-Host '[OK] Started Miru Server now' -ForegroundColor Green
