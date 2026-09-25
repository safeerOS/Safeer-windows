@echo off
title Safeer OS & Control - Odstranitev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
