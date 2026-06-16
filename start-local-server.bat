@echo off
setlocal

set "BASE_DIR=C:\Users\User\Ai Projects\Luxpower"
set "SERVER_DIR=%BASE_DIR%\energy_flow"
set "URL=http://127.0.0.1:8765/"

if not exist "%SERVER_DIR%\server.py" (
  echo [ERROR] Could not find "%SERVER_DIR%\server.py"
  pause
  exit /b 1
)

cd /d "%SERVER_DIR%"

echo Starting local server from: %SERVER_DIR%
start "" cmd /c "python server.py"

timeout /t 2 /nobreak >nul
start "" "%URL%"

echo Local dashboard opened: %URL%
exit /b 0
