@echo off
title Codex API Manager
cd /d "%~dp0"

echo ============================================
echo   Codex API Manager - Browser Mode
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 goto :nopython

echo [1/2] Checking dependencies...
python -c "import flask, tomlkit, requests, waitress" >nul 2>nul
if errorlevel 1 goto :installdeps

:run
echo [2/2] Starting service and opening browser...
echo Close this window to stop the service.
echo.
python app.py --browser

echo.
echo Service stopped.
pause
exit /b 0

:installdeps
echo [INFO] Installing dependencies (first run, needs network)...
python -m pip install -r requirements.txt
if errorlevel 1 goto :installfail
goto :run

:nopython
echo [ERROR] Python not found. Install Python 3.9+ with Add-to-PATH.
pause
exit /b 1

:installfail
echo [ERROR] Dependency install failed. Check your network.
pause
exit /b 1