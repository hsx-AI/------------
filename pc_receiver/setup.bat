@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple -r requirements.txt
if errorlevel 1 exit /b 1
echo Setup complete. Configure the shared secret with:
echo   .venv\Scripts\python.exe -m app.main set-secret
endlocal
