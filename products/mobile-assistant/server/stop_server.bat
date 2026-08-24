@echo off
chcp 65001 >nul
REM ============================================================
REM Miru 后端停止脚本：结束占用 8765 端口的后端进程（释放约 1GB 内存）
REM 下次需要时双击 start_server.bat 即可重新启动
REM ============================================================

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  echo 正在停止 Miru 后端 (PID %%p)...
  taskkill /F /PID %%p >nul 2>&1
)
echo Miru 后端已停止
exit /b 0
