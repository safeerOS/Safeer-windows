"""Pravi zajem zaslona Windows v H.264 in vnos z druge naprave (TV daljinec, telefon).

Televizor (ZaslonOdjemalec) pricakuje isto kot na Linuxu (core/link_zaslon.py): po glavi JSON
okvirje ``[vrsta 1 B][dolzina 4 B, big-endian][surovi H.264 Annex-B]``. Na Linuxu sliko kodira
ffmpeg; na Windows ga ni, zato kodiramo v procesu s PyAV:

* ``h264_mf`` - kodirnik Windows (Media Foundation): brez dodatnih licenc, strojno, kjer gre;
* ``libx264`` - rezerva, ce Media Foundation na tem racunalniku ne odpre.

Vnos gre z ``SendInput`` (ctypes), z enakimi imeni dogodkov in tipk kot core/link_vnos.py.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from fractions import Fraction
from typing import Iterator, Optional, Tuple

#: Najvecja slika, ki jo posiljamo (kot na Linuxu: 1080p je za namizje dovolj in je hitrejsa).
NAJVEC_SIRINA, NAJVEC_VISINA = 1920, 1080
NAJVEC_PREMIK = 400
NAJVEC_BESEDILA = 200


def kodirnik_na_voljo() -> Optional[str]:
    """Ime H.264 kodirnika, ki ga zna ta racunalnik, ali None (ni PyAV)."""
    try:
        import av  # noqa: F401
    except Exception:
        return None
    try:
        import av
        na_voljo = av.codecs_available
    except Exception:
        return None
    for ime in KODIRNIKI:
        if ime in na_voljo:
            return ime
    return None


#: Vrstni red kodirnikov: najprej strojni kodirnik graficne kartice (NVIDIA, Intel Quick Sync, AMD), nato
#: Media Foundation in programski libx264. Na seznamu PyAV so vsi, odpre pa se le tisti, ki ga kartica ima.
#: Izmerjeno 9. 10. 2026 (i5-4590, HD 4600, 1440x900): h264_qsv 3,6 ms na sliko.
KODIRNIKI = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_mf", "libx264")


def _moznosti(ime: str) -> dict:
    if ime == "libx264":
        return {"preset": "veryfast", "tune": "zerolatency", "profile": "high"}
    if ime == "h264_mf":
        return {"rate_control": "cbr", "scenario": "display_remoting"}
    if ime == "h264_qsv":
        return {"preset": "veryfast", "async_depth": "1", "look_ahead": "0"}
    if ime == "h264_nvenc":
        return {"preset": "p1", "tune": "ll", "zerolatency": "1", "rc": "cbr"}
    if ime == "h264_amf":
        return {"usage": "ultralowlatency", "rc": "cbr"}
    return {}


def dxgi_na_voljo() -> bool:
    """Ali je na tem racunalniku hiter zajem DXGI (Windows in namescena knjiznica dxcam)."""
    if sys.platform != "win32":
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("dxcam") is not None
    except Exception:
        return False


class _DxgiZajem:
    """Zajem prek DXGI Desktop Duplication (knjiznica dxcam): ~2 ms na sliko namesto ~34 ms z GDI.

    DXGI da novo sliko samo, ko se zaslon spremeni; vmes vrnemo zadnjo. Ko je monitor ugasnjen, Windows zaslona ne
    risa in DXGI skoraj ne daje slik (izmerjeno: ~1 na sekundo) - takrat ``slika()`` vrne None in klicatelj vzame GDI.
    """

    #: Brez nove slike DXGI tako dolgo -> morda je monitor ugasnjen: preverimo z GDI.
    TISINA_S = 0.5

    #: Ena kamera DXGI za ves proces. Ustvarjanje in sproscanje vec kamer (dxcam.release) je na Windows povzrocilo
    #: krsitev pomnilnika v comtypes (izmerjeno 9. 10. 2026), zato jo ustvarimo enkrat in je ne sproscamo.
    _kamera_procesa = None
    _zaklep = threading.Lock()

    def __init__(self):
        import dxcam  # noqa: F401  (ni namesceno -> ImportError, klicatelj ostane pri GDI)
        with _DxgiZajem._zaklep:
            if _DxgiZajem._kamera_procesa is None:
                _DxgiZajem._kamera_procesa = dxcam.create(output_color="BGRA")
        self._kamera = _DxgiZajem._kamera_procesa
        if self._kamera is None:
            raise RuntimeError("DXGI ni na voljo")
        self._zadnja = None
        self._zadnjic = 0.0

    def slika(self):
        with _DxgiZajem._zaklep:
            nova = self._kamera.grab()
        zdaj = time.monotonic()
        if nova is not None:
            self._zadnja, self._zadnjic = nova, zdaj
            return nova
        if self._zadnja is None or zdaj - self._zadnjic > self.TISINA_S:
            return None
        return self._zadnja

    def zapri(self) -> None:
        """Kamera ostane procesu (glej _kamera_procesa); seja samo pozabi svojo zadnjo sliko."""
        self._zadnja = None


def _velikost_zaslona() -> Tuple[int, int]:
    if sys.platform != "win32":
        return 1920, 1080
    u = ctypes.windll.user32
    return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))


def velikost_slike(izvor: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
    """Velikost poslane slike: izvor, pomanjsan v 1920x1080, sodi mere (H.264 zahteva sode)."""
    sw, sv = izvor or _velikost_zaslona()
    faktor = min(1.0, NAJVEC_SIRINA / max(1, sw), NAJVEC_VISINA / max(1, sv))
    w, h = int(sw * faktor) // 2 * 2, int(sv * faktor) // 2 * 2
    return max(2, w), max(2, h)


class H264Zajem:
    """Zajema glavni zaslon in vraca kose H.264 (Annex-B), primerne za televizor."""

    def __init__(self, fps: int = 30, bitrate: int = 6_000_000, kodirnik: Optional[str] = None):
        import av
        from PIL import ImageGrab  # noqa: F401  (preverimo zgodaj, da napaka pride ob zagonu)

        self._av = av
        self.izvor = _velikost_zaslona()
        self.sirina, self.visina = velikost_slike(self.izvor)
        self.fps = max(5, min(60, int(fps)))
        kandidati = [kodirnik] if kodirnik else [k for k in KODIRNIKI if k in getattr(av, "codecs_available", ())]
        if not kandidati:
            raise RuntimeError("Na tem racunalniku ni kodirnika H.264")
        napaka = None
        self._c = None
        for ime in kandidati:
            try:
                self._c = self._odpri(ime, bitrate)
                self.kodirnik = ime
                break
            except Exception as e:  # kodirnik je v PyAV, kartica pa ga nima
                napaka = e
        if self._c is None:
            raise RuntimeError(f"Kodirnika H.264 ni mogoce odpreti: {napaka}")
        self._st = 0
        try:
            self._dxgi: Optional[_DxgiZajem] = _DxgiZajem() if sys.platform == "win32" else None
        except Exception:
            self._dxgi = None
        print(f"[Zaslon] zajem {'DXGI' if self._dxgi else 'GDI'}, kodirnik {self.kodirnik}, {self.sirina}x{self.visina} @ {self.fps}")

    def _odpri(self, ime: str, bitrate: int):
        c = self._av.CodecContext.create(ime, "w")
        c.width, c.height = self.sirina, self.visina
        c.pix_fmt = "yuv420p" if ime == "libx264" else "nv12"
        c.framerate = Fraction(self.fps, 1)
        c.time_base = Fraction(1, self.fps)
        # Brez B-slik in z rednim kljucnim okvirjem: televizor se prikljuci hitro, izguba se popravi v 1 s.
        c.gop_size = self.fps
        c.max_b_frames = 0
        c.bit_rate = int(bitrate)
        c.options = _moznosti(ime)
        c.open()
        return c

    def _slika(self):
        if self._dxgi is not None:
            surova = self._dxgi.slika()
            if surova is not None:
                okvir = self._av.VideoFrame.from_ndarray(surova, format="bgra").reformat(
                    width=self.sirina, height=self.visina, format=self._c.pix_fmt)
                okvir.pts = self._st
                self._st += 1
                return okvir
        from PIL import ImageGrab
        slika = ImageGrab.grab()
        if slika.size != (self.sirina, self.visina):
            slika = slika.resize((self.sirina, self.visina))
        okvir = self._av.VideoFrame.from_image(slika).reformat(format=self._c.pix_fmt)
        okvir.pts = self._st
        self._st += 1
        return okvir

    def okvirji(self, tece) -> Iterator[bytes]:
        """Kosi H.264, dokler ``tece()`` vraca True. Hitrost omeji fps (zajem je lahko pocasnejsi)."""
        interval = 1.0 / self.fps
        prvi = True
        while tece():
            zacetek = time.monotonic()
            for paket in self._c.encode(self._slika()):
                podatki = bytes(paket)
                if prvi:
                    prvi = False
                    podatki = self._z_nastavitvami(podatki)
                if podatki:
                    yield podatki
            pocakaj = interval - (time.monotonic() - zacetek)
            if pocakaj > 0:
                time.sleep(pocakaj)

    def _z_nastavitvami(self, podatki: bytes) -> bytes:
        """Televizor mora dobiti SPS/PPS pred prvo sliko; nekateri kodirniki jih dajo le v extradata."""
        if b"\x00\x00\x00\x01\x67" in podatki[:256] or b"\x00\x00\x01\x67" in podatki[:256]:
            return podatki
        dodatno = bytes(self._c.extradata or b"")
        if dodatno.startswith(b"\x00\x00\x00\x01") or dodatno.startswith(b"\x00\x00\x01"):
            return dodatno + podatki
        return podatki

    def zapri(self) -> None:
        try:
            for _ in self._c.encode(None):
                pass
        except Exception:
            pass
        if getattr(self, "_dxgi", None) is not None:
            self._dxgi.zapri()


# ---------------------------------------------------------------------------------------- vnos

_VK = {
    "gor": 0x26, "dol": 0x28, "levo": 0x25, "desno": 0x27, "ok": 0x0D, "vnasalka": 0x0D,
    "nazaj": 0x1B, "ubezna": 0x1B, "domov": 0x5B, "meni": 0x5D, "presledek": 0x20,
    "vracalka": 0x08, "brisalka": 0x2E, "tabulator": 0x09, "stran_gor": 0x21, "stran_dol": 0x22,
    "zacetek": 0x24, "konec": 0x23, "predvajaj": 0xB3, "ustavi": 0xB2, "naprej": 0xB0,
    "prejsnja": 0xB1, "glasneje": 0xAF, "tiseje": 0xAE, "utisaj": 0xAD, "celozaslonsko": 0x7A,
    "osvezi": 0x74, "iskanje_naprej": 0x72,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    "krmilka": 0x11, "alt": 0x12, "dvigalka": 0x10, "sistemska": 0x5B,
    **{chr(k): k - 32 for k in range(ord("a"), ord("z") + 1)},
    **{str(k): 0x30 + k for k in range(10)},
}
_KOMBINACIJE = {
    "isci": (0x11, 0x46), "kopiraj": (0x11, 0x43), "prilepi": (0x11, 0x56), "izrezi": (0x11, 0x58),
    "razveljavi": (0x11, 0x5A), "zapri_okno": (0x11, 0x57), "preklopi_okno": (0x12, 0x09),
    "brskalnik_nazaj": (0x12, 0x25), "brskalnik_naprej": (0x12, 0x27), "nov_zavihek": (0x11, 0x54),
    "shrani": (0x11, 0x53), "izberi_vse": (0x11, 0x41), "ponovi": (0x11, 0x59), "krepko": (0x11, 0x42),
    "lezece": (0x11, 0x49), "podcrtano": (0x11, 0x55), "natisni": (0x11, 0x50),
    "shrani_kot": (0x11, 0x10, 0x53),
}
_RAZSIRJENE = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E, 0x5B, 0x5D}

MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004
_GUMBI = {
    "levi": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "desni": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "srednji": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class WindowsVnos:
    """Dogodki televizorja (core/link_vnos.py oblika) na pravi miski in tipkovnici Windows."""

    def __init__(self, izvor: Tuple[int, int], slika: Tuple[int, int]):
        self.izvor = izvor
        self.slika = slika
        self.mozno = sys.platform == "win32"
        self._drzan: Optional[str] = None
        self._drzane_tipke: set[int] = set()

    # -- nizka raven
    def _miska(self, zastavice: int, dx: int = 0, dy: int = 0, podatki: int = 0) -> bool:
        ctypes.windll.user32.mouse_event(zastavice, dx, dy, podatki, 0)
        return True

    def _tipka_vk(self, vk: int, gor: bool) -> None:
        zastavice = (KEYEVENTF_KEYUP if gor else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _RAZSIRJENE else 0)
        ctypes.windll.user32.keybd_event(vk, 0, zastavice, 0)

    def _pritisni(self, *vk: int) -> bool:
        for k in vk:
            self._tipka_vk(k, False)
        for k in reversed(vk):
            self._tipka_vk(k, True)
        return True

    # -- dogodki
    def izvedi(self, dogodek: dict) -> bool:
        if not self.mozno or not isinstance(dogodek, dict):
            return False
        vrsta = str(dogodek.get("vrsta") or "")
        try:
            if vrsta == "tipka":
                oznaka = str(dogodek.get("tipka") or "").strip().lower()
                if oznaka in _KOMBINACIJE:
                    return self._pritisni(*_KOMBINACIJE[oznaka])
                vk = _VK.get(oznaka)
                return self._pritisni(vk) if vk else False
            if vrsta in ("tipka_dol", "tipka_gor"):
                vk = _VK.get(str(dogodek.get("tipka") or "").strip().lower())
                if not vk:
                    return False
                self._tipka_vk(vk, vrsta == "tipka_gor")
                if vrsta == "tipka_gor":
                    self._drzane_tipke.discard(vk)
                else:
                    self._drzane_tipke.add(vk)
                return True
            if vrsta == "besedilo":
                return self._besedilo(str(dogodek.get("besedilo") or ""))
            if vrsta == "premik":
                dx = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dogodek.get("dx") or 0)))
                dy = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dogodek.get("dy") or 0)))
                return self._miska(MOUSEEVENTF_MOVE, dx, dy) if (dx or dy) else False
            if vrsta == "tocka":
                return self._tocka(float(dogodek.get("x")), float(dogodek.get("y")))
            if vrsta == "klik":
                dol, gor = _GUMBI.get(str(dogodek.get("gumb") or "levi").strip().lower(), _GUMBI["levi"])
                for _ in range(2 if dogodek.get("dvojni") else 1):
                    self._miska(dol)
                    self._miska(gor)
                return True
            if vrsta == "gumb":
                par = _GUMBI.get(str(dogodek.get("gumb") or "levi").strip().lower())
                if not par:
                    return False
                self._drzan = str(dogodek.get("gumb") or "levi").strip().lower() if dogodek.get("dol") else None
                return self._miska(par[0] if dogodek.get("dol") else par[1])
            if vrsta == "kolesce":
                smer = str(dogodek.get("smer") or "").strip().lower()
                if smer not in ("gor", "dol"):
                    return False
                n = max(1, min(10, int(dogodek.get("koliko") or 1)))
                return self._miska(MOUSEEVENTF_WHEEL, 0, 0, (120 if smer == "gor" else -120) * n)
        except (TypeError, ValueError, OSError, AttributeError):
            return False
        return False

    def _tocka(self, x: float, y: float) -> bool:
        """Tocka iz slike (kot jo vidi televizor/tablica) na tocko zaslona, absolutno 0..65535."""
        sw, sv = max(1, self.slika[0]), max(1, self.slika[1])
        x = min(max(x, 0.0), sw - 1)
        y = min(max(y, 0.0), sv - 1)
        ax = int(x * 65535 / (sw - 1 if sw > 1 else 1))
        ay = int(y * 65535 / (sv - 1 if sv > 1 else 1))
        return self._miska(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, ax, ay)

    def _besedilo(self, besedilo: str) -> bool:
        besedilo = besedilo[:NAJVEC_BESEDILA]
        if not besedilo or any(ord(z) < 32 for z in besedilo):
            return False
        for z in besedilo:
            self._unicode(ord(z))
        return True

    def _unicode(self, koda: int) -> None:
        # keybd_event ne zna KEYEVENTF_UNICODE; SendInput z INPUT_KEYBOARD zna.
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

        for zastavice in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            vhod = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, koda, zastavice, 0, 0)))
            ctypes.windll.user32.SendInput(1, ctypes.byref(vhod), ctypes.sizeof(INPUT))

    def sprosti_vse(self) -> None:
        """Povezava je padla: spustimo vse drzane tipke in miskin gumb."""
        if self._drzan and self._drzan in _GUMBI:
            try:
                self._miska(_GUMBI[self._drzan][1])
            except Exception:
                pass
        self._drzan = None
        for vk in list(self._drzane_tipke):
            try:
                self._tipka_vk(vk, True)
            except Exception:
                pass
        self._drzane_tipke.clear()
