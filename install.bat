@echo off
setlocal EnableExtensions
title Safeer OS - Namestitev

rem Vedno delaj iz mape namestitvenega paketa. Tako zagon deluje tudi,
rem ce Windows odpre ukazno vrstico v C:\Windows\System32.
cd /d "%~dp0"

if not exist "%~dp0install.ps1" (
    echo.
    echo [NAPAKA] Datoteka install.ps1 ni bila najdena.
    echo Razsiri CELOTEN ZIP v eno mapo in ponovno zazeni install.bat.
    echo Ne zaganjaj datotek neposredno iz predogleda ZIP arhiva.
    echo.
    pause
    exit /b 2
)

rem Za pravilo pozarnega zidu je potrebna skrbniska seja. Ob navadnem
rem dvokliku jo zahtevamo samodejno in ohranimo absolutno pot do skripte.
net session >nul 2>&1
if errorlevel 1 (
    echo Zahtevam skrbniske pravice za namestitev Safeer OS ...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
    if errorlevel 1 (
        echo.
        echo [NAPAKA] Skrbnisko dovoljenje ni bilo potrjeno ali zagon ni uspel.
        pause
        exit /b 1
    )
    exit /b 0
)

echo Zaganjam namestitev Safeer OS iz:
echo %~dp0
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Clean -LaunchOS %*
set "SAFEER_EXIT=%ERRORLEVEL%"
if not "%SAFEER_EXIT%"=="0" (
    echo.
    echo [NAPAKA] Namestitev se je zakljucila z napako (koda %SAFEER_EXIT%).
    pause
)
exit /b %SAFEER_EXIT%
