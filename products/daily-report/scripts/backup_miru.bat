@echo off
REM Miru Assistant - Backup Script
REM Usage: scripts\backup_miru.bat
REM Output: backup\YYYYMMDD\

set BACKUP_DIR=%~dp0..\backup\%date:~0,4%%date:~5,2%%date:~8,2%
mkdir "%BACKUP_DIR%" 2>nul

echo === Miru Backup: %date% %time% ===
echo Target: %BACKUP_DIR%
echo.

if exist "%~dp0..\config\settings.yaml" (
    copy /Y "%~dp0..\config\settings.yaml" "%BACKUP_DIR%\" >nul
    echo [OK] config\settings.yaml
) else (
    echo [MISS] config\settings.yaml - CRITICAL
)

if exist "%~dp0..\data\miru.db" (
    copy /Y "%~dp0..\data\miru.db" "%BACKUP_DIR%\" >nul
    echo [OK] data\miru.db
)

if exist "%~dp0run_daily.py" (
    copy /Y "%~dp0run_daily.py" "%BACKUP_DIR%\" >nul
    echo [OK] run_daily.py
)

if exist "%~dp0run_daily.bat" (
    copy /Y "%~dp0run_daily.bat" "%BACKUP_DIR%\" >nul
    echo [OK] run_daily.bat
)

if exist "%~dp0setup_scheduler.ps1" (
    copy /Y "%~dp0setup_scheduler.ps1" "%BACKUP_DIR%\" >nul
    echo [OK] setup_scheduler.ps1
)

if exist "%~dp0..\pyproject.toml" (
    copy /Y "%~dp0..\pyproject.toml" "%BACKUP_DIR%\" >nul
    echo [OK] pyproject.toml
)

if exist "%USERPROFILE%\.chatlog\chatlog.json" (
    copy /Y "%USERPROFILE%\.chatlog\chatlog.json" "%BACKUP_DIR%\" >nul
    echo [OK] chatlog.json
)

echo.
echo === Backup complete: %BACKUP_DIR% ===
exit /b 0
