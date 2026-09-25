@echo off
title Safeer OS & Control - Namestitev
echo Zaganjam namestitveno skripto PowerShell...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Namestitev se je zakljucila z napako (koda %ERRORLEVEL%).
    pause
)
