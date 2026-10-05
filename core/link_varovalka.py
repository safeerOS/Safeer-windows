"""Safeer Link: varovalka kode za povezavo.

Sestmestna koda (900.000 moznosti) je edina skrivnost v Safeer Linku, ki jo je mogoce ugibati. Seznanitev tece po
SPAKE2: vsak krog (``/cast/pair/spake``) napravi pove, ali je njena koda prava - en krog je en poskus. Prijava dovoli
pet krogov, prijav pa je bilo lahko poljubno. Obramba (``link_obramba``) steje po viru: kdor hiti, je ustavljen, kdor
ostane pod pragom ali menja naslov v domacem omrezju, pa ne - ena naprava je lahko poskusila vec sto kod na uro.

Varovalka zato steje VSE poskuse kode in VSE zacetke prijave skupaj, ne glede na vir:

* v eni uri najvec ``POSKUSOV`` neuspelih poskusov kode in ``ZACETKOV`` zacetkov prijave (vsak zacetek uporabniku
  pokaze kodo na zaslonu). Uspesna seznanitev svoj poskus in svoj zacetek vrne - domace povezovanje ne steje;
* ko je meja dosezena, se povezovanje s kodo ZAPRE: prvic za eno uro, drugic za en dan, potem za en teden. Po zapori
  veljata manjsi meji (``POSKUSOV_PO_ZAPORI``, ``ZACETKOV_PO_ZAPORI``), dokler ne mine ``POZABI_S`` brez nove zapore;
* med zaporo se nova naprava poveze samo, ce je uporabnik na eni od svojih naprav odprl »Povezi naprave« (vabilo):
  to je izrecno dejanje zaupane naprave. Tudi takrat je poskusov najvec ``KREDIT_VABILA`` na zaporo;
* povezava s kodo QR ni prizadeta: njena skrivnost ima 128 bitov in je ni mogoce uganiti.

Stanje prezivi ponovni zagon (``shrani``/``stanje``): sicer bi vsak zagon sredisca napadalcu vrnil polno mejo.

Ista pravila ima ``HubVarovalka.kt`` na Androidu; ista preizkusa sta ``tests/test_link_varovalka.py`` in
``tests/HubVarovalkaTest.kt``.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

#: Okno stetja.
OKNO_S = 3600.0
#: Neuspelih poskusov kode v oknu, preden se povezovanje s kodo zapre; manjsa meja velja po zapori.
POSKUSOV = 20
POSKUSOV_PO_ZAPORI = 5
#: Zacetkov prijave v oknu (vsak pokaze kodo na zaslonu); manjsa meja velja po zapori.
ZACETKOV = 30
ZACETKOV_PO_ZAPORI = 10
#: Trajanje prve, druge in vsake naslednje zapore.
ZAPORE_S: Tuple[float, ...] = (3600.0, 86400.0, 7 * 86400.0)
#: Toliko casa po koncu zadnje zapore se stetje ponovitev zacne znova.
POZABI_S = 30 * 86400.0
#: Poskusov kode med zaporo, kadar je uporabnik na svoji napravi odprl »Povezi naprave«.
KREDIT_VABILA = 10
#: Koliko virov nasteje dogodek ob zapori (najpogostejsi najprej).
NAJVEC_VIROV = 3

Zapis = Tuple[float, str]


class VarovalkaKode:
    """Skupna omejitev ugibanja kode. Brez omrezja in brez datotek - oboje ji da sredisce."""

    def __init__(self, ura: Callable[[], float] = time.time, stanje: Optional[dict] = None,
                 shrani: Optional[Callable[[dict], None]] = None,
                 ob_zapori: Optional[Callable[[dict], None]] = None) -> None:
        self.ura = ura
        self._shrani = shrani
        #: Klic ob zapori: {"trajanje_s", "razlog" ("kode" | "zacetki"), "ponovitev", "viri": [(vir, stevilo)]}.
        self.ob_zapori = ob_zapori
        self._zaklep = threading.Lock()
        self._poskusi: List[Zapis] = []
        self._zacetki: List[Zapis] = []
        self._zaprto_do = 0.0
        self._ponovitev = 0
        self._kredit = 0
        self._uvozi(stanje)

    # ------------------------------------------------------------------ stanje na disku

    def _uvozi(self, stanje: Optional[dict]) -> None:
        if not isinstance(stanje, dict):
            return

        def zapisi(kljuc: str) -> List[Zapis]:
            izid: List[Zapis] = []
            for z in stanje.get(kljuc) or []:
                try:
                    izid.append((float(z[0]), str(z[1])[:64]))
                except (TypeError, ValueError, IndexError):
                    continue
            return izid[-max(POSKUSOV, ZACETKOV):]

        try:
            self._poskusi = zapisi("poskusi")
            self._zacetki = zapisi("zacetki")
            self._zaprto_do = float(stanje.get("zaprto_do") or 0.0)
            self._ponovitev = max(0, min(int(stanje.get("ponovitev") or 0), 1000))
            self._kredit = max(0, min(int(stanje.get("kredit") or 0), KREDIT_VABILA))
        except (TypeError, ValueError):
            self._poskusi, self._zacetki, self._zaprto_do, self._ponovitev, self._kredit = [], [], 0.0, 0, 0

    def izvozi(self) -> dict:
        with self._zaklep:
            return self._izvoz()

    def _izvoz(self) -> dict:
        return {"poskusi": [[t, v] for t, v in self._poskusi], "zacetki": [[t, v] for t, v in self._zacetki],
                "zaprto_do": self._zaprto_do, "ponovitev": self._ponovitev, "kredit": self._kredit}

    def _zapisi(self) -> None:
        """Klice se pod kljucavnico. Napaka pri pisanju varovalke ne ustavi."""
        if self._shrani is None:
            return
        try:
            self._shrani(self._izvoz())
        except Exception:
            pass

    # ------------------------------------------------------------------ pravila

    def _pocisti(self, zdaj: float) -> None:
        """Klice se pod kljucavnico. Zapis iz »prihodnosti« (ura je sla nazaj) velja za pravkar narejenega."""
        meja = zdaj - OKNO_S
        self._poskusi = [(min(t, zdaj), v) for t, v in self._poskusi if min(t, zdaj) > meja]
        self._zacetki = [(min(t, zdaj), v) for t, v in self._zacetki if min(t, zdaj) > meja]
        if self._zaprto_do > zdaj + ZAPORE_S[-1]:
            self._zaprto_do = zdaj + ZAPORE_S[-1]
        if self._ponovitev and self._zaprto_do <= zdaj and zdaj - self._zaprto_do > POZABI_S:
            self._ponovitev = 0

    def _meji(self) -> Tuple[int, int]:
        return (POSKUSOV_PO_ZAPORI, ZACETKOV_PO_ZAPORI) if self._ponovitev else (POSKUSOV, ZACETKOV)

    def _zapri(self, zdaj: float, razlog: str) -> dict:
        """Klice se pod kljucavnico. Vrne dogodek za ``ob_zapori``."""
        trajanje = ZAPORE_S[min(self._ponovitev, len(ZAPORE_S) - 1)]
        stetje: Dict[str, int] = {}
        for _t, vir in (self._poskusi if razlog == "kode" else self._zacetki):
            if vir:
                stetje[vir] = stetje.get(vir, 0) + 1
        viri = sorted(stetje.items(), key=lambda par: (-par[1], par[0]))[:NAJVEC_VIROV]
        self._ponovitev += 1
        self._zaprto_do = zdaj + trajanje
        self._kredit = KREDIT_VABILA
        self._poskusi, self._zacetki = [], []
        self._zapisi()
        return {"trajanje_s": trajanje, "razlog": razlog, "ponovitev": self._ponovitev, "viri": viri}

    def _sporoci(self, dogodek: Optional[dict]) -> None:
        if dogodek is None or self.ob_zapori is None:
            return
        try:
            self.ob_zapori(dogodek)
        except Exception:
            pass

    def zaprto(self) -> bool:
        with self._zaklep:
            return self.ura() < self._zaprto_do

    def sme_zaceti(self, vabilo: bool = False) -> bool:
        """Ali sme nova naprava zdaj zaceti prijavo s kodo (brez stetja)."""
        with self._zaklep:
            zdaj = self.ura()
            self._pocisti(zdaj)
            if zdaj >= self._zaprto_do:
                return True
            return bool(vabilo) and self._kredit > 0

    def zacetek(self, vir: str = "", vabilo: bool = False) -> bool:
        """Nova naprava zacenja prijavo s kodo. False = povezovanje s kodo je zaprto (prijave se ne odpre)."""
        dogodek = None
        with self._zaklep:
            zdaj = self.ura()
            self._pocisti(zdaj)
            if zdaj < self._zaprto_do:
                return bool(vabilo) and self._kredit > 0
            self._zacetki.append((zdaj, str(vir or "")[:64]))
            if len(self._zacetki) >= self._meji()[1]:
                dogodek = self._zapri(zdaj, "zacetki")
            else:
                self._zapisi()
        self._sporoci(dogodek)
        if dogodek is not None:
            # Zacetek, ki je sprozil zaporo, velja le, ce je uporabnik sam odprl »Povezi naprave«.
            return bool(vabilo)
        return True

    def poskus(self, vir: str = "", vabilo: bool = False) -> bool:
        """En krog SPAKE2 = en poskus kode. False = poskusa ne izvedemo (povezovanje s kodo je zaprto)."""
        dogodek = None
        with self._zaklep:
            zdaj = self.ura()
            self._pocisti(zdaj)
            if zdaj < self._zaprto_do:
                if not vabilo or self._kredit <= 0:
                    return False
                self._kredit -= 1
                self._zapisi()
                return True
            self._poskusi.append((zdaj, str(vir or "")[:64]))
            if len(self._poskusi) >= self._meji()[0]:
                dogodek = self._zapri(zdaj, "kode")
                if vabilo:
                    self._kredit -= 1
                    self._zapisi()
            else:
                self._zapisi()
        self._sporoci(dogodek)
        if dogodek is not None:
            return bool(vabilo)
        return True

    def uspeh(self, vir: str = "") -> None:
        """Seznanitev je uspela: njen poskus in njen zacetek ne stejeta (koda je bila prava)."""
        with self._zaklep:
            zdaj = self.ura()
            self._pocisti(zdaj)
            vir = str(vir or "")[:64]
            if zdaj < self._zaprto_do:
                self._kredit = min(KREDIT_VABILA, self._kredit + 1)
            for seznam in (self._poskusi, self._zacetki):
                for i in range(len(seznam) - 1, -1, -1):
                    if seznam[i][1] == vir:
                        del seznam[i]
                        break
            self._zapisi()

    def odpri(self) -> None:
        """Uporabnik je zaporo sam koncal. Stetje ponovitev ostane: naslednja zapora je daljsa."""
        with self._zaklep:
            zdaj = self.ura()
            if zdaj < self._zaprto_do:
                self._zaprto_do = zdaj
                self._kredit = 0
                self._zapisi()

    def stanje(self) -> dict:
        with self._zaklep:
            zdaj = self.ura()
            self._pocisti(zdaj)
            meja_poskusov, meja_zacetkov = self._meji()
            zaprto = zdaj < self._zaprto_do
            return {"zaprto": zaprto, "se_s": int(self._zaprto_do - zdaj) if zaprto else 0,
                    "poskusov": len(self._poskusi), "meja_poskusov": meja_poskusov,
                    "zacetkov": len(self._zacetki), "meja_zacetkov": meja_zacetkov,
                    "ponovitev": self._ponovitev, "kredit": self._kredit if zaprto else 0}
