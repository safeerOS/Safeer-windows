"""Datoteke za namizje Safeer OS na Windows: tisto, kar je v core/os_datoteke.py vezano na Linux.

Skupne (ciste) funkcije - pregled mape, iskanje, nova mapa/datoteka, preimenovanje, lepljenje, razveljavitev,
lastnosti, najvecje datoteke - ostanejo v core/os_datoteke.py, isto kot na Linuxu. Tukaj so Windows razlicice:
odpiranje (privzeti program), »Pokazi v mapi« (Raziskovalec), Koš (nikoli trajno brisanje brez Koša), nosilci
(pogoni) in izmet, skrite datoteke po atributih Windows.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import struct
import subprocess
import sys
import time
from typing import List, Optional

from core import os_datoteke

_WIN = sys.platform == "win32"
FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM = 0x2, 0x4


# ------------------------------------------------------------------ pregled mape (skrite po atributih Windows)
def _skrita(pot: str) -> bool:
    if not _WIN:
        return os.path.basename(pot).startswith(".")
    try:
        atributi = os.stat(pot, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(atributi & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def preglej(pot: str, skrite: bool = False) -> dict:
    izid = os_datoteke.preglej(pot, skrite=True)
    if not skrite:
        elementi = [e for e in izid.get("elementi", []) if not _skrita(e["pot"]) and not e["ime"].startswith(".")]
        izid["elementi"], izid["skupaj"] = elementi, len(elementi)
    koren = os.path.splitdrive(izid.get("pot", ""))[0] + os.sep
    if izid.get("pot") and os.path.normcase(izid["pot"]) == os.path.normcase(koren):
        izid["stars"] = ""          # koren pogona: navzgor ni nicesar (namesto iste mape)
    return izid


# ------------------------------------------------------------------ odpiranje
def odpri(pot: str) -> bool:
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot):
        return False
    try:
        os.startfile(pot)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def pokazi_v_mapi(pot: str) -> bool:
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot):
        return False
    try:
        subprocess.Popen(["explorer.exe", "/select," + pot], close_fds=True)
        return True
    except OSError:
        return False


def odpri_z(pot: str) -> bool:
    """»Odpri z …«: sistemsko okno Windows za izbiro programa."""
    pot = os.path.abspath(str(pot or ""))
    if not os.path.isfile(pot):
        return False
    try:
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", pot], close_fds=True)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ Koš
def _sid_uporabnika() -> str:
    """SID prijavljenega uporabnika (mapa Koša v $Recycle.Bin). Najprej Win32, sicer whoami."""
    if not _WIN:
        return ""
    try:
        from ctypes import wintypes
        advapi, kernel = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        zeton = wintypes.HANDLE()
        if advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(zeton)):
            try:
                dolzina = wintypes.DWORD()
                advapi.GetTokenInformation(zeton, 1, None, 0, ctypes.byref(dolzina))
                medpomnilnik = ctypes.create_string_buffer(dolzina.value)
                if advapi.GetTokenInformation(zeton, 1, medpomnilnik, dolzina, ctypes.byref(dolzina)):
                    sid = ctypes.c_void_p.from_buffer(medpomnilnik).value
                    niz = wintypes.LPWSTR()
                    if advapi.ConvertSidToStringSidW(sid, ctypes.byref(niz)):
                        vrednost = niz.value or ""
                        kernel.LocalFree(ctypes.cast(niz, ctypes.c_void_p))
                        if vrednost:
                            return vrednost
            finally:
                kernel.CloseHandle(zeton)
    except Exception:  # noqa: BLE001
        pass
    try:
        r = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip().split(",")[-1].strip('"')
    except (OSError, subprocess.SubprocessError):
        return ""


def _pogoni() -> List[str]:
    if not _WIN:
        return []
    maska = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if maska & (1 << i)]


def _mape_kosa() -> List[str]:
    sid = _sid_uporabnika()
    if not sid:
        return []
    mape = []
    for pogon in _pogoni():
        if ctypes.windll.kernel32.GetDriveTypeW(pogon) not in (2, 3):   # odstranljiv ali fiksni
            continue
        mapa = os.path.join(pogon, "$Recycle.Bin", sid)
        if os.path.isdir(mapa):
            mape.append(mapa)
    return mape


def beri_info(podatki: bytes) -> Optional[dict]:
    """Zapis $I iz Koša (cista funkcija): razlicica 1 (Vista-8) ali 2 (Windows 10+)."""
    if len(podatki) < 24:
        return None
    razlicica, velikost, cas = struct.unpack_from("<qqq", podatki, 0)
    if razlicica == 2 and len(podatki) >= 28:
        znakov = struct.unpack_from("<i", podatki, 24)[0]
        pot = podatki[28:28 + 2 * max(0, znakov)].decode("utf-16-le", "replace")
    elif razlicica == 1:
        pot = podatki[24:24 + 520].decode("utf-16-le", "replace")
    else:
        return None
    pot = pot.split("\x00", 1)[0]
    izbrisano = (cas - 116444736000000000) / 1e7 if cas > 0 else 0.0     # FILETIME -> Unix
    return {"izvirna": pot, "velikost": int(velikost), "izbrisano": izbrisano}


def smeti() -> dict:
    elementi = []
    for mapa in _mape_kosa():
        try:
            imena = os.listdir(mapa)
        except OSError:
            continue
        for ime in imena:
            if not ime.startswith("$I"):
                continue
            vsebina = os.path.join(mapa, "$R" + ime[2:])
            try:
                with open(os.path.join(mapa, ime), "rb") as f:
                    info = beri_info(f.read(4096))
            except OSError:
                continue
            if info is None or not os.path.lexists(vsebina):
                continue
            prikaz = os.path.basename(info["izvirna"]) or ime
            je_mapa = os.path.isdir(vsebina)
            elementi.append({"id": vsebina, "ime": prikaz, "pot": vsebina, "izvirna": info["izvirna"],
                             "izbrisano": info["izbrisano"], "mapa": je_mapa,
                             "velikost": 0 if je_mapa else info["velikost"],
                             "vrsta": os_datoteke.vrsta_datoteke(prikaz, je_mapa)})
    elementi.sort(key=lambda e: -e["izbrisano"])
    return {"skupaj": len(elementi), "elementi": elementi[:os_datoteke.NAJVEC_V_MAPI]}


def _v_kosu(id_: str) -> Optional[str]:
    """Varnost: obnovimo samo datoteko, ki je res v Košu tega uporabnika."""
    pot = os.path.abspath(str(id_ or ""))
    for mapa in _mape_kosa():
        if os.path.normcase(os.path.dirname(pot)) == os.path.normcase(mapa) and os.path.basename(pot).startswith("$R"):
            return pot if os.path.lexists(pot) else None
    return None


def v_smeti(pot: str) -> dict:
    """V Koš (z razveljavitvijo), nikoli trajno."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.lexists(pot) or os.path.normcase(pot) in (os.path.normcase(os.path.expanduser("~")),
                                                               os.path.normcase(os.path.splitdrive(pot)[0] + os.sep)):
        return {"ok": False, "napaka": "ni_dovoljeno"}
    if not _WIN:
        return {"ok": False, "napaka": "ni_podprto"}
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    zacetek = time.time()
    op = SHFILEOPSTRUCTW(None, FO_DELETE, pot + "\0", None, FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI,
                         False, None, None)
    koda = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if koda != 0 or op.fAnyOperationsAborted or os.path.lexists(pot):
        return {"ok": False, "napaka": f"koda_{koda}"}
    # Kateri vnos v Košu je nas (za »Razveljavi«): ista izvirna pot, izbrisan od zacetka naprej.
    najden = ""
    for e in smeti()["elementi"]:
        if os.path.normcase(e["izvirna"]) == os.path.normcase(pot) and e["izbrisano"] >= zacetek - 2:
            najden = e["id"]
            break
    return {"ok": True, "id": najden}


def obnovi_iz_smeti(id_: str) -> dict:
    vsebina = _v_kosu(id_)
    if vsebina is None:
        return {"ok": False, "napaka": "ni_v_smeteh"}
    info_pot = os.path.join(os.path.dirname(vsebina), "$I" + os.path.basename(vsebina)[2:])
    try:
        with open(info_pot, "rb") as f:
            info = beri_info(f.read(4096))
    except OSError:
        info = None
    if not info or not info["izvirna"]:
        return {"ok": False, "napaka": "ni_izvirne_poti"}
    cilj = info["izvirna"]
    os.makedirs(os.path.dirname(cilj), exist_ok=True)
    if os.path.lexists(cilj):
        osnova, koncnica = os.path.splitext(cilj)
        i = 2
        while os.path.lexists(f"{osnova} ({i}){koncnica}"):
            i += 1
        cilj = f"{osnova} ({i}){koncnica}"
    try:
        shutil.move(vsebina, cilj)
        os.remove(info_pot)
    except OSError as e:
        return {"ok": False, "napaka": str(e)}
    return {"ok": True, "pot": cilj}


def izprazni_smeti() -> dict:
    """Izprazni Koš (to zahteva uporabnik sam v vmesniku, ki prej vprasa)."""
    if not _WIN:
        return {"ok": False}
    koda = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return {"ok": koda in (0, -2147418113)}   # S_OK ali E_UNEXPECTED (Koš je ze prazen)


# ------------------------------------------------------------------ pogoni
def nosilci() -> List[dict]:
    """Pogoni kot na Linuxu: ime, pot, velikost, prosto, ali se da izvreci (USB, SD, optika)."""
    if not _WIN:
        return []
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    izid = []
    for pogon in _pogoni():
        vrsta = k32.GetDriveTypeW(pogon)
        if vrsta not in (2, 3, 5):      # odstranljiv, fiksni, optika
            continue
        oznaka = ctypes.create_unicode_buffer(261)
        sistem = ctypes.create_unicode_buffer(261)
        if not k32.GetVolumeInformationW(pogon, oznaka, 261, None, None, None, sistem, 261):
            if vrsta == 5:
                continue                # prazen optični pogon
            oznaka.value = ""
        prosto, skupaj = ctypes.c_ulonglong(), ctypes.c_ulonglong()
        k32.GetDiskFreeSpaceExW(pogon, None, ctypes.byref(skupaj), ctypes.byref(prosto))
        sistemski = os.path.normcase(pogon) == os.path.normcase(os.environ.get("SystemDrive", "C:") + "\\")
        izid.append({"ime": oznaka.value or pogon.rstrip("\\"), "pot": pogon, "naprava": pogon if vrsta in (2, 5) else "",
                     "velikost": skupaj.value, "prosto": prosto.value, "sistem": sistem.value,
                     "odstranljiv": vrsta in (2, 5), "sistemski": sistemski})
    return izid


def izvrzi(pot: str) -> dict:
    """Varno odstrani USB/SD ali izvrže optični disk (verb »Eject« lupine Windows)."""
    pot = str(pot or "")
    cilj = next((n for n in nosilci() if os.path.normcase(n["pot"]) == os.path.normcase(pot) and n["odstranljiv"]), None)
    if cilj is None:
        return {"ok": False, "napaka": "ni_nosilca"}
    crka = cilj["pot"][:2]
    skripta = ("(New-Object -ComObject Shell.Application).Namespace(17).ParseName('%s').InvokeVerb('Eject')" % crka)
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", skripta], capture_output=True,
                       timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "napaka": str(e)}
    for _ in range(20):
        if not os.path.exists(cilj["pot"]):
            return {"ok": True}
        time.sleep(0.25)
    return {"ok": False, "napaka": "v_uporabi"}


def prostor() -> dict:
    try:
        u = shutil.disk_usage(os.path.expanduser("~"))
    except OSError:
        return {"skupaj": 0, "prosto": -1, "malo": False}
    return {"skupaj": u.total, "prosto": u.free,
            "malo": u.free < os_datoteke.MALO_BAJTOV or (u.total > 0 and u.free < u.total * os_datoteke.MALO_DELEZ)}


# Skupni os_datoteke.razveljavi (»Razveljavi« po brisanju) klice obnovi_iz_smeti istega modula: na Windows je to Koš.
os_datoteke.obnovi_iz_smeti = obnovi_iz_smeti
os_datoteke.v_smeti = v_smeti


def slicice(poti, velikost: int = 160, rok: float = 4.0) -> dict:
    """Slicice slik (PNG/JPEG/WebP/GIF/BMP) kot data: URL - stran namizja je na http://127.0.0.1 in ne bere file://."""
    import base64
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImageReader
    except ImportError:
        return {}
    izid, konec = {}, time.monotonic() + rok
    for pot in list(poti or [])[:120]:
        if time.monotonic() > konec:
            break
        pot = str(pot)
        if os.path.splitext(pot)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            continue
        try:
            if os.path.getsize(pot) > 60 * 1024 * 1024:
                continue
        except OSError:
            continue
        bralnik = QImageReader(pot)
        bralnik.setAutoTransform(True)
        v = bralnik.size()
        if v.isValid() and max(v.width(), v.height()) > velikost:
            bralnik.setScaledSize(v.scaled(velikost, velikost, Qt.AspectRatioMode.KeepAspectRatio))
        slika = bralnik.read()
        if slika.isNull():
            continue
        podatki = QByteArray()
        medpomnilnik = QBuffer(podatki)
        medpomnilnik.open(QIODevice.OpenModeFlag.WriteOnly)
        slika.save(medpomnilnik, "JPEG", 82)
        izid[pot] = "data:image/jpeg;base64," + base64.b64encode(bytes(podatki)).decode("ascii")
    return izid


# ------------------------------------------------------------------ nedavne datoteke (Windows »Recent«)
def cilj_bliznjice(podatki: bytes) -> str:
    """Pot, na katero kaze bliznjica .lnk (cista funkcija; LinkInfo -> LocalBasePath[Unicode]). Prazno, ce je ni."""
    if len(podatki) < 0x4C or podatki[:4] != b"\x4c\x00\x00\x00":
        return ""
    zastavice = struct.unpack_from("<I", podatki, 0x14)[0]
    odmik = 0x4C
    if zastavice & 0x1:                                   # HasLinkTargetIDList
        odmik += 2 + struct.unpack_from("<H", podatki, odmik)[0]
    if not zastavice & 0x2 or odmik + 28 > len(podatki):  # HasLinkInfo
        return ""
    li = odmik
    velikost_li, glava = struct.unpack_from("<II", podatki, li)
    li_zastavice = struct.unpack_from("<I", podatki, li + 8)[0]
    if not li_zastavice & 0x1:                            # VolumeIDAndLocalBasePath
        return ""
    if glava >= 0x24 and li + 0x24 <= len(podatki):
        unicode_odmik = struct.unpack_from("<I", podatki, li + 0x1C)[0]
        if unicode_odmik:
            konec = podatki.find(b"\x00\x00", li + unicode_odmik)
            while konec != -1 and (konec - (li + unicode_odmik)) % 2:
                konec = podatki.find(b"\x00\x00", konec + 1)
            if konec != -1:
                osnova = podatki[li + unicode_odmik:konec].decode("utf-16-le", "replace")
                pripona = ""
                pripona_odmik = struct.unpack_from("<I", podatki, li + 0x20)[0] if glava >= 0x24 else 0
                if pripona_odmik:
                    k2 = podatki.find(b"\x00\x00", li + pripona_odmik)
                    while k2 != -1 and (k2 - (li + pripona_odmik)) % 2:
                        k2 = podatki.find(b"\x00\x00", k2 + 1)
                    if k2 != -1:
                        pripona = podatki[li + pripona_odmik:k2].decode("utf-16-le", "replace")
                return osnova + pripona
    def ansi(odmik: int) -> str:
        if not odmik or li + odmik >= li + velikost_li:
            return ""
        konec = podatki.find(b"\x00", li + odmik)
        return "" if konec == -1 else podatki[li + odmik:konec].decode("mbcs" if _WIN else "latin-1", "replace")
    # Polna pot = LocalBasePath + CommonPathSuffix.
    return ansi(struct.unpack_from("<I", podatki, li + 0x10)[0]) + ansi(struct.unpack_from("<I", podatki, li + 0x18)[0])


# Znane mape, prestavljene na drug disk (testni PC 26. 10. 2026: vse na D:): bliznjice v Recent iz casa pred premikom
# kazejo na staro pot pod domaco mapo - 207 od 221 bliznjic z manjkajocim ciljem, od tega 67 datotek najdenih na
# novem mestu. Bliznjic brez LinkInfo je bilo 65, vse spletni naslovi (61) ali Nadzorna plosca (4) - ne datoteke.
_PRIVZETE_ZNANE = (("DESKTOP", "Desktop"), ("DOCUMENTS", "Documents"), ("DOWNLOAD", "Downloads"),
                   ("PICTURES", "Pictures"), ("MUSIC", "Music"), ("VIDEOS", "Videos"))


def preslikaj_premaknjeno(pot: str, znane: dict, dom: Optional[str] = None) -> str:
    """Pot pod privzeto znano mapo (~/Documents ...), ki je zdaj drugje, na novo mesto (cista funkcija); sicer pot."""
    dom = dom or os.path.expanduser("~")
    for vrsta, privzeto in _PRIVZETE_ZNANE:
        stara, nova = os.path.join(dom, privzeto), znane.get(vrsta)
        if not nova or os.path.normcase(nova) == os.path.normcase(stara):
            continue
        if os.path.normcase(pot).startswith(os.path.normcase(stara) + os.sep):
            return os.path.join(nova, os.path.relpath(pot, stara))
    return pot


#: Datoteke, ki jih programi sami ustvarijo zraven pravih (zaklep Officea, zacasne) - niso »nedavne datoteke«.
_NI_NEDAVNA = (("~$",), (".tmp", ".crdownload", ".part", ".partial", ".lnk", ".ini", ".db"))
NEDAVNO_DNI = 30
_NEDAVNO_MAP = 400


def _sveze_v_mapah(mape: List[str], od: float, najvec: int) -> List[tuple]:
    """(cas, pot) datotek, spremenjenih po [od], v znanih mapah do dveh ravni globoko (brez skritih)."""
    izid, pregledanih = [], 0
    for koren in mape:
        vrsta = [(koren, 0)]
        while vrsta and pregledanih < _NEDAVNO_MAP:
            mapa, globina = vrsta.pop(0)
            pregledanih += 1
            try:
                with os.scandir(mapa) as vsebina:
                    vnosi = list(vsebina)
            except OSError:
                continue
            for v in vnosi:
                ime = v.name
                if ime.startswith((".",) + _NI_NEDAVNA[0]) or ime.lower().endswith(_NI_NEDAVNA[1]):
                    continue
                try:
                    # Na Windows da scandir stat in atribute brez dodatnega klica (prej 4,4 s za mape na D:).
                    st = v.stat(follow_symlinks=False)
                except OSError:
                    continue
                if getattr(st, "st_file_attributes", 0) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                    continue
                if v.is_dir(follow_symlinks=False):
                    if globina < 2 and ime not in os_datoteke.PRESKOCI:
                        vrsta.append((v.path, globina + 1))
                    continue
                cas = max(st.st_mtime, st.st_ctime)                # ctime: tudi preneseno/premaknjeno s starim datumom
                if cas >= od:
                    izid.append((cas, v.path))
    izid.sort(reverse=True)
    return izid[:najvec]


def sledenje_nedavnim() -> bool:
    """Ali Windows belezi nedavno odprte elemente (Nastavitve > Prilagajanje > Start > »Prikazi nedavno odprte
    elemente«; pravilnik NoRecentDocsHistory). Izklopljeno = mapa Recent ostane prazna ali zastarela."""
    if not _WIN:
        return True
    try:
        import winreg
    except ImportError:
        return True
    for koren, pot, ime, izklop in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "Start_TrackDocs", 0),
                                    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoRecentDocsHistory", 1),
                                    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoRecentDocsHistory", 1)):
        try:
            with winreg.OpenKey(koren, pot) as k:
                if int(winreg.QueryValueEx(k, ime)[0]) == izklop:
                    return False
        except (OSError, ValueError):
            pass
    return True


def nedavne(najvec: int = 24, znane: Optional[dict] = None, recent: Optional[str] = None) -> List[dict]:
    """Nedavne datoteke, najnovejse najprej: odprte (mapa Recent sistema Windows) in nove ali spremenjene v
    uporabnikovih mapah (Namizje, Dokumenti, Prenosi ...). Na testnem PC 26. 10. 2026 Windows v Recent ni zapisal
    nicesar 12 dni, datoteke, ki jih ustvari drug program, pa tja sploh ne pridejo - prej je seznam ostal prazen."""
    mapa = recent or os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Recent")
    try:
        vnosi = [e for e in os.scandir(mapa) if e.name.lower().endswith(".lnk") and e.is_file()]
    except OSError:
        vnosi = []
    vnosi.sort(key=lambda e: -e.stat().st_mtime)
    if znane is None:
        from . import os_backend_win
        znane = os_backend_win.znane_mape()
    kandidati: List[tuple] = []
    for e in vnosi[:200]:
        try:
            with open(e.path, "rb") as f:
                glava = f.read(65536)
        except OSError:
            continue
        pot = cilj_bliznjice(glava)
        if pot:
            kandidati.append((e.stat().st_mtime, preslikaj_premaknjeno(pot, znane)))
    mape = [p for p in dict.fromkeys(znane.values()) if p and os.path.isdir(p)]
    kandidati += _sveze_v_mapah(mape, time.time() - NEDAVNO_DNI * 86400, najvec * 4)
    kandidati.sort(key=lambda k: -k[0])
    izhod, videno = [], set()
    for cas, pot in kandidati:
        if os.path.normcase(pot) in videno or not os.path.isfile(pot):
            continue
        videno.add(os.path.normcase(pot))
        try:
            velikost = os.path.getsize(pot)
        except OSError:
            velikost = 0
        ime = os.path.basename(pot)
        izhod.append({"ime": ime, "pot": pot, "cas": cas, "spremenjeno": cas, "velikost": velikost,
                      "vrsta": os_datoteke.vrsta_datoteke(ime), "mapa": False})
        if len(izhod) >= najvec:
            break
    return izhod
