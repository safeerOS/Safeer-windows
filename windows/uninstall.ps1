<#
.SYNOPSIS
    Odstranitev Safeer OS & Safeer Control iz sistema Windows.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\SafeerOS",
    [switch]$NoPrompt
)

Write-Host "Odstranjujem Safeer OS & Control iz $InstallDir..." -ForegroundColor Yellow

# Zapri morebitne tekococe procese
Get-Process SafeerOS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process SafeerControl -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Odstrani bližnjice
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$StartPrograms = [Environment]::GetFolderPath("Programs")
$SafeerStartFolder = Join-Path $StartPrograms "Safeer OS"

Remove-Item (Join-Path $DesktopPath "Safeer Control.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DesktopPath "Safeer OS.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DesktopPath "Safeer Browser.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item $SafeerStartFolder -Recurse -Force -ErrorAction SilentlyContinue

# Odstrani mapo aplikacije
if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Požarni zid
try {
    Remove-NetFirewallRule -DisplayName "Safeer OS & Control (Link Port 8990)" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "Safeer OS Aplikacija" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "Safeer Control Aplikacija" -ErrorAction SilentlyContinue
} catch {}

Write-Host "[OK] Safeer OS & Control uspesno odstranjena." -ForegroundColor Green
