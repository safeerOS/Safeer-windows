"""Stanje in nadzor racunalnika za Safeer OS na Linuxu (Linux Mint / Cinnamon).

Safeer OS ne izumlja svojih nastavitev: za vse uporabi orodja, ki jih Mint ze ima (NetworkManager,
PulseAudio/PipeWire, Cinnamon, systemd-logind, Upravitelj posodobitev ...). Zato se vse, kar
uporabnik spremeni tu, vidi tudi v Mintovih nastavitvah in obratno.

Vsak ukaz je fiksen seznam argumentov (brez lupine); stran poslje samo oznako dejanja ali modula,
ki ju tu preverimo na seznamu.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

CAS = 4.0


def _zazeni(ukaz: List[str], cas: float = CAS) -> Optional[str]:
    """Pozene ukaz in vrne izpis (None ob napaki ali ce ukaza ni)."""
    if not ukaz or shutil.which(ukaz[0]) is None:
        return None
    try:
        r = subprocess.run(ukaz, capture_output=True, text=True, timeout=cas)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _v_ozadju(ukaz: List[str]) -> bool:
    if not ukaz or shutil.which(ukaz[0]) is None:
        return False
    try:
        subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------- baterija
def baterija(koren: str = "/sys/class/power_supply") -> Optional[dict]:
    for pot in sorted(glob.glob(os.path.join(koren, "BAT*"))):
        try:
            with open(os.path.join(pot, "capacity")) as f:
                odstotek = int(f.read().strip())
        except Exception:
            continue
        stanje = ""
        try:
            with open(os.path.join(pot, "status")) as f:
                stanje = f.read().strip()
        except Exception:
            pass
        return {"odstotek": max(0, min(100, odstotek)), "polni": stanje in ("Charging", "Full"),
                "polna": stanje == "Full"}
    return None


# ---------------------------------------------------------------------- omrezje
def omrezje() -> dict:
    """{"vrsta": "wifi"|"ethernet"|"", "ime", "signal", "wifi_vklopljen", "wifi_obstaja"}."""
    izhod = {"vrsta": "", "ime": "", "signal": 0, "wifi_vklopljen": False, "wifi_obstaja": False}
    naprave = _zazeni(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"]) or ""
    for vrstica in naprave.splitlines():
        deli = _razdeli(vrstica)
        if len(deli) < 3:
            continue
        vrsta, stanje, ime = deli[0], deli[1], deli[2]
        if vrsta == "wifi":
            izhod["wifi_obstaja"] = True
        if vrsta in ("wifi", "ethernet") and stanje == "connected" and not izhod["vrsta"]:
            izhod["vrsta"], izhod["ime"] = vrsta, ime
    radio = (_zazeni(["nmcli", "radio", "wifi"]) or "").strip()
    izhod["wifi_vklopljen"] = radio == "enabled"
    if izhod["vrsta"] == "wifi":
        seznam = _zazeni(["nmcli", "-t", "-f", "IN-USE,SIGNAL,SSID", "device", "wifi", "list", "--rescan", "no"]) or ""
        for vrstica in seznam.splitlines():
            deli = _razdeli(vrstica)
            if len(deli) >= 2 and deli[0] == "*":
                try:
                    izhod["signal"] = int(deli[1])
                except ValueError:
                    pass
                break
    return izhod


def _razdeli(vrstica: str) -> List[str]:
    """nmcli -t loci polja z ':' in ubezi dvopicje v vrednostih z '\\:'."""
    deli, trenutni, ubezi = [], "", False
    for znak in vrstica:
        if ubezi:
            trenutni += znak
            ubezi = False
        elif znak == "\\":
            ubezi = True
        elif znak == ":":
            deli.append(trenutni)
            trenutni = ""
        else:
            trenutni += znak
    deli.append(trenutni)
    return deli


def nastavi_wifi(vklop: bool) -> bool:
    return _zazeni(["nmcli", "radio", "wifi", "on" if vklop else "off"]) is not None


# ---------------------------------------------------------------------- zvok
def zvok() -> Optional[dict]:
    """{"glasnost": 0-150, "utisan": bool} privzetega izhoda ali None."""
    izpis = _zazeni(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    if izpis:
        m = re.search(r"(\d+)%", izpis)
        if m:
            utisan = "yes" in (_zazeni(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]) or "").lower()
            return {"glasnost": int(m.group(1)), "utisan": utisan}
    izpis = _zazeni(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    if izpis:
        m = re.search(r"Volume:\s*([0-9.]+)", izpis)
        if m:
            return {"glasnost": int(round(float(m.group(1)) * 100)), "utisan": "MUTED" in izpis}
    return None


def nastavi_glasnost(odstotek: int) -> bool:
    odstotek = max(0, min(100, int(odstotek)))
    if _zazeni(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % odstotek]) is not None:
        _zazeni(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        return True
    if _zazeni(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "%d%%" % odstotek]) is not None:
        _zazeni(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
        return True
    return False


def preklopi_utisaj() -> bool:
    if _zazeni(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]) is not None:
        return True
    return _zazeni(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]) is not None


# ---------------------------------------------------------------------- zaslon
_MOC = ["gdbus", "call", "--session", "--dest", "org.cinnamon.SettingsDaemon.Power",
        "--object-path", "/org/cinnamon/SettingsDaemon/Power"]


def svetlost(koren: str = "/sys/class/backlight") -> Optional[int]:
    """Svetlost vgrajenega zaslona v odstotkih (None na racunalniku brez nje)."""
    izpis = _zazeni(_MOC + ["--method", "org.cinnamon.SettingsDaemon.Power.Screen.GetPercentage"], 2.0)
    if izpis:
        m = re.search(r"(\d+)", izpis)
        if m:
            return int(m.group(1))
    for pot in sorted(glob.glob(os.path.join(koren, "*"))):
        try:
            with open(os.path.join(pot, "brightness")) as f:
                zdaj = int(f.read().strip())
            with open(os.path.join(pot, "max_brightness")) as f:
                najvec = int(f.read().strip())
            if najvec > 0:
                return int(round(zdaj * 100 / najvec))
        except Exception:
            continue
    return None


def nastavi_svetlost(odstotek: int) -> bool:
    odstotek = max(5, min(100, int(odstotek)))
    return _zazeni(_MOC + ["--method", "org.cinnamon.SettingsDaemon.Power.Screen.SetPercentage",
                           str(odstotek)], 2.0) is not None


_NOCNA = ["org.cinnamon.settings-daemon.plugins.color", "night-light-enabled"]


def nocna_luc() -> Optional[bool]:
    izpis = _zazeni(["gsettings", "get"] + _NOCNA)
    if izpis is None:
        return None
    return izpis.strip() == "true"


def nastavi_nocno_luc(vklop: bool) -> bool:
    return _zazeni(["gsettings", "set"] + _NOCNA + ["true" if vklop else "false"]) is not None


def ozadje_namizja() -> str:
    """Pot do slike ozadja namizja Cinnamon ('' ce je ni) - Safeer OS jo uporabi za svoje ozadje."""
    izpis = _zazeni(["gsettings", "get", "org.cinnamon.desktop.background", "picture-uri"]) or ""
    uri = izpis.strip().strip("'")
    if uri.startswith("file://"):
        from urllib.parse import unquote
        pot = unquote(uri[len("file://"):])
        if os.path.isfile(pot):
            return pot
    return ""


def stanje() -> dict:
    return {"baterija": baterija(), "omrezje": omrezje(), "zvok": zvok(), "svetlost": svetlost(),
            "nocna": nocna_luc()}


# ---------------------------------------------------------------------- nastavitve Minta
#: Moduli cinnamon-settings, ki jih Safeer OS ponuja (oznaka modula = argument ukaza).
MODULI = {
    "backgrounds", "themes", "fonts", "effects", "desktop", "desklets", "applets", "extensions", "panel",
    "display", "nightlight", "screensaver", "sound", "power", "mouse", "keyboard", "gestures",
    "thunderbolt", "accessibility", "user", "privacy", "startup", "default", "calendar", "notifications",
    "windows", "workspaces", "hotcorner", "general", "actions",
}

#: Samostojna orodja Minta in GNOME, ki jih nastavitve ponujajo (oznaka -> mozni ukazi).
ORODJA: Dict[str, List[List[str]]] = {
    "posodobitve": [["mintupdate"]],
    "programska-oprema": [["mintinstall"]],
    "gonilniki": [["driver-manager"], ["mintdrivers"]],
    "varnostne-kopije": [["timeshift-launcher"], ["timeshift-gtk"]],
    "kopije-datotek": [["mintbackup"]],
    "sistemsko-porocilo": [["mintreport"]],
    "opravila": [["gnome-system-monitor"]],
    "diski": [["gnome-disks"]],
    "omrezje": [["nm-connection-editor"]],
    "bluetooth": [["blueman-manager"], ["blueberry"]],
    "tiskalniki": [["system-config-printer"]],
    "jezik": [["mintlocale"]],
    "viri-programov": [["mintsources"]],
    "terminal": [["gnome-terminal"], ["x-terminal-emulator"]],
    "posnetek-zaslona": [["gnome-screenshot", "--interactive"]],
    "datoteke": [["nemo"]],
    "warpinator": [["warpinator"]],
}


def razpolozljivo() -> dict:
    """Kaj od nastavitev in orodij ta racunalnik res ima (stran skrije ostalo)."""
    moduli = sorted(MODULI) if shutil.which("cinnamon-settings") else []
    orodja = sorted(o for o, ukazi in ORODJA.items() if any(shutil.which(u[0]) for u in ukazi))
    return {"moduli": moduli, "orodja": orodja}


def odpri_nastavitve(modul: str) -> bool:
    modul = str(modul or "")
    if modul in MODULI:
        return _v_ozadju(["cinnamon-settings", modul])
    for ukaz in ORODJA.get(modul, []):
        if shutil.which(ukaz[0]):
            return _v_ozadju(ukaz)
    return False


# ---------------------------------------------------------------------- napajanje
DEJANJA = {
    "zakleni": [["cinnamon-screensaver-command", "--lock"], ["loginctl", "lock-session"]],
    "odjava": [["cinnamon-session-quit", "--logout", "--no-prompt"]],
    "spanje": [["systemctl", "suspend"]],
    "ponovni-zagon": [["systemctl", "reboot"]],
    "izklop": [["systemctl", "poweroff"]],
}


def napajanje(dejanje: str) -> bool:
    for ukaz in DEJANJA.get(str(dejanje or ""), []):
        if shutil.which(ukaz[0]) and _v_ozadju(ukaz):
            return True
    return False
