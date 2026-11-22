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
import math
import sys
import threading
import time
from fractions import Fraction
from typing import Iterator, Optional, Tuple

#: Nespremenjen zaslon posljemo znova po tem casu. Redni ritem (vsak interval) je odziv miske poslabsal s 34 na 51 ms
#: (ponovljene slike zasedejo prostor, ko pride sprememba); 0,5 s pa je na starejsih Androidih (Safeer OS do 0.5.74)
#: zadrzalo zadnjo spremembo, ker njihov sprejemnik da sliko dekoderju sele ob naslednji. Novejsi sprejemnik
#: (glava "au") ne caka nic. Izmerjeno 9. 10. 2026.
POLNITEV_S = 0.1

#: Najvecja slika, ki jo posiljamo (kot na Linuxu: 1080p je za namizje dovolj in je hitrejsa).
NAJVEC_SIRINA, NAJVEC_VISINA = 1920, 1080
NAJVEC_PREMIK = 400
NAJVEC_BESEDILA = 200


def ura_ms() -> float:
    """Skupna ura zigov zajema za sliko in zvok: monotona ura procesa v ms (ista nit-varna ura za oba vira)."""
    return time.monotonic() * 1000.0


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


#: Moznosti, s katerimi kodirnik sliko z oznako I (pict_type) naredi kot IDR in ne le kot vmesno I-sliko.
#: libx264 to naredi sam (zaprta skupina slik); h264_mf in h264_amf takih moznosti nimata (NEPREVERJENO,
#: zato izid vedno preverimo v toku, glej H264Zajem._je_idr).
_MOZNOSTI_IDR = {"h264_nvenc": {"forced-idr": "1"}, "h264_qsv": {"forced_idr": "1"},
                 # HEVC: isti imeni moznosti kot pri H.264 istega proizvajalca (NEPREVERJENO na testnem PC, ukaz W3).
                 "hevc_nvenc": {"forced-idr": "1"}, "hevc_qsv": {"forced_idr": "1"}}

#: Strojni kodirniki HEVC (H.265) v PyAV na Windows, v istem vrstnem redu kot za H.264. Programskega libx265
#: in hevc_mf namenoma ni: hitrost libx265 ni izmerjena, hevc_mf pa potrebuje razsiritev HEVC iz trgovine.
KODIRNIKI_HEVC = ("hevc_nvenc", "hevc_qsv", "hevc_amf")
#: Najvecja slika s HEVC (4K); vec kot 1920x1080 samo s HEVC in samo ob izjavi televizorja.
NAJVEC_HEVC = (3840, 2160)

#: Ce kodirnik izsiljene slike v tem stevilu paketov ne vrne kot IDR, ga zamenjamo z novim kontekstom
#: (nov kontekst vedno zacne s SPS, PPS in IDR - enako kot nov ffmpeg na Linuxu, a brez procesa).
KLJUCNI_PAKETOV = 3

#: Najvec zigov, ki cakajo na paket kodirnika. Kodirnik, ki ne vraca pts, jih nikoli ne pobere: nad mejo
#: zavrzemo najstarejse (600 je 10 s pri 60 slikah/s, dalec nad zakasnitvijo kateregakoli kodirnika).
NAJVEC_ZIGOV = 600


def _moznosti(ime: str) -> dict:
    if ime == "libx264":
        return {"preset": "veryfast", "tune": "zerolatency", "profile": "high"}
    if ime == "hevc_nvenc":
        return {"preset": "p1", "tune": "ll", "zerolatency": "1", "rc": "cbr"}
    if ime == "hevc_qsv":
        # look_ahead ima samo h264_qsv: neznane moznosti ne posljemo.
        return {"preset": "veryfast", "async_depth": "1"}
    if ime == "hevc_amf":
        return {"usage": "ultralowlatency", "rc": "cbr"}
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
        return self.slika_nova()[0]

    def slika_nova(self):
        """(slika, ali je nova). Slika je None, ko DXGI predolgo molci (verjetno ugasnjen monitor)."""
        with _DxgiZajem._zaklep:
            nova = self._kamera.grab()
        zdaj = time.monotonic()
        if nova is not None:
            self._zadnja, self._zadnjic = nova, zdaj
            return nova, True
        if self._zadnja is None or zdaj - self._zadnjic > self.TISINA_S:
            return None, False
        return self._zadnja, False

    def zapri(self) -> None:
        """Kamera ostane procesu (glej _kamera_procesa); seja samo pozabi svojo zadnjo sliko."""
        self._zadnja = None


#: Oblike sistemskih kazalcev (IDC_*) -> ime, ki ga naprava zna narisati. Neznan (lasten) kazalec je puscica.
_OBLIKE_KAZALCA = {32512: "puscica", 32513: "besedilo", 32514: "cakanje", 32515: "kriz", 32642: "velikost_nwse",
                   32643: "velikost_nesw", 32644: "velikost_we", 32645: "velikost_ns", 32646: "premik", 32649: "roka",
                   32650: "puscica_cakanje", 32648: "ne"}
_rocaji_oblik: dict = {}


def kazalec() -> Optional[Tuple[int, int, str, bool]]:
    """(x, y, oblika, viden) miskinega kazalca v tockah zaslona ali None (ni Windows / klic ni uspel).

    Zajem DXGI in GDI kazalca NE vsebujeta (preverjeno 9. 10. 2026 na pravem toku): napravi ga povemo posebej, ona ga
    nariše sama - takoj ob premiku, brez cakanja na sliko (zamisel Stream Decka: odziv na napravi, ukaz racunalniku)."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    class _CI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HANDLE),
                    ("ptScreenPos", wintypes.POINT)]

    u = ctypes.windll.user32
    if not _rocaji_oblik:
        u.LoadCursorW.restype = wintypes.HANDLE
        for idc, ime in _OBLIKE_KAZALCA.items():
            r = u.LoadCursorW(None, ctypes.c_void_p(idc))
            if r:
                _rocaji_oblik[int(r)] = ime
    ci = _CI()
    ci.cbSize = ctypes.sizeof(_CI)
    if not u.GetCursorInfo(ctypes.byref(ci)):
        return None
    oblika = _rocaji_oblik.get(int(ci.hCursor or 0), "puscica")
    return int(ci.ptScreenPos.x), int(ci.ptScreenPos.y), oblika, bool(ci.flags & 1) and bool(ci.hCursor)


#: Zvok oddaljenega zaslona: surov PCM 48 kHz stereo s16le v koscih po 10 ms - enako kot Safeer na Linuxu (link_zaslon),
#: zato ga Android predvaja brez sprememb.
ZVOK_HZ, ZVOK_KANALI, ZVOK_KOS = 48000, 2, 480
#: Toliko zaporednih popolnoma tihih koscev se posljemo, nato utihnemo (kot Linux: dolga tisina ne stane nic).
ZVOK_REP_TISINE = 30


def zvok_na_voljo() -> bool:
    """Ali lahko zajamemo zvok, ki ga racunalnik predvaja (WASAPI loopback prek knjiznice soundcard)."""
    if sys.platform != "win32":
        return False
    try:
        import soundcard  # noqa: F401
        return soundcard.default_speaker() is not None
    except Exception:
        return False


#: Ce stetje vzorcev zaostaja za uro branja za vec kot toliko, zig kosa ni znan (None). Poravnamo ga sele, ko
#: zaostanek traja ZVOK_OKNO_MS (vrzel: WASAPI je izpustil podatke ali ura kartice tece pocasneje). Krajsi zaostanek
#: je zastoj bralca (pisanje na TV, razporejevalnik) in zig ne premakne. Enako nacelo kot Linux (link_zaslon).
ZVOK_PORAVNAJ_MS, ZVOK_OKNO_MS = 40.0, 200.0
#: Ce kos premakne zacetek nazaj za vec kot toliko (sunek po zastoju, sunek ob zagonu), zig tega kosa ni znan.
ZVOK_TOCNOST_MS = 1.0


class ZigiZvoka:
    """Zig zajema prvega vzorca kosa iz stetja vzorcev, s spodnjo ovojnico casa branja.

    ``po_branju`` (cas branja minus dolzina kosa) je zgornja meja casa zajema: kos je lahko cakal v medpomnilniku
    WASAPI. Zacetek zato premikamo samo nazaj (spodnja ovojnica); naprej (vrzel) samo po ZVOK_OKNO_MS
    neprekinjenega zaostanka, za najmanjsi zaostanek v oknu. Med zaostankom zig ni znan, ker iz (dolzina, cas)
    vrzeli ne locimo od zastoja. Zig po zaokrozitvi v cele ms nikoli ne gre nazaj.
    NEPREVERJENO: stalna zakasnitev WASAPI (od predvajanja do branja) ni odsteta, ker ni izmerjena.
    """

    def __init__(self, hz: int = ZVOK_HZ, poravnaj_ms: float = ZVOK_PORAVNAJ_MS, okno_ms: float = ZVOK_OKNO_MS,
                 tocnost_ms: float = ZVOK_TOCNOST_MS):
        self._na_ms = hz / 1000.0
        self._poravnaj_ms, self._okno_ms, self._tocnost_ms = poravnaj_ms, okno_ms, tocnost_ms
        self._zacetek: Optional[float] = None
        self._vzorcev = 0                      # vzorcev (na kanal) od prvega kosa, tudi izpuscenih tihih
        self._nad_min: Optional[float] = None  # najmanjsi zaostanek od zacetka tekocega zaostanka
        self._nad_od = 0                       # stevec vzorcev ob zacetku tekocega zaostanka
        self.poravnav = 0
        #: Velikost zadnje poravnave (ms), za dnevnik.
        self.zadnja_poravnava_ms = 0.0
        #: Zadnji vrnjeni zig v celih ms (kot gre na TV): nov zig ne sme biti manjsi.
        self._zadnji_ms: Optional[int] = None
        #: Po poravnavi naprej: do tega stevca vzorcev premik zacetka nazaj pomeni, da poravnava ni bila vrzel,
        #: ampak zaloga po zastoju bralca, ki se pocasi prazni.
        self._preizkus_do: Optional[int] = None
        #: Do tega stevca vzorcev zig ni znan (zacetek se po napacni poravnavi se vraca nazaj).
        self._dvom_do: Optional[int] = None

    def zig(self, vzorcev: int, prebrano_ms: float) -> Optional[float]:
        """Zig kosa z ``vzorcev`` vzorci (na kanal), prebranega ob ``prebrano_ms``; None, ce ni znan."""
        if vzorcev <= 0 or not math.isfinite(prebrano_ms):
            return None
        po_branju = prebrano_ms - vzorcev / self._na_ms
        if self._zacetek is None:
            # Prvi kos: brez primerjave ne vemo, ali je cakal v medpomnilniku (sunek ob zagonu).
            self._zacetek = po_branju
            self._vzorcev = vzorcev
            return None
        zig = self._zacetek + self._vzorcev / self._na_ms
        self._vzorcev += vzorcev
        zaostanek = po_branju - zig
        znan = True
        if zaostanek < 0:
            # Kos je prebran prej, kot pravi stetje: zacetek je bil prepozen, premaknemo ga nazaj.
            self._zacetek += zaostanek
            zig = po_branju
            self._nad_min = None
            if -zaostanek > self._tocnost_ms:
                znan = False
            if self._preizkus_do is not None and self._vzorcev <= self._preizkus_do:
                # Zacetek gre nazaj kmalu po poravnavi naprej: to je bila zaloga, ne vrzel. Ziga ni, dokler
                # se zacetek ne umiri za cel ZVOK_OKNO_MS (sicer bi sli znani, a za zalogo prepozni zigi).
                self._dvom_do = self._vzorcev + int(round(self._okno_ms * self._na_ms))
                self._preizkus_do = self._dvom_do
        elif zaostanek <= self._poravnaj_ms:
            self._nad_min = None
        else:
            # Stetje zaostaja: vrzel ali zastoj bralca. Ne locimo ju, zato zig tega kosa ni znan.
            znan = False
            if self._nad_min is None:
                self._nad_min, self._nad_od = zaostanek, self._vzorcev - vzorcev
            else:
                self._nad_min = min(self._nad_min, zaostanek)
            if (self._vzorcev - self._nad_od) / self._na_ms >= self._okno_ms:
                # Vrzel: od tu naprej stejemo od novega zacetka; zig gre samo naprej.
                self._zacetek += self._nad_min
                self.zadnja_poravnava_ms = self._nad_min
                self._nad_min = None
                self.poravnav += 1
                self._preizkus_do = self._vzorcev + int(round(self._okno_ms * self._na_ms))
        if self._dvom_do is not None:
            if self._vzorcev < self._dvom_do:
                znan = False
            else:
                self._dvom_do = None
        if not znan:
            return None
        zig_ms = int(round(zig))
        if self._zadnji_ms is not None and zig_ms < self._zadnji_ms:
            return None
        self._zadnji_ms = zig_ms
        return zig


def _dnevnik_poravnave(zigi: "ZigiZvoka") -> None:
    """Poravnava je lahko tudi trajna zakasnitev: velikost v dnevnik (kot Linux _cas("zvok_poravnava"))."""
    print("safeer zvok: dogodek=zvok_poravnava ms=%d stevilo=%d" % (int(round(zigi.zadnja_poravnava_ms)),
          zigi.poravnav), file=sys.stderr, flush=True)


def kosi_zvoka(tece) -> Iterator[bytes]:
    """Kar racunalnik predvaja (privzeti zvocnik), v koscih po 10 ms kot s16le, dokler ``tece()`` vraca True.

    Popolna tisina po kratkem repu ne gre v tok (tako kot na Linuxu). Napaka naprave (zvocnik izkljucen, zamenjan)
    zajem konca - slika tece naprej brez zvoka. Brez zigov (za stare klicatelje); glej ``kosi_zvoka_z_zigi``."""
    for _zig, pcm in kosi_zvoka_z_zigi(tece):
        yield pcm


def kosi_zvoka_z_zigi(tece) -> Iterator[Tuple[Optional[float], bytes]]:
    """Kot ``kosi_zvoka``, a vsak kos pride z zigom zajema prvega vzorca (``ura_ms``) ali None, ce ni znan.

    Zig racunamo iz stetja vzorcev (ZigiZvoka), ne iz casa branja: ``record`` se vrne v ritmu medpomnilnika WASAPI
    in z tresenjem razporejevalnika, po zastoju bralca pa v sunku. Generator nima svoje niti: ``record`` tece samo,
    ko klicatelj zahteva naslednji kos, zato zastoj klicatelja (npr. pisanje na TV) zadrzi branje. Steti moramo
    tudi izpuscene tihe koscke, sicer zig po tisini zaostane."""
    import soundcard as sc   # vrne polja numpy (numpy pride s soundcard); posebej ga ne uvazamo
    zvocnik = sc.default_speaker()
    mikrofon = sc.get_microphone(id=str(zvocnik.name), include_loopback=True)
    tihih = 0
    zigi = ZigiZvoka()
    poravnav_prej = 0
    with mikrofon.recorder(samplerate=ZVOK_HZ, channels=ZVOK_KANALI, blocksize=ZVOK_KOS) as zapis:
        while tece():
            podatki = zapis.record(numframes=ZVOK_KOS)
            if podatki.size == 0:
                continue
            prebrano_ms = ura_ms()
            # Stejemo vsak kos, tudi tihega, ki ga spodaj izpustimo.
            zig = zigi.zig(int(podatki.shape[0]), prebrano_ms)
            if zigi.poravnav != poravnav_prej:
                poravnav_prej = zigi.poravnav
                _dnevnik_poravnave(zigi)
            pcm = (podatki.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            if not podatki.any():
                tihih += 1
                if tihih > ZVOK_REP_TISINE:
                    continue
            else:
                tihih = 0
            yield zig, pcm


def _velikost_zaslona() -> Tuple[int, int]:
    if sys.platform != "win32":
        return 1920, 1080
    u = ctypes.windll.user32
    return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))


def velikost_slike(izvor: Optional[Tuple[int, int]] = None,
                   meja: Tuple[int, int] = (NAJVEC_SIRINA, NAJVEC_VISINA)) -> Tuple[int, int]:
    """Velikost poslane slike: izvor, pomanjsan v `meja` (privzeto 1920x1080), sodi mere (H.264 zahteva sode).
    Slike ne povecamo."""
    sw, sv = izvor or _velikost_zaslona()
    faktor = min(1.0, meja[0] / max(1, sw), meja[1] / max(1, sv))
    w, h = int(sw * faktor) // 2 * 2, int(sv * faktor) // 2 * 2
    return max(2, w), max(2, h)


# ------------------------------------------------------------------ HEVC: cisti del (se ni vezan v sejo)

#: Vrste NAL: IDR in nastavitve za vsak kodek. H.264: IDR 5, SPS 7, PPS 8. H.265: IDR_W_RADL 19, IDR_N_LP 20,
#: VPS 32, SPS 33, PPS 34 (H.265 tabela 7-1; specifikacija ni v prilogi, NEPREVERJENO na pravem toku, ukaz W4).
_NAL_IDR = {"h264": frozenset((5,)), "hevc": frozenset((19, 20))}
_NAL_NASTAVITVE = {"h264": frozenset((7, 8)), "hevc": frozenset((32, 33, 34))}


def vrsta_nal(podatki: bytes, i: int, kodek: str = "h264") -> int:
    """Vrsta enote NAL za zacetno kodo 00 00 01 na `i`; -1, ce glave ni (konec podatkov).

    H.264 ima 1-bajtno glavo (vrsta = b & 0x1F), H.265 2-bajtno (vrsta = (b >> 1) & 0x3F). Pri H.265 bi
    maska H.264 brala narobe: IDR_N_LP 20 (bajt 0x28) bi bil "PPS" 8, SPS 33 (0x42) pa "rezina" 2."""
    if i < 0 or i + 3 >= len(podatki):
        return -1
    b = podatki[i + 3]
    return (b >> 1) & 0x3F if kodek == "hevc" else b & 0x1F


def je_idr(podatki: bytes, kodek: str = "h264") -> bool:
    """Ali paket Annex-B vsebuje rezino IDR (H.264: 5; H.265: 19 ali 20). Za H.264 enako H264Zajem._je_idr."""
    idr = _NAL_IDR[kodek]
    i = podatki.find(b"\x00\x00\x01")
    while i >= 0:
        if vrsta_nal(podatki, i, kodek) in idr:
            return True
        i = podatki.find(b"\x00\x00\x01", i + 3)
    return False


def nastavitve(podatki: bytes, kodek: str = "h264", najvec: int = 1024) -> bytes:
    """Nastavitve (H.264 SPS/PPS; H.265 VPS/SPS/PPS) iz paketa, s 4-bajtno zacetno kodo, v istem vrstnem redu.
    Za H.264 enako H264Zajem._nastavitve (isti postopek, druga mnozica vrst)."""
    vrste = _NAL_NASTAVITVE[kodek]
    ven = b""
    i = podatki.find(b"\x00\x00\x01", 0, najvec + 2)
    prejsnja = False
    while 0 <= i and i + 3 < len(podatki):
        nastavitev = vrsta_nal(podatki, i, kodek) in vrste
        if i >= najvec and not (prejsnja and nastavitev):
            break
        if nastavitev:
            naslednji = podatki.find(b"\x00\x00\x01", i + 3)
            konec = naslednji if naslednji >= 0 else len(podatki)
            ven += b"\x00\x00\x00\x01" + podatki[i + 3:konec].rstrip(b"\x00")
        else:
            naslednji = podatki.find(b"\x00\x00\x01", i + 3, najvec + 2)
        prejsnja, i = nastavitev, naslednji
    return ven


#: Isto kot nastavitve; ime za H264Zajem.okvirji_z_zigi, kjer je `nastavitve` lokalna spremenljivka.
_nal_nastavitve = nastavitve


def ima_nastavitve_spredaj(podatki: bytes, kodek: str = "h264") -> bool:
    """Ali so nastavitve ze na zacetku paketa (prvih 256 B). H.264 natanko kot H264Zajem._z_nastavitvami
    (SPS z bajtom 0x67); H.265 po VPS (glava 0x40 0x01: vrsta 32, plast 0, tid 1)."""
    glava = b"\x40\x01" if kodek == "hevc" else b"\x67"
    zacetek = podatki[:256]
    return b"\x00\x00\x00\x01" + glava in zacetek or b"\x00\x00\x01" + glava in zacetek


def kodirniki_hevc(av) -> list:
    """Strojni kodirniki HEVC, ki jih ima ta PyAV (av.codecs_available), v vrstnem redu KODIRNIKI_HEVC."""
    na_voljo = getattr(av, "codecs_available", ()) or ()
    return [k for k in KODIRNIKI_HEVC if k in na_voljo]


#: Izid preizkusa kodiranja HEVC po (ime, sirina, visina): odpiranje samo ne pove, ali gonilnik zmore velikost.
_HEVC_PREIZKUS: dict = {}


def preizkusi_hevc(av, ime: str, sirina: int, visina: int, fps: int = 60, bitrate: int = 24_000_000) -> bool:
    """Ali kodirnik `ime` res kodira sliko velikosti seje: odpre kontekst, kodira eno crno sliko nv12 in izprazni.
    Uspeh samo, ce pride vsaj en paket in je v njem IDR (19/20). Izid si zapomnimo (kot Linux hevc_vaapi_mozen)."""
    kljuc = (ime, int(sirina), int(visina))
    if kljuc in _HEVC_PREIZKUS:
        return _HEVC_PREIZKUS[kljuc]
    izid = False
    c = None
    try:
        c = av.CodecContext.create(ime, "w")
        c.width, c.height = int(sirina), int(visina)
        c.pix_fmt = "nv12"
        c.framerate = Fraction(int(fps), 1)
        c.time_base = Fraction(1, int(fps))
        c.gop_size = int(fps)
        c.max_b_frames = 0
        c.bit_rate = int(bitrate)
        c.options = _moznosti(ime)
        c.open()
        okvir = av.VideoFrame(int(sirina), int(visina), "nv12")
        okvir.pts = 0
        paketi = [bytes(p) for p in c.encode(okvir)] + [bytes(p) for p in c.encode(None)]
        izid = any(je_idr(p, "hevc") for p in paketi)
    except Exception:  # noqa: BLE001 - brez uspesnega preizkusa ostanemo pri H.264
        izid = False
    finally:
        zapri = getattr(c, "close", None)
        if zapri is not None:
            try:
                zapri()
            except Exception:
                pass
    _HEVC_PREIZKUS[kljuc] = izid
    return izid


def _velikost_izjave(najvecja, kodek: str) -> Optional[Tuple[int, int]]:
    """(sirina, visina) iz izjave televizorja {"hevc": [w, h]}; None za vse, kar ni dvoje pozitivnih celih stevil."""
    if not isinstance(najvecja, dict):
        return None
    v = najvecja.get(kodek)
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    if not all(isinstance(x, int) and not isinstance(x, bool) and 0 < x <= 16384 for x in v):
        return None
    return int(v[0]), int(v[1])


def izberi_tok(kodeki, najvecja, izvor: Tuple[int, int], hevc_mozen, polna: bool = True) -> Tuple[str, int, int]:
    """(kodek, sirina, visina) seje, po istem pravilu kot Linux (link_zaslon.izberi_tok).

    HEVC samo, ce ga televizor izrecno navede v `kodeki` (codecs iz screen.start) pred "h264" IN ga racunalnik
    res kodira (hevc_mozen(sirina, visina)). Vec kot 1920x1080 samo s HEVC, samo ob izjavi `najvecja`
    {"hevc": [w, h]} in samo pri polni kakovosti; najvec NAJVEC_HEVC. Sicer H.264 kot doslej (velikost_slike)."""
    privzeto = ("h264",) + tuple(velikost_slike(izvor))
    if not isinstance(kodeki, (list, tuple)):
        return privzeto
    hoce = False
    for k in list(kodeki)[:8]:
        k = k.strip().lower() if isinstance(k, str) else ""
        if k == "hevc":
            hoce = True
            break
        if k == "h264":
            break
    if not hoce:
        return privzeto
    meja = (NAJVEC_SIRINA, NAJVEC_VISINA)
    izjava = _velikost_izjave(najvecja, "hevc")
    if izjava is not None:
        if izjava[0] < meja[0] or izjava[1] < meja[1]:
            # Dekoder HEVC ne zmore niti osnovne velikosti: raje H.264 kot manjsa slika.
            return privzeto
        if polna:
            meja = (min(izjava[0], NAJVEC_HEVC[0]), min(izjava[1], NAJVEC_HEVC[1]))
    sirina, visina = velikost_slike(izvor, meja)
    if not hevc_mozen(sirina, visina):
        return privzeto
    return "hevc", sirina, visina


def izberi_kodek(kodeki, najvecja, kodirniki_hevc_preizkus, izvor: Optional[Tuple[int, int]] = None,
                 polna: bool = True) -> Tuple[str, Tuple[int, int]]:
    """(kodek, (sirina, visina)) seje iz izrecnih zmoznosti televizorja (screen.start "codecs", "maxsize").

    HEVC samo, ce je "hevc" v `kodeki` (pred "h264", kot Linux izberi_tok) IN `kodirniki_hevc_preizkus(w, h)`
    vrne True za zeljeno velikost (vsaj en kodirnik je presel preizkusi_hevc). Meja iz najvecja["hevc"] velja
    samo za HEVC; sicer velikost_slike (zaslon v 1920x1080). Ob kakrsnikoli napaki H.264 kot doslej."""
    try:
        kodek, sirina, visina = izberi_tok(kodeki, najvecja, izvor, kodirniki_hevc_preizkus, polna)
    except Exception:  # noqa: BLE001 - neznano ali pokvarjeno: H.264 kot prej
        return "h264", tuple(velikost_slike(izvor))
    if kodek != "hevc":
        return "h264", tuple(velikost_slike(izvor))
    return "hevc", (int(sirina), int(visina))


def hevc_preizkus(sirina: int, visina: int) -> bool:
    """Ali ta racunalnik kodira HEVC v velikosti seje: vsaj en strojni kodirnik je presel preizkusi_hevc.
    Brez PyAV False. Izid preizkusa je shranjen po (ime, sirina, visina), zato je drugi klic hiter."""
    try:
        import av
    except Exception:  # noqa: BLE001 - brez PyAV ni HEVC
        return False
    return any(preizkusi_hevc(av, k, sirina, visina) for k in kodirniki_hevc(av))


def glava_toka(sirina: int, visina: int, fps: int, zvok: bool, zig: dict, kodek: str = "h264") -> dict:
    """Glava toka po pozdravu. Za H.264 enaka kot prej (isti kljuci v istem vrstnem redu, json.dumps bajt za
    bajtom); za HEVC dodatno "kodek": "hevc" (TV bere glava.optString("kodek") == "hevc")."""
    glava = {
        "v": 2, "w": sirina, "h": visina, "fps": fps,
        # Zvok racunalnika (WASAPI loopback), ce ga lahko zajamemo; sicer slika brez zvoka kot prej.
        "zvok": ({"hz": ZVOK_HZ, "kanali": ZVOK_KANALI, "oblika": "s16le"} if zvok else None),
        "vnos": True, "plosek": False,
        # Vsak okvir slike je cela slika (en paket kodirnika): sprejemnik jo sme takoj dati dekoderju,
        # ne da caka na zacetek naslednje (Android ZaslonOdjemalec, od Safeer OS 0.5.75). Za HEVC ga TV prezre.
        "au": True,
        # Zigi zajema (okvir 4 pred sliko/zvokom). Stari gledalec kljuc prezre (JSONObject.opt*).
        "zig": dict(zig),
    }
    if kodek == "hevc":
        glava["kodek"] = "hevc"
    return glava


def _v_vrsto(vrsta, element) -> None:
    """Postavi element v vrsto brez cakanja. Ce je polna, zavrzemo NAJSTAREJSI element in obdrzimo novega:
    kodirnik vedno dobi zadnjo sliko, zamik zaradi vrste pa ni vec kot ena slika cakanja (prej: zajem je cakal
    na prostor in slika je v vrsti zastarela do dveh intervalov). Slike v vrsti so nekodirane, zato zavrzena slika
    ne pokvari toka H.264. Vrsto polni samo ena nit (zajem), zato je po odvzemu prostor zagotovo prost."""
    import queue
    while True:
        try:
            vrsta.put_nowait(element)
            return
        except queue.Full:
            try:
                vrsta.get_nowait()
            except queue.Empty:
                pass


class H264Zajem:
    """Zajema glavni zaslon in vraca kose H.264 (Annex-B), primerne za televizor.
    Z `kodek="hevc"` (samo po izberi_kodek) kose H.265 s strojnim kodirnikom, ki je presel preizkusi_hevc."""

    def __init__(self, fps: int = 30, bitrate: int = 6_000_000, kodirnik: Optional[str] = None,
                 kodek: str = "h264", velikost: Optional[Tuple[int, int]] = None):
        import av
        from PIL import ImageGrab  # noqa: F401  (preverimo zgodaj, da napaka pride ob zagonu)

        self._av = av
        self.kodek = "hevc" if kodek == "hevc" else "h264"
        self.izvor = _velikost_zaslona()
        if velikost is not None:
            # Velikost seje iz izberi_kodek (pri HEVC lahko do NAJVEC_HEVC); sode mere.
            self.sirina, self.visina = max(2, int(velikost[0]) // 2 * 2), max(2, int(velikost[1]) // 2 * 2)
        else:
            self.sirina, self.visina = velikost_slike(self.izvor)
        self.fps = max(5, min(60, int(fps)))
        if self.kodek == "hevc":
            # Samo strojni kodirniki, ki so v tej velikosti zares kodirali (izid je shranjen); nikoli libx265.
            kandidati = [kodirnik] if kodirnik else [
                k for k in kodirniki_hevc(av) if preizkusi_hevc(av, k, self.sirina, self.visina)]
            if not kandidati:
                raise RuntimeError("Na tem racunalniku ni kodirnika HEVC")
        else:
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
            raise RuntimeError(f"Kodirnika {'HEVC' if self.kodek == 'hevc' else 'H.264'} ni mogoce odpreti: {napaka}")
        #: Oblika slike za kodirnik. Nit zajema bere to in ne self._c, ker nit kodiranja self._c zamenja in
        #: zapre (_obnovi_kodirnik); nov kontekst istega kodirnika ima isto obliko (_odpri).
        self._pix_fmt = self._c.pix_fmt
        self._bitrate = int(bitrate)
        self._st = 0
        #: Zahteva televizorja po kljucnem okvirju: postavi jo nit vnosa (zahtevaj_kljucni), porabi nit kodiranja.
        self._kljucni_zahtevan = threading.Event()
        #: Stevci za dnevnik: izsiljenih IDR in zamenjav konteksta kodirnika.
        self.kljucnih = 0
        self.obnov_kodirnika = 0
        #: pts slike -> zig zajema (ura_ms); kodirnik vrne paket z istim pts (brez B-slik je vrstni red enak).
        #: Pise in bere ga samo nit kodiranja (okvirji_z_zigi); zajem poslje zig skupaj s sliko skozi vrsto.
        self._zigi: dict = {}
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
        c.options = dict(_moznosti(ime), **_MOZNOSTI_IDR.get(ime, {}))
        try:
            c.open()
        except Exception as e:
            if ime not in _MOZNOSTI_IDR:
                raise
            # Prvi vzrok zapisemo: ce pade tudi odpiranje brez moznosti, bi ga njegova napaka skrila.
            print(f"[Zaslon] {ime}: odpiranje z IDR moznostjo ni uspelo ({type(e).__name__}: {e}); brez nje",
                  flush=True)
            # Starejsi gonilnik ali ffmpeg moznosti morda ne pozna: brez nje odpremo kot prej, IDR pa preveri tok.
            c = self._av.CodecContext.create(ime, "w")
            c.width, c.height = self.sirina, self.visina
            c.pix_fmt = "yuv420p" if ime == "libx264" else "nv12"
            c.framerate = Fraction(self.fps, 1)
            c.time_base = Fraction(1, self.fps)
            c.gop_size = self.fps
            c.max_b_frames = 0
            c.bit_rate = int(bitrate)
            c.options = _moznosti(ime)
            c.open()
        return c

    def zahtevaj_kljucni(self) -> None:
        """Televizor prosi za kljucni okvir. Varno iz katerekoli niti: samo postavi zastavico, IDR naredi nit
        kodiranja na naslednji sliki. Po koncu seje (kodiranje ne tece) klic nima ucinka."""
        self._kljucni_zahtevan.set()

    def _oznaci_kljucni(self, okvir) -> bool:
        """Oznaci sliko kot I (kodirnik jo naredi kot IDR). PyAV >= 11 ima PictureType, starejsi niz."""
        try:
            from av.video.frame import PictureType
            okvir.pict_type = PictureType.I
            return True
        except Exception:
            pass
        try:
            okvir.pict_type = "I"
            return True
        except Exception:
            return False

    @staticmethod
    def _je_idr(podatki: bytes) -> bool:
        """Ali paket Annex-B vsebuje rezino IDR (vrsta NAL 5)."""
        i = podatki.find(b"\x00\x00\x01")
        while i >= 0:
            if i + 3 < len(podatki) and (podatki[i + 3] & 0x1F) == 5:
                return True
            i = podatki.find(b"\x00\x00\x01", i + 3)
        return False

    @staticmethod
    def _nastavitve(podatki: bytes, najvec: int = 1024) -> bytes:
        """SPS in PPS (vrsti NAL 7 in 8) iz paketa, z zacetno kodo, v istem vrstnem redu; prazno, ce jih ni."""
        # Zacetke enot iscemo samo v prvih `najvec` bajtih (vroca pot). Enoto SPS/PPS pa beremo do njenega
        # pravega konca v celem paketu, za njo pa tudi SPS/PPS, ki ji neposredno sledi: enota, ki se zacne pred
        # mejo in konca za njo (ali PPS takoj za takim SPS), ne sme biti odrezana ali izgubljena.
        ven = b""
        i = podatki.find(b"\x00\x00\x01", 0, najvec + 2)
        prejsnja = False                     # prejsnja enota je bila SPS/PPS
        while 0 <= i and i + 3 < len(podatki):
            nastavitev = (podatki[i + 3] & 0x1F) in (7, 8)
            if i >= najvec and not (prejsnja and nastavitev):
                break
            if nastavitev:
                naslednji = podatki.find(b"\x00\x00\x01", i + 3)
                konec = naslednji if naslednji >= 0 else len(podatki)
                ven += b"\x00\x00\x00\x01" + podatki[i + 3:konec].rstrip(b"\x00")
            else:
                naslednji = podatki.find(b"\x00\x00\x01", i + 3, najvec + 2)
            prejsnja, i = nastavitev, naslednji
        return ven

    def _obnovi_kodirnik(self) -> bool:
        """Zamenja kontekst kodirnika z novim istega imena (zacne z IDR). Stari se izprazni in zapre; njegovi
        zadnji paketi se zavrzejo (niso bili poslani, zato stevec "bajt" ostane pravilen). Ce nov ne odpre,
        ostane stari in tok tece naprej (redni kljucni okvir vsako sekundo, gop_size)."""
        try:
            nov = self._odpri(self.kodirnik, getattr(self, "_bitrate", 6_000_000))
        except Exception as e:
            print(f"[Zaslon] kljucni: nov kodirnik ni odprl ({type(e).__name__})", flush=True)
            return False
        star, self._c = self._c, nov
        try:
            for _ in star.encode(None):
                pass
        except Exception:
            pass
        zapri = getattr(star, "close", None)
        if zapri is not None:
            try:
                zapri()
            except Exception:
                pass
        self.obnov_kodirnika = getattr(self, "obnov_kodirnika", 0) + 1
        return True

    def _iz_bgra(self, surova):
        """Slika DXGI (BGRA) -> okvir za kodirnik. Kopija v obstojeci okvir (~0,4 ms) namesto novega okvirja
        (~4,5 ms) in pretvorba z vec nitmi (~1,4 ms): izmerjeno 9. 10. 2026, skupaj ~2 ms namesto ~10 ms."""
        v, s = int(surova.shape[0]), int(surova.shape[1])
        okvir = getattr(self, "_bgra", None)
        try:
            if okvir is None or (okvir.width, okvir.height) != (s, v):
                okvir = self._bgra = self._av.VideoFrame(s, v, "bgra")
            if okvir.planes[0].line_size != s * 4 or not surova.flags["C_CONTIGUOUS"]:
                raise ValueError("razlicen korak vrstice")
            okvir.planes[0].update(surova)
        except Exception:
            okvir = self._av.VideoFrame.from_ndarray(surova, format="bgra")
        try:
            return okvir.reformat(width=self.sirina, height=self.visina, format=self._oblika(), threads=4)
        except TypeError:  # starejsi PyAV brez niti
            return okvir.reformat(width=self.sirina, height=self.visina, format=self._oblika())

    def _oblika(self) -> str:
        """Oblika slike za kodirnik, nastavljena v __init__ (klice jo nit zajema). Rezerva self._c velja samo za
        predmet brez __init__ (preizkusi z object.__new__); v pravem zajemu se ne uporabi."""
        oblika = getattr(self, "_pix_fmt", None)
        return oblika if oblika is not None else self._c.pix_fmt

    def _slika(self):
        if self._dxgi is not None:
            surova = self._dxgi.slika()
            if surova is not None:
                okvir = self._iz_bgra(surova)
                okvir.pts = self._st
                self._st += 1
                return okvir
        from PIL import ImageGrab
        slika = ImageGrab.grab()
        if slika.size != (self.sirina, self.visina):
            slika = slika.resize((self.sirina, self.visina))
        okvir = self._av.VideoFrame.from_image(slika).reformat(format=self._oblika())
        okvir.pts = self._st
        self._st += 1
        return okvir

    def okvirji(self, tece) -> Iterator[bytes]:
        """Kosi H.264, dokler ``tece()`` vraca True. Brez zigov (za stare klicatelje); glej ``okvirji_z_zigi``."""
        for _zig, podatki in self.okvirji_z_zigi(tece):
            yield podatki

    def okvirji_z_zigi(self, tece) -> Iterator[Tuple[Optional[float], bytes]]:
        """Kosi H.264 z zigom zajema slike (``ura_ms``; None, ce ga kodirnik ne vrne z znanim pts).
        Hitrost omeji fps (zajem je lahko pocasnejsi).

        Zajem in pretvorba barv (~10 ms) tečeta v svoji niti, kodiranje in posiljanje v tej: tako se casa ne
        sestevata (izmerjeno 9. 10. 2026: zaporedno ~50 slik/s v pravi seji, cilj 60).
        """
        import queue
        interval = 1.0 / self.fps
        # Najvec 2 sliki; ce je polna, zavrzemo najstarejso (glej _v_vrsto), ne cakamo.
        vrsta: "queue.Queue" = queue.Queue(maxsize=2)
        konec = threading.Event()

        def zajemaj():
            # DXGI: sliko vzamemo takoj, ko jo Windows nariše (ne v stalnem ritmu: to je dodajalo do 17 ms
            # zamika), najvec fps-krat na sekundo. Nespremenjen zaslon ponovimo po POLNITEV_S (glej tam).
            # GDI (ni DXGI ali je monitor ugasnjen): stalni ritem kot prej.
            zadnji = 0.0
            try:
                while not konec.is_set():
                    zdaj = time.monotonic()
                    okvir = None
                    if self._dxgi is not None:
                        # Najvec ritem zaslona (DXGI da novo sliko ob osvežitvi); 0,6 intervala, sicer bi po vsaki
                        # sliki zgrešili naslednjo osvežitev (izmerjeno: 43 namesto 60 slik/s).
                        if zdaj - zadnji < interval * 0.6:
                            time.sleep(0.001)
                            continue
                        surova, nova = self._dxgi.slika_nova()
                        zig = ura_ms()     # slika je bila na zaslonu najkasneje zdaj
                        if surova is not None:
                            if not nova and zdaj - zadnji < POLNITEV_S:
                                time.sleep(0.001)
                                continue
                            okvir = self._iz_bgra(surova)
                            okvir.pts = self._st
                            self._st += 1
                    if okvir is None:
                        if zdaj - zadnji < interval:
                            time.sleep(interval - (zdaj - zadnji))
                            continue
                        zig = ura_ms()     # GDI: zajem se zacne zdaj in traja ~34 ms (glej _DxgiZajem)
                        okvir = self._slika()
                    zadnji = time.monotonic()
                    _v_vrsto(vrsta, (zig, okvir))
            except Exception as e:  # zajem ne sme obtiči tiho: kodirnik dobi napako in seja se konca
                _v_vrsto(vrsta, e)

        nit = threading.Thread(target=zajemaj, name="safeer-zajem-zaslona", daemon=True)
        nit.start()
        prvi = True
        pts = 0
        # Izsiljen kljucni okvir: None = ne cakamo; sicer stevilo paketov, ki jih se cakamo na IDR.
        caka_idr: Optional[int] = None
        # pts oznacene slike: paketi starejsih slik (zakasnitev kodirnika) se v caka_idr ne stejejo.
        idr_od_pts = 0
        nastavitve = b""
        zahteva = getattr(self, "_kljucni_zahtevan", None)
        # Vrste NAL po kodeku (H.264: IDR 5, SPS/PPS 7/8; HEVC: IDR 19/20, VPS/SPS/PPS 32-34).
        kodek = getattr(self, "kodek", "h264")
        try:
            while tece():
                try:
                    okvir = vrsta.get(timeout=1.0)
                except queue.Empty:
                    continue
                if isinstance(okvir, Exception):
                    raise okvir
                zig, okvir = okvir
                # pts dodelimo sele tu, zaporedno: zavrzena slika (glej _v_vrsto) ne pusti luknje v pts,
                # kodirnik dobi enak tok kot prej. Slovar pise in bere samo ta nit (brez zaklepa).
                okvir.pts = pts
                self._zigi[pts] = zig
                while len(self._zigi) > NAJVEC_ZIGOV:
                    # Kodirnik brez pts zigov ne pobira: zavrzemo najstarejsega (pts narasca, vrstni red slovarja).
                    del self._zigi[next(iter(self._zigi))]
                pts += 1
                if zahteva is not None and zahteva.is_set():
                    zahteva.clear()
                    if self._oznaci_kljucni(okvir):
                        caka_idr, idr_od_pts = KLJUCNI_PAKETOV, okvir.pts
                    elif self._obnovi_kodirnik():
                        # PyAV oznake ne zna: nov kontekst sam zacne z IDR.
                        prvi, nastavitve = True, b""
                        self.kljucnih = getattr(self, "kljucnih", 0) + 1
                for paket in self._c.encode(okvir):
                    podatki = bytes(paket)
                    zig = self._zigi.pop(paket.pts, None) if paket.pts is not None else None
                    if paket.pts is not None:
                        for star in [p for p in self._zigi if p < paket.pts]:   # izpusceni pri kodiranju
                            del self._zigi[star]
                    if prvi:
                        prvi = False
                        podatki = self._z_nastavitvami(podatki)
                    if not nastavitve and podatki:
                        # SPS/PPS (HEVC: VPS/SPS/PPS) so na zacetku paketa; dalje ne iscemo (vroca pot).
                        nastavitve = _nal_nastavitve(podatki, kodek)
                    if caka_idr is not None and podatki:
                        if je_idr(podatki, kodek):
                            caka_idr = None
                            self.kljucnih = getattr(self, "kljucnih", 0) + 1
                            # Televizor je po napaki dekodirnik morda ponastavil: nastavitve morajo biti pred IDR.
                            if nastavitve and not _nal_nastavitve(podatki, kodek):
                                podatki = nastavitve + podatki
                        elif paket.pts is None or paket.pts >= idr_od_pts:
                            caka_idr -= 1
                    if podatki:
                        yield zig, podatki
                if caka_idr is not None and caka_idr <= 0:
                    # Kodirnik oznake I ni upostevel (NEPREVERJENO za h264_mf/h264_amf): nov kontekst.
                    caka_idr = None
                    if self._obnovi_kodirnik():
                        prvi, nastavitve = True, b""
                        self.kljucnih = getattr(self, "kljucnih", 0) + 1
        finally:
            konec.set()
            nit.join(timeout=2.0)

    def _z_nastavitvami(self, podatki: bytes) -> bytes:
        """Televizor mora dobiti SPS/PPS (HEVC: VPS/SPS/PPS) pred prvo sliko; nekateri kodirniki jih dajo le
        v extradata. Za H.264 isto preverjanje kot prej (SPS z bajtom 0x67)."""
        if ima_nastavitve_spredaj(podatki, getattr(self, "kodek", "h264")):
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
        # Kontekst zapremo izrecno (strojni kodirnik drzi sejo gonilnika); starejsi PyAV close nima.
        zapri = getattr(self._c, "close", None)
        if zapri is not None:
            try:
                zapri()
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
