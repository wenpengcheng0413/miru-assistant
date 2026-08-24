# Miru Assistant - Windows Task Scheduler Setup (V2)
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
#
# V2 变更: 使用 cmd.exe + launcher.bat 代替 pythonw.exe 直接调用，
#         解决路径含空格时 Task Scheduler 解析失败的问题。

$ErrorActionPreference = "Stop"

$TaskName = "Miru Daily Report"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# V2: 入口改为项目根目录的 launcher.bat
$LauncherBat = Join-Path $ProjectDir "launcher.bat"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Miru Assistant - Install Scheduled Task" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Project:  $ProjectDir"
Write-Host "  Launcher: $LauncherBat"
Write-Host ""

# Check admin
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[ERROR] Run as Administrator" -ForegroundColor Red
    exit 1
}

# V2: 检查 launcher.bat
if (-not (Test-Path $LauncherBat)) {
    Write-Host "[ERROR] launcher.bat not found: $LauncherBat" -ForegroundColor Red
    Write-Host "This file should be at the project root." -ForegroundColor Red
    exit 1
}

# Check config
$ConfigFile = Join-Path $ProjectDir "config\settings.yaml"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[WARNING] Config not found: $ConfigFile" -ForegroundColor Yellow
}

# Remove existing task
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] Removing existing task: $TaskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# V2: Action — cmd.exe /c "<launcher_path>"
#     cmd.exe 路径无空格（始终可解析）
#     launcher.bat 路径用双引号包裹（免疫路径空格）
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$LauncherBat`"" `
    -WorkingDirectory $ProjectDir

# Trigger: daily at 22:00 + at logon (catch-up)
$Trigger1 = New-ScheduledTaskTrigger -Daily -At 22:00
$Trigger2 = New-ScheduledTaskTrigger -AtLogon -RandomDelay (New-TimeSpan -Minutes 2)

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -Compatibility Win8 `
    -MultipleInstances IgnoreNew

# Register with highest privileges (needed to read WeChat process memory)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger1, $Trigger2 `
    -Settings $Settings `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Task installed successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Name:     $TaskName"
Write-Host "  Trigger:  Daily 22:00 + AtLogon"
Write-Host "  Entry:    cmd.exe /c launcher.bat"
Write-Host ""
Write-Host "  Logs:"
Write-Host "    Tier 0: data\logs\launcher.log"
Write-Host "    Tier 1: data\logs\bootstrap.log"
Write-Host "    Tier 2: data\logs\miru_YYYY-MM-DD.log"
Write-Host ""
Write-Host "  Test manually:"
Write-Host "    launcher.bat"
Write-Host ""
Write-Host "  Manage:"
Write-Host "    taskschd.msc"
Write-Host "    schtasks /Delete /TN '$TaskName' /F"
Write-Host ""
