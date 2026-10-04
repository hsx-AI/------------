@echo off
cd /d "%~dp0"
"%CD%\pc_receiver\.venv\Scripts\python.exe" -m dashboard_api.main
