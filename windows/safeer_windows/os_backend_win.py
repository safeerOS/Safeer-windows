"""Windows zaledje za Safeer OS: programi, datoteke, sistemski viri in nastavitve."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import List, Optional

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "SafeerOS")
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

def doloci_skupino(ime: str, pot: str) -> str:
    niz = (ime + " " + pot).lower()
    for skup, kljucne in KATEGORIJE_PROGRAMOV.items():
        if any(k in niz for k in kljucne):
            return skup
    return "drugo"


def poisci_start_menu_programe() -> List[dict]:
    programi = []
    videni = set()

    mape = []
    if sys.platform == "win32":
        all_users = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                 r"Microsoft\Windows\Start Menu\Programs")
        cur_user = os.path.join(os.environ.get("APPDATA", ""),
                                r"Microsoft\Windows\Start Menu\Programs")
        mape.extend([all_users, cur_user])
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
                    ime = stem.replace("-", " ").replace("_", " ").title()
                    # Odstrani odvečne sistemske besede
                    ime = ime.replace("Shortcut", "").strip()
                    if not ime or ime.lower() in ("uninstall", "odstrani", "help", "readme"):
                        continue
                    if ime.lower() in videni:
                        continue
                    videni.add(ime.lower())
                    polna = os.path.join(root, file)
                    programi.append({
                        "id": f"win_app_{len(programi)}",
                        "ime": ime,
                        "pot": polna.replace("/", "\\"),
                        "skupina": doloci_skupino(ime, polna),
                        "ikona": "znak.svg",
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
                "ikona": "znak.svg",
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


# ---------------------------------------------------------------------------
# Sistemski viri
# ---------------------------------------------------------------------------

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
    }


def _ukaz_samozagona() -> str:
    """Ukaz za HKCU Run, pravilno citiran tudi pri poteh s presledki."""
    if getattr(sys, "frozen", False):
        deli = [sys.executable, "--ozadje"]
    else:
        deli = [sys.executable, os.path.abspath(sys.argv[0]), "--ozadje"]
    return subprocess.list2cmdline(deli)


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
