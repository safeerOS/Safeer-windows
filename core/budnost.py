"""Računalnik naj ne zaspi sam, dokler Safeer predvaja ali dela za drugo napravo.

Zadržimo samo SAMODEJNO spanje ob nedejavnosti, med videom tudi ohranjevalnik zaslona, zaklep in ugašanje zaslona -
tako kot vsak predvajalnik. Zaprt pokrov in ročno spanje delujeta kot vedno: prenosnik v torbi mora zaspati.
Zadržanje velja, dokler živi naša povezava z vodilom seje; če se program sesuje, ga upravitelj seje sprosti sam.

Vmesniki po vrsti: org.gnome.SessionManager (Cinnamon, GNOME, MATE - en klic za spanje in zaslon), sicer
org.freedesktop.PowerManagement.Inhibit (spanje) in org.freedesktop.ScreenSaver (zaslon) - KDE, Xfce. Kjer ni nobenega,
se ne zgodi nič (in ne poskušamo znova ob vsakem klicu).
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

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


class Budnost:
    """Zadržanja samodejnega spanja po razlogih (»predvajanje«, »pomoc«); vsak razlog ima največ eno."""

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
