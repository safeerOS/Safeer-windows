"""Računalnik naj ne zaspi sam, dokler Safeer predvaja ali dela za drugo napravo.

Zadržimo samo SAMODEJNO spanje ob nedejavnosti, med videom tudi ohranjevalnik zaslona, zaklep in ugašanje zaslona -
tako kot vsak predvajalnik. Zaprt pokrov in ročno spanje delujeta kot vedno: prenosnik v torbi mora zaspati.
Zadržanje velja, dokler živi naša povezava z vodilom seje; če se program sesuje, ga upravitelj seje sprosti sam.

Linux - vmesniki po vrsti: org.gnome.SessionManager (Cinnamon, GNOME, MATE - en klic za spanje in zaslon), sicer
org.freedesktop.PowerManagement.Inhibit (spanje) in org.freedesktop.ScreenSaver (zaslon) - KDE, Xfce. Kjer ni nobenega,
se ne zgodi nič (in ne poskušamo znova ob vsakem klicu).

Windows (skupna koda z Safeer-windows, 25. 10. 2026; prej loceno v windows/safeer_windows/budnost_win.py):
PowerCreateRequest + PowerSetRequest (kernel32, od Windows 7; isti mehanizem kot Chromium/Edge) - zahteva pripada rocaju,
ob sesutju jo sistem sprosti sam, razlog je viden v `powercfg /requests`; rezerva SetThreadExecutionState. Budnost()
izbere zaledje po platformi; vmesnik (nastavi, po_dejavnosti, sprosti_vse, stanje) je isti.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

_log = logging.getLogger("safeer.budnost")

#: Samodejno spanje ob nedejavnosti (zastavica upravitelja seje »suspend«).
SPANJE = 4
#: Ohranjevalnik zaslona, zaklep in ugašanje zaslona ob nedejavnosti (zastavica »idle«).
ZASLON = 8

#: Kdaj je računalnik nazadnje delal za drugo napravo (pošiljal datoteko ali tok, pretvarjal), po razlogu.
_dejavnost: Dict[str, float] = {}


def dotik(razlog: str = "pomoc") -> None:
    """Računalnik ta trenutek dela za drugo napravo. Kliče se iz niti strežnika ob vsakem poslanem kosu, zato samo
    zapiše čas; zadržanje spanja uredi glavna nit (Budnost.po_dejavnosti)."""
    _dejavnost[razlog] = time.monotonic()


def dejavno(razlog: str = "pomoc", okno_s: float = 150.0) -> bool:
    """Ali je bila dejavnost za `razlog` v zadnjih `okno_s` sekundah."""
    kdaj = _dejavnost.get(razlog)
    return kdaj is not None and time.monotonic() - kdaj <= okno_s


#: Povezava z vodilom seje. Držimo jo ves čas: zadržanje pripada povezavi - če bi jo po klicu spustili (GDBus skupno
#: povezavo zapre, ko je nihče več ne drži), bi upravitelj seje zadržanje takoj odstranil.
_vodilo = None


def _klic_seje(storitev: str, pot: str, vmesnik: str, metoda: str, podpis: str, vrednosti: tuple, vrne: Optional[str]):
    """Sinhron klic na vodilu seje. Vrne terko vrednosti ali sproži izjemo (storitve ni, napaka)."""
    global _vodilo
    from gi.repository import Gio, GLib  # noqa: WPS433 - sele ob prvi rabi
    if _vodilo is None or _vodilo.is_closed():
        _vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    izid = _vodilo.call_sync(storitev, pot, vmesnik, metoda, GLib.Variant(podpis, vrednosti),
                             GLib.VariantType(vrne) if vrne else None, Gio.DBusCallFlags.NONE, 1500, None)
    return izid.unpack() if izid is not None else ()


class BudnostDbus:
    """Linux (D-Bus): zadržanja samodejnega spanja po razlogih (»predvajanje«, »pomoc«); vsak razlog ima največ eno."""

    def __init__(self, program: str = "Safeer", klic: Optional[Callable] = None) -> None:
        self.program = program
        self._klic = klic or _klic_seje
        #: razlog -> (zastavice, [(vmesnik, žeton), ...]); prazen seznam = namizje zadržanja ne pozna.
        self._drzim: Dict[str, Tuple[int, List[Tuple[str, int]]]] = {}

    def nastavi(self, razlog: str, zastavice: int, opis: str = "") -> bool:
        """Zadrži (SPANJE in/ali ZASLON) ali sprosti (0) samodejno spanje za `razlog`. Enako stanje ne naredi nič,
        zato se sme klicati vsako sekundo. Vrne, ali zadržanje res velja."""
        zastavice = int(zastavice) & (SPANJE | ZASLON)
        staro = self._drzim.get(razlog)
        if staro is not None and staro[0] == zastavice:
            return bool(staro[1])
        if staro is not None:
            self._sprosti(staro[1])
            del self._drzim[razlog]
        if not zastavice:
            return False
        zetoni = self._zadrzi(zastavice, opis or self.program)
        self._drzim[razlog] = (zastavice, zetoni)
        return bool(zetoni)

    def po_dejavnosti(self, razlog: str = "pomoc", opis: str = "", okno_s: float = 150.0) -> bool:
        """Delo za druge naprave: zadrži spanje, dokler je bila dejavnost (dotik) v zadnjih `okno_s` sekundah."""
        return self.nastavi(razlog, SPANJE if dejavno(razlog, okno_s) else 0, opis)

    def sprosti_vse(self) -> None:
        for razlog in list(self._drzim):
            self.nastavi(razlog, 0)

    def stanje(self) -> Dict[str, int]:
        """razlog -> zastavice za zadržanja, ki res veljajo (za preizkuse in dnevnik)."""
        return {razlog: z for razlog, (z, zetoni) in self._drzim.items() if zetoni}

    def _zadrzi(self, zastavice: int, opis: str) -> List[Tuple[str, int]]:
        try:
            (zeton,) = self._klic("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
                                  "Inhibit", "(susu)", (self.program, 0, opis, zastavice), "(u)")
            return [("seja", int(zeton))]
        except Exception:  # noqa: BLE001 - namizje brez upravitelja seje GNOME: ločena vmesnika
            pass
        zetoni: List[Tuple[str, int]] = []
        if zastavice & SPANJE:
            try:
                (zeton,) = self._klic("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit",
                                      "org.freedesktop.PowerManagement.Inhibit", "Inhibit", "(ss)", (self.program, opis), "(u)")
                zetoni.append(("napajanje", int(zeton)))
            except Exception:  # noqa: BLE001
                pass
        if zastavice & ZASLON:
            try:
                (zeton,) = self._klic("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                                      "org.freedesktop.ScreenSaver", "Inhibit", "(ss)", (self.program, opis), "(u)")
                zetoni.append(("zaslon", int(zeton)))
            except Exception:  # noqa: BLE001
                pass
        return zetoni

    def _sprosti(self, zetoni: List[Tuple[str, int]]) -> None:
        for vmesnik, zeton in zetoni:
            try:
                if vmesnik == "seja":
                    self._klic("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
                               "Uninhibit", "(u)", (zeton,), None)
                elif vmesnik == "napajanje":
                    self._klic("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit",
                               "org.freedesktop.PowerManagement.Inhibit", "UnInhibit", "(u)", (zeton,), None)
                else:
                    self._klic("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                               "org.freedesktop.ScreenSaver", "UnInhibit", "(u)", (zeton,), None)
            except Exception:  # noqa: BLE001 - seja se končuje ali storitve ni več: žeton je tako ali tako mrtev
                pass


# ---------------------------------------------------------------------------------------------------------- Windows
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


class BudnostWindows:
    """Windows: zadrzanja samodejnega spanja po razlogih (»predvajanje«, »predvajalnik«, »pomoc«); vsak razlog ima
    najvec eno zahtevo moci. Enako stanje ne naredi nic, zato se sme klicati ob vsaki spremembi predvajanja.
    SPANJE = samodejno spanje ob nedejavnosti; ZASLON = se ugasanje zaslona (in zaklep, ki mu sledi). Zaprt pokrov, gumb
    za vklop in rocno spanje delujejo kot vedno. Rezerva SetThreadExecutionState velja za KLICOCO nit, zato modul
    nastavi skupno stanje vseh razlogov naenkrat; predvajalniki ga klicejo iz niti vmesnika."""

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


def Budnost(program: str = "Safeer", klic: Optional[Callable] = None, jedro=None):  # noqa: N802 - ime ostane (klicatelji)
    """Zaledje po platformi: Windows -> zahteve moci (kernel32), sicer D-Bus. [klic] = lazni klic D-Bus (preizkus Linuxa),
    [jedro] = lazni kernel32 (preizkus Windows - dela tudi na Linuxu)."""
    if jedro is not None or (klic is None and _je_windows()):
        return BudnostWindows(program, jedro)
    return BudnostDbus(program, klic)
