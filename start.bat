@echo off
setlocal enabledelayedexpansion
title Wardrobe - AI & Rules File Organizer

cd /d "%~dp0"

echo ======================================================================
echo   ⚡ WARDROBE - Intelligent File Organizer ^& Live Control Room
echo ======================================================================
echo.

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERROR] Python is not installed or not found in your PATH.
        echo Please download and install Python 3.10+ from https://www.python.org/
        echo (Make sure to check "Add Python to PATH" during installation)
        echo.
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

:: 2. Verify / Install Dependencies
echo [*] Checking Python environment...
%PYTHON_CMD% -c "import flask, pymupdf, pypdf, PIL" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required dependencies from requirements.txt...
    %PYTHON_CMD% -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [!] Warning: Some dependencies failed to install. Continuing anyway...
    )
) else (
    echo [OK] All core dependencies verified.
)

:: 3. Launch Dashboard & Auto-open Browser
echo.
echo ======================================================================
echo   Starting Live Dashboard at http://127.0.0.1:8765
echo   Press CTRL+C in this window to stop the server.
echo ======================================================================
echo.

:: Launch browser in background after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8765"

:: Run dashboard server
%PYTHON_CMD% organize.py dashboard

pause
