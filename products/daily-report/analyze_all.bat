@echo off
chcp 65001 >nul
REM ============================================================
REM Miru Chat Analyzer — 一键批量全流程
REM
REM 双击运行:
REM   1. 自动请求管理员权限（读取微信数据库需要）
REM   2. 询问要处理的联系人（留空 = 白名单全部）
REM   3. 自动导出 + 统计 + 时间线 + AI 分析
REM   4. 完成后自动打开输出目录
REM ============================================================

REM ---- 请求管理员权限（非管理员时重新以管理员启动） ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM ---- 进入项目目录 ----
cd /d "%~dp0"

echo.
echo ============================================================
echo   Miru Chat Analyzer — 一键批量全流程
echo ============================================================
echo   联系人白名单: config\contacts.yaml
echo   输出目录:     output\
echo ============================================================
echo.

REM ---- 询问联系人（留空 = 全部） ----
set /p CONTACTS=请输入联系人名称（多个用逗号分隔，留空=处理全部）:

REM ---- 优先使用项目自己的 .venv，兼容迁移前的仓库根 venv ----
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%CD%\..\..\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到 Python 虚拟环境，请先运行: python -m venv .venv
    pause
    exit /b 1
)

set EXTRA_ARGS=
if not "%CONTACTS%"=="" set EXTRA_ARGS=--contacts %CONTACTS%

echo.
"%PYTHON_EXE%" scripts\analyze_all.py --output output %EXTRA_ARGS%
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
echo   处理完成 (exit=%EXIT_CODE%)
echo ============================================================
echo.

REM ---- 打开输出目录 ----
start "" explorer "%CD%\output"

pause
exit /b %EXIT_CODE%
