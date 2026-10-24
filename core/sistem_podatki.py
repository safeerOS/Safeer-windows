"""Diski s prostim prostorom in podatki o strojni in programski opremi (lastnik, 24.-25. 10. 2026: »uporabniku manjka
podatek, kje in na katerem disku ima koliko prostora«, »vse pomembne informacije o strojni in programski opremi«).

Isti modul na Linuxu in Windows (Safeer-linux je vir, Safeer-windows ima kopijo). Ciste funkcije za razclenjevanje so
preizkusene v tests/test_sistem_podatki.py; branje sistema je tanek ovoj okoli njih. Brez skrbniskih pravic: Linux bere
/proc, /sys in lsblk, priklop gre prek udisks (polkit vprasa, ce je treba); Windows bere prek Win32 API in registra.
Nic od tega ne zapusti racunalnika - prikaz je samo v Safeer OS.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from typing import Callable, Optional

#: Opozorilo o malo prostora: manj kot 5 GB, ali manj kot 10 % in hkrati manj kot 15 GB (na velikem disku 10 % ni malo -
#: izmerjeno: prenosnik s 500 GB in 39 GB prostega bi sicer opozarjal brez potrebe).
OPOZORILO_DELEZ = 0.10
OPOZORILO_BAJTOV = 5 * 1024 ** 3
OPOZORILO_DELEZ_MEJA = 15 * 1024 ** 3

_PRESKOCI_TOCKE = ("/boot", "/boot/efi", "/efi", "[SWAP]")
_PRESKOCI_FS = {"swap", "squashfs", "iso9660", "udf", "crypto_LUKS", "LVM2_member", "linux_raid_member", ""}
_NAJMANJSI_RAZDELEK = 2 * 1024 ** 3    # razdelki pod 2 GB (EFI, obnovitveni, rezervirani) niso zanimivi


def malo_prostora(prosto: int, velikost: int) -> bool:
    if velikost <= 0:
        return False
    return prosto < OPOZORILO_BAJTOV or (prosto < velikost * OPOZORILO_DELEZ and prosto < OPOZORILO_DELEZ_MEJA)


# ---------------------------------------------------------------------- Linux: diski

def diski_iz_lsblk(izpis: str, statvfs: Callable[[str], Optional[tuple]], dom: str = "") -> list:
    """Razdelki iz `lsblk -J -b -o NAME,PATH,LABEL,SIZE,TYPE,RM,HOTPLUG,MOUNTPOINT,FSTYPE,MODEL` (cista funkcija).
    [statvfs](pot) -> (velikost, prosto) ali None. Vrne priklopljene (z zasedenostjo) in nepriklopljene razdelke z
    datotecnim sistemom; sistemski disk je »sistem«, razdelek z domaco mapo »dom«."""
    try:
        drevo = json.loads(izpis).get("blockdevices") or []
    except (ValueError, AttributeError):
        return []
    izid, videne = [], set()

    def obisci(n: dict, model: str, odstranljiv: bool) -> None:
        model = str(n.get("model") or model or "").strip()
        odstranljiv = odstranljiv or bool(n.get("rm")) or bool(n.get("hotplug"))
        tip, fs = str(n.get("type") or ""), str(n.get("fstype") or "")
        tocka = str(n.get("mountpoint") or "")
        velikost = int(n.get("size") or 0)
        if tip in ("part", "disk", "lvm", "crypt") and fs not in _PRESKOCI_FS and tocka not in _PRESKOCI_TOCKE \
                and not tocka.startswith(("/snap/", "/boot/", "/var/snap/")) and velikost >= _NAJMANJSI_RAZDELEK \
                and str(n.get("path") or "") not in videne:
            videne.add(str(n.get("path") or ""))
            d = {"naprava": str(n.get("path") or ""), "oznaka": str(n.get("label") or ""), "model": model,
                 "datotecni_sistem": fs, "velikost": velikost, "pot": tocka, "priklopljen": bool(tocka),
                 "odstranljiv": odstranljiv, "sistem": tocka == "/",
                 "dom": bool(tocka) and tocka != "/" and bool(dom) and (dom == tocka or dom.startswith(tocka.rstrip("/") + "/"))}
            if tocka:
                m = statvfs(tocka)
                if m:
                    d["velikost"], d["prosto"] = int(m[0]), int(m[1])
                else:
                    d["prosto"] = 0
                d["malo_prostora"] = malo_prostora(d["prosto"], d["velikost"])
            izid.append(d)
        for o in n.get("children") or []:
            obisci(o, model, odstranljiv)

    for n in drevo:
        obisci(n, "", False)
    # Najprej sistemski, nato priklopljeni, nato nepriklopljeni; znotraj po velikosti.
    izid.sort(key=lambda d: (not d["sistem"], not d["priklopljen"], -d["velikost"]))
    return izid


def _statvfs(pot: str) -> Optional[tuple]:
    try:
        st = os.statvfs(pot)
        return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    except OSError:
        return None


def _diski_linux() -> list:
    if not shutil.which("lsblk"):
        return []
    try:
        r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,LABEL,SIZE,TYPE,RM,HOTPLUG,MOUNTPOINT,FSTYPE,MODEL"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return diski_iz_lsblk(r.stdout, _statvfs, os.path.expanduser("~")) if r.returncode == 0 else []


def priklopi(naprava: str) -> dict:
    """Priklopi nepriklopljen razdelek s seznama diski() prek udisks (brez sudo; polkit vprasa, ce sistem to zahteva).
    Vrne {"ok": True, "pot": tocka} ali {"ok": False, "napaka": ...}."""
    if not sys.platform.startswith("linux"):
        return {"ok": False, "napaka": "ni_podprto"}
    cilj = next((d for d in _diski_linux() if d["naprava"] == str(naprava or "") and not d["priklopljen"]), None)
    try:
        from core import root_ukaz
        udisksctl = root_ukaz.sistemski_program("udisksctl")
    except Exception:  # noqa: BLE001
        udisksctl = None
    if cilj is None or not udisksctl:
        return {"ok": False, "napaka": "ni_diska"}
    try:
        r = subprocess.run([udisksctl, "mount", "-b", cilj["naprava"]], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "napaka": "napaka"}
    if r.returncode != 0:
        besedilo = (r.stderr + r.stdout).lower()
        return {"ok": False, "napaka": "zavrnjeno" if "not authorized" in besedilo or "dismissed" in besedilo else "napaka"}
    pot = next((d["pot"] for d in _diski_linux() if d["naprava"] == cilj["naprava"] and d["priklopljen"]), "")
    return {"ok": True, "pot": pot}


# ---------------------------------------------------------------------- Windows: diski

def _diski_windows() -> list:
    import ctypes
    k32 = ctypes.windll.kernel32
    izid = []
    maska = k32.GetLogicalDrives()
    sistemski = (os.environ.get("SystemDrive") or "C:").upper().rstrip("\\") + "\\"
    for i in range(26):
        if not maska & (1 << i):
            continue
        koren = "%s:\\" % chr(65 + i)
        vrsta = k32.GetDriveTypeW(koren)            # 2 odstranljiv, 3 fiksen, 4 omrezni, 5 CD
        if vrsta not in (2, 3, 4):
            continue
        ime = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        if not k32.GetVolumeInformationW(ctypes.c_wchar_p(koren), ime, 261, None, None, None, fs, 261):
            continue                                 # prazen bralnik kartic ipd.
        prosto, skupaj = ctypes.c_ulonglong(0), ctypes.c_ulonglong(0)
        if not k32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(koren), ctypes.byref(prosto), ctypes.byref(skupaj), None):
            continue
        d = {"naprava": koren[:2], "oznaka": ime.value, "model": "", "datotecni_sistem": fs.value,
             "velikost": int(skupaj.value), "prosto": int(prosto.value), "pot": koren, "priklopljen": True,
             "odstranljiv": vrsta == 2, "omrezje": vrsta == 4, "sistem": koren.upper() == sistemski, "dom": False}
        d["malo_prostora"] = malo_prostora(d["prosto"], d["velikost"])
        izid.append(d)
    izid.sort(key=lambda d: (not d["sistem"], -d["velikost"]))
    return izid


def diski() -> list:
    """Vsi diski in razdelki z velikostjo in prostim prostorom (Linux tudi nepriklopljeni)."""
    try:
        return _diski_windows() if sys.platform == "win32" else _diski_linux()
    except Exception:  # noqa: BLE001 - brez seznama, ostalo dela naprej
        return []


# ---------------------------------------------------------------------- podatki o sistemu

def os_iz_release(besedilo: str) -> str:
    vrednosti = {}
    for v in (besedilo or "").splitlines():
        if "=" in v:
            k, _, x = v.partition("=")
            vrednosti[k.strip()] = x.strip().strip('"')
    return vrednosti.get("PRETTY_NAME") or " ".join(x for x in (vrednosti.get("NAME"), vrednosti.get("VERSION")) if x)


def procesor_iz_cpuinfo(besedilo: str) -> str:
    for v in (besedilo or "").splitlines():
        k, _, x = v.partition(":")
        if k.strip() in ("model name", "Hardware", "Model") and x.strip():
            return re.sub(r"\s+", " ", x.strip())
    return ""


def pomnilnik_iz_meminfo(besedilo: str) -> dict:
    v = {}
    for vrstica in (besedilo or "").splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", vrstica)
        if m:
            v[m.group(1)] = int(m.group(2)) * 1024
    return {"skupaj": v.get("MemTotal", 0), "na_voljo": v.get("MemAvailable", v.get("MemFree", 0)),
            "izmenjalni": v.get("SwapTotal", 0)}


def graficne_iz_lspci(besedilo: str) -> list:
    izid = []
    for v in (besedilo or "").splitlines():
        m = re.match(r"^\S+\s+(VGA compatible controller|3D controller|Display controller):\s*(.+)$", v.strip())
        if m:
            izid.append(re.sub(r"\s*\(rev [0-9a-f]+\)$", "", m.group(2)).strip())
    return izid


def _beri(pot: str) -> str:
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _podatki_linux() -> dict:
    p = {"sistem": os_iz_release(_beri("/etc/os-release")) or "Linux", "jedro": platform.release(),
         "namizje": os.environ.get("XDG_CURRENT_DESKTOP", ""), "procesor": procesor_iz_cpuinfo(_beri("/proc/cpuinfo")),
         "jeder": os.cpu_count() or 0, "pomnilnik": pomnilnik_iz_meminfo(_beri("/proc/meminfo")), "graficne": [],
         "racunalnik": " ".join(x for x in (_beri("/sys/class/dmi/id/sys_vendor").strip(),
                                           _beri("/sys/class/dmi/id/product_name").strip()) if x and "O.E.M" not in x)}
    try:
        p["cas_delovanja_s"] = int(float(_beri("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        p["cas_delovanja_s"] = 0
    if shutil.which("lspci"):
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=3)
            p["graficne"] = graficne_iz_lspci(r.stdout) if r.returncode == 0 else []
        except (OSError, subprocess.SubprocessError):
            pass
    return p


def _tick64() -> int:
    import ctypes
    f = ctypes.windll.kernel32.GetTickCount64
    f.restype = ctypes.c_ulonglong              # privzeti int bi pri dolgem delovanju odrezal vrednost
    return int(f())


def _podatki_windows() -> dict:
    import ctypes
    import winreg

    class _Stanje(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    def reg(pot: str, ime: str) -> str:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, pot) as k:
                return str(winreg.QueryValueEx(k, ime)[0]).strip()
        except OSError:
            return ""

    st = _Stanje()
    st.dwLength = ctypes.sizeof(_Stanje)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    razlicica = reg(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion")
    ime = reg(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName") or "Windows"
    gradnja = reg(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuild")
    if gradnja.isdigit() and int(gradnja) >= 22000:
        ime = ime.replace("Windows 10", "Windows 11")   # register ima pri Windows 11 se vedno »Windows 10«
    graficne = []
    razred = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    for i in range(8):
        opis = reg(razred + "\\%04d" % i, "DriverDesc")
        if opis and opis not in graficne and "Basic Display" not in opis:
            graficne.append(opis)
    return {"sistem": " ".join(x for x in (ime, razlicica) if x), "jedro": "build " + gradnja if gradnja else platform.version(),
            "namizje": "Windows", "procesor": reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString"),
            "jeder": os.cpu_count() or 0,
            "pomnilnik": {"skupaj": int(st.ullTotalPhys), "na_voljo": int(st.ullAvailPhys), "izmenjalni": 0},
            "graficne": graficne,
            "racunalnik": " ".join(x for x in (reg(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer"),
                                               reg(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName")) if x),
            "cas_delovanja_s": int(_tick64() // 1000)}


def podatki() -> dict:
    """Strojna in programska oprema tega racunalnika za stran »O tem racunalniku«, skupaj z diski."""
    zacetek = time.monotonic()
    try:
        p = _podatki_windows() if sys.platform == "win32" else _podatki_linux()
    except Exception:  # noqa: BLE001
        p = {"sistem": platform.platform(), "jedro": platform.release(), "procesor": "", "jeder": os.cpu_count() or 0,
             "pomnilnik": {"skupaj": 0, "na_voljo": 0, "izmenjalni": 0}, "graficne": [], "racunalnik": "", "cas_delovanja_s": 0}
    p["arhitektura"] = platform.machine()
    p["python"] = platform.python_version()
    p["diski"] = diski()
    p["cas_ms"] = int((time.monotonic() - zacetek) * 1000)
    return p
