@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM Miru Assistant - Universal Launcher (V2)
REM
REM Invoked by Windows Task Scheduler daily at 22:00.
REM Also callable manually.
REM
REM Tier 0 log: data\logs\launcher.log (shell level)
REM Tier 1 log: data\logs\bootstrap.log (Python level)
REM Tier 2 log: data\logs\miru_YYYY-MM-DD.log (loguru)
REM
REM This file writes launcher.log even if Python is absent.
REM ============================================================

REM ---- Locate project root (%~dp0 = directory of this .bat) ----
set "MIRU_ROOT=%~dp0"
if "%MIRU_ROOT:~-1%"=="\" set "MIRU_ROOT=%MIRU_ROOT:~0,-1%"

set "LOG_DIR=%MIRU_ROOT%\data\logs"
set "LOG_FILE=%LOG_DIR%\launcher.log"
set "PYTHONW=%MIRU_ROOT%\venv\Scripts\pythonw.exe"

REM ---- Ensure log directory exists ----
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM ---- Log startup ----
echo [%date% %time%] ============================================= >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Miru Launcher START >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Project: "%MIRU_ROOT%" >> "%LOG_FILE%" 2>&1
echo [%date% %time%] Python: "%PYTHONW%" >> "%LOG_FILE%" 2>&1

REM ---- Shell-level checks ----
if not exist "%PYTHONW%" (
    echo [%date% %time%] [FATAL] pythonw.exe not found >> "%LOG_FILE%" 2>&1
    echo [%date% %time%] [FATAL] Path: "%PYTHONW%" >> "%LOG_FILE%" 2>&1
    echo [%date% %time%] [FATAL] Run: python -m venv venv >> "%LOG_FILE%" 2>&1
    exit /b 1
)

if not exist "%MIRU_ROOT%\config\settings.yaml" (
    echo [%date% %time%] [FATAL] config\settings.yaml not found >> "%LOG_FILE%" 2>&1
    echo [%date% %time%] [FATAL] Copy from settings.example.yaml and edit >> "%LOG_FILE%" 2>&1
    exit /b 1
)

REM ---- Launch Python bootstrap ----
set "BOOTSTRAP_PY=%MIRU_ROOT%\src\miru\bootstrap.py"

echo [%date% %time%] Running pythonw.exe bootstrap.py >> "%LOG_FILE%" 2>&1

call "%PYTHONW%" "%BOOTSTRAP_PY%" >> "%LOG_FILE%" 2>&1
set EXIT_CODE=%ERRORLEVEL%

echo [%date% %time%] Bootstrap exited (code=%EXIT_CODE%) >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%" 2>&1

exit /b %EXIT_CODE%
