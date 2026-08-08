@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: virtual environment missing. Run: python -m venv .venv
  exit /b 1
)
echo Dashboard: http://127.0.0.1:8765/
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765/'"
".venv\Scripts\python.exe" -m app.main run
endlocal
