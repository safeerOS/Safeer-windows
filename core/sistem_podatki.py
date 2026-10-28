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


def _lsblk() -> str:
    """Izpis lsblk (JSON) ali "" - brez lsblk (Flatpak, vsebnik) ostanejo priklopi iz /proc/self/mounts."""
    if not shutil.which("lsblk"):
        return ""
    try:
        r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,LABEL,SIZE,TYPE,RM,HOTPLUG,MOUNTPOINT,FSTYPE,MODEL,ROTA,TRAN"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _diski_linux(izpis: Optional[str] = None) -> list:
    izpis = _lsblk() if izpis is None else izpis
    dom = os.path.expanduser("~")
    return dopolni_iz_priklopov(diski_iz_lsblk(izpis, _statvfs, dom) if izpis else [],
                                _beri("/proc/self/mounts"), _statvfs, dom)


#: Navidezni datotecni sistemi (jedro, pomnilnik, vsebniki, slike programov): niso prostor za uporabnikove datoteke.
PSEVDO_FS = frozenset({
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "ramfs", "rootfs", "overlay", "squashfs", "iso9660", "udf",
    "cgroup", "cgroup2", "securityfs", "selinuxfs", "pstore", "bpf", "debugfs", "tracefs", "configfs", "fusectl",
    "mqueue", "hugetlbfs", "autofs", "binfmt_misc", "efivarfs", "nsfs", "rpc_pipefs", "nfsd", "devfs", "zram",
    "fuse.gvfsd-fuse", "fuse.portal", "fuse.snapfuse", "fuse.lxcfs", "fuse.agent-store", "fuse.appimagefuse",
})
#: Omrezni datotecni sistemi: statvfs na odklopljenem strezniku lahko visi minute - jih ne merimo.
OMREZNI_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "ceph", "glusterfs", "9p", "afs"})
_PRESKOCI_POD = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/snap", "/boot", "/var/lib/docker",
                 "/var/lib/containers", "/var/lib/flatpak", "/tmp")


def _odkodiraj_priklop(pot: str) -> str:
    """/proc/self/mounts zapise presledek, tab, nova vrstica in \\ kot osmisko kodo (\\040)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), pot)


def priklopi_iz_mounts(besedilo: str) -> list:
    """Pravi priklopljeni datotecni sistemi iz /proc/self/mounts (cista funkcija): [(naprava, tocka, fs)].
    Brez navideznih in omreznih, brez /proc, /sys, /run, /snap, /boot …; ista naprava na vec mestih (bind) samo enkrat,
    z najkrajso potjo."""
    izid: dict = {}
    for vrstica in (besedilo or "").splitlines():
        deli = vrstica.split()
        if len(deli) < 3:
            continue
        naprava, tocka, fs = _odkodiraj_priklop(deli[0]), _odkodiraj_priklop(deli[1]), deli[2]
        if fs in PSEVDO_FS or fs in OMREZNI_FS or fs.startswith("fuse.") and fs != "fuseblk":
            continue
        if not naprava.startswith("/dev/") or naprava.startswith(("/dev/loop", "/dev/zram", "/dev/ram")):
            continue
        if tocka != "/" and any(tocka == p or tocka.startswith(p + "/") for p in _PRESKOCI_POD) \
                and not tocka.startswith("/run/media/"):
            continue
        prej = izid.get(naprava)
        if prej is None or len(tocka) < len(prej[1]):
            izid[naprava] = (naprava, tocka, fs)
    return list(izid.values())


def dopolni_iz_priklopov(diski: list, mounts: str, statvfs: Callable[[str], Optional[tuple]], dom: str = "") -> list:
    """Diskom iz lsblk doda priklope iz /proc/self/mounts, ki jih lsblk ne pozna (cista funkcija). lsblk brez podatkov
    udev (vsebnik, Flatpak) ne pove datotecnega sistema in sistemski disk izpade - izmerjeno 27. 10. 2026 na virtualnem
    racunalniku: lsblk »/dev/vdb /« brez FSTYPE, seznam diskov je bil prazen."""
    znane = {d.get("naprava") for d in diski} | {d.get("pot") for d in diski if d.get("pot")}
    izid = list(diski)
    for naprava, tocka, fs in priklopi_iz_mounts(mounts):
        if naprava in znane or tocka in znane:
            continue
        m = statvfs(tocka)
        if not m or int(m[0]) <= 0:
            continue
        velikost, prosto = int(m[0]), int(m[1])
        izid.append({"naprava": naprava, "oznaka": "", "model": "", "datotecni_sistem": fs, "velikost": velikost,
                     "prosto": prosto, "pot": tocka, "priklopljen": True, "odstranljiv": tocka.startswith(("/media/", "/run/media/")),
                     "sistem": tocka == "/",
                     "dom": tocka != "/" and bool(dom) and (dom == tocka or dom.startswith(tocka.rstrip("/") + "/")),
                     "malo_prostora": malo_prostora(prosto, velikost)})
        znane.update((naprava, tocka))
    izid.sort(key=lambda d: (not d["sistem"], not d["priklopljen"], -d["velikost"]))
    return izid


def naprave_iz_lsblk(izpis: str) -> list:
    """Fizicne naprave za shranjevanje (cista funkcija): model, velikost, vrsta (SSD/HDD/NVMe/USB …), odstranljiva.
    Brez loop, zram, ram in praznih bralnikov kartic (velikost 0)."""
    try:
        drevo = json.loads(izpis).get("blockdevices") or []
    except (ValueError, AttributeError):
        return []
    izid = []
    for n in drevo:
        ime = str(n.get("name") or "")
        if str(n.get("type") or "") != "disk" or ime.startswith(("loop", "zram", "ram")) or not int(n.get("size") or 0):
            continue
        prenos = str(n.get("tran") or "").lower()
        rota = n.get("rota")
        vrsta = "nvme" if prenos == "nvme" or ime.startswith("nvme") else "usb" if prenos == "usb" \
            else "mmc" if ime.startswith("mmcblk") else "hdd" if rota in (True, 1, "1") else "ssd" if rota in (False, 0, "0") else ""
        izid.append({"naprava": str(n.get("path") or "/dev/" + ime), "model": str(n.get("model") or "").strip(),
                     "velikost": int(n.get("size") or 0), "vrsta": vrsta,
                     "odstranljiv": bool(n.get("rm")) or bool(n.get("hotplug"))})
    izid.sort(key=lambda d: (d["odstranljiv"], -d["velikost"]))
    return izid


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


def jedra_iz_cpuinfo(besedilo: str) -> int:
    """Fizicna jedra (razlicni pari physical id + core id); 0, ce /proc/cpuinfo tega ne pove (ARM, virtualni stroj)."""
    pari, fizicni = set(), "0"
    for v in (besedilo or "").splitlines():
        k, _, x = v.partition(":")
        k, x = k.strip(), x.strip()
        if k == "physical id":
            fizicni = x
        elif k == "core id":
            pari.add((fizicni, x))
        elif not k:
            fizicni = "0"
    return len(pari)


def uevent(besedilo: str) -> dict:
    """KLJUC=vrednost iz datoteke uevent v /sys (cista funkcija)."""
    izid = {}
    for v in (besedilo or "").splitlines():
        k, je, x = v.partition("=")
        if je:
            izid[k.strip()] = x.strip()
    return izid


def baterija_iz_uevent(besedilo: str) -> Optional[dict]:
    """Baterija racunalnika iz /sys/class/power_supply/*/uevent (cista funkcija) ali None (napajalnik, baterija miske:
    SCOPE=Device). Zdravje = trenutna polna / nazivna zmogljivost, ce jedro pove obe."""
    u = uevent(besedilo)
    if u.get("POWER_SUPPLY_TYPE") != "Battery" or u.get("POWER_SUPPLY_SCOPE") == "Device" \
            or u.get("POWER_SUPPLY_PRESENT", "1") == "0":
        return None
    try:
        napolnjenost = max(0, min(100, int(u.get("POWER_SUPPLY_CAPACITY", ""))))
    except ValueError:
        napolnjenost = -1
    zdravje = -1
    for polna, nazivna in (("POWER_SUPPLY_ENERGY_FULL", "POWER_SUPPLY_ENERGY_FULL_DESIGN"),
                           ("POWER_SUPPLY_CHARGE_FULL", "POWER_SUPPLY_CHARGE_FULL_DESIGN")):
        try:
            a, b = int(u[polna]), int(u[nazivna])
        except (KeyError, ValueError):
            continue
        if b > 0:
            zdravje = max(0, min(100, round(100 * a / b)))
            break
    stanje = {"Charging": "polni", "Discharging": "prazni", "Full": "polna", "Not charging": "ne_polni"}
    return {"ime": u.get("POWER_SUPPLY_NAME", ""), "model": " ".join(x for x in (u.get("POWER_SUPPLY_MANUFACTURER", ""),
                                                                             u.get("POWER_SUPPLY_MODEL_NAME", "")) if x),
            "napolnjenost": napolnjenost, "stanje": stanje.get(u.get("POWER_SUPPLY_STATUS", ""), ""), "zdravje": zdravje}


def graficna_iz_uevent(besedilo: str) -> str:
    """Graficna iz /sys/class/drm/cardN/device/uevent, kadar lspci ni (Flatpak): gonilnik in PCI ID."""
    u = uevent(besedilo)
    gonilnik, pci = u.get("DRIVER", ""), u.get("PCI_ID", "").lower()
    return "%s (%s)" % (gonilnik, pci) if gonilnik and pci else gonilnik


def zaslon_iz_drm(prikljucek: str, stanje: str, nacini: str) -> Optional[dict]:
    """Prikljucen zaslon iz /sys/class/drm/cardN-<prikljucek>/{status,modes} (cista funkcija): prvi nacin je zaslonu
    najljubsi (»preferred«). Brez locljivosti ga se vedno pokazemo (npr. zaslon v varcevanju)."""
    if (stanje or "").strip() != "connected":
        return None
    ime = re.sub(r"^card\d+-", "", prikljucek or "")
    nacin = next((v.strip() for v in (nacini or "").splitlines() if v.strip()), "")
    return {"prikljucek": ime, "locljivost": nacin, "vgrajen": ime.startswith(("eDP", "LVDS", "DSI"))}


def osnova_iz_release(besedilo: str) -> str:
    """Distribucija, na kateri sistem temelji (ID_LIKE in ime izdaje), npr. »ubuntu debian (noble)«."""
    v = {}
    for vrstica in (besedilo or "").splitlines():
        if "=" in vrstica:
            k, _, x = vrstica.partition("=")
            v[k.strip()] = x.strip().strip('"')
    izdaja = v.get("UBUNTU_CODENAME") or v.get("DEBIAN_CODENAME") or ""
    osnova = v.get("ID_LIKE", "")
    return (osnova + (" (%s)" % izdaja if izdaja and osnova else "")).strip()


def komponente_iz_modulov(moduli: dict) -> list:
    """Razlicice knjiznic, ki jih Safeer OS ZE uporablja (cista funkcija nad sys.modules): nic novega ne uvozimo, zato
    prikaz ne nalozi Qt ali WebKita, ce ju proces nima. [(ime, razlicica)]."""
    izid = [("Python", platform.python_version())]
    for ime, modul in (("Qt", "PySide6.QtCore"), ("GTK", "gi.repository.Gtk"), ("WebKitGTK", "gi.repository.WebKit"),
                       ("libsoup", "gi.repository.Soup"), ("GStreamer", "gi.repository.Gst")):
        m = moduli.get(modul)
        if m is None:
            continue
        try:
            if ime == "Qt":
                r = str(m.qVersion())
            elif ime == "GStreamer":
                r = ".".join(str(x) for x in m.version()[:3])
            else:
                r = "%d.%d.%d" % (m.get_major_version(), m.get_minor_version(), m.get_micro_version())
        except Exception:  # noqa: BLE001 - nepopoln modul ali knjiznica brez funkcij razlicice: vrstice ne pokazemo
            continue
        izid.append((ime, r))
    return izid


def _sys_imenik(koren: str) -> list:
    try:
        return sorted(os.listdir(koren))
    except OSError:
        return []


def baterije(koren: str = "/sys/class/power_supply") -> list:
    return [b for b in (baterija_iz_uevent(_beri(os.path.join(koren, i, "uevent"))) for i in _sys_imenik(koren)) if b]


def zasloni(koren: str = "/sys/class/drm") -> list:
    izid = []
    for i in _sys_imenik(koren):
        if re.match(r"^card\d+-", i):
            z = zaslon_iz_drm(i, _beri(os.path.join(koren, i, "status")), _beri(os.path.join(koren, i, "modes")))
            if z:
                izid.append(z)
    return izid


def graficne_iz_drm(koren: str = "/sys/class/drm") -> list:
    izid = []
    for i in _sys_imenik(koren):
        if re.match(r"^card\d+$", i):
            g = graficna_iz_uevent(_beri(os.path.join(koren, i, "device", "uevent")))
            if g and g not in izid:
                izid.append(g)
    return izid


def _beri(pot: str) -> str:
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _podatki_linux() -> dict:
    os_release = _beri("/etc/os-release") or _beri("/usr/lib/os-release")
    cpuinfo = _beri("/proc/cpuinfo")
    p = {"sistem": os_iz_release(os_release) or "Linux", "jedro": platform.release(),
         "namizje": os.environ.get("XDG_CURRENT_DESKTOP", ""), "procesor": procesor_iz_cpuinfo(cpuinfo),
         "jeder": os.cpu_count() or 0, "pomnilnik": pomnilnik_iz_meminfo(_beri("/proc/meminfo")), "graficne": [],
         "racunalnik": " ".join(x for x in (_beri("/sys/class/dmi/id/sys_vendor").strip(),
                                           _beri("/sys/class/dmi/id/product_name").strip()) if x and "O.E.M" not in x),
         # O tem racunalniku v Datotekah (lastnik, 27. 10. 2026): vse iz /proc, /sys in /etc, brez root in brez omrezja.
         "fizicnih_jeder": jedra_iz_cpuinfo(cpuinfo), "osnova": osnova_iz_release(os_release),
         "seja": os.environ.get("XDG_SESSION_TYPE", ""), "baterije": baterije(), "zasloni": zasloni()}
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
    if not p["graficne"]:
        p["graficne"] = graficne_iz_drm()
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


def podatki(safeer: str = "") -> dict:
    """Strojna in programska oprema tega racunalnika za stran »O tem racunalniku«, skupaj z diski.
    [safeer] razlicica Safeer OS (safeer_os.RAZLICICA); manjkajoci podatek je prazen, nikoli izmisljen."""
    zacetek = time.monotonic()
    izpis = ""
    try:
        if sys.platform == "win32":
            p = _podatki_windows()
        else:
            p = _podatki_linux()
            izpis = _lsblk()
    except Exception:  # noqa: BLE001
        p = {"sistem": platform.platform(), "jedro": platform.release(), "procesor": "", "jeder": os.cpu_count() or 0,
             "pomnilnik": {"skupaj": 0, "na_voljo": 0, "izmenjalni": 0}, "graficne": [], "racunalnik": "", "cas_delovanja_s": 0}
    p["arhitektura"] = platform.machine()
    p["python"] = platform.python_version()
    p["safeer"] = str(safeer or "")
    p["komponente"] = [{"ime": i, "razlicica": r} for i, r in komponente_iz_modulov(sys.modules)]
    p["naprave"] = naprave_iz_lsblk(izpis) if izpis else []
    try:
        p["diski"] = _diski_linux(izpis) if sys.platform.startswith("linux") else diski()
    except Exception:  # noqa: BLE001 - brez seznama diskov, ostali podatki ostanejo
        p["diski"] = []
    p["cas_ms"] = int((time.monotonic() - zacetek) * 1000)
    return p


# ---------------------------------------------------------------------- velikost map (O tem racunalniku v Datotekah)

#: Stetje velikosti map: najvec toliko sekund in vnosov, nato delni izid (»vsaj«). Tece v niti mostu, nikoli v vmesniku.
ROK_MAP = 6.0
NAJVEC_VNOSOV = 400_000
_rod_map = 0          # vsak nov zacetek ali preklic poveca rod; stetje starejsega roda se ustavi ob naslednjem vnosu


def preklici_velikosti_map() -> bool:
    global _rod_map
    _rod_map += 1
    return True


def velikosti_map(pot: str, rok: float = ROK_MAP, najvec: int = NAJVEC_VNOSOV, koliko: int = 12,
                  ura: Callable[[], float] = time.monotonic) -> dict:
    """Koliko prostora na disku zasede vsaka podmapa mape `pot` (kot `du`: dodeljeni bloki, trda povezava enkrat).
    Ne sledi simbolnim povezavam in ne prestopi na drug datotecni sistem; samo branje z uporabnikovimi pravicami.
    Ustavi se ob roku, meji vnosov ali preklicu (nov klic, preklici_velikosti_map) in vrne delni izid s popolno=False."""
    global _rod_map
    _rod_map += 1
    rod = _rod_map
    pot = os.path.realpath(os.path.expanduser(str(pot or "~")))
    try:
        naprava = os.stat(pot).st_dev
        vnosi = list(os.scandir(pot))
    except OSError:
        return {"ok": False, "pot": pot, "mape": [], "popolno": False, "preklicano": False}
    konec = ura() + rok
    videni: set = set()
    stevec = 0
    ustavljeno = ""

    def velikost_vnosa(st) -> int:
        if st.st_nlink > 1:
            kljuc = (st.st_dev, st.st_ino)
            if kljuc in videni:
                return 0
            videni.add(kljuc)
        return (st.st_blocks * 512) if hasattr(st, "st_blocks") else st.st_size

    mape, datoteke_tu = [], 0
    for v in vnosi:
        try:
            if v.is_dir(follow_symlinks=False):
                mape.append(v)
            elif not v.is_symlink():
                datoteke_tu += velikost_vnosa(v.stat(follow_symlinks=False))
        except OSError:
            continue
    izid = []
    for m in mape:
        skupaj, datotek, sklad = 0, 0, [m.path]
        while sklad and not ustavljeno:
            mapa = sklad.pop()
            try:
                with os.scandir(mapa) as it:
                    for v in it:
                        stevec += 1
                        if rod != _rod_map:
                            ustavljeno = "preklic"
                            break
                        if stevec % 512 == 0 and (ura() > konec or stevec > najvec):
                            ustavljeno = "meja"
                            break
                        try:
                            st = v.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if st.st_dev != naprava:
                            continue
                        skupaj += velikost_vnosa(st)
                        if v.is_dir(follow_symlinks=False):
                            sklad.append(v.path)
                        elif not v.is_symlink():
                            datotek += 1
            except OSError:
                continue
        izid.append({"ime": m.name, "pot": m.path, "velikost": skupaj, "datotek": datotek, "popolno": not sklad and not ustavljeno})
        if ustavljeno == "preklic":
            break
    izid.sort(key=lambda d: -d["velikost"])
    return {"ok": True, "pot": pot, "mape": izid[:koliko], "datoteke_tu": datoteke_tu, "vseh_map": len(mape),
            "popolno": not ustavljeno, "preklicano": ustavljeno == "preklic"}
