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

from core import root_ukaz, zasebni_webkit

CAS = 4.0


def _zazeni(ukaz: List[str], cas: float = CAS) -> Optional[str]:
    """Pozene ukaz in vrne izpis (None ob napaki ali ce ukaza ni). Program samo iz sistemskih map (nmcli ...
    lahko vprasa za geslo prek polkita - core/root_ukaz.sistemski_program)."""
    ukaz = root_ukaz.sistemski_ukaz(ukaz)
    if not ukaz:
        return None
    try:
        r = subprocess.run(ukaz, capture_output=True, text=True, timeout=cas)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _v_ozadju(ukaz: List[str]) -> bool:
    # Program z absolutno potjo iz sistemskih map, ne po PATH: orodja Minta, Nastavitve in systemctl lahko sama vprasajo
    # za geslo - podtaknjen program v ~/.local/bin bi ga dobil (core/root_ukaz.sistemski_program).
    ukaz = root_ukaz.sistemski_ukaz(ukaz)
    if not ukaz:
        return False
    from core import varuh_procesov
    try:
        pid = varuh_procesov.zazeni_program(ukaz, zasebni_webkit.okolje_za_zunanje())
        if pid:
            return True
    except Exception:
        pass
    try:
        # Nastavitve sistema so zunanji program: brez nasih zasebnih poti (core/zasebni_webkit.py).
        subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env=zasebni_webkit.okolje_za_zunanje())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------- baterija
def baterija(koren: str = "/sys/class/power_supply") -> Optional[dict]:
    for pot in sorted(glob.glob(os.path.join(koren, "BAT*"))):
        try:
            with open(os.path.join(pot, "capacity"), encoding="utf-8") as f:
                odstotek = int(f.read().strip())
        except Exception:
            continue
        stanje = ""
        try:
            with open(os.path.join(pot, "status"), encoding="utf-8") as f:
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
            with open(os.path.join(pot, "brightness"), encoding="utf-8") as f:
                zdaj = int(f.read().strip())
            with open(os.path.join(pot, "max_brightness"), encoding="utf-8") as f:
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
    """Pot do slike ozadja namizja Cinnamon ali GNOME ('' ce je ni) - Safeer OS jo uporabi za svoje ozadje.

    GNOME (Ubuntu 24.04): ozadje je v org.gnome.desktop.background, v temnem slogu picture-uri-dark. Prej je Safeer OS
    tam ostal brez ozadja (bral je samo Cinnamon)."""
    izpis = _zazeni(["gsettings", "get", "org.cinnamon.desktop.background", "picture-uri"]) or ""
    uri = izpis.strip().strip("'")
    if not uri.startswith("file://"):
        temno = "prefer-dark" in (_zazeni(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]) or "")
        kljuc = "picture-uri-dark" if temno else "picture-uri"
        uri = (_zazeni(["gsettings", "get", "org.gnome.desktop.background", kljuc]) or "").strip().strip("'")
    if uri.startswith("file://"):
        from urllib.parse import unquote
        pot = unquote(uri[len("file://"):])
        if os.path.isfile(pot):
            return pot
        # Flatpak: /usr racunalnika (ozadja Safeer, Minta) je v peskovniku pod /run/host/usr (--filesystem=host-os:ro).
        # Brez tega je delovna povrsina v Flatpaku ostala brez ozadja (testni PC, 14. 10. 2026).
        if pot.startswith("/usr/") and os.path.isfile("/run/host" + pot):
            return "/run/host" + pot
    return ""


def stanje() -> dict:
    return {"baterija": baterija(), "omrezje": omrezje(), "zvok": zvok(), "svetlost": svetlost(),
            "nocna": nocna_luc()}


# ---------------------------------------------------------------------- nastavitve Minta
# Lastnik, 19. 10. 2026: »Nastavitve morajo odrazati celotne nastavitve operacijskega sistema.« Safeer OS pokaze vsak
# modul Cinnamona, vsako orodje Minta in vsako plosco Nastavitev GNOME, ki jih ta racunalnik RES ima (brez mrtvih gumbov).
#: Moduli cinnamon-settings (oznaka = argument ukaza) v Cinnamonu 5.2-6.6 (Mint 21-22.x). Seznam je iz izvorne kode
#: Cinnamona (files/usr/share/cinnamon/cinnamon-settings/modules/cs_*.py, oznake 5.2.7, 5.8.4, 6.0.4, 6.2.9 in master,
#: preverjeno 19. 10. 2026): tiling je do 6.2, online-accounts do 6.0, nightlight in thunderbolt od 6.4.
MODULI = {
    "backgrounds", "themes", "fonts", "effects", "desktop", "desklets", "applets", "extensions", "panel",
    "display", "nightlight", "screensaver", "sound", "power", "mouse", "keyboard", "gestures",
    "thunderbolt", "accessibility", "user", "privacy", "startup", "default", "calendar", "notifications",
    "windows", "workspaces", "hotcorner", "general", "actions", "info", "tiling", "online-accounts",
}
#: Moduli, ki jih imajo vse te razlicice: rezerva, kadar mape modulov ni mogoce prebrati (Flatpak brez dostopa do /usr).
MODULI_VEDNO = {
    "accessibility", "applets", "backgrounds", "calendar", "default", "desklets", "desktop", "display", "effects",
    "extensions", "fonts", "general", "hotcorner", "info", "keyboard", "mouse", "notifications", "panel", "power",
    "privacy", "screensaver", "sound", "startup", "themes", "user", "windows", "workspaces",
}
#: Kje so moduli Cinnamona in namizne datoteke sistema (v Flatpaku je /usr gostitelja pod /run/host/usr).
MAPE_MODULOV = ("/usr/share/cinnamon/cinnamon-settings/modules", "/run/host/usr/share/cinnamon/cinnamon-settings/modules")
MAPE_PROGRAMOV = ("/usr/share/applications", "/run/host/usr/share/applications")

#: Samostojna orodja Minta, Cinnamona, GNOME in Ubuntuja (oznaka -> mozni ukazi, prvi namesceni velja). Ukazi so iz
#: namiznih datotek v izvorni kodi teh programov (Exec=, preverjeno 19. 10. 2026); pkexec kot v njihovi namizni datoteki.
ORODJA: Dict[str, List[List[str]]] = {
    "posodobitve": [["mintupdate"], ["update-manager"]],
    "programska-oprema": [["mintinstall"], ["gnome-software"]],
    "gonilniki": [["driver-manager"], ["mintdrivers"], ["software-properties-gtk", "--open-tab=4"]],
    "varnostne-kopije": [["timeshift-launcher"], ["timeshift-gtk"]],
    "kopije-datotek": [["mintbackup"]],
    "sistemsko-porocilo": [["mintreport"]],
    "opravila": [["gnome-system-monitor"]],
    "diski": [["gnome-disks"]],
    "poraba-diska": [["baobab"]],
    "omrezje": [["nm-connection-editor"]],
    "bluetooth": [["blueman-manager"], ["blueberry"]],
    "tiskalniki": [["system-config-printer"]],
    "jezik": [["mintlocale"]],
    "vnosna-metoda": [["mintlocale-im"]],
    "viri-programov": [["pkexec", root_ukaz.MINTSOURCES], ["software-properties-gtk"]],
    "paketi": [["pkexec", root_ukaz.SYNAPTIC]],      # ovoj synaptic-pkexec bi pkexec poiskal po PATH
    "uporabniki": [["cinnamon-settings-users"]],
    "prijavno-okno": [["pkexec", root_ukaz.LIGHTDM_SETTINGS]],
    "pozarni-zid": [["gufw"]],
    "spletni-racuni": [["gnome-online-accounts-gtk"]],
    "gesla": [["seahorse"]],
    "urejevalnik-menija": [["cinnamon-menu-editor"]],
    "usb-slika": [["mintstick", "-m", "iso"]],
    "usb-formatiranje": [["mintstick", "-m", "format"]],
    "dobrodoslica": [["mintwelcome"]],
    "terminal": [["gnome-terminal"], ["x-terminal-emulator"]],
    "posnetek-zaslona": [["cinnamon-screenshot", "--interactive"], ["gnome-screenshot", "--interactive"]],
    "datoteke": [["nemo"]],
    "warpinator": [["warpinator"]],
}

#: Plosce Nastavitev GNOME (gnome-control-center 46, panels/*/gnome-<plosca>-panel.desktop; Ubuntu doda »ubuntu«).
#: Katere ima ta racunalnik in s katerimi argumenti se odprejo (46: »system about«), pove namizna datoteka plosce.
PLOSCE_GNOME = (
    "wifi", "network", "wwan", "bluetooth", "display", "sound", "power", "multitasking", "background", "ubuntu",
    "notifications", "search", "applications", "privacy", "online-accounts", "sharing", "mouse", "keyboard",
    "printers", "wacom", "color", "universal-access", "system", "region", "datetime", "users", "about",
    # GNOME 42-45 (Ubuntu 22.04): ista vsebina pod starimi imeni.
    "info-overview", "user-accounts", "default-apps", "removable-media", "location", "camera", "microphone",
    "usage", "lock", "thunderbolt", "diagnostics",
)
_ARGUMENT = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


def _program(ukaz: List[str]) -> str:
    """Program, ki mora obstajati, da ukaz deluje (pri »pkexec program« je to program, ne pkexec)."""
    return ukaz[1] if ukaz and ukaz[0] == "pkexec" and len(ukaz) > 1 else (ukaz[0] if ukaz else "")


def _ukaz_orodja(oznaka: str) -> Optional[List[str]]:
    for ukaz in ORODJA.get(oznaka, []):
        if ukaz[0] == "pkexec":
            # Kot root: pkexec in program z absolutno potjo, ne po uporabnikovem PATH (core/root_ukaz.py).
            if shutil.which(_program(ukaz)) and root_ukaz.na_voljo():
                return root_ukaz.ukaz(*ukaz[1:])
            continue
        if root_ukaz.sistemski_program(ukaz[0]):       # samo sistemske mape (zagon v _v_ozadju), ne PATH
            return ukaz
    return None


def _namizna(pot: str) -> Dict[str, str]:
    """Vnosi razdelka [Desktop Entry] namizne datoteke (kljuc -> vrednost); prazno ob napaki."""
    vnosi: Dict[str, str] = {}
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            razdelek = ""
            for vrstica in f.read(65536).splitlines():
                vrstica = vrstica.strip()
                if vrstica.startswith("["):
                    razdelek = vrstica
                elif razdelek == "[Desktop Entry]" and "=" in vrstica and not vrstica.startswith("#"):
                    k, _, v = vrstica.partition("=")
                    vnosi.setdefault(k.strip(), v.strip())
    except OSError:
        return {}
    return vnosi


def _ime_iz_namizne(vnosi: Dict[str, str], jezik: str) -> Dict[str, str]:
    """Krajevno ime in kljucne besede iz namizne datoteke (rezerva za plosce, ki jih Safeer se ne pozna)."""
    ime = vnosi.get("Name[%s]" % jezik) or vnosi.get("Name") or ""
    kljucne = " ".join(x for x in (vnosi.get("Keywords[%s]" % jezik, ""), vnosi.get("Keywords", "")) if x)
    return {"ime": ime[:80], "kljucne": kljucne.replace(";", " ").strip()[:300]}


def moduli_cinnamon(mape: Optional[tuple] = None, mape_programov: Optional[tuple] = None) -> set:
    """Moduli Cinnamona, ki jih ta racunalnik ima. Vir je mapa modulov (cs_<modul>.py), sicer namizne datoteke
    cinnamon-settings-<modul>.desktop; brez obojega samo moduli vseh razlicic. Prej je Safeer OS pokazal vseh 30 (tudi
    Nocno luc in Thunderbolt v Mintu 22.1, ki ju se ni bilo - gumb ni naredil nicesar)."""
    najdeni = set()
    for mapa in MAPE_MODULOV if mape is None else mape:
        try:
            imena = os.listdir(mapa)
        except OSError:
            continue
        najdeni |= {i[3:-3].replace("_", "-") for i in imena if i.startswith("cs_") and i.endswith(".py")}
    if not najdeni:
        for mapa in MAPE_PROGRAMOV if mape_programov is None else mape_programov:
            try:
                imena = os.listdir(mapa)
            except OSError:
                continue
            najdeni |= {i[len("cinnamon-settings-"):-len(".desktop")] for i in imena
                        if i.startswith("cinnamon-settings-") and i.endswith(".desktop")}
    return (najdeni & MODULI) if najdeni else set(MODULI_VEDNO)


def plosce_gnome(mape_programov: Optional[tuple] = None, jezik: str = "") -> Dict[str, dict]:
    """Plosce Nastavitev GNOME, ki jih ta racunalnik ima: oznaka -> {"ukaz": [...], "ime", "kljucne"}. Ukaz je iz vrstice
    Exec namizne datoteke gnome-<oznaka>-panel.desktop - sprejmemo samo »gnome-control-center« z oznakami (brez lupine)."""
    plosce: Dict[str, dict] = {}
    for mapa in MAPE_PROGRAMOV if mape_programov is None else mape_programov:
        try:
            imena = sorted(os.listdir(mapa))
        except OSError:
            continue
        for ime in imena:
            if not (ime.startswith("gnome-") and ime.endswith("-panel.desktop")):
                continue
            oznaka = ime[len("gnome-"):-len("-panel.desktop")]
            if oznaka in plosce or not _ARGUMENT.match(oznaka):
                continue
            vnosi = _namizna(os.path.join(mapa, ime))
            deli = vnosi.get("Exec", "").split()
            if len(deli) < 2 or os.path.basename(deli[0]) != "gnome-control-center" or len(deli) > 4 \
                    or not all(_ARGUMENT.match(d) for d in deli[1:]):
                continue
            plosce[oznaka] = dict(_ime_iz_namizne(vnosi, jezik), ukaz=["gnome-control-center"] + deli[1:])
    return plosce


def _gnome_seja() -> bool:
    try:
        from core import seja_prikaza
        return seja_prikaza.namizje() == "gnome"
    except Exception:  # noqa: BLE001
        return False


def razpolozljivo(jezik: str = "") -> dict:
    """Kaj od nastavitev in orodij ta racunalnik res ima (stran skrije ostalo).

    moduli: moduli Cinnamona (ne v seji GNOME - cinnamon-settings tam ne dela prav); plosce: plosce Nastavitev GNOME (samo
    v seji GNOME ali brez Cinnamona); orodja: samostojni programi; imena: krajevno ime plosce iz sistema, kadar ga
    Safeer nima v svojih besedilih (plosca, ki pride z novo razlicico GNOME)."""
    gnome = _gnome_seja()
    cinnamon = bool(root_ukaz.sistemski_program("cinnamon-settings")) and not gnome
    moduli = sorted(moduli_cinnamon()) if cinnamon else []
    plosce = plosce_gnome(jezik=jezik) if (not cinnamon and root_ukaz.sistemski_program("gnome-control-center")) else {}
    orodja = sorted(o for o in ORODJA if _ukaz_orodja(o))
    return {"moduli": moduli, "orodja": orodja, "plosce": sorted(plosce),
            "imena": {"p:" + k: {"ime": v["ime"], "kljucne": v["kljucne"]} for k, v in plosce.items()
                      if k not in PLOSCE_GNOME and v["ime"]}}


def odpri_nastavitve(modul: str) -> bool:
    """Odpre modul Cinnamona, orodje ali plosco GNOME (»p:<oznaka>«). Samo, kar je na seznamu in na tem racunalniku."""
    modul = str(modul or "")
    if modul.startswith("p:"):
        plosca = plosce_gnome().get(modul[2:])
        return bool(plosca) and _v_ozadju(plosca["ukaz"])
    if modul in MODULI:
        return _v_ozadju(["cinnamon-settings", modul])
    ukaz = _ukaz_orodja(modul)
    return bool(ukaz) and _v_ozadju(ukaz)


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
        if root_ukaz.sistemski_program(ukaz[0]) and _v_ozadju(ukaz):
            return True
    return False
