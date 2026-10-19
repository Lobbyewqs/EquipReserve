@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist data\mysql.json (
  .venv\Scripts\python.exe mysql_local.py
  if errorlevel 1 goto end
  .venv\Scripts\python.exe reset_password.py
) else (
  python reset_password.py
)
:end
pause
