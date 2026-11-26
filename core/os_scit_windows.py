"""Scit za Safeer OS na Windows: platformni sloj (isti razresevalnik, seznami in blokada po IP kot na Linuxu).

Jedro Scita (core/os_scit.py: razresevalnik, seznami, blokada po IP odgovora) je skupno; tu je samo to, kar je
na Windows drugace od Linuxa (systemd-resolved, NetworkManager, polkit):

- Sistemski DNS na Windows ne pozna vrat, zato razresevalnik poslusa na 127.0.0.1:53 (os_scit.VRATA), nastavitev pa
  je navaden DNS vmesnika »127.0.0.1« (Set-DnsClientServerAddress).
- Nastavitev DNS zahteva skrbnika. Kot polkit na Linuxu: ob prvem vklopu enkrat (UAC) namestimo naloga Task Scheduler
  »SafeerScitDns« (tece kot trenutni uporabnik z najvisjimi pravicami, zato brez UAC ob vsaki spremembi) in skripto
  v C:\\ProgramData\\Safeer\\ScitDns, ki jo lahko pise samo skrbnik. Skripta sprejme SAMO ukaza `SET <indeks>` ali
  `RESET <indeks>` za fizicni vmesnik in nastavi samo naslov 127.0.0.1 oziroma vrne DHCP - kot Linux pomocnik
  (fiksna dejanja, noben poljuben naslov).
- Strezniki usmerjevalnika (kam posredujemo) so prvotni DNS vmesnika; pred prvo nastavitvijo jih shranimo.

Vse funkcije so cisti klici z lazljivim `_ps` (preizkusi brez Windows); ukazi so fiksni seznami argumentov.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

NASLOV = "127.0.0.1"
VRATA = 53
IME_NALOGE = "SafeerScitDns"
REZERVNI_STREZNIKI = ("1.1.1.1", "9.9.9.9", "8.8.8.8")
#: Brez okna konzole (CREATE_NO_WINDOW); na drugih sistemih 0.
_BREZ_OKNA = 0x08000000 if sys.platform == "win32" else 0

#: Skripta, ki jo naloga zazene z najvisjimi pravicami. Bere samo prvo vrstico zahteve in jo preveri z regularnim izrazom.
SKRIPTA = r"""$ErrorActionPreference = 'Stop'
$mapa = Join-Path $env:ProgramData 'Safeer\ScitDns'
$zahteva = Join-Path $mapa 'zahteva.txt'
$vrstica = Get-Content -LiteralPath $zahteva -TotalCount 1
if ($vrstica -match '^(SET|RESET) ([0-9]{1,6})$') {
    $ukaz = $Matches[1]
    $indeks = [int]$Matches[2]
    $vmesnik = Get-NetAdapter -Physical | Where-Object { $_.ifIndex -eq $indeks }
    if ($vmesnik) {
        if ($ukaz -eq 'SET') {
            Set-DnsClientServerAddress -InterfaceIndex $indeks -ServerAddresses '127.0.0.1'
        } else {
            Set-DnsClientServerAddress -InterfaceIndex $indeks -ResetServerAddresses
        }
        Clear-DnsClientCache
    }
}
"""


def _ps(ukaz: str, cas: float = 15.0) -> Tuple[int, str]:
    """PowerShell z enim ukazom; (koda, izpis). Napaka ali pretek casa = (1, "")."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return 1, ""
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ukaz],
                           capture_output=True, text=True, timeout=cas, creationflags=_BREZ_OKNA)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, (r.stdout or "").strip()


def mapa_podatkov() -> str:
    return os.path.join(os.environ.get("ProgramData") or r"C:\ProgramData", "Safeer", "ScitDns")


def _stanje_pot() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Safeer", "scit-windows-prvotni-dns.json")


def veljaven_indeks(v: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{1,6}", v or ""))


def razlog_nemoznosti() -> str:
    """'' = Scit lahko dela; 'ni_resolved' = ni PowerShella (Windows brez Get-NetAdapter)."""
    if not (shutil.which("powershell") or shutil.which("pwsh")):
        return "ni_resolved"
    return ""


def vmesniki_povezani() -> List[str]:
    """Indeksi fizicnih vmesnikov (Ethernet, Wi-Fi), ki so povezani; virtualni (Hyper-V, VPN, Docker) ne."""
    koda, izpis = _ps("Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { $_.ifIndex }")
    if koda != 0:
        return []
    return [v.strip() for v in izpis.splitlines() if veljaven_indeks(v.strip())]


def _streznik_vmesnika(vmesnik: str) -> List[str]:
    if not veljaven_indeks(vmesnik):
        return []
    koda, izpis = _ps("(Get-DnsClientServerAddress -InterfaceIndex %s -AddressFamily IPv4).ServerAddresses" % vmesnik)
    if koda != 0:
        return []
    return [s.strip() for s in izpis.splitlines() if re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){3}", s.strip())]


def _preberi_stanje() -> dict:
    try:
        with open(_stanje_pot(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _zapisi_stanje(d: dict) -> None:
    pot = _stanje_pot()
    try:
        os.makedirs(os.path.dirname(pot), exist_ok=True)
        tmp = pot + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, pot)
    except OSError:
        pass


def dns_vmesnika(vmesnik: str) -> str:
    """DNS vmesnika v obliki kot na Linuxu (»127.0.0.1:53 ...«): nas naslov dobi vrata."""
    deli = []
    for s in _streznik_vmesnika(vmesnik):
        deli.append("%s:%d" % (s, VRATA) if s == NASLOV else s)
    return " ".join(deli)


def upstream_strezniki(vmesnik: str) -> List[str]:
    """Kam posredujemo: prvotni DNS vmesnika (DHCP ali ročno), brez nas. Ko smo ga ze nastavili, ga beremo iz shrambe."""
    trenutni = [s for s in _streznik_vmesnika(vmesnik) if s != NASLOV]
    if trenutni:
        return trenutni
    shranjeni = [s for s in _preberi_stanje().get(vmesnik, []) if s != NASLOV]
    return shranjeni or list(REZERVNI_STREZNIKI)   # kot dosedanji Scit na Windows: brez znanega DNS posredujemo javnim


def trenutni_streznik(vmesnik: str) -> str:
    """Prvi DNS vmesnika; Windows ne pozna »Current DNS Server« kot systemd-resolved."""
    deli = _streznik_vmesnika(vmesnik)
    if not deli:
        return ""
    return "%s:%d" % (deli[0], VRATA) if deli[0] == NASLOV else deli[0]


def znak_dns() -> Tuple[int, int]:
    """Windows nima datoteke, ki bi se ob spremembi omrezja spremenila; straza pregleduje redno (PREGLED_S)."""
    return 0, 0


def tuj_scit(dns: str, nasa_vrata: int) -> bool:
    """Na Windows poslusa na vratih 53 en razresevalnik na racunalnik; Scita drugega uporabnika ne iscemo."""
    return False


def je_ostanek(vmesnik: str) -> bool:
    """Vmesnik kaze na nas (127.0.0.1), a nihce ne poslusa: ostanek po sesutju. Prazno ni ostanek (DHCP je prazen DNS)."""
    deli = _streznik_vmesnika(vmesnik)
    return bool(deli) and deli[0] == NASLOV and not nekdo_poslusa()


def nekdo_poslusa(vrata: int = VRATA) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.3)
        s.bind((NASLOV, vrata))
        return False            # lahko zasedemo: nihce ne poslusa
    except OSError:
        return True
    finally:
        s.close()


def vrata_nasa(vrata: int) -> bool:
    """Vrata (UDP, 127.0.0.1) drzi proces trenutnega uporabnika (Linux: lastniki_vrat == nas uid)."""
    if not isinstance(vrata, int) or not 0 < vrata < 65536:
        return False
    koda, izpis = _ps(
        "$e = Get-NetUDPEndpoint -LocalAddress 127.0.0.1 -LocalPort %d -ErrorAction SilentlyContinue; "
        "if (-not $e) { exit 3 }; "
        "foreach ($x in $e) { $o = Invoke-CimMethod -InputObject (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $x.OwningProcess)) "
        "-MethodName GetOwner; if ($o.User -ne $env:USERNAME) { exit 4 } }; exit 0" % vrata)
    return koda == 0


def izprazni_predpomnilnik() -> None:
    _ps("Clear-DnsClientCache", cas=10.0)


def uredi_domene(vmesnik: str) -> None:
    """Windows iskalnih domen vmesnika pri nastavitvi DNS ne spremeni: nic za popraviti."""
    return None


def dovoljenje_za_posodobitev() -> str:
    """Stanje dovoljenja za prikaz (Linux: posodobljeno pravilo). Windows: naloga je ali je ni."""
    return "" if pravilo_namesceno() else "pravilo"


def pravilo_namesceno() -> bool:
    koda, _ = _ps("Get-ScheduledTask -TaskName %s -ErrorAction Stop | Out-Null" % IME_NALOGE, cas=15.0)
    return koda == 0


def _kodiraj(ps: str) -> str:
    return base64.b64encode(ps.encode("utf-16-le")).decode("ascii")


def _dvigni(ps: str, cas: float = 120.0) -> bool:
    """Isti PowerShell ukaz z UAC (enkrat). Vrne True, ce se je ukaz izvedel brez napake."""
    ukaz = ("$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
            "'-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','%s'; exit $p.ExitCode" % _kodiraj(ps))
    koda, _ = _ps(ukaz, cas=cas)
    return koda == 0


def namesti_pravilo() -> bool:
    """Enkrat (UAC): skripta v ProgramData in naloga Task Scheduler. Po tem sprememba DNS brez gesla."""
    return _dvigni(_namesti_ps())


def _namesti_ps() -> str:
    skripta_b64 = base64.b64encode(SKRIPTA.encode("utf-8")).decode("ascii")
    return "\n".join([
        "$ErrorActionPreference='Stop'",
        "$mapa = Join-Path $env:ProgramData 'Safeer\\ScitDns'",
        "New-Item -ItemType Directory -Force -Path $mapa | Out-Null",
        "icacls $mapa /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' 'Users:(OI)(CI)RX' | Out-Null",
        "$skripta = Join-Path $mapa 'scit-dns.ps1'",
        "[IO.File]::WriteAllBytes($skripta, [Convert]::FromBase64String('%s'))" % skripta_b64,
        "$zahteva = Join-Path $mapa 'zahteva.txt'",
        "Set-Content -LiteralPath $zahteva -Value '' -Encoding ASCII",
        "icacls $zahteva /grant 'Users:M' | Out-Null",
        "$uporabnik = [Security.Principal.WindowsIdentity]::GetCurrent().Name",
        "$dejanje = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File \"' + $skripta + '\"')",
        "$nacelo = New-ScheduledTaskPrincipal -UserId $uporabnik -LogonType Interactive -RunLevel Highest",
        "Register-ScheduledTask -TaskName '%s' -Action $dejanje -Principal $nacelo -Force | Out-Null" % IME_NALOGE,
    ])


def _zahteva(ukaz: str, vmesnik: str) -> bool:
    """Zapise zahtevo v datoteko in zazene nalogo; True, ce je naloga stekla."""
    if ukaz not in ("SET", "RESET") or not veljaven_indeks(vmesnik):
        return False
    try:
        with open(os.path.join(mapa_podatkov(), "zahteva.txt"), "w", encoding="ascii") as f:
            f.write("%s %s\n" % (ukaz, vmesnik))
    except OSError:
        return False
    koda, _ = _ps("Start-ScheduledTask -TaskName %s -ErrorAction Stop" % IME_NALOGE, cas=20.0)
    return koda == 0


def usmeri(vmesnik: str, vrata: int, rezerva: Optional[List[str]] = None) -> str:
    """DNS vmesnika na nas. '' = uspelo; 'pravilo' = naloge ni ali ni stekla. Prvotni DNS shranimo, da vemo, kam posredujemo."""
    if not veljaven_indeks(vmesnik):
        return "pravilo"
    prvotni = [s for s in _streznik_vmesnika(vmesnik) if s != NASLOV]
    if prvotni:
        stanje = _preberi_stanje()
        stanje[vmesnik] = prvotni
        _zapisi_stanje(stanje)
    if not _zahteva("SET", vmesnik):
        return "pravilo"
    return ""


def povrni(vmesnik: str) -> bool:
    """DNS vmesnika nazaj na DHCP (ali prvotne stevilke, ce so bile rocne)."""
    return _zahteva("RESET", vmesnik)
