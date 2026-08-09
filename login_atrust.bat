@echo off
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
if "%ATRUST_PHONE%"=="" (
  set /p ATRUST_PHONE=请输入 aTrust 登录手机号: 
)
python "%~dp0atrust_auto_login.py" --phone "%ATRUST_PHONE%"
if errorlevel 1 pause
if errorlevel 1 exit /b 1
if not exist "%~dp0ecs_login_config.json" (
  echo.
  echo aTrust 已完成。若要继续自动登录 AE 平台，请复制 ecs_login_config.example.json
  echo 为 ecs_login_config.json，并填写账号密码。
  pause
  exit /b 0
)
"%~dp0pc_receiver\.venv\Scripts\python.exe" "%~dp0ecs_auto_login.py"
if errorlevel 1 pause
endlocal
