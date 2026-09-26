<#
.SYNOPSIS
    Hiter samopreizkus nameščene Windows različice Safeer OS.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\PREIZKUSI-SAFEER.ps1 -Launch
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\SafeerOS",
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$appDir = Join-Path $InstallDir "app"
$required = @(
    (Join-Path $InstallDir "SafeerOS.exe"),
    (Join-Path $appDir "windows\safeer_os_windows.py"),
    (Join-Path $appDir "windows\safeer_windows\os_app.py"),
    (Join-Path $appDir "assets\os\index.html"),
    (Join-Path $appDir "assets\link\index.html"),
    (Join-Path $appDir "core\os_media.py")
)

Write-Host "Safeer OS - samopreizkus" -ForegroundColor Cyan
$missing = @($required | Where-Object { -not (Test-Path $_) })
if ($missing.Count) {
    Write-Host "[NAPAKA] Namestitev ni popolna:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "Ponovno razširite celoten ZIP in dvokliknite install.bat." -ForegroundColor Yellow
    exit 2
}
Write-Host "[OK] Vse programske datoteke so prisotne." -ForegroundColor Green

$python = $null
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $python = @($pyLauncher.Source, "-3")
} else {
    $pythonExe = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonExe) { $python = @($pythonExe.Source) }
}
if (-not $python) {
    Write-Host "[NAPAKA] Python 3 ni dosegljiv." -ForegroundColor Red
    exit 3
}

$smoke = @"
import os, sys
sys.path.insert(0, r'$appDir')
sys.path.insert(0, r'$appDir\windows')
from safeer_windows.control_backend import SafeerControlBackend
from core.os_media import MediaCenter
cb = SafeerControlBackend(config_pot=os.path.join(os.environ.get('TEMP', r'$InstallDir'), 'safeer-smoke-link.json'))
assert cb.stanje_linka()['control'] is True
assert cb.navidezni_zaslon.stanje_naprave()['screen'] == 'virtual'
mc = MediaCenter(os.path.join(os.environ.get('TEMP', r'$InstallDir'), 'safeer-smoke-media'), roots=[])
assert isinstance(mc.catalog(), dict)
print('SAFEER_SMOKE_OK')
"@

$exe = $python[0]
$prefix = if ($python.Count -gt 1) { @($python[1]) } else { @() }
$result = & $exe @prefix -c $smoke 2>&1
if ($LASTEXITCODE -ne 0 -or $result -notmatch "SAFEER_SMOKE_OK") {
    Write-Host "[NAPAKA] Programsko jedro ni prestalo samopreizkusa:" -ForegroundColor Red
    Write-Host $result
    exit 4
}
Write-Host "[OK] Safeer OS, Safeer Control, navidezni zaslon in Safeer Media so pripravljeni." -ForegroundColor Green

$vlc = @(
    "$env:ProgramFiles\VideoLAN\VLC\libvlc.dll",
    "${env:ProgramFiles(x86)}\VideoLAN\VLC\libvlc.dll"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($vlc) {
    Write-Host "[OK] LibVLC je nameščen: $vlc" -ForegroundColor Green
} else {
    Write-Host "[OPOZORILO] LibVLC ni najden; neposredni video tokovi bodo uporabili rezervni predvajalnik." -ForegroundColor Yellow
}

if ($Launch) {
    Start-Process -FilePath (Join-Path $InstallDir "SafeerOS.exe")
    Write-Host "[OK] Safeer OS je zagnan." -ForegroundColor Green
}

Write-Host "Samopreizkus je uspešno končan." -ForegroundColor Cyan
