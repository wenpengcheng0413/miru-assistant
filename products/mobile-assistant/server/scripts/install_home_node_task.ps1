param(
    [Parameter(Mandatory = $true)]
    [string]$CloudUrl,
    [string]$TaskName = 'Miru Home Node'
)

$ErrorActionPreference = 'Stop'
if (-not $CloudUrl.StartsWith('wss://') -or -not $CloudUrl.EndsWith('/ws/node')) {
    throw 'CloudUrl must be a wss:// URL ending in /ws/node'
}
$stateDir = Join-Path $env:LOCALAPPDATA 'Miru'
$tokenPath = Join-Path $stateDir 'home-node-token.dat'
$journalPath = Join-Path $stateDir 'home-node-journal.json'
$configPath = Join-Path $stateDir 'home-node.yaml'
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
    throw 'DPAPI token file is missing; provision credentials before installing the task'
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$yaml = @"
cloud_url: $CloudUrl
node_id: node-home
token_path: "$($tokenPath.Replace('\', '\\'))"
journal_path: "$($journalPath.Replace('\', '\\'))"
capabilities:
  - home_node_ping
  - wechat_search_messages
wechat_data_root: ""
wechat_max_days: 90
wechat_max_results: 20
connect_timeout_s: 12
max_backoff_s: 60
"@
Set-Content -LiteralPath $configPath -Value $yaml -Encoding UTF8

$runner = Join-Path $PSScriptRoot 'run_home_node.ps1'
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" -ConfigPath `"$configPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Miru outbound-only Home Node WSS client' `
    -Force | Out-Null
Write-Output 'home_node_task_installed=true'
