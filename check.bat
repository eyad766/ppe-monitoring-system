@echo off
title PPE Monitoring System - Environment Check
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Not installed yet - run install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m backend.selfcheck
pause
