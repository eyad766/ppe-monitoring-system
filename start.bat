@echo off
title PPE Monitoring System
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run - installing the system...
    call install.bat
    if not exist ".venv\Scripts\python.exe" exit /b 1
)

echo ======================================================================
echo   PPE Monitoring System is starting...
echo   Dashboard: http://127.0.0.1:8000  (opens automatically)
echo   Keep this window open. Press Ctrl+C or close it to stop the system.
echo ======================================================================
".venv\Scripts\python.exe" -m backend.main
if errorlevel 1 (
    echo.
    echo [X] The system stopped with an error. See logs\app.log for details.
    pause
)
