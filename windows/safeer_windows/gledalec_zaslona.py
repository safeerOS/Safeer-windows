"""Zavihek Spleta, v katerem Safeer OS pokaze deljen zaslon druge naprave (share.screen).

Do 1.0.39 je gledalec zamenjal stran v zavihku, ki ga je imel uporabnik odprtega, ob koncu pa je stran spraznil in
se vedno vrnil na Domov. Konec, ki je prisel pred nalozeno stranjo, zavihka sploh ni zaprl (izmerjeno 5. 10. 2026:
na zaslonu je ostala stran z napako). Zdaj:

  * gledalec dobi SVOJ zavihek - uporabnikovi zavihki ostanejo, kot so bili;
  * ob koncu deljenja se zapre natanko ta zavihek; ce uporabnik pred deljenjem ni bil v Spletu, se Safeer OS vrne v
    razdelek, kjer je bil; ce je bil v Spletu, ostane tam pri svojih zavihkih;
  * zavihka, v katerem je uporabnik medtem odprl nekaj svojega, ne zapremo; ce ga je zaprl sam, ni kaj storiti;
  * konec, ki prehiti odpiranje, odpiranje preklice.

Razred ne pozna Qt: okno dobi kot funkcije, zato je preizkusljiv brez zaslona.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

#: Del naslova strani gledalca pri vsakem sredisci (Android in racunalnik): /cast/screen/<id>/view?k=...
POT_GLEDALCA = "/cast/screen/"


def je_gledalec(naslov: str) -> bool:
    return POT_GLEDALCA in str(naslov or "")


class GledalecZaslona:
    def __init__(self, *, nov_zavihek: Callable[[str], Any], zapri_zavihek: Callable[[Any], bool],
                 je_trenutni: Callable[[Any], bool], naslov: Callable[[Any], str], v_spletu: Callable[[], bool],
                 preberi_razdelek: Callable[[Callable[[str], None]], None], pokazi_splet: Callable[[], None],
                 vrni_v_os: Callable[[str], None]) -> None:
        self._nov_zavihek = nov_zavihek
        self._zapri_zavihek = zapri_zavihek
        self._je_trenutni = je_trenutni
        self._naslov = naslov
        self._v_spletu = v_spletu
        self._preberi_razdelek = preberi_razdelek
        self._pokazi_splet = pokazi_splet
        self._vrni_v_os = vrni_v_os
        self._zavihek: Optional[Any] = None
        #: Stevec zahtev: konec ali novo deljenje razveljavi odpiranje, ki se caka na odgovor strani.
        self._zahteva = 0
        #: Razdelek Safeer OS pred deljenjem ("splet" = uporabnik je bil ze v Spletu).
        self._prej = ""

    def odprt(self) -> bool:
        return self._zavihek is not None

    def odpri(self, url: str) -> None:
        """Zacetek deljenja: stran gledalca v novem zavihku. Prejsnji gledalec (novo deljenje) se zapre brez vrnitve."""
        prej = self._prej if self.zapri(vrni=False) else ""
        zahteva = self._zahteva
        if prej:
            self._odpri(zahteva, url, prej)          # gledalca menjamo: velja razdelek pred PRVIM deljenjem
        elif self._v_spletu():
            self._odpri(zahteva, url, "splet")
        else:
            self._preberi_razdelek(lambda razdelek: self._odpri(zahteva, url, str(razdelek or "") or "domov"))

    def _odpri(self, zahteva: int, url: str, prej: str) -> None:
        if zahteva != self._zahteva or self._zavihek is not None:
            return                                   # konec ali novo deljenje je prehitelo odgovor strani
        self._prej = prej
        self._zavihek = self._nov_zavihek(url)
        self._pokazi_splet()

    def zapri(self, vrni: bool = True) -> bool:
        """Konec deljenja. Vrne True, ce je zaprl zavihek gledalca."""
        self._zahteva += 1
        zavihek, self._zavihek = self._zavihek, None
        if zavihek is None:
            return False
        try:
            if not je_gledalec(self._naslov(zavihek)):
                return False                         # uporabnik je v tem zavihku odprl nekaj svojega
            bil_trenutni = bool(self._je_trenutni(zavihek))
            if not self._zapri_zavihek(zavihek):
                return False                         # zaprl ga je ze sam
        except RuntimeError:
            return False                             # pogled je ze unicen (zavihek zaprt)
        if vrni and bil_trenutni and self._v_spletu() and self._prej != "splet":
            self._vrni_v_os(self._prej or "domov")
        return True
