"""Windows zaledje za Safeer OS: programi, datoteke, sistemski viri in nastavitve."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "SafeerOS")
CONFIG_FILE = os.path.join(CONFIG_DIR, "os.json")

MAPE_WINDOWS = [
    ("HOME", os.path.expanduser("~"), "Uporabnik"),
    ("DOCUMENTS", os.path.join(os.path.expanduser("~"), "Documents"), "Dokumenti"),
    ("DOWNLOAD", os.path.join(os.path.expanduser("~"), "Downloads"), "Prenosi"),
    ("PICTURES", os.path.join(os.path.expanduser("~"), "Pictures"), "Slike"),
    ("MUSIC", os.path.join(os.path.expanduser("~"), "Music"), "Glasba"),
    ("VIDEOS", os.path.join(os.path.expanduser("~"), "Videos"), "Videoposnetki"),
    ("DESKTOP", os.path.join(os.path.expanduser("~"), "Desktop"), "Namizje"),
]

KATEGORIJE_PROGRAMOV = {
    "splet": ("chrome", "firefox", "edge", "opera", "brave", "vivaldi", "safeer", "browser", "brskalnik",
              "thunderbird", "outlook", "discord", "telegram", "whatsapp", "skype", "zoom", "teams"),
    "pisarna": ("word", "excel", "powerpoint", "access", "onenote", "libreoffice", "acrobat", "foxit",
                "pdf", "beležnica", "notepad", "calculator", "računalo", "office"),
    "predstavnost": ("vlc", "spotify", "media player", "itunes", "audacity", "obs", "photos", "fotografije",
                     "netflix", "predvajalnik", "glasba", "film"),
    "igre": ("steam", "epic games", "gog", "riot", "minecraft", "xbox", "game", "igre"),
    "programiranje": ("visual studio", "vscode", "vs code", "git", "python", "terminal", "powershell",
                      "cmd", "pycharm", "sublime", "intellij", "node"),
    "orodja": ("7-zip", "winrar", "poweriso", "ccleaner", "paint", "slikar", "snip", "izrezovanje",
               "orodja", "tools", "total commander"),
    "sistem": ("settings", "nastavitve", "control panel", "nadzorna plošča", "task manager",
               "upravitelj opravil", "regedit", "disk", "device manager"),
}


def nalozi_shrambo() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {"pripeti": [], "skriti": [], "pogosti": {}, "celozaslonsko": True}


def shrani_shrambo(podatki: dict) -> bool:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(podatki, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Datoteke
# ---------------------------------------------------------------------------

def uporabniske_mape() -> List[dict]:
    izhod = []
    for vrsta, pot, privzeto_ime in MAPE_WINDOWS:
        if os.path.isdir(pot):
            izhod.append({
                "vrsta": vrsta,
                "pot": pot.replace("/", "\\"),
                "ime": os.path.basename(pot) or privzeto_ime
            })
    return izhod


def medijske_mape() -> List[dict]:
    """Vrne samo uporabnikove mape Slike, Glasba in Videi.

    Na Windowsu so znane mape lahko prestavljene (npr. v OneDrive), zato najprej
    preberemo dejanske poti iz registra in sele nato uporabimo varne privzetke.
    """
    kljuci = {
        "PICTURES": ("My Pictures", "Pictures", "Slike"),
        "MUSIC": ("My Music", "Music", "Glasba"),
        "VIDEOS": ("My Video", "Videos", "Videoposnetki"),
    }
    registrske: dict[str, str] = {}
    if sys.platform == "win32":
        try:
            import winreg
            pot_kljuca = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, pot_kljuca) as kljuc:
                for vrsta, (ime_vrednosti, _mapa, _opis) in kljuci.items():
                    try:
                        vrednost, _ = winreg.QueryValueEx(kljuc, ime_vrednosti)
                        registrske[vrsta] = os.path.expandvars(str(vrednost))
                    except OSError:
                        pass
        except (ImportError, OSError):
            pass

    rezultat = []
    videne = set()
    dom = os.path.expanduser("~")
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or ""
    for vrsta, (_ime_vrednosti, privzeta, opis) in kljuci.items():
        kandidati = [registrske.get(vrsta, ""), os.path.join(dom, privzeta)]
        if onedrive:
            kandidati.append(os.path.join(onedrive, privzeta))
        for kandidat in kandidati:
            pot = os.path.normpath(kandidat) if kandidat else ""
            oznaka = os.path.normcase(os.path.abspath(pot)) if pot else ""
            if pot and os.path.isdir(pot) and oznaka not in videne:
                videne.add(oznaka)
                rezultat.append({"vrsta": vrsta, "pot": pot, "ime": os.path.basename(pot) or opis})
                break
    return rezultat


def vrsta_datoteke(ime: str, je_mapa: bool = False) -> str:
    if je_mapa:
        return "mapa"
    konc = os.path.splitext(ime)[1].lower()
    if konc in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico"):
        return "slika"
    if konc in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"):
        return "video"
    if konc in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"):
        return "zvok"
    if konc in (".zip", ".rar", ".7z", ".tar", ".gz", ".iso"):
        return "arhiv"
    if konc in (".exe", ".msi", ".bat", ".cmd", ".ps1", ".lnk"):
        return "program"
    if konc in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".txt", ".md", ".csv"):
        return "dokument"
    return "drugo"


def preglej_mapo(pot: str, skrite: bool = False) -> dict:
    if not pot or pot == "~":
        pot = os.path.expanduser("~")
    pot = os.path.abspath(os.path.expanduser(pot))
    if not os.path.isdir(pot):
        return {"pot": pot, "starsek": os.path.dirname(pot), "elementi": []}

    starsek = os.path.dirname(pot) if os.path.dirname(pot) != pot else ""
    elementi = []
    try:
        with os.scandir(pot) as it:
            for entry in it:
                if not skrite and entry.name.startswith((".", "$")):
                    continue
                try:
                    je_mapa = entry.is_dir(follow_symlinks=False)
                    st = entry.stat(follow_symlinks=False)
                    elementi.append({
                        "ime": entry.name,
                        "pot": entry.path.replace("/", "\\"),
                        "mapa": je_mapa,
                        "velikost": 0 if je_mapa else st.st_size,
                        "spremenjeno": st.st_mtime,
                        "vrsta": vrsta_datoteke(entry.name, je_mapa)
                    })
                except OSError:
                    continue
    except OSError:
        pass

    elementi.sort(key=lambda x: (not x["mapa"], x["ime"].lower()))
    return {"pot": pot.replace("/", "\\"), "starsek": starsek.replace("/", "\\") if starsek else "", "elementi": elementi[:500]}


def isci_datoteke(poizvedba: str, koren: Optional[str] = None) -> List[dict]:
    if not poizvedba or len(poizvedba.strip()) < 2:
        return []
    poizvedba_lower = poizvedba.strip().lower()
    koren = os.path.abspath(koren or os.path.expanduser("~"))
    zadetki = []

    for root, dirs, files in os.walk(koren):
        dirs[:] = [d for d in dirs if not d.startswith((".", "$", "AppData", "node_modules"))]
        for name in dirs + files:
            if poizvedba_lower in name.lower():
                polna_pot = os.path.join(root, name)
                je_mapa = os.path.isdir(polna_pot)
                zadetki.append({
                    "ime": name,
                    "pot": polna_pot.replace("/", "\\"),
                    "mapa": je_mapa,
                    "vrsta": vrsta_datoteke(name, je_mapa)
                })
                if len(zadetki) >= 50:
                    return zadetki
    return zadetki


def odpri_datoteko(pot: str) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(pot)  # noqa: S606
            return True
        subprocess.Popen(["xdg-open", pot], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri odpiranju datoteke {pot}: {e}")
        return False


def odpri_mapo(pot: str) -> bool:
    """Odpre MAPO v Raziskovalcu; datoteke s tem nikoli ne odpremo (lahko bi bila program)."""
    if not pot or not os.path.isdir(pot):
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", os.path.abspath(pot)])
        else:
            subprocess.Popen(["xdg-open", pot], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri odpiranju mape {pot}: {e}")
        return False


def pokazi_v_mapi(pot: str) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", f"/select,{pot}"])
            return True
        subprocess.Popen(["xdg-open", os.path.dirname(pot) if os.path.isfile(pot) else pot])
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri prikazu v mapi: {e}")
        return False


# ---------------------------------------------------------------------------
# Programi
# ---------------------------------------------------------------------------

_IKONA_PREDPOMNILNIK: dict[str, str] = {}
_ICON_PROVIDER = None


def _pridobi_icon_provider():
    global _ICON_PROVIDER
    if _ICON_PROVIDER is None:
        try:
            from PySide6.QtWidgets import QApplication, QFileIconProvider
            if not QApplication.instance():
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                _ = QApplication(sys.argv)
            _ICON_PROVIDER = QFileIconProvider()
        except Exception:
            _ICON_PROVIDER = False
    return _ICON_PROVIDER if _ICON_PROVIDER is not False else None


def pridobi_ikono_programa(pot: str, ime: str = "") -> str:
    """Pridobi pristno ikono programa v obliki Base64 PNG.

    Uporablja nativni Windows Shell prek Qt QFileIconProvider, s predpomnjenjem
    v pomnilniku za bliskovito hitrost.
    """
    if not pot:
        return ""

    if pot in _IKONA_PREDPOMNILNIK:
        return _IKONA_PREDPOMNILNIK[pot]

    polna_pot = pot
    if not os.path.isabs(polna_pot):
        najdena = shutil.which(polna_pot)
        if najdena:
            polna_pot = najdena

    provider = _pridobi_icon_provider()
    if provider and os.path.exists(polna_pot):
        try:
            from PySide6.QtCore import QFileInfo, QByteArray, QBuffer, QIODevice
            qicon = provider.icon(QFileInfo(polna_pot))
            if not qicon.isNull():
                pm = qicon.pixmap(64, 64)
                if not pm.isNull():
                    ba = QByteArray()
                    buf = QBuffer(ba)
                    buf.open(QIODevice.WriteOnly)
                    if pm.save(buf, "PNG"):
                        raw = bytes(ba.data())
                        if raw:
                            data_uri = f"data:image/png;base64,{base64.b64encode(raw).decode('ascii')}"
                            _IKONA_PREDPOMNILNIK[pot] = data_uri
                            return data_uri
        except Exception:
            pass

    _IKONA_PREDPOMNILNIK[pot] = ""
    return ""


def doloci_skupino(ime: str, pot: str) -> str:
    niz = (ime + " " + pot).lower()
    for skup, kljucne in KATEGORIJE_PROGRAMOV.items():
        if any(k in niz for k in kljucne):
            return skup
    return "drugo"


_NI_PROGRAM = re.compile(
    r"\b(uninstall|uninstaller|odstrani|odstranitev|readme|read me|help|pomoč|manuals?|documentation|"
    r"setup|registration|release notes|what is new|license|licence)\b", re.IGNORECASE)


def _ni_program(ime: str) -> bool:
    """Pomožni vnosi v meniju Start (odstranjevalniki, navodila, namestitve) niso programi za seznam."""
    return bool(_NI_PROGRAM.search(ime))


def poisci_start_menu_programe(z_ikonami: bool = True) -> List[dict]:
    """Programi iz menija Start. z_ikonami=False: brez risanja ikon (polje `ikona` ostane prazno) - za katalog ob
    prijavi v Safeer Link, kjer gresta samo ime in vrsta; id-ji in vrstni red so enaki kot pri polnem seznamu."""
    programi = []
    videni = set()

    mape = []
    if sys.platform == "win32":
        all_users = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                 r"Microsoft\Windows\Start Menu\Programs")
        cur_user = os.path.join(os.environ.get("APPDATA", ""),
                                r"Microsoft\Windows\Start Menu\Programs")
        desktop_user = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        desktop_public = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")
        for m in (all_users, cur_user, desktop_user, desktop_public):
            if m and os.path.isdir(m) and m not in mape:
                mape.append(m)
    else:
        # Za testiranje na Linuxu
        mape.append("/usr/share/applications")

    for mapa in mape:
        if not os.path.isdir(mapa):
            continue
        for root, _, files in os.walk(mapa):
            for file in files:
                if file.lower().endswith((".lnk", ".desktop", ".exe")):
                    stem = os.path.splitext(file)[0]
                    ime = stem.replace("-", " ").replace("_", " ")
                    # Imena bližnjic so že človeška (»Safeer OS«, »YouTube«); .title() jih je kvaril v »Safeer Os«.
                    if not any(c.isupper() for c in ime):
                        ime = ime.title()
                    # Odstrani odvečne sistemske besede
                    ime = ime.replace("Shortcut", "").replace("- Bližnjica", "").strip()
                    if not ime or _ni_program(ime):
                        continue
                    if ime.lower() in videni:
                        continue
                    videni.add(ime.lower())
                    polna = os.path.join(root, file)
                    stabilni_id = "win_app_" + hashlib.sha256(
                        os.path.normcase(os.path.abspath(polna)).encode("utf-8", "replace")
                    ).hexdigest()[:16]
                    programi.append({
                        "id": stabilni_id,
                        "ime": ime,
                        "pot": polna.replace("/", "\\"),
                        "skupina": doloci_skupino(ime, polna),
                        "ikona": pridobi_ikono_programa(polna, ime) if z_ikonami else "",
                        "opis": ""
                    })

    # Dodaj še pogosta sistemska orodja Windows, če niso najdena
    sistemski = [
        ("Nadzorna plošča", "control.exe", "sistem"),
        ("Upravitelj opravil", "taskmgr.exe", "sistem"),
        ("Beležnica", "notepad.exe", "pisarna"),
        ("Računalo", "calc.exe", "pisarna"),
        ("Slikar", "mspaint.exe", "orodja"),
        ("Ukazni poziv", "cmd.exe", "programiranje"),
        ("Windows PowerShell", "powershell.exe", "programiranje"),
    ]
    for ime, cmd, skup in sistemski:
        if ime.lower() not in videni:
            videni.add(ime.lower())
            programi.append({
                "id": f"win_sys_{cmd}",
                "ime": ime,
                "pot": cmd,
                "skupina": skup,
                "ikona": pridobi_ikono_programa(cmd, ime) if z_ikonami else "",
                "opis": ""
            })

    programi.sort(key=lambda p: p["ime"].lower())
    return programi


def zazeni_program(pot: str) -> bool:
    try:
        shramba = nalozi_shrambo()
        pogosti = shramba.setdefault("pogosti", {})
        pogosti[pot] = pogosti.get(pot, 0) + 1
        shrani_shrambo(shramba)

        if sys.platform == "win32":
            os.startfile(pot)  # noqa: S606
            return True
        subprocess.Popen([pot], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri zagonu programa {pot}: {e}")
        return False


# ---------------------------------------------------------------------------
# Nastavitve in Napajanje
# ---------------------------------------------------------------------------

NASTAVITVE_URI = {
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
    # Ključi, ki jih uporablja skupni Safeer OS vmesnik.
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
    # cmd.exe je prisoten na vseh podprtih Windows 10/11; Windows Terminal ni.
    "terminal": "cmd.exe",
    "datoteke": "explorer.exe",
}

WINDOWS_MODULI = (
    "display", "nightlight", "screensaver", "sound", "power", "mouse", "keyboard",
    "user", "privacy", "default", "startup", "calendar", "notifications",
    "accessibility", "windows",
)
WINDOWS_ORODJA = (
    "omrezje", "bluetooth", "posodobitve", "opravila", "diski", "terminal", "datoteke",
)


def razpolozljive_nastavitve() -> dict:
    """Vrne pogodbo, ki jo pričakuje skupni spletni vmesnik Safeer OS."""
    return {"moduli": list(WINDOWS_MODULI), "orodja": list(WINDOWS_ORODJA)}


def odpri_nastavitve(razdelek: str = "") -> bool:
    target = NASTAVITVE_URI.get(razdelek.lower(), "ms-settings:")
    try:
        if sys.platform == "win32":
            if target.startswith("control.exe"):
                subprocess.Popen(target.split())
            elif target.endswith(".exe"):
                subprocess.Popen([target])
            else:
                os.startfile(target)  # noqa: S606
            return True
        subprocess.Popen(["cinnamon-settings"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri odpiranju nastavitev ({razdelek}): {e}")
        return False


def napajanje(dejanje: str) -> bool:
    dejanje = (dejanje or "").lower()
    try:
        if sys.platform == "win32":
            if dejanje in ("izklop", "shutdown"):
                subprocess.Popen(["shutdown.exe", "/s", "/t", "0"])
            elif dejanje in ("ponovni-zagon", "ponovni_zagon", "restart", "reboot"):
                subprocess.Popen(["shutdown.exe", "/r", "/t", "0"])
            elif dejanje in ("zakleni", "zaklep", "lock"):
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            elif dejanje in ("spanje", "sleep"):
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
            elif dejanje in ("odjava", "logoff", "signout"):
                subprocess.Popen(["shutdown.exe", "/l"])
            else:
                return False
            return True
        # Linux fallback
        if dejanje in ("izklop", "shutdown"):
            subprocess.Popen(["systemctl", "poweroff"])
        elif dejanje in ("ponovni_zagon", "restart"):
            subprocess.Popen(["systemctl", "reboot"])
        else:
            return False
        return True
    except Exception as e:
        print(f"[SafeerOS] Napaka pri ukazu napajanja {dejanje}: {e}")
        return False


def pridobi_stanje_omrezja() -> dict:
    povezan = False
    # Pri žični povezavi ostane ime prazno: vmesnik izpiše prevedeno »Žična povezava«,
    # zasebni naslov IP pa se ne kaže na zaslonu (le v polju "ip").
    ime_omrezja = ""
    naslov_ip = ""
    vrsta = "ethernet"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.8)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            povezan = True
            naslov_ip = ip
    except Exception:
        try:
            import socket
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None):
                ip = info[4][0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    povezan = True
                    naslov_ip = ip
                    break
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"],
                                          text=True, errors="replace", timeout=1.5)
            for line in out.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        ssid = parts[1].strip()
                        ime_omrezja = ssid
                        vrsta = "wifi"
                        povezan = True
                        break
        except Exception:
            pass

    if povezan:
        return {
            "povezan": True,
            "vrsta": vrsta,
            "ime": ime_omrezja,
            "ip": naslov_ip,
            "omrezja": [{"ssid": ime_omrezja or "Ethernet", "povezan": True, "moc": 100}],
            "naprave": [{"ime": ime_omrezja or "Ethernet", "vrsta": vrsta, "povezan": True}],
            "shranjene": [],
            "wifi_vklopljen": True,
            "napredno": True
        }
    return {
        "povezan": False,
        "vrsta": "brez",
        "ime": "Brez omrežja",
        "omrezja": [],
        "naprave": [],
        "shranjene": [],
        "wifi_vklopljen": False,
        "napredno": True
    }


def stanje_sistema() -> dict:
    ram_odstotek = 50
    ram_gb = "4.0 / 8.0 GB"
    disk_odstotek = 40
    cpu_odstotek = 10

    try:
        import shutil
        total, used, _ = shutil.disk_usage(os.path.expanduser("~"))
        disk_odstotek = int((used / total) * 100) if total else 0
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_odstotek = int(stat.dwMemoryLoad)
                skupaj_gb = stat.ullTotalPhys / (1024 ** 3)
                uporabljeno_gb = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024 ** 3)
                ram_gb = f"{uporabljeno_gb:.1f} / {skupaj_gb:.1f} GB"
        except Exception:
            pass

    return {
        "cpu": cpu_odstotek,
        "ram": ram_odstotek,
        "ram_gb": ram_gb,
        "disk": disk_odstotek,
        "baterija": None,
        "omrezje": pridobi_stanje_omrezja(),
    }


# ---- zakon solidarnosti: koliko proste moci ima ta racunalnik in ali sme pomagati drugim napravam
#: Enaka pravila kot Linux (core/link_daljinec.py) in Android (Zmogljivost.kt).
VKLOP_BATERIJA = 40
IZKLOP_BATERIJA = 30
NAJVEC_CPU = 85            # % obremenitve procesorja, nad katero ne prevzame dela drugih
NAJMANJ_RAM = 512 * 1024 * 1024
REZERVA_DISKA = 2 * 1024 * 1024 * 1024
_POMAGA = {"zadnje": True}
_CPU_PREJ = {"cas": None}


def _cpu_obremenitev_win() -> int:
    """Obremenitev procesorja v % od zadnjega klica (GetSystemTimes); -1, ce je ni mogoce izmeriti."""
    try:
        import ctypes
        from ctypes import wintypes
        mirovanje, jedro, uporabnik = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(mirovanje), ctypes.byref(jedro), ctypes.byref(uporabnik)):
            return -1
        v = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
        zdaj = (v(mirovanje), v(jedro) + v(uporabnik))
        prej = _CPU_PREJ["cas"]
        _CPU_PREJ["cas"] = zdaj
        if prej is None:
            import time
            time.sleep(0.25)
            return _cpu_obremenitev_win()
        skupaj = zdaj[1] - prej[1]
        if skupaj <= 0:
            return -1
        return max(0, min(100, int(100 * (1 - (zdaj[0] - prej[0]) / skupaj))))
    except Exception:
        return -1


def _baterija_win() -> dict:
    """{raven, polni} prenosnika iz GetSystemPowerStatus; {} pri namiznem racunalniku."""
    try:
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

        st = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return {}
        if st.BatteryFlag == 128 or st.BatteryLifePercent == 255:   # brez baterije / neznano
            return {}
        return {"raven": int(st.BatteryLifePercent), "polni": st.ACLineStatus == 1,
                "varcevanje": st.SystemStatusFlag == 1}
    except Exception:
        return {}


def odlocitev_pomoci(cpu: int, ram_prosto: int, disk_prosto: int, bat: dict) -> dict:
    """{lahko, razlog} po zakonu solidarnosti; baterija: na omrezju ali >= 40 %, pod 30 % ne (vmes ostane)."""
    if cpu >= NAJVEC_CPU:
        return {"lahko": False, "razlog": "preobremenjen"}
    if 0 <= ram_prosto < NAJMANJ_RAM:
        return {"lahko": False, "razlog": "malo_pomnilnika"}
    if 0 <= disk_prosto < REZERVA_DISKA:
        return {"lahko": False, "razlog": "ni_prostora"}
    if bat:
        if bat.get("varcevanje"):
            return {"lahko": False, "razlog": "varcevanje"}
        if bat.get("polni"):
            _POMAGA["zadnje"] = True
        else:
            raven = int(bat.get("raven", 100))
            if raven >= VKLOP_BATERIJA:
                _POMAGA["zadnje"] = True
            elif raven < IZKLOP_BATERIJA:
                _POMAGA["zadnje"] = False
            if not _POMAGA["zadnje"]:
                return {"lahko": False, "razlog": "baterija"}
    return {"lahko": True, "razlog": ""}


def zmogljivost() -> dict:
    """host.info za Safeer Link v istem zapisu kot Linux in Android: cpu, ram, disk, gpu, baterija, pomoc."""
    import platform
    import shutil
    p: dict = {"hostname": platform.node(), "sistem": "Windows " + platform.release(), "vrsta": "racunalnik"}
    cpu = {"jedra": os.cpu_count() or 0}
    obremenitev = _cpu_obremenitev_win() if sys.platform == "win32" else -1
    if obremenitev >= 0:
        cpu["odstotek"] = obremenitev
    p["cpu"] = cpu
    ram_prosto = -1
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_prosto = int(stat.ullAvailPhys)
                p["ram"] = {"skupaj": int(stat.ullTotalPhys), "prosto": ram_prosto}
        except Exception:
            pass
    disk_prosto = -1
    try:
        skupaj, _, prosto = shutil.disk_usage(os.path.expanduser("~"))
        disk_prosto = int(prosto)
        p["disk"] = {"skupaj": int(skupaj), "prosto": disk_prosto}
    except Exception:
        pass
    bat = _baterija_win() if sys.platform == "win32" else {}
    if bat:
        p["baterija"] = {"raven": bat["raven"], "polni": bat["polni"]}
    p["pomoc"] = odlocitev_pomoci(obremenitev, ram_prosto, disk_prosto, bat)
    return p


#: Vpis samozagona v HKCU Run in znacilni del starega ukaza (Python neposredno), po katerem ga prepoznamo.
KLJUC_SAMOZAGONA = r"Software\Microsoft\Windows\CurrentVersion\Run"
IME_SAMOZAGONA = "SafeerOS"
STARI_SAMOZAGON = "safeer_os_windows.py"


def _ukaz_samozagona() -> str:
    """Ukaz za HKCU Run, pravilno citiran tudi pri poteh s presledki.

    Prek zaganjalnika (SafeerOS.exe --ozadje): ta zazene Python brez konzolnega okna in pred zagonom uredi datoteke
    programa. Prej je vpis klical python.exe neposredno - ob prijavi v Windows se je odprlo crno konzolno okno z
    izpisom programa (potrjeno 5. 10. 2026 na testnem racunalniku); ce ga je uporabnik zaprl, se je zaprl Safeer OS.
    """
    from safeer_windows import magnet_win      # pozno: magnet_win je majhen modul brez odvisnosti od tega
    ukaz = magnet_win.zaganjalnik()
    if not ukaz:
        ukaz = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(sys.argv[0])]
    return subprocess.list2cmdline(list(ukaz) + ["--ozadje"])


def osvezi_samozagon() -> bool:
    """Vpis samozagona iz starejse razlicice (Python neposredno) zamenja z danasnjim ukazom. Vrne True, ce ga je.

    Samo vklopljen samozagon in samo nas stari vpis: ce uporabnik samozagona nima ali je vrednost spremenil v kaj
    drugega, se je ne dotaknemo. Stanje »onemogoceno« iz Upravitelja opravil je zapisano drugje in ostane.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KLJUC_SAMOZAGONA, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            vrednost, _ = winreg.QueryValueEx(key, IME_SAMOZAGONA)
            nov = _ukaz_samozagona()
            if not vrednost or not nov or str(vrednost) == nov or STARI_SAMOZAGON not in str(vrednost) \
                    or STARI_SAMOZAGON in nov:
                return False
            winreg.SetValueEx(key, IME_SAMOZAGONA, 0, winreg.REG_SZ, nov)
            return True
    except (FileNotFoundError, OSError):
        return False


def samozagon_vklopljen() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            vrednost, _ = winreg.QueryValueEx(key, "SafeerOS")
        return bool(vrednost)
    except (FileNotFoundError, OSError):
        return False


def nastavi_samozagon(vklop: bool) -> bool:
    """Vključi ali izključi zagon Safeer OS za trenutnega uporabnika."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        pot = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, pot) as key:
            if vklop:
                winreg.SetValueEx(key, "SafeerOS", 0, winreg.REG_SZ, _ukaz_samozagona())
            else:
                try:
                    winreg.DeleteValue(key, "SafeerOS")
                except FileNotFoundError:
                    pass
        return samozagon_vklopljen() == bool(vklop)
    except OSError as e:
        print(f"[SafeerOS] Samozagona ni bilo mogoče spremeniti: {e}")
        return samozagon_vklopljen()


# ---------------------------------------------------------------------------- DRM storitve
# Vgrajena pogona (Qt WebEngine, WebView2 v Safeer OS) nimata Widevine/PlayReady, zato
# Netflix & co. v Spletu ne morejo predvajati. Microsoft Edge na Windows ima Widevine
# (preverjeno z requestMediaKeySystemAccess), zato te storitve odpremo v Edge v nacinu
# aplikacije: okno brez naslovne vrstice, prijave ostanejo v uporabnikovem Edge profilu.
DRM_DOMENE = (
    "netflix.com", "primevideo.com", "amazon.com/gp/video", "disneyplus.com", "max.com",
    "hbomax.com", "skyshowtime.com", "tv.apple.com", "music.apple.com", "voyo.si",
    "paramountplus.com", "dazn.com", "tidal.com", "deezer.com", "open.spotify.com",
    "crunchyroll.com", "mubi.com", "rakuten.tv", "play.hbomax.com", "tv.youtube.com",
)


def je_drm_storitev(url: str) -> bool:
    from urllib.parse import urlsplit
    try:
        deli = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    if deli.scheme.lower() not in ("http", "https"):
        return False
    gostitelj = (deli.hostname or "").lower()
    pot = gostitelj + (deli.path or "")
    for domena in DRM_DOMENE:
        if "/" in domena:
            if pot.startswith(domena) or pot.startswith("www." + domena):
                return True
        elif gostitelj == domena or gostitelj.endswith("." + domena):
            return True
    return False


def najdi_edge() -> Optional[str]:
    kandidati = []
    for spremenljivka in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        koren = os.environ.get(spremenljivka)
        if koren:
            kandidati.append(os.path.join(koren, "Microsoft", "Edge", "Application", "msedge.exe"))
    for pot in kandidati:
        if os.path.isfile(pot):
            return pot
    return shutil.which("msedge")


def odpri_drm_storitev(url: str) -> dict:
    """Odpre DRM storitev v Edge (nacin aplikacije); brez Edge v privzetem brskalniku."""
    edge = najdi_edge()
    if edge:
        try:
            subprocess.Popen([edge, "--app=" + url, "--start-maximized"], close_fds=True)
            return {"zunanje": True, "brskalnik": "Microsoft Edge"}
        except OSError:
            pass
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return {"zunanje": True, "brskalnik": "privzeti brskalnik"}
    except (OSError, AttributeError):
        return {"zunanje": False}


def zazeni_skripto_v_ozadju(skripta: str) -> None:
    """Posodobitev: .cmd skripta tece loceno od tega procesa (pocaka, da se Safeer OS zapre, in zazene nov zaganjalnik)."""
    import subprocess
    subprocess.Popen(["cmd", "/c", skripta], creationflags=0x08000000 | 0x00000200, close_fds=True)   # CREATE_NO_WINDOW | NEW_PROCESS_GROUP

