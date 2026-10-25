"""Windows: racunalnik naj ne zaspi sam, dokler Safeer predvaja (SAFEER-ZNANJE Z4608, zapisnik 25. 10. W3).

core/budnost.py je skupna koda z Linuxom (skupna-koda.json, »skupne«) in zna samo D-Bus: na Windows ni upravitelja
seje, zato tam ne zadrzi nicesar. Ta modul ima ISTI vmesnik (Budnost.nastavi / po_dejavnosti / sprosti_vse / stanje,
zastavici SPANJE in ZASLON ter dotik/dejavno iz core.budnost), zaledje pa je Windows:

1. PowerCreateRequest + PowerSetRequest (kernel32, od Windows 7; isti mehanizem kot Chromium/Edge). Zahteva pripada
   rocaju, ne niti: sprostitev dela iz katerekoli niti, ob izhodu ali sesutju procesa jo sistem sprosti sam, razlog
   (»Safeer predvaja«) pa je viden v `powercfg /requests` - tako se preveri na pravem Windows.
2. Rezerva, ce zahteve moci niso na voljo: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED
   [| ES_DISPLAY_REQUIRED]). Velja za KLICOCO nit, zato modul nastavi skupno stanje vseh razlogov naenkrat; predvajalniki
   ga klicejo iz niti vmesnika (Qt).

SPANJE = samodejno spanje ob nedejavnosti; ZASLON = se ugasanje zaslona (in zaklep, ki sledi ugasnjenemu zaslonu).
Zaprt pokrov, gumb za vklop in rocno spanje delujejo kot vedno - sistemske zahteve jih ne zadrzijo (prenosnik v torbi
mora zaspati). Ohranjevalnika zaslona SetThreadExecutionState po Microsoftovi dokumentaciji ne ustavi; v Windows 10/11
je privzeto izklopljen. Na Linuxu ostane core/budnost.py (D-Bus).
"""
from __future__ import annotations

import logging
import sys
from typing import Dict, Optional, Tuple

from core.budnost import SPANJE, ZASLON, dejavno, dotik  # noqa: F401 - isti zastavici in isti dotik kot na Linuxu

__all__ = ["Budnost", "Kernel32", "SPANJE", "ZASLON", "budnost", "dejavno", "dotik", "ob_predvajanju", "sprosti",
           "zastavice_predvajanja"]

_log = logging.getLogger("safeer.budnost")

# winbase.h
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000
# POWER_REQUEST_TYPE (winnt.h)
ZAHTEVA_ZASLON = 0          # PowerRequestDisplayRequired
ZAHTEVA_SISTEM = 1          # PowerRequestSystemRequired
_POWER_REQUEST_CONTEXT_VERSION = 0
_POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1


def _je_windows() -> bool:
    return sys.platform == "win32"


def _tipi(zastavice: int) -> Tuple[int, ...]:
    """Zastavice -> zahteve moci. ZASLON vkljuci tudi sistem: prizgan zaslon na specem racunalniku ni smiseln (tudi
    upravitelj seje na Linuxu ob zadrzani nedejavnosti ne zaspi)."""
    tipi = []
    if zastavice & (SPANJE | ZASLON):
        tipi.append(ZAHTEVA_SISTEM)
    if zastavice & ZASLON:
        tipi.append(ZAHTEVA_ZASLON)
    return tuple(tipi)


def _stanje_niti(zastavice: int) -> int:
    es = ES_CONTINUOUS
    if zastavice & (SPANJE | ZASLON):
        es |= ES_SYSTEM_REQUIRED
    if zastavice & ZASLON:
        es |= ES_DISPLAY_REQUIRED
    return es


def tip_reason_context():
    """REASON_CONTEXT (minwinbase.h) kot ctypes struktura; na 64-bitnem sistemu 32 bajtov (preizkus to preveri tudi na
    Linuxu, kjer kernel32 ni)."""
    import ctypes

    class _Podrobno(ctypes.Structure):
        _fields_ = [("LocalizedReasonModule", ctypes.c_void_p), ("LocalizedReasonId", ctypes.c_uint32),
                    ("ReasonStringCount", ctypes.c_uint32), ("ReasonStrings", ctypes.POINTER(ctypes.c_wchar_p))]

    class _Razlog(ctypes.Union):
        _fields_ = [("Detailed", _Podrobno), ("SimpleReasonString", ctypes.c_wchar_p)]

    class _ReasonContext(ctypes.Structure):
        _fields_ = [("Version", ctypes.c_uint32), ("Flags", ctypes.c_uint32), ("Reason", _Razlog)]

    return _ReasonContext


class Kernel32:
    """Tanek ovoj okrog kernel32 (ctypes) - samo na Windows. Preizkusi namesto njega podajo laznega z istimi metodami."""

    def __init__(self) -> None:
        import ctypes
        self._ct = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)   # lasten primerek: argtypes ne vplivajo na druge module
        _ReasonContext = tip_reason_context()
        self._ReasonContext = _ReasonContext
        self._ustvari = k32.PowerCreateRequest
        self._ustvari.argtypes = [ctypes.POINTER(_ReasonContext)]
        self._ustvari.restype = ctypes.c_void_p
        self._nastavi = k32.PowerSetRequest
        self._nastavi.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._nastavi.restype = ctypes.c_int
        self._pocisti = k32.PowerClearRequest
        self._pocisti.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._pocisti.restype = ctypes.c_int
        self._zapri = k32.CloseHandle
        self._zapri.argtypes = [ctypes.c_void_p]
        self._zapri.restype = ctypes.c_int
        self._niti = k32.SetThreadExecutionState
        self._niti.argtypes = [ctypes.c_uint32]
        self._niti.restype = ctypes.c_uint32

    def ustvari_zahtevo(self, opis: str) -> int:
        ct = self._ct
        kontekst = self._ReasonContext()
        kontekst.Version = _POWER_REQUEST_CONTEXT_VERSION
        kontekst.Flags = _POWER_REQUEST_CONTEXT_SIMPLE_STRING
        kontekst.Reason.SimpleReasonString = opis      # sistem besedilo prepise ob klicu (Chromium dela enako)
        rocaj = self._ustvari(ct.byref(kontekst))
        if not rocaj or rocaj == ct.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
            raise OSError(ct.get_last_error(), "PowerCreateRequest ni uspel")
        return rocaj

    def nastavi_zahtevo(self, rocaj: int, tip: int) -> None:
        if not self._nastavi(rocaj, tip):
            raise OSError(self._ct.get_last_error(), "PowerSetRequest ni uspel")

    def pocisti_zahtevo(self, rocaj: int, tip: int) -> None:
        self._pocisti(rocaj, tip)

    def zapri(self, rocaj: int) -> None:
        self._zapri(rocaj)

    def stanje_niti(self, es: int) -> int:
        """SetThreadExecutionState: vrne prejsnje stanje, 0 = napaka."""
        return int(self._niti(es) or 0)


class Budnost:
    """Zadrzanja samodejnega spanja po razlogih (»predvajanje«, »predvajalnik«, »pomoc«); vsak razlog ima najvec eno
    zahtevo. Enako stanje ne naredi nic, zato se sme klicati ob vsaki spremembi predvajanja."""

    def __init__(self, program: str = "Safeer", jedro=None) -> None:
        self.program = program
        self._jedro = jedro            # Kernel32 ali lazni; None = ustvari ob prvi rabi (samo na Windows)
        self._brez_jedra = False       # ni Windows ali kernel32 ni nalozljiv: ne poskusamo ob vsakem klicu znova
        self._zahteve = True           # False po prvi napaki PowerCreateRequest/PowerSetRequest -> rezerva
        self._nit_es = ES_CONTINUOUS   # zadnje stanje, ki ga je nastavila rezerva
        #: razlog -> (zastavice, rocaj zahteve ali None = velja rezerva, ali zadrzanje res velja)
        self._drzim: Dict[str, Tuple[int, Optional[int], bool]] = {}

    def _k32(self):
        if self._jedro is None and not self._brez_jedra:
            if not _je_windows():
                self._brez_jedra = True
            else:
                try:
                    self._jedro = Kernel32()
                except Exception as e:  # noqa: BLE001 - brez kernel32 predvajanje dela naprej, le brez zadrzanja
                    _log.warning("budnost: kernel32 ni na voljo (%s)", e)
                    self._brez_jedra = True
        return self._jedro

    def nastavi(self, razlog: str, zastavice: int, opis: str = "") -> bool:
        """Zadrzi (SPANJE in/ali ZASLON) ali sprosti (0) samodejno spanje za `razlog`. Vrne, ali zadrzanje velja."""
        zastavice = int(zastavice) & (SPANJE | ZASLON)
        staro = self._drzim.get(razlog)
        if staro is not None and staro[0] == zastavice:
            return staro[2]
        if staro is not None:
            del self._drzim[razlog]
            self._sprosti(staro)
        if not zastavice:
            return False
        k = self._k32()
        if k is None:
            self._drzim[razlog] = (zastavice, None, False)
            return False
        if self._zahteve:
            rocaj = None
            try:
                rocaj = k.ustvari_zahtevo(opis or self.program)
                for tip in _tipi(zastavice):
                    k.nastavi_zahtevo(rocaj, tip)
                self._drzim[razlog] = (zastavice, rocaj, True)
                _log.info("budnost: %s zadrzano (%s)", razlog, "spanje in zaslon" if zastavice & ZASLON else "spanje")
                return True
            except Exception as e:  # noqa: BLE001
                if rocaj is not None:
                    self._zapri_zahtevo(rocaj, zastavice)
                self._zahteve = False
                _log.warning("budnost: zahteve moci niso na voljo (%s) - rezerva SetThreadExecutionState", e)
        self._drzim[razlog] = (zastavice, None, False)
        velja = self._uveljavi_rezervo()
        self._drzim[razlog] = (zastavice, None, velja)
        return velja

    def po_dejavnosti(self, razlog: str = "pomoc", opis: str = "", okno_s: float = 150.0) -> bool:
        """Delo za druge naprave: zadrzi spanje, dokler je bila dejavnost (dotik) v zadnjih `okno_s` sekundah."""
        return self.nastavi(razlog, SPANJE if dejavno(razlog, okno_s) else 0, opis)

    def sprosti_vse(self) -> None:
        for razlog in list(self._drzim):
            self.nastavi(razlog, 0)

    def stanje(self) -> Dict[str, int]:
        """razlog -> zastavice za zadrzanja, ki res veljajo (za preizkuse in dnevnik)."""
        return {razlog: z for razlog, (z, _rocaj, velja) in self._drzim.items() if velja}

    # ---- notranje ----
    def _zapri_zahtevo(self, rocaj: int, zastavice: int) -> None:
        k = self._jedro
        for tip in _tipi(zastavice):
            try:
                k.pocisti_zahtevo(rocaj, tip)
            except Exception:  # noqa: BLE001
                pass
        try:
            k.zapri(rocaj)
        except Exception:  # noqa: BLE001
            pass

    def _sprosti(self, zapis: Tuple[int, Optional[int], bool]) -> None:
        zastavice, rocaj, _velja = zapis
        if rocaj is not None:
            self._zapri_zahtevo(rocaj, zastavice)
            _log.info("budnost: zahteva sproscena")
        elif self._jedro is not None:
            self._uveljavi_rezervo()

    def _uveljavi_rezervo(self) -> bool:
        """SetThreadExecutionState za vse razloge brez zahteve moci hkrati (unija zastavic). Vrne, ali velja."""
        unija = 0
        for z, rocaj, _velja in self._drzim.values():
            if rocaj is None:
                unija |= z
        es = _stanje_niti(unija)
        if es == self._nit_es:
            return es != ES_CONTINUOUS
        try:
            ok = self._jedro.stanje_niti(es) != 0
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            self._nit_es = es
        return ok and es != ES_CONTINUOUS


_skupna: Optional[Budnost] = None


def budnost() -> Budnost:
    """Ena Budnost na proces (Medijski center, samostojni predvajalnik)."""
    global _skupna
    if _skupna is None:
        _skupna = Budnost("Safeer")
    return _skupna


def zastavice_predvajanja(p: Optional[dict]) -> int:
    """Podatki pogona -> zastavice: predvaja -> SPANJE, ce ima posnetek sliko, se ZASLON (kot Linux
    _budnost_predvajanja). Premor, konec in napaka -> 0. Slika: steze.slika (izbrana video sled, ki ni naslovnica
    albuma), sicer vrsta vnosa."""
    p = p or {}
    if p.get("stanje") != "predvaja":
        return 0
    steze = p.get("steze") or {}
    if "slika" in steze:
        slika = bool(steze.get("slika"))
    else:
        slika = p.get("vrsta") in ("video", "tv")
    return SPANJE | (ZASLON if slika else 0)


def ob_predvajanju(razlog: str, p: Optional[dict]) -> None:
    """Predvajalnik jo poklice ob vsaki spremembi stanja (nit vmesnika). Napaka nikoli ne ustavi predvajanja."""
    try:
        budnost().nastavi(razlog, zastavice_predvajanja(p), "Safeer predvaja")
    except Exception as e:  # noqa: BLE001
        _log.debug("budnost: %s", e)


def sprosti(razlog: str) -> None:
    """Predvajalnik je ustavljen ali zaprt."""
    try:
        budnost().nastavi(razlog, 0)
    except Exception as e:  # noqa: BLE001
        _log.debug("budnost: %s", e)
