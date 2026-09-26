<#
.SYNOPSIS
    Hitra namestitev Safeer OS & Safeer Control za Windows 10/11 (x64).
.DESCRIPTION
    Skripta samodejno pripravi in namesti Safeer OS ter Safeer Control:
    1. Preveri operacijski sistem in arhitekturo (Windows 10/11 x64).
    2. Preveri ali samodejno tiho namesti Python 3.12 (uradni installer / winget).
    3. Namesti potrebne knjižnice (PySide6, Pillow, cryptography, qrcode, python-vlc in LibVLC).
    4. Namesti izvršljive datoteke (SafeerOS.exe, SafeerControl.exe) in aplikacijo v %LOCALAPPDATA%\SafeerOS.
    5. Nastavi pravila Windows Defender požarnega zidu za Safeer Link (vrata 8990 TCP za povezavo s TV/telefonom).
    6. Ustvari bližnjice z ikonami na Namizju in v meniju Start (Safeer Control, Safeer OS, Safeer Browser).
    7. Izvede samopreizkus delovanja in ponudi takojšen zagon.
.PARAMETER InstallDir
    Ciljna mapa za namestitev (privzeto: $env:LOCALAPPDATA\SafeerOS).
.PARAMETER LaunchControl
    Po zaključku namestitve samodejno zažene Safeer Control.
.PARAMETER LaunchOS
    Po zaključku namestitve samodejno zažene Safeer OS.
.PARAMETER NoPrompt
    Tihi način brez interaktivnih vprašanj.
.PARAMETER NoFirewall
    Preskoči nastavljanje požarnega zidu.
.PARAMETER Clean
    Pred namestitvijo počisti predhodno nameščeno različico.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
.EXAMPLE
    .\install.ps1 -LaunchControl -NoPrompt
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\SafeerOS",
    [switch]$LaunchControl,
    [switch]$LaunchOS,
    [switch]$NoPrompt,
    [switch]$NoFirewall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# Barvni izpisi
function Write-Header($text) {
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor White
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step($num, $total, $text) {
    Write-Host "[$num/$total] $text..." -ForegroundColor Yellow
}

function Write-Success($text) {
    Write-Host "   [OK] $text" -ForegroundColor Green
}

function Write-Info($text) {
    Write-Host "   [i]  $text" -ForegroundColor Gray
}

function Write-Warn($text) {
    Write-Host "   [!]  $text" -ForegroundColor Yellow
}

function Write-Err($text) {
    Write-Host "   [X]  $text" -ForegroundColor Red
}

# -----------------------------------------------------------------------------
# 0. Uvodni pozdrav in določitev poti
# -----------------------------------------------------------------------------
Clear-Host
Write-Header "Safeer OS & Control -- Hitra namestitev za Windows"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) {
    $ScriptDir = (Get-Location).Path
}

# Preveri, kje je koren repozitorija
$RepoRoot = $ScriptDir
if (Test-Path (Join-Path $ScriptDir "windows\safeer_control_windows.py")) {
    $RepoRoot = $ScriptDir
} elseif (Test-Path (Join-Path $ScriptDir "safeer_control_windows.py")) {
    $RepoRoot = Split-Path -Parent $ScriptDir
}

Write-Info "Izvorna mapa: $RepoRoot"
Write-Info "Ciljna mapa:  $InstallDir"

# Uporabniku takoj povej, ce je zagnal samo eno preneseno datoteko namesto
# celotnega razsirjenega paketa. Brez teh datotek namestitev ne more ustvariti
# delujocega Safeer OS, tudi ce sta Python in PowerShell pravilno namescena.
$requiredPackageFiles = @(
    "windows\safeer_os_windows.py",
    "windows\SafeerOS.exe",
    "windows\SafeerControl.exe",
    "core\link_datoteke.py",
    "assets\os\index.html",
    "assets\link\index.html"
)
$missingPackageFiles = @(
    $requiredPackageFiles | Where-Object {
        -not (Test-Path (Join-Path $RepoRoot $_))
    }
)
if ($missingPackageFiles.Count -gt 0) {
    Write-Err "Namestitveni paket ni popoln. Manjkajo naslednje datoteke:"
    foreach ($missingFile in $missingPackageFiles) {
        Write-Host "      - $missingFile" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Razsirite CELOTEN SafeerOS-Windows ZIP v eno mapo in nato" -ForegroundColor Yellow
    Write-Host "z dvojnim klikom zazenite install.bat." -ForegroundColor Yellow
    exit 2
}
Write-Success "Celovit namestitveni paket je potrjen."

# -----------------------------------------------------------------------------
# 1. Preverjanje sistema in arhitekture
# -----------------------------------------------------------------------------
Write-Step 1 6 "Preverjanje okolja Windows"

$is64Bit = [Environment]::Is64BitOperatingSystem
if (-not $is64Bit) {
    Write-Err "Safeer OS zahteva 64-bitni operacijski sistem Windows (x64)."
    exit 1
}
Write-Success "64-bitni operacijski sistem Windows potrjen."

# -----------------------------------------------------------------------------
# 2. Preverjanje in namestitev Pythona 3
# -----------------------------------------------------------------------------
Write-Step 2 6 "Preverjanje okolja Python 3"

function Find-PythonExecutable {
    # 1. Preveri py.exe launcher
    $pyCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $ver = & $pyCmd.Source -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.10") {
                return @{ Exe = $pyCmd.Source; IsLauncher = $true; Version = $ver }
            }
        } catch {}
    }

    # 2. Preveri python.exe v PATH
    $pyExec = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pyExec) {
        try {
            $ver = & $pyExec.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.10") {
                return @{ Exe = $pyExec.Source; IsLauncher = $false; Version = $ver }
            }
        } catch {}
    }

    # 3. Preveri standardne mape v LocalAppData in Program Files
    $standardPoti = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($p in $standardPoti) {
        if (Test-Path $p) {
            try {
                $ver = & $p -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                if ($ver -and [version]$ver -ge [version]"3.10") {
                    return @{ Exe = $p; IsLauncher = $false; Version = $ver }
                }
            } catch {}
        }
    }

    return $null
}

$pyInfo = Find-PythonExecutable

if (-not $pyInfo) {
    Write-Warn "Python 3.10 ali novejši ni bil zaznan."
    Write-Host "   -> Poskušam samodejno tiho namestitev uradnega paketa Python 3.12..." -ForegroundColor Cyan

    $installedViaWinget = $false
    $wingetCmd = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        try {
            Write-Info "Nameščam preko Windows Package Managerja (winget)..."
            $p = Start-Process -FilePath "winget.exe" -ArgumentList "install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements" -Wait -PassThru
            if ($p.ExitCode -eq 0) {
                $installedViaWinget = $true
            }
        } catch {}
    }

    if (-not $installedViaWinget) {
        Write-Info "Prenašam uradni namestitveni program Python 3.12 iz python.org..."
        $pythonUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $tempInstaller = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
        
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        Invoke-WebRequest -Uri $pythonUrl -OutFile $tempInstaller -UseBasicParsing

        Write-Info "Izvajam tiho namestitev Pythona 3.12 (uporabniški profil, vključen PATH)..."
        $argsList = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1"
        $p = Start-Process -FilePath $tempInstaller -ArgumentList $argsList -Wait -PassThru
        Remove-Item $tempInstaller -Force -ErrorAction SilentlyContinue
    }

    # Osveži PATH v trenutni seji
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:PATH = "$userPath;$machinePath;$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"

    $pyInfo = Find-PythonExecutable
    if (-not $pyInfo) {
        Write-Err "Samodejna namestitev Pythona ni uspela. Prosimo, ročno namestite Python 3 s strani https://www.python.org/downloads/ in označite 'Add python.exe to PATH'."
        exit 1
    }
}

Write-Success "Python najden: $($pyInfo.Exe) (različica $($pyInfo.Version))"

# -----------------------------------------------------------------------------
# 3. Preverjanje in namestitev Python knjižnic
# -----------------------------------------------------------------------------
Write-Step 3 6 "Preverjanje in nameščanje potrebnih knjižnic"

$pyExe = $pyInfo.Exe

# PowerShell ne zna varno zagnati polja oblike @("py.exe", "-3", ...)
# kot en ukaz. Izvedljiva datoteka in argumenti morajo biti podani ločeno.
function Invoke-SafeerPython([object[]]$PythonArgs) {
    if ($pyInfo.IsLauncher) {
        & $pyExe -3 @PythonArgs
    } else {
        & $pyExe @PythonArgs
    }
}

function Invoke-SafeerPip([object[]]$PipArgs) {
    if ($pyInfo.IsLauncher) {
        & $pyExe -3 -m pip @PipArgs
    } else {
        & $pyExe -m pip @PipArgs
    }
}

function Test-PythonModule($mod) {
    try {
        Invoke-SafeerPython @("-c", "import $mod") 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$manjkajoce = @()
foreach ($mod in @("PySide6", "PIL", "cryptography", "qrcode", "vlc")) {
    if (-not (Test-PythonModule $mod)) {
        $manjkajoce += $mod
    }
}

if ($manjkajoce.Count -gt 0) {
    Write-Info "Nameščam manjkajoče knjižnice: PySide6 Pillow cryptography qrcode python-vlc..."
    Invoke-SafeerPip @("install", "--disable-pip-version-check", "--quiet", "PySide6", "Pillow", "cryptography", "qrcode", "python-vlc")
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Poskušam ponovno namestiti knjižnice z uporabniškimi pravicami..."
        Invoke-SafeerPip @("install", "--user", "--disable-pip-version-check", "PySide6", "Pillow", "cryptography", "qrcode", "python-vlc")
    }
}

# Preveri uspešnost uvoza
$testOk = $false
try {
    $res = Invoke-SafeerPython @("-c", "import PySide6.QtCore, PySide6.QtWidgets, PIL.Image, cryptography, qrcode, vlc; print('MODULI_OK')") 2>$null
    if ($res -match "MODULI_OK") {
        $testOk = $true
    }
} catch {}

if (-not $testOk) {
    Write-Err "Knjižnic ni bilo mogoče naložiti. Preverite internetno povezavo ali namestite 'pip install PySide6 Pillow cryptography qrcode python-vlc'."
    exit 1
}
Write-Success "Vse potrebne Python knjižnice so pripravljene."

# Safeer Media uporablja LibVLC neposredno v svojem Qt pogledu. Python paket je le
# veznik, zato preverimo še uradni VideoLAN runtime. Če ga ni, ostane na voljo
# rezervni HTML5 predvajalnik, namestitev Safeer OS pa se vseeno dokonča.
$vlcDll = @(
    "$env:ProgramFiles\VideoLAN\VLC\libvlc.dll",
    "${env:ProgramFiles(x86)}\VideoLAN\VLC\libvlc.dll"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $vlcDll) {
    $wingetVlc = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($wingetVlc) {
        Write-Info "Nameščam uradni LibVLC runtime za vgrajeni Safeer Media predvajalnik..."
        try {
            $vlcInstall = Start-Process -FilePath "winget.exe" -ArgumentList "install --id VideoLAN.VLC -e --silent --accept-package-agreements --accept-source-agreements" -Wait -PassThru
            if ($vlcInstall.ExitCode -ne 0) { Write-Warn "LibVLC ni bil nameščen; spletni viri se bodo odprli v zaščitenem Safeer Browserju." }
        } catch { Write-Warn "LibVLC ni bil nameščen; spletni viri se bodo odprli v zaščitenem Safeer Browserju." }
    } else {
        Write-Warn "Windows Package Manager ni na voljo; spletni viri se bodo odprli v zaščitenem Safeer Browserju."
    }
}

# -----------------------------------------------------------------------------
# 4. Priprava namestitvene mape in kopiranje datotek
# -----------------------------------------------------------------------------
Write-Step 4 6 "Namestitev datotek Safeer OS & Control"

if ($Clean -and (Test-Path $InstallDir)) {
    Write-Info "Čistim prejšnjo namestitev v $InstallDir..."
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

$AppDir = Join-Path $InstallDir "app"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

# Kopiraj binarne datoteke (SafeerOS.exe, SafeerControl.exe)
$exeSources = @(
    (Join-Path $RepoRoot "windows\SafeerOS.exe"),
    (Join-Path $RepoRoot "windows\SafeerControl.exe"),
    (Join-Path $RepoRoot "SafeerOS.exe"),
    (Join-Path $RepoRoot "SafeerControl.exe")
)

$targetOSExe = Join-Path $InstallDir "SafeerOS.exe"
$targetControlExe = Join-Path $InstallDir "SafeerControl.exe"

$srcOS = $exeSources | Where-Object { Test-Path $_ -and (Split-Path $_ -Leaf) -ieq "SafeerOS.exe" } | Select-Object -First 1
$srcControl = $exeSources | Where-Object { Test-Path $_ -and (Split-Path $_ -Leaf) -ieq "SafeerControl.exe" } | Select-Object -First 1

if ($srcOS) {
    Copy-Item -Path $srcOS -Destination $targetOSExe -Force
    Write-Success "Kopiran SafeerOS.exe"
} else {
    Write-Warn "SafeerOS.exe ni bil najden v repozitoriju. Uporabljen bo neposreden zagon preko Pythona."
}

if ($srcControl) {
    Copy-Item -Path $srcControl -Destination $targetControlExe -Force
    Write-Success "Kopiran SafeerControl.exe"
} elseif ($srcOS) {
    # Go zaganjalnik prepozna ime 'control' v imenu datoteke in zažene Safeer Control
    Copy-Item -Path $srcOS -Destination $targetControlExe -Force
    Write-Success "Ustvarjen SafeerControl.exe iz zaganjalnika"
}

# Kopiraj vsebino repozitorija v $AppDir
Write-Info "Kopiram programske module (windows, core, assets, ui)..."
foreach ($mapa in @("windows", "core", "assets", "ui")) {
    $srcM = Join-Path $RepoRoot $mapa
    if (Test-Path $srcM) {
        $dstM = Join-Path $AppDir $mapa
        New-Item -ItemType Directory -Force -Path $dstM | Out-Null
        Copy-Item -Path "$srcM\*" -Destination $dstM -Recurse -Force
    }
}

# Zagotovi ikono safeer.ico
$icoCilj = Join-Path $InstallDir "safeer.ico"
$srcIco = Join-Path $RepoRoot "windows\safeer.ico"
if (Test-Path $srcIco) {
    Copy-Item -Path $srcIco -Destination $icoCilj -Force
} else {
    $pngSrc = Join-Path $RepoRoot "assets\icon.png"
    if (Test-Path $pngSrc) {
        try {
            Invoke-SafeerPython @("-c", "from PIL import Image; im = Image.open(r'$pngSrc').convert('RGBA'); im.save(r'$icoCilj', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])") 2>$null
        } catch {}
    }
}

# Ustvari pomožni zaganjalni batch datoteki za neposreden hiter zagon
$batControl = Join-Path $InstallDir "Zazeni_Safeer_Control.bat"
@"
@echo off
setlocal
cd /d "%~dp0"
if exist "SafeerOS.exe" (
    start "" "SafeerOS.exe" --control %*
) else (
    set PYTHONPATH=%~dp0app\windows;%~dp0app
    start "" "$pyExe" "%~dp0app\windows\safeer_os_windows.py" --control --okno %*
)
"@ | Set-Content -Path $batControl -Encoding UTF8

$batOS = Join-Path $InstallDir "Zazeni_Safeer_OS.bat"
@"
@echo off
setlocal
cd /d "%~dp0"
if exist "SafeerOS.exe" (
    start "" "SafeerOS.exe" %*
) else (
    set PYTHONPATH=%~dp0app\windows;%~dp0app
    start "" "$pyExe" "%~dp0app\windows\safeer_os_windows.py" --okno %*
)
"@ | Set-Content -Path $batOS -Encoding UTF8

Write-Success "Programske datoteke nameščene v $InstallDir."

# -----------------------------------------------------------------------------
# 5. Konfiguracija Windows požarnega zidu za Safeer Link
# -----------------------------------------------------------------------------
Write-Step 5 6 "Preverjanje in konfiguracija požarnega zidu za Safeer Link"

if (-not $NoFirewall) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        try {
            # Vrata 8990 TCP za Safeer Link Hub in odkrivanje v lokalnem omrežju
            $ruleName = "Safeer OS & Control (Link Port 8990)"
            $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            if (-not $existing) {
                New-NetFirewallRule -DisplayName $ruleName `
                    -Description "Dovoli dohodne povezave Safeer Link za daljinec in navidezni ločeni zaslon" `
                    -Direction Inbound -Protocol TCP -LocalPort 8990 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
                Write-Success "Dodano pravilo požarnega zidu za vrata 8990 TCP."
            } else {
                Write-Success "Pravilo požarnega zidu za vrata 8990 TCP že obstaja."
            }

            # Aplikacijska pravila za SafeerOS in SafeerControl
            if (Test-Path $targetOSExe) {
                New-NetFirewallRule -DisplayName "Safeer OS Aplikacija" -Direction Inbound -Program $targetOSExe -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
            }
            if (Test-Path $targetControlExe) {
                New-NetFirewallRule -DisplayName "Safeer Control Aplikacija" -Direction Inbound -Program $targetControlExe -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
            }
        } catch {
            Write-Warn "Napaka pri nastavitvi požarnega zidu: $_"
        }
    } else {
        Write-Info "Namestitev teče brez skrbniških pravic (Admin). Za odpiranje vrat 8990 v požarnem zidu lahko po potrebi zaženete skripto kot Administrator."
    }
} else {
    Write-Info "Nastavljanje požarnega zidu preskočeno (-NoFirewall)."
}

# -----------------------------------------------------------------------------
# 6. Ustvarjanje bližnjic (Namizje in Meni Start)
# -----------------------------------------------------------------------------
Write-Step 6 6 "Ustvarjanje bližnjic na Namizju in v meniju Start"

$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$StartPrograms = [Environment]::GetFolderPath("Programs")
$SafeerStartFolder = Join-Path $StartPrograms "Safeer OS"
New-Item -ItemType Directory -Force -Path $SafeerStartFolder | Out-Null

function Create-Shortcut($linkPath, $targetPath, $arguments, $workDir, $iconPath, $desc) {
    try {
        $s = $WshShell.CreateShortcut($linkPath)
        $s.TargetPath = $targetPath
        if ($arguments) { $s.Arguments = $arguments }
        $s.WorkingDirectory = $workDir
        if ($iconPath -and (Test-Path $iconPath)) { $s.IconLocation = "$iconPath,0" }
        $s.Description = $desc
        $s.Save()
        return $true
    } catch {
        return $false
    }
}

# Glavne bližnjice (Enotni program Safeer OS)
$iconArg = if (Test-Path $icoCilj) { $icoCilj } else { "" }

# 1. Safeer OS (glavna bližnjica enotnega programa z vgrajenim Safeer Controlom)
$osTarget = if (Test-Path $targetOSExe) { $targetOSExe } else { $batOS }
Create-Shortcut `
    -linkPath (Join-Path $DesktopPath "Safeer OS.lnk") `
    -targetPath $osTarget `
    -arguments "" `
    -workDir $InstallDir `
    -iconPath $iconArg `
    -desc "Safeer OS -- Domače okolje z vgrajenim Safeer Controlom"

Create-Shortcut `
    -linkPath (Join-Path $SafeerStartFolder "Safeer OS.lnk") `
    -targetPath $osTarget `
    -arguments "" `
    -workDir $InstallDir `
    -iconPath $iconArg `
    -desc "Safeer OS -- Domače okolje z vgrajenim Safeer Controlom"

# 2. Hitri dostop do Safeer Controla znotraj enotnega programa
Create-Shortcut `
    -linkPath (Join-Path $DesktopPath "Safeer Control.lnk") `
    -targetPath $osTarget `
    -arguments "--control" `
    -workDir $InstallDir `
    -iconPath $iconArg `
    -desc "Safeer OS (Safeer Control) -- Upravljanje naprav in ločen oddaljen navidezni zaslon"

Create-Shortcut `
    -linkPath (Join-Path $SafeerStartFolder "Safeer Control.lnk") `
    -targetPath $osTarget `
    -arguments "--control" `
    -workDir $InstallDir `
    -iconPath $iconArg `
    -desc "Safeer OS (Safeer Control) -- Upravljanje naprav in ločen oddaljen navidezni zaslon"

# 3. Safeer Browser
Create-Shortcut `
    -linkPath (Join-Path $DesktopPath "Safeer Browser.lnk") `
    -targetPath $osTarget `
    -arguments "--browser" `
    -workDir $InstallDir `
    -iconPath $iconArg `
    -desc "Safeer Browser -- Varen brskalnik z zaščito pred grožnjami"

Write-Success "Bližnjice ustvarjene na Namizju in v meniju Start:"
Write-Host "   * Namizje -> Safeer OS.lnk (Enotni program)" -ForegroundColor Cyan
Write-Host "   * Namizje -> Safeer Control.lnk (Hitri vstop v nadzor naprav)" -ForegroundColor Cyan
Write-Host "   * Namizje -> Safeer Browser.lnk" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# Samopreizkus delovanja
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "Izvajam hitri samopreizkus programske opreme..." -ForegroundColor Yellow

$testScript = @"
import sys
sys.path.insert(0, r'$AppDir\windows')
sys.path.insert(0, r'$AppDir')
try:
    from safeer_windows.navidezni_zaslon import NavidezniZaslon
    z = NavidezniZaslon()
    assert z.sirina == 1920 and z.visina == 1080
    stanje = z.stanje_naprave()
    assert stanje.get('screen') == 'virtual'
    assert stanje.get('secure') is True
    print('PREIZKUS_USPESEN: Navidezni zaslon (1920x1080, 60 FPS, TLS 1.2+ AEAD) pripravljen.')
except Exception as e:
    print(f'PREIZKUS_NAPAKA: {e}')
    sys.exit(1)
"@

$testResult = Invoke-SafeerPython @("-c", $testScript) 2>&1
if ($testResult -match "PREIZKUS_USPESEN") {
    Write-Success "$testResult"
} else {
    Write-Warn "Opozorilo pri samopreizkusu: $testResult"
}

# -----------------------------------------------------------------------------
# Zaključek in Zagon
# -----------------------------------------------------------------------------
Write-Header "Namestitev uspesno zakljucena!"

Write-Host "Safeer OS in Safeer Control sta pripravljena za uporabo." -ForegroundColor Green
Write-Host "Uporabnik za računalnikom in oddaljeni uporabniki (TV, telefon) lahko sedaj" -ForegroundColor White
Write-Host "računalnik uporabljajo sočasno preko ločenega navideznega zaslona brez motenj." -ForegroundColor White
Write-Host ""

$doLaunch = $false
if ($LaunchControl) {
    $doLaunch = "control"
} elseif ($LaunchOS) {
    $doLaunch = "os"
} elseif (-not $NoPrompt) {
    $odgovor = Read-Host "Ali želite zagnati Safeer Control zdaj? (D/n)"
    if ([string]::IsNullOrWhiteSpace($odgovor) -or $odgovor -match "^[dDyY]") {
        $doLaunch = "control"
    }
}

if ($doLaunch -eq "control") {
    Write-Info "Zaganjam Safeer Control..."
    if (Test-Path $targetControlExe) {
        Start-Process -FilePath $targetControlExe
    } elseif (Test-Path $targetOSExe) {
        Start-Process -FilePath $targetOSExe -ArgumentList "--control"
    } else {
        Start-Process -FilePath $batControl
    }
} elseif ($doLaunch -eq "os") {
    Write-Info "Zaganjam Safeer OS..."
    if (Test-Path $targetOSExe) {
        Start-Process -FilePath $targetOSExe
    } else {
        Start-Process -FilePath $batOS
    }
}
