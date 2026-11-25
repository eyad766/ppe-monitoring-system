@echo off
setlocal EnableDelayedExpansion
title PPE Monitoring System - Installer
cd /d "%~dp0"

echo ======================================================================
echo   PPE Monitoring System - Installation
echo ======================================================================
echo.

rem ---------------------------------------------------------------- find Python
set "TRIED_WINGET="
:findpy
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32 else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [X] Python 3.10 - 3.13 ^(64-bit^) was not found.
    echo.
    where winget >nul 2>&1
    if !errorlevel! == 0 (
        choice /C YN /M "Install Python 3.12 now with winget"
        if !errorlevel! == 1 (
            if not defined TRIED_WINGET (
                set "TRIED_WINGET=1"
                winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
                echo.
                goto findpy
            )
        )
    )
    echo Download Python 3.12 from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" during setup. Then run install.bat again.
    pause
    exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import platform; print(platform.python_version())"') do set PYVER=%%i
echo [OK] Using Python %PYVER%  (%PY%)

rem ---------------------------------------------------------------- virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [..] Creating virtual environment in .venv
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        pause
        exit /b 1
    )
)
set "VPY=.venv\Scripts\python.exe"

echo [..] Upgrading pip
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q

echo [..] Installing dependencies (first time: several minutes, ~1 GB download)
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [X] Dependency installation failed. Check your internet connection and run install.bat again.
    pause
    exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

for %%D in (data data\violations logs reports config models) do if not exist "%%D" mkdir "%%D"

echo [..] Checking AI model files (downloads any that are missing)
"%VPY%" tools\download_models.py
if errorlevel 1 (
    echo [X] Could not download the AI models. Check your internet connection and run install.bat again.
    pause
    exit /b 1
)

echo.
echo [..] Running the environment check (AI models + cameras)
"%VPY%" -m backend.selfcheck
echo.
echo ======================================================================
echo   Installation finished. Start the system with start.bat
echo ======================================================================
pause
exit /b 0
