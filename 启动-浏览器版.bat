@echo off
title Codex API Manager
cd /d "%~dp0"

echo ============================================
echo   Codex API Manager - Browser Mode
echo ============================================
echo.

rem Pick a Python interpreter that already has the dependencies.
rem (Multiple Python versions may be installed; PATH order is unreliable.)
set "PYEXE="

python -c "import flask, tomlkit, requests, waitress" >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  py -3.9 -c "import flask, tomlkit, requests, waitress" >nul 2>nul && set "PYEXE=py -3.9"
)
if not defined PYEXE (
  py -3.12 -c "import flask, tomlkit, requests, waitress" >nul 2>nul && set "PYEXE=py -3.12"
)
if not defined PYEXE (
  py -3.11 -c "import flask, tomlkit, requests, waitress" >nul 2>nul && set "PYEXE=py -3.11"
)
if not defined PYEXE (
  py -3.10 -c "import flask, tomlkit, requests, waitress" >nul 2>nul && set "PYEXE=py -3.10"
)

if defined PYEXE goto :run

echo [1/2] Checking dependencies...
python -c "import sys" >nul 2>nul
if errorlevel 1 goto :nopython
goto :installdeps

:run
echo [1/2] Dependencies OK  (%PYEXE%)
echo [2/2] Starting service and opening browser...
echo Close this window to stop the service.
echo.
%PYEXE% app.py --browser

echo.
echo Service stopped.
pause
exit /b 0

:installdeps
echo [INFO] Installing dependencies (first run, needs network)...
python -m pip install -r requirements.txt
if errorlevel 1 goto :installfail
set "PYEXE=python"
goto :run

:nopython
echo [ERROR] Python not found. Install Python 3.9+ with Add-to-PATH.
pause
exit /b 1

:installfail
echo [ERROR] Dependency install failed. Check your network.
pause
exit /b 1
