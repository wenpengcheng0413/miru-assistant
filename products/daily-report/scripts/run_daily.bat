@echo off
chcp 65001 >nul
REM ============================================================
REM Miru Assistant — 每日运行脚本
REM
REM 由 Windows 任务计划程序在每天 21:00 调用。
REM 也可手动运行: scripts\run_daily.bat
REM ============================================================

cd /d "%~dp0\.."

REM 记录开始
echo [%date% %time%] Miru Daily Run START >> data\logs\scheduler.log

REM 优先使用项目自己的 .venv，兼容迁移前的仓库根 venv
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%CD%\..\..\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [%date% %time%] Python virtualenv not found >> data\logs\scheduler.log
    exit /b 1
)
"%PYTHON_EXE%" scripts\run_daily.py >> data\logs\scheduler.log 2>&1
set EXIT_CODE=%ERRORLEVEL%

REM 记录结束
echo [%date% %time%] Miru Daily Run END (exit=%EXIT_CODE%) >> data\logs\scheduler.log
echo. >> data\logs\scheduler.log

exit /b %EXIT_CODE%
