"""Pomanjsane slicice slik in videov za Datoteke na namizju Safeer OS (Windows): ta racunalnik in naprave v Linku.

Lastnik, 25. 10. 2026: »pomanjsanih slicic nisi vgradil« - in naj delajo tudi za naprave, povezane prek Safeer Linka.

- Ta racunalnik: slika s Pillow (JPEG se dekodira ze pomanjsan - draft, obrnjena po EXIF), sicer s Qt QImageReader;
  video z nasim ffmpeg (%LOCALAPPDATA%\\SafeerOS\\ffmpeg, ffmpeg_win.pot_ffmpeg), slika s tretje sekunde.
- Naprava v Linku: `GET <base_url>/thumb/<id>` z zetonom v glavi X-Safeer-Token in pripetim potrdilom (odtis `fp`) -
  isti streznik in isti zeton, kot ju naprava da v odgovoru na `files.list` (Android DatotekeStreznik, Linux in
  Windows core/link_datoteke). Naprava sama preveri, ali ta racunalnik sme do njenih datotek (krog, zmoznost »files«);
  mi ne vidimo nicesar, cesar nam ni dala.
- Predpomnilnik na disku: %LOCALAPPDATA%\\SafeerOS\\slicice, kljuc = izvor (»ta« ali id naprave) + pot/oznaka + cas
  spremembe + velikost. Ko datoteka spremeni cas ali velikost, je kljuc drug in slicica nova. Najvec NAJVEC_BAJTOV:
  najdlje neuporabljene gredo prve.
- Vse delo je v nitih v ozadju (najvec DELAVCEV hkrati); vmesnik dobi vsako slicico sproti, ko je narejena.
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import Callable, Iterable, List, Optional

ROB = 256                          # daljsa stranica slicice v tockah (mreza do 128 tock na zaslonu z 2x gostoto)
KAKOVOST = 82
NAJVEC_BAJTOV = 200 * 1024 * 1024  # predpomnilnik na disku
NAJVEC_SLIKE_B = 80 * 1024 * 1024  # vecjih slik ne dekodiramo (slicice ni, vmesnik pokaze ikono)
NAJVEC_PIK = 50_000_000            # kot Linux core/link_datoteke: ~200 MB RGBA po pomanjsanju JPEG
NAJVEC_ODGOVORA_B = 2 * 1024 * 1024  # slicica z naprave (Android: 256 px JPEG, nekaj deset kB)
NAJVEC_NA_ZAHTEVO = 600            # toliko slicic vmesnik zahteva naenkrat (stran mape ima najvec 500 vnosov)
DELAVCEV = 2                       # hkrati: mapa s sto videi ne zasede vseh jeder in diska
ROK_VIDEA_S = 15
ROK_NAPRAVE_S = 8.0

KONCNICE_SLIK = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif")
KONCNICE_VIDEOV = (".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".flv")


# ------------------------------------------------------------------ ciste funkcije (preizkusi: windows/tests/test_slicice_win.py)
def vrsta_po_imenu(ime: str) -> str:
    """»slika«, »video« ali '' po koncnici imena."""
    k = os.path.splitext(str(ime or ""))[1].lower()
    return "slika" if k in KONCNICE_SLIK else "video" if k in KONCNICE_VIDEOV else ""


def vrsta_vnosa(e: dict) -> str:
    """Vrsta vnosa iz vmesnika: lokalni vnos (vrsta »slika«/»video«), vnos naprave (type »image«/»video«, mime) ali ime."""
    if not isinstance(e, dict) or e.get("mapa"):
        return ""
    v = str(e.get("vrsta") or e.get("type") or "").lower()
    if v in ("slika", "image"):
        return "slika"
    if v == "video":
        return "video"
    mime = str(e.get("mime") or "").lower()
    if mime.startswith("image/"):
        return "slika"
    if mime.startswith("video/"):
        return "video"
    return vrsta_po_imenu(str(e.get("ime") or e.get("name") or ""))


def kljuc(izvor: str, oznaka: str, spremenjeno: float, velikost: int, rob: int = ROB) -> str:
    """Ime datoteke v predpomnilniku: izvor (»ta« ali id naprave), pot ali oznaka, cas spremembe, velikost, rob.
    Spremenjena datoteka (cas ali velikost) da nov kljuc - stara slicica se nikoli ne pokaze za novo vsebino."""
    try:
        cas = int(float(spremenjeno or 0))
    except (TypeError, ValueError):
        cas = 0
    try:
        vel = int(velikost or 0)
    except (TypeError, ValueError):
        vel = 0
    niz = "\x1f".join((str(izvor or "ta"), str(oznaka or ""), str(cas), str(vel), str(int(rob))))
    return hashlib.sha256(niz.encode("utf-8", "surrogatepass")).hexdigest()[:40] + ".jpg"


def za_brisanje(datoteke: Iterable[tuple], najvec_bajtov: int) -> List[str]:
    """[(pot, velikost, cas_rabe)] -> poti, ki jih pobrisemo, da ostane najvec `najvec_bajtov` (najstarejsa raba prva)."""
    seznam = sorted(datoteke, key=lambda d: d[2])
    skupaj = sum(int(d[1]) for d in seznam)
    izid = []
    for pot, vel, _cas in seznam:
        if skupaj <= najvec_bajtov:
            break
        izid.append(pot)
        skupaj -= int(vel)
    return izid


def varen_streznik(streznik) -> Optional[dict]:
    """Opis streznika naprave iz `files.list` ({base_url, fp, token}) ali None, ce ni uporaben. Samo https z odtisom
    potrdila (pripeto) - slicic po nesifrirani povezavi ali brez preverjenega potrdila ne jemljemo."""
    if not isinstance(streznik, dict):
        return None
    base = str(streznik.get("base_url") or "").rstrip("/")
    u = urllib.parse.urlparse(base)
    fp = str(streznik.get("fp") or "")
    if u.scheme != "https" or not u.hostname or not fp or u.path not in ("", "/"):
        return None
    return {"base_url": base, "fp": fp, "token": str(streznik.get("token") or "")}


# ------------------------------------------------------------------ predpomnilnik na disku
def mapa() -> str:
    m = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "slicice")
    os.makedirs(m, exist_ok=True)
    return m


def _iz_predpomnilnika(ime: str) -> str:
    pot = os.path.join(mapa(), ime)
    if os.path.isfile(pot):
        try:
            os.utime(pot, None)            # raba: najdlje neuporabljene gredo ob ciscenju prve
        except OSError:
            pass
        return pot
    return ""


def _shrani(ime: str, podatki: bytes) -> str:
    pot = os.path.join(mapa(), ime)
    zacasna = pot + ".%d.tmp" % threading.get_ident()
    try:
        with open(zacasna, "wb") as f:
            f.write(podatki)
        os.replace(zacasna, pot)
    except OSError:
        try:
            os.remove(zacasna)
        except OSError:
            pass
        return ""
    _pocisti_obcasno()
    return pot


_zadnje_ciscenje = [0.0]


def _pocisti_obcasno() -> None:
    if time.monotonic() - _zadnje_ciscenje[0] < 60:
        return
    _zadnje_ciscenje[0] = time.monotonic()
    pocisti()


def pocisti(najvec_bajtov: int = NAJVEC_BAJTOV) -> int:
    """Predpomnilnik na najvec `najvec_bajtov`; vrne stevilo odstranjenih slicic (samo nase .jpg v nasi mapi)."""
    m = mapa()
    datoteke = []
    try:
        for ime in os.listdir(m):
            if not ime.endswith(".jpg"):
                continue
            p = os.path.join(m, ime)
            try:
                s = os.stat(p)
                datoteke.append((p, s.st_size, s.st_mtime))
            except OSError:
                continue
    except OSError:
        return 0
    n = 0
    for p in za_brisanje(datoteke, najvec_bajtov):
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    # Zacasne datoteke (.jpg.<nit>.tmp), ki so ostale po sesutju, starejse od ure (pregled N6).
    try:
        meja = time.time() - 3600
        for ime in os.listdir(m):
            p = os.path.join(m, ime)
            if ime.endswith(".tmp") and os.path.getmtime(p) < meja:
                os.remove(p)
                n += 1
    except OSError:
        pass
    return n


# ------------------------------------------------------------------ izdelava (ta racunalnik)
def _slika_pillow(pot: str, rob: int) -> Optional[bytes]:
    try:
        from PIL import Image, ImageOps
    except Exception:  # noqa: BLE001 - brez Pillow poskusi Qt
        return None
    try:
        with Image.open(pot) as im:
            try:
                im.draft("RGB", (rob * 2, rob * 2))
            except Exception:  # noqa: BLE001
                pass
            if im.size[0] * im.size[1] > NAJVEC_PIK:
                return b""
            im.thumbnail((rob, rob))                 # najprej pomanjsaj, nato obrni (brez kopije v polni velikosti)
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            izhod = io.BytesIO()
            im.save(izhod, "JPEG", quality=KAKOVOST)
            return izhod.getvalue()
    except Exception:  # noqa: BLE001 - pokvarjena ali nepodprta slika (HEIC brez vticnika): poskusi Qt
        return None


def _slika_qt(pot: str, rob: int) -> Optional[bytes]:
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImageReader
    except ImportError:
        return None
    bralnik = QImageReader(pot)
    bralnik.setAutoTransform(True)
    v = bralnik.size()
    if v.isValid():
        if v.width() * v.height() > NAJVEC_PIK:
            return None
        if max(v.width(), v.height()) > rob:
            bralnik.setScaledSize(v.scaled(rob, rob, Qt.AspectRatioMode.KeepAspectRatio))
    slika = bralnik.read()
    if slika.isNull():
        return None
    podatki = QByteArray()
    medpomnilnik = QBuffer(podatki)
    medpomnilnik.open(QIODevice.OpenModeFlag.WriteOnly)
    slika.save(medpomnilnik, "JPEG", KAKOVOST)
    return bytes(podatki)


def _pot_ffmpeg() -> str:
    try:
        from . import ffmpeg_win
        p = ffmpeg_win.pot_ffmpeg()
        if p:
            return p
    except Exception:  # noqa: BLE001
        pass
    if sys.platform != "win32":                      # preizkusi na Linuxu
        import shutil
        return shutil.which("ffmpeg") or ""
    return ""


def slika_qt(pot: str, rob: int) -> Optional[bytes]:
    """Slicica slike s Qt (rezerva brez Pillow - tudi za strežnik core/link_datoteke.REZERVA_SLIKE v paketu Windows,
    ki je zgrajen brez PIL)."""
    try:
        return _slika_qt(pot, rob)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ ffmpeg v »poslu« (Job Object)
_posel = [None]
_posel_kljuc = threading.Lock()


def _posel_windows():
    """En Job Object z JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE za vse procese ffmpeg za slicice: ko se Safeer OS konca (tudi
    sesuje), Windows zapre rocaj in ubije vse njegove ffmpeg - ne ostanejo v pomnilniku (pregled 25. 10. 2026, S6).
    Samo ffmpeg, ne cel Safeer OS: programi, ki jih uporabnik zazene z namizja, morajo zivo ostati."""
    with _posel_kljuc:
        if _posel[0] is not None:
            return _posel[0] or None
        try:
            import ctypes
            from ctypes import wintypes

            class _Osnovno(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                           "OtherOperationCount", "ReadTransferCount",
                                                           "WriteTransferCount", "OtherTransferCount")]

            class _Razsirjeno(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Osnovno), ("IoInfo", _Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            k32 = ctypes.windll.kernel32
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            posel = k32.CreateJobObjectW(None, None)
            info = _Razsirjeno()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not posel or not k32.SetInformationJobObject(wintypes.HANDLE(posel), 9, ctypes.byref(info),
                                                            ctypes.sizeof(info)):
                _posel[0] = 0
                return None
            _posel[0] = posel                                        # rocaj drzimo do konca procesa
            return posel
        except Exception:  # noqa: BLE001
            _posel[0] = 0
            return None


def zazeni_v_poslu(ukaz: list, rok_s: float):
    """(izhodna koda, stdout) procesa; na Windows v Job Object (ubit ob koncu Safeer OS), ob roku ubit."""
    zastavice = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW: brez cmd okna
    p = subprocess.Popen(ukaz, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         creationflags=zastavice)
    if sys.platform == "win32":
        posel = _posel_windows()
        if posel:
            try:
                import ctypes
                from ctypes import wintypes
                ctypes.windll.kernel32.AssignProcessToJobObject(wintypes.HANDLE(posel), wintypes.HANDLE(int(p._handle)))
            except Exception:  # noqa: BLE001
                pass
    try:
        izhod, _ = p.communicate(timeout=rok_s)
        return p.returncode, izhod
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            p.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            pass
        return -1, b""


def _video(pot: str, rob: int) -> Optional[bytes]:
    ffmpeg = _pot_ffmpeg()
    if not ffmpeg:
        return None
    from core import link_datoteke
    for zamik in ("3", "0"):                         # zacetek je pogosto crn; kratek posnetek da prvo sliko
        try:
            koda, izhod = zazeni_v_poslu(link_datoteke.ukaz_slicice_videa(ffmpeg, pot, zamik, rob), ROK_VIDEA_S)
        except Exception:  # noqa: BLE001 - ffmpeg ni mogoce zagnati
            return None
        if koda == 0 and len(izhod or b"") > 200:
            return izhod
    return None


#: Datoteke (kljuc predpomnilnika), za katere slicice v tej seji ni bilo mogoce narediti: ne poskusamo znova (S6).
_ni_slicice: set = set()
NAJVEC_NI_SLICICE = 5000


def _zapomni_neuspeh(ime: str) -> None:
    if len(_ni_slicice) > NAJVEC_NI_SLICICE:
        _ni_slicice.clear()
    _ni_slicice.add(ime)


def naredi_lokalno(pot: str, rob: int = ROB) -> str:
    """Pot do slicice datoteke na tem racunalniku (iz predpomnilnika ali narejena zdaj) ali '' (slicice ni)."""
    try:
        s = os.stat(pot)
    except OSError:
        return ""
    vrsta = vrsta_po_imenu(pot)
    if not vrsta:
        return ""
    ime = kljuc("ta", os.path.normcase(os.path.abspath(pot)), s.st_mtime, s.st_size, rob)
    znana = _iz_predpomnilnika(ime)
    if znana:
        return znana
    if ime in _ni_slicice:
        return ""
    if vrsta == "slika":
        if s.st_size > NAJVEC_SLIKE_B:
            return ""
        podatki = _slika_pillow(pot, rob)
        if podatki is None:
            podatki = _slika_qt(pot, rob)
    else:
        podatki = _video(pot, rob)
    if not podatki:
        _zapomni_neuspeh(ime)
        return ""
    return _shrani(ime, podatki)


# ------------------------------------------------------------------ naprava v Linku
#: Naslov, ki ga Android da, kadar nima domacega omrezja (DatotekeStreznik.NASLOV_BREZ_OMREZJA, RFC 5737): tam ni nikogar.
NASLOV_BREZ_OMREZJA = "192.0.2.1"
#: Streznik, ki se ni odzval: toliko sekund ga ne klicemo vec (sicer vsaka slicica caka ROK_NAPRAVE_S).
PREMOR_MRTVEGA_S = 60.0
_mrtvi: dict = {}


def _prenesi_z_naprave(streznik: dict, oznaka: str) -> Optional[bytes]:
    from core import link_tls
    u = urllib.parse.urlparse(streznik["base_url"])
    if u.hostname == NASLOV_BREZ_OMREZJA or time.monotonic() < _mrtvi.get(streznik["base_url"], 0.0):
        return None
    povezava = None
    try:
        povezava = link_tls._PripetaHttps(u.hostname, u.port or 443, streznik["fp"], timeout=ROK_NAPRAVE_S)
        glave = {"X-Safeer-Token": streznik["token"]} if streznik.get("token") else {}
        povezava.request("GET", "/thumb/" + urllib.parse.quote(oznaka, safe=""), headers=glave)
        odgovor = povezava.getresponse()
        if odgovor.status == 404:
            return b""                               # naprava slicice nima: v tej seji ne sprasujemo znova
        if odgovor.status != 200:
            return None
        if "image/" not in str(odgovor.getheader("Content-Type") or "image/jpeg"):
            return None
        telo = odgovor.read(NAJVEC_ODGOVORA_B + 1)
        return telo if 0 < len(telo) <= NAJVEC_ODGOVORA_B else None
    except OSError:                                  # ni povezave (tudi rok): streznik za nekaj casa izpustimo
        _mrtvi[streznik["base_url"]] = time.monotonic() + PREMOR_MRTVEGA_S
        return None
    except Exception:  # noqa: BLE001 - naprava zavrne potrdilo ali odgovor ni slika: ikona
        return None
    finally:
        if povezava is not None:
            try:
                povezava.close()
            except Exception:  # noqa: BLE001
                pass


def naredi_z_naprave(id_naprave: str, oznaka: str, spremenjeno: float, velikost: int, streznik) -> str:
    """Slicica datoteke naprave v Linku (iz predpomnilnika ali z naprave) ali ''."""
    s = varen_streznik(streznik)
    if not id_naprave or not oznaka or s is None:
        return ""
    ime = kljuc(id_naprave, oznaka, spremenjeno, velikost)
    znana = _iz_predpomnilnika(ime)
    if znana:
        return znana
    if ime in _ni_slicice:
        return ""
    podatki = _prenesi_z_naprave(s, oznaka)
    if podatki == b"":
        _zapomni_neuspeh(ime)
    return _shrani(ime, podatki) if podatki else ""


# ------------------------------------------------------------------ vrsta del v ozadju
class Slicice:
    """Zahteve vmesnika: vsaka nova zahteva istega okna (nova mapa) preklice se ne zacete slicice prejsnje.

    Delavci so niti »daemon«: ob zaprtju Safeer OS ne cakamo na ffmpeg ali napravo (zapiranje ostane tekoce)."""

    def __init__(self, ob_slicici: Callable[[dict], None], delavcev: int = DELAVCEV) -> None:
        import queue
        self._ob_slicici = ob_slicici
        self._vrsta: "queue.Queue" = queue.Queue()
        self._generacija = 0
        self._kljuc = threading.Lock()
        self._ustavljeno = False
        for i in range(max(1, delavcev)):
            threading.Thread(target=self._delavec, name="safeer-slicice-%d" % i, daemon=True).start()

    def zahtevaj(self, izvor: str, elementi: list, streznik=None, nadaljuj: bool = False) -> dict:
        """Takoj vrne slicice, ki so ze v predpomnilniku ({id: pot}); ostale naredi v ozadju in vsako sporoci
        z ob_slicici({"izvor", "id", "pot", "generacija"}). `izvor` je »ta« ali id naprave. `nadaljuj`: isti pogled
        (»Nalozi vec«) - prejsnje zahteve ne preklice."""
        with self._kljuc:
            if not nadaljuj:
                self._generacija += 1
            generacija = self._generacija
        takoj, delo = {}, []
        for e in list(elementi or [])[:NAJVEC_NA_ZAHTEVO]:
            if not isinstance(e, dict) or not vrsta_vnosa(e):
                continue
            ident = str(e.get("id") or e.get("pot") or "")
            if not ident:
                continue
            spremenjeno = e.get("spremenjeno") or 0
            velikost = e.get("velikost") or 0
            if izvor == "ta":
                try:
                    s = os.stat(ident)
                    ime = kljuc("ta", os.path.normcase(os.path.abspath(ident)), s.st_mtime, s.st_size)
                except OSError:
                    continue
            else:
                ime = kljuc(izvor, ident, spremenjeno, velikost)
            znana = _iz_predpomnilnika(ime)
            if znana:
                takoj[ident] = znana
            else:
                delo.append((ident, spremenjeno, velikost))
        for ident, spremenjeno, velikost in delo:
            self._vrsta.put((generacija, izvor, ident, spremenjeno, velikost, streznik))
        return {"generacija": generacija, "slicice": takoj, "v_delu": len(delo)}

    def _delavec(self) -> None:
        while not self._ustavljeno:
            naloga = self._vrsta.get()
            if naloga is None:
                return
            self._naredi(*naloga)

    def _naredi(self, generacija: int, izvor: str, ident: str, spremenjeno, velikost, streznik) -> None:
        if generacija != self._generacija or self._ustavljeno:
            return                                   # uporabnik je ze drugje: ne delamo zaman
        try:
            pot = naredi_lokalno(ident) if izvor == "ta" else naredi_z_naprave(izvor, ident, spremenjeno, velikost, streznik)
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerOS slicice] {e}", flush=True)
            pot = ""
        if pot and generacija == self._generacija:
            try:
                self._ob_slicici({"izvor": izvor, "id": ident, "pot": pot, "generacija": generacija})
            except Exception:  # noqa: BLE001
                pass

    def ustavi(self) -> None:
        self._ustavljeno = True
        self._generacija += 1
        for _ in range(DELAVCEV * 2):
            self._vrsta.put(None)
