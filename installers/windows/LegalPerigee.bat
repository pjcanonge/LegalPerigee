@echo off
:: LegalPerigee — Windows Launcher
:: Double-click to open LegalPerigee in its own window.

title LegalPerigee
cd /d "%~dp0..\.."

:: Load .env variables (skip comments and blank lines)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" if not "%%A"=="" (
            set "%%A=%%B"
        )
    )
)

:: Check venv exists
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  LegalPerigee dependencies not installed.
    echo  Running setup...
    echo.
    powershell -ExecutionPolicy Bypass -File "installers\windows\setup.ps1"
    exit /b
)

:: Launch
echo Starting LegalPerigee...
start "" ".venv\Scripts\python.exe" window.py
