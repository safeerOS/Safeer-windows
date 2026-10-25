"""Tanek most platforme za Safeer OS: EN vir za vse, kar Linux in Windows naredita razlicno.

Lastnik, 25. 10. 2026: »Kar velja za eno okolje, mora veljati za drugo.« Vmesnik (assets/os) in jedro (core/) sta
skupna; tu je samo, KAKO platforma naredi isto stvar: poti podatkov in nastavitev, diski, zagon programa, »pokazi v
mapi«, sistemske nastavitve in napajanje, bliznjice, zvok, DNS Scita. Ista datoteka je v Safeer-linux in
Safeer-windows (skupna-koda.json).

Pravila:
  - Vsaka funkcija ima obe veji. Parameter `windows` (None = ta racunalnik) izbere vejo, zato se veja Windows preizkusi
    tudi na Linuxu z laznimi subprocess/os.startfile (tests/test_platforma.py).
  - Linux veja klice obstojece jedro (os_sistem, os_scit, sistem_podatki), kjer je koda ze (varnostno pregledana,
    root prek core/root_ukaz). Windows veja je tu - izlocena iz os_backend_win.py, namizje_datoteke.py in Windows
    kopije core/os_scit.py; stare funkcije zdaj klicejo te.
  - Uvozi jedra so leni (v funkciji): tovor Safeer OS ne potrebuje modulov druge platforme.
"""
from __future__ import annotations

import importlib
import ipaddress
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional

JE_WINDOWS = sys.platform == "win32"
IME = "windows" if JE_WINDOWS else "linux"

#: Windows: brez okna konzole za PowerShell/netsh (0 drugje).
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _win(windows: Optional[bool]) -> bool:
    return JE_WINDOWS if windows is None else bool(windows)


def ime(windows: Optional[bool] = None) -> str:
    """»windows« ali »linux« - isto polje kot »platforma« v odgovoru zacetek/zmoznosti."""
    return "windows" if _win(windows) else "linux"


# ---------------------------------------------------------------------------------------- jedro Linuxa (leni uvozi)
# Tovor Safeer Control (packaging/install_control_payload.sh) nosi samo, kar Control potrebuje (os_datoteke za
# »pokazi v mapi«); nastavitev, zvoka, Scita in diskov tam ni - funkcije vrnejo neuspeh namesto ImportError. Uvoz z
# nizom v try/ImportError: tests/test_tovor_uvozi.py ga vidi kot neobveznega (Safeer OS te module ima v tovoru).
def _os_sistem():
    try:
        return importlib.import_module("core.os_sistem")
    except ImportError:
        return None


def _os_scit():
    try:
        return importlib.import_module("core.os_scit")
    except ImportError:
        return None


def _sistem_podatki():
    try:
        return importlib.import_module("core.sistem_podatki")
    except ImportError:
        return None


# ---------------------------------------------------------------------------------------- poti
# Iste vrednosti kot do zdaj na vsaki platformi (uporabnikovi podatki se ne premaknejo):
# Linux os_programi.MAPA_NASTAVITEV, os_govor.MAPA, os_lupina._mapa_ikon; Windows os_backend_win.CONFIG_DIR,
# varnostna_vrata._pot, namizje_qml._mapa_ikon.
def _o(okolje: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if okolje is None else okolje


def mapa_nastavitev(windows: Optional[bool] = None, okolje: Optional[Mapping[str, str]] = None) -> str:
    """Nastavitve Safeer OS: Linux $XDG_CONFIG_HOME/safeer-os, Windows %APPDATA%\\SafeerOS."""
    o = _o(okolje)
    if _win(windows):
        return os.path.join(o.get("APPDATA") or o.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "SafeerOS")
    return os.path.join(o.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "safeer-os")


def mapa_podatkov(windows: Optional[bool] = None, okolje: Optional[Mapping[str, str]] = None) -> str:
    """Podatki Safeer OS: Linux $XDG_DATA_HOME/safeer-os, Windows %LOCALAPPDATA%\\SafeerOS."""
    o = _o(okolje)
    if _win(windows):
        return os.path.join(o.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS")
    return os.path.join(o.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "safeer-os")


def mapa_predpomnilnika(windows: Optional[bool] = None, okolje: Optional[Mapping[str, str]] = None) -> str:
    """Predpomnilnik (ikone, slicice): Linux $XDG_CACHE_HOME/safeer-os, Windows %LOCALAPPDATA%\\SafeerOS."""
    o = _o(okolje)
    if _win(windows):
        return os.path.join(o.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS")
    return os.path.join(o.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os")


# ---------------------------------------------------------------------------------------- diski
def diski() -> list:
    """Diski s prostim prostorom (core/sistem_podatki: lsblk na Linuxu, GetLogicalDrives na Windows)."""
    sp = _sistem_podatki()
    return sp.diski() if sp is not None else []


def priklopi_disk(naprava: str, windows: Optional[bool] = None) -> dict:
    """Priklop razdelka (udisks na Linuxu). Windows pogone priklopi sam - tako je vracal os_app tudi do zdaj."""
    if _win(windows):
        return {"ok": False, "napaka": "ni_podprto"}
    sp = _sistem_podatki()
    return sp.priklopi(str(naprava or "")) if sp is not None else {"ok": False, "napaka": "ni_podprto"}


# ---------------------------------------------------------------------------------------- zagon programov
def zazeni_locen(ukaz: List[str], windows: Optional[bool] = None) -> bool:
    """Zunanji program (Nemo, Raziskovalec ...), loceno od Safeer OS. Linux: prek varuha procesov (oom_score_adj 0,
    svoja seja), sicer Popen v novi seji - oboje z okoljem brez nasih zasebnih poti (core/zasebni_webkit.py).
    Windows: Popen brez dedovanja rocajev."""
    ukaz = [str(x) for x in (ukaz or [])]
    if not ukaz:
        return False
    if _win(windows):
        try:
            subprocess.Popen(ukaz, close_fds=True)
            return True
        except Exception:  # noqa: BLE001
            return False
    from core import varuh_procesov, zasebni_webkit
    okolje = zasebni_webkit.okolje_za_zunanje()
    try:
        if varuh_procesov.zazeni_program(ukaz, okolje):
            return True
    except Exception as e:  # noqa: BLE001 - varuh je neobvezen; rezerva je Popen spodaj
        print("[SafeerOS] zagon prek varuha:", e, flush=True)
    try:
        subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=okolje)
        return True
    except Exception:  # noqa: BLE001
        return False


def zazeni_program(pot: str, windows: Optional[bool] = None) -> bool:
    """Program, bliznjica ali datoteka s privzetim programom. Windows: os.startfile (kot os_backend_win.zazeni_program).
    Linux: .desktop prek »gio launch«, sicer program sam (seznam programov z oznakami je core/os_programi.Programi)."""
    pot = str(pot or "")
    if not pot:
        return False
    if _win(windows):
        startfile = getattr(os, "startfile", None)       # samo Windows
        if startfile is None:
            return False
        try:
            startfile(pot)
            return True
        except Exception:  # noqa: BLE001
            return False
    if pot.endswith(".desktop"):
        return bool(shutil.which("gio")) and zazeni_locen(["gio", "launch", pot], windows=False)
    return zazeni_locen([pot], windows=False)


def pokazi_v_mapi(pot: str, windows: Optional[bool] = None) -> bool:
    """Upravitelj datotek z oznaceno datoteko: Nemo (Linux Mint) ali Raziskovalec (/select,). Samo obstojeca pot."""
    if not str(pot or "").strip():
        return False                # abspath("") je trenutna mapa - prazna pot ni »ta mapa«
    pot = os.path.abspath(os.path.expanduser(str(pot)))
    if not os.path.exists(pot):
        return False
    if _win(windows):
        return zazeni_locen(["explorer.exe", "/select," + pot], windows=True)
    if shutil.which("nemo") is None:
        return False
    return zazeni_locen(["nemo", pot], windows=False)


# ---------------------------------------------------------------------------------------- sistemske nastavitve
#: Windows: razdelek Nastavitev Safeer OS -> stran Nastavitev Windows ali sistemsko orodje (iz os_backend_win.py).
NASTAVITVE_WINDOWS = {
    "": "ms-settings:",
    "sistem": "ms-settings:display",
    "omrezje": "ms-settings:network",
    "zvok": "ms-settings:sound",
    "aplikacije": "ms-settings:appsfeatures",
    "baterija": "ms-settings:powersleep",
    "posodobitve": "ms-settings:windowsupdate",
    "varnost": "ms-settings:windowsdefender",
    "racuni": "ms-settings:yourinfo",
    "nadzorna_plosca": "control.exe",
    # Kljuci skupnega vmesnika Safeer OS (isti kot moduli Cinnamona na Linuxu).
    "display": "ms-settings:display",
    "nightlight": "ms-settings:nightlight",
    "screensaver": "control.exe desk.cpl,,1",
    "sound": "ms-settings:sound",
    "power": "ms-settings:powersleep",
    "mouse": "ms-settings:mousetouchpad",
    "keyboard": "ms-settings:typing",
    "user": "ms-settings:yourinfo",
    "privacy": "ms-settings:privacy",
    "default": "ms-settings:defaultapps",
    "startup": "ms-settings:startupapps",
    "calendar": "ms-settings:dateandtime",
    "notifications": "ms-settings:notifications",
    "accessibility": "ms-settings:easeofaccess",
    "windows": "ms-settings:multitasking",
    "bluetooth": "ms-settings:bluetooth",
    "opravila": "taskmgr.exe",
    "diski": "diskmgmt.msc",
    # cmd.exe je na vseh podprtih Windows 10/11; Windows Terminal ni.
    "terminal": "cmd.exe",
    "datoteke": "explorer.exe",
}
MODULI_WINDOWS = ("display", "nightlight", "screensaver", "sound", "power", "mouse", "keyboard", "user", "privacy",
                  "default", "startup", "calendar", "notifications", "accessibility", "windows")
ORODJA_WINDOWS = ("omrezje", "bluetooth", "posodobitve", "opravila", "diski", "terminal", "datoteke")


def razpolozljive_nastavitve(jezik: str = "", windows: Optional[bool] = None) -> dict:
    """Kaj od nastavitev ta racunalnik ima (vmesnik skrije ostalo): {"moduli": [...], "orodja": [...], ...}."""
    if _win(windows):
        return {"moduli": list(MODULI_WINDOWS), "orodja": list(ORODJA_WINDOWS)}
    m = _os_sistem()
    return m.razpolozljivo(jezik) if m is not None else {"moduli": [], "orodja": []}


def odpri_nastavitve(razdelek: str = "", windows: Optional[bool] = None) -> bool:
    """Odpre nastavitev sistema. Linux: modul Cinnamona, plosca GNOME ali orodje s seznama (core/os_sistem).
    Windows: stran ms-settings ali orodje s seznama NASTAVITVE_WINDOWS (neznan razdelek -> zacetna stran)."""
    razdelek = str(razdelek or "")
    if not _win(windows):
        m = _os_sistem()
        return m is not None and m.odpri_nastavitve(razdelek)
    cilj = NASTAVITVE_WINDOWS.get(razdelek.lower(), "ms-settings:")
    try:
        if cilj.startswith("control.exe"):
            subprocess.Popen(cilj.split())
        elif cilj.endswith(".exe"):
            subprocess.Popen([cilj])
        elif getattr(os, "startfile", None) is None:
            return False
        else:
            os.startfile(cilj)      # ms-settings:..., diskmgmt.msc  # noqa: S606
        return True
    except Exception as e:  # noqa: BLE001
        print("[SafeerOS] nastavitve (%s): %s" % (razdelek, e), flush=True)
        return False


#: Windows: dejanje napajanja -> ukaz (iz os_backend_win.napajanje; vsa imena, ki jih vmesnik poslje).
NAPAJANJE_WINDOWS = {
    "izklop": ["shutdown.exe", "/s", "/t", "0"], "shutdown": ["shutdown.exe", "/s", "/t", "0"],
    "ponovni-zagon": ["shutdown.exe", "/r", "/t", "0"], "ponovni_zagon": ["shutdown.exe", "/r", "/t", "0"],
    "restart": ["shutdown.exe", "/r", "/t", "0"], "reboot": ["shutdown.exe", "/r", "/t", "0"],
    "zakleni": ["rundll32.exe", "user32.dll,LockWorkStation"], "zaklep": ["rundll32.exe", "user32.dll,LockWorkStation"],
    "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    "spanje": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
    "odjava": ["shutdown.exe", "/l"], "logoff": ["shutdown.exe", "/l"], "signout": ["shutdown.exe", "/l"],
}


def napajanje(dejanje: str, windows: Optional[bool] = None) -> bool:
    """Zakleni, odjava, spanje, ponovni zagon, izklop. Linux: core/os_sistem (systemd/Cinnamon); Windows: shutdown.exe."""
    dejanje = str(dejanje or "").lower()
    if not _win(windows):
        m = _os_sistem()
        return m is not None and m.napajanje(dejanje)
    ukaz = NAPAJANJE_WINDOWS.get(dejanje)
    if not ukaz:
        return False
    try:
        subprocess.Popen(list(ukaz))
        return True
    except Exception as e:  # noqa: BLE001
        print("[SafeerOS] napajanje %s: %s" % (dejanje, e), flush=True)
        return False


# ---------------------------------------------------------------------------------------- bliznjice
#: Bliznjice za namige v vmesniku. Samo preverjene (25. 10. 2026): Linux safeer_os._na_tipko (Super+Tab je v Cinnamonu
#: prost), Windows varnostna_vrata.py (Win+Tab je Pogled opravil Windows, zato Ctrl+Win+Tab). Cesar platforma nima,
#: ni na seznamu - vmesnik namiga ne pokaze.
BLIZNJICE: Dict[str, Dict[str, str]] = {
    "linux": {"tipka": "Super", "zasloni": "Super+Tab", "zasloniNazaj": "Shift+Super+Tab",
              "sosednjiZaslon": "Super+Alt+←/→", "celZaslon": "F11"},
    "windows": {"tipka": "Win", "zasloni": "Ctrl+Win+Tab", "varnostnaVrata": "Ctrl+Alt+Shift+W"},
}


def bliznjice(windows: Optional[bool] = None) -> Dict[str, str]:
    return dict(BLIZNJICE[ime(windows)])


# ---------------------------------------------------------------------------------------- zvok
def _glasnost_win():
    """Windows Core Audio (windows/safeer_windows/glasnost_win.py) - samo na Windows, uvoz ob prvem klicu. Navaden
    uvoz (ne importlib), da ga PyInstaller najde; »windows.safeer_windows« je pot pri zagonu iz izvorne kode."""
    try:
        from safeer_windows import glasnost_win
        return glasnost_win
    except ImportError:
        g = None
    try:
        from windows.safeer_windows import glasnost_win as g
    except ImportError:
        g = None
    return g


def zvok(windows: Optional[bool] = None) -> Optional[dict]:
    """Privzeti izhod: {"glasnost": 0-150, "utisan": bool} ali None (oblika core/os_sistem.zvok na obeh platformah)."""
    if not _win(windows):
        m = _os_sistem()
        return m.zvok() if m is not None else None
    g = _glasnost_win()
    s = g.stanje() if g is not None else None
    if not isinstance(s, dict):
        return None
    return {"glasnost": int(s.get("level") or 0), "utisan": bool(s.get("muted"))}


def nastavi_glasnost(odstotek: int, windows: Optional[bool] = None) -> bool:
    odstotek = max(0, min(100, int(odstotek)))
    if not _win(windows):
        m = _os_sistem()
        return m is not None and m.nastavi_glasnost(odstotek)
    g = _glasnost_win()
    return g is not None and g.nastavi(raven=odstotek) is not None


def preklopi_utisaj(windows: Optional[bool] = None) -> bool:
    if not _win(windows):
        m = _os_sistem()
        return m is not None and m.preklopi_utisaj()
    g = _glasnost_win()
    return g is not None and g.nastavi("toggle_mute") is not None


# ---------------------------------------------------------------------------------------- DNS Scita
# Linux: systemd-resolved (core/os_scit, resolvectl z dovoljenjem polkit). Windows: PowerShell DnsClient, netsh kot
# rezerva. Ime vmesnika gre v PowerShell kot niz v enojnih narekovajih (podvojen ' v imenu), rezervni strezniki samo
# kot veljavni naslovi IP - prej je bilo ime vstavljeno v ukaz brez ubeznice (Windows kopija os_scit.py).
def _ps_niz(besedilo: str) -> str:
    return "'" + str(besedilo).replace("'", "''") + "'"


def _veljavno_ime_vmesnika(vmesnik: str) -> bool:
    v = str(vmesnik or "")
    return 0 < len(v) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in v)


def _powershell(ukaz: str, cas: float = 8.0) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ukaz], capture_output=True, text=True,
                    timeout=cas, creationflags=CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return None


def _netsh(argumenti: List[str], cas: float = 5.0) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(["netsh"] + argumenti, capture_output=True, text=True, timeout=cas, creationflags=CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return None


def dns_vmesniki(windows: Optional[bool] = None) -> List[str]:
    """Povezani omrezni vmesniki (ethernet, wifi), na katerih Scit nastavi DNS."""
    if not _win(windows):
        m = _os_scit()
        return m.vmesniki_povezani() if m is not None else []
    izhod: List[str] = []
    r = _powershell("Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object -ExpandProperty Name", 5.0)
    if r is not None and r.returncode == 0:
        for vrstica in (r.stdout or "").splitlines():
            v = vrstica.strip()
            if v and v not in izhod and _veljavno_ime_vmesnika(v):
                izhod.append(v)
    return izhod or ["Ethernet", "Wi-Fi"]


def dns_vmesnika(vmesnik: str, windows: Optional[bool] = None) -> str:
    """Strezniki DNS vmesnika (presledek med njimi) ali ''."""
    if not _win(windows):
        m = _os_scit()
        return m.dns_vmesnika(vmesnik) if m is not None else ""
    if not _veljavno_ime_vmesnika(vmesnik):
        return ""
    r = _powershell("(Get-DnsClientServerAddress -InterfaceAlias %s -AddressFamily IPv4).ServerAddresses"
                    % _ps_niz(vmesnik), 5.0)
    if r is None or r.returncode != 0:
        return ""
    return " ".join(x.strip() for x in (r.stdout or "").splitlines() if x.strip())


def dns_usmeri(vmesnik: str, vrata: int, rezerva: Optional[List[str]] = None, windows: Optional[bool] = None) -> bool:
    """DNS vmesnika na Scit (127.0.0.1), strezniki usmerjevalnika za njim kot rezerva. Windows DNS odjemalec vrat ne
    pozna - Scit tam poslusa na 53 (vrata so samo za Linux)."""
    if not _win(windows):
        m = _os_scit()
        return m is not None and m.usmeri(vmesnik, int(vrata), rezerva)
    if not _veljavno_ime_vmesnika(vmesnik):
        return False
    strezniki = ["127.0.0.1"]
    for naslov in rezerva or []:
        try:
            n = str(ipaddress.ip_address(str(naslov).strip()))
        except ValueError:
            continue
        if n not in strezniki:
            strezniki.append(n)
    r = _powershell("Set-DnsClientServerAddress -InterfaceAlias %s -ServerAddresses @(%s)"
                    % (_ps_niz(vmesnik), ", ".join(_ps_niz(s) for s in strezniki)))
    if r is not None and r.returncode == 0:
        return True
    r = _netsh(["interface", "ip", "set", "dns", "name=" + str(vmesnik), "static", "127.0.0.1"])
    return r is not None and r.returncode == 0


def dns_povrni(vmesnik: str, windows: Optional[bool] = None) -> bool:
    """Vmesniku vrne streznike DNS, ki jih doloci sistem (DHCP / NetworkManager)."""
    if not _win(windows):
        m = _os_scit()
        return m is not None and m.povrni(vmesnik)
    if not _veljavno_ime_vmesnika(vmesnik):
        return False
    r = _powershell("Set-DnsClientServerAddress -InterfaceAlias %s -ResetServerAddresses" % _ps_niz(vmesnik))
    if r is not None and r.returncode == 0:
        return True
    r = _netsh(["interface", "ip", "set", "dns", "name=" + str(vmesnik), "dhcp"])
    return r is not None and r.returncode == 0


def opis(windows: Optional[bool] = None) -> Dict[str, Any]:
    """Povzetek za zacetek/zmoznosti vmesnika: platforma in bliznjice."""
    return {"platforma": ime(windows), "bliznjice": bliznjice(windows)}
