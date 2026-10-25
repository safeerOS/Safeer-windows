"""Skupni dispecer metod mosta Safeer OS: ime metode -> funkcija, za HTML in QML, na Linuxu in Windows.

Lastnik, 25. 10. 2026: »Kar velja za eno okolje, mora veljati za drugo.« Vmesnik (assets/os) klice zaledje po imenu
(klic("novaMapa", [...])). Do zdaj je vsaka platforma imela svoj seznam: Linux slovarje v safeer_os._obdelaj_klic,
Windows verigo if v os_app._izvedi_metodo in namizje_win.metode - ista metoda je bila napisana dvakrat, z razlikami
(npr. Windows ne oznaci indeksa datotek kot zastarelega po novi mapi).

Tu so metode, ki so na obeh platformah SAMO klic jedra (core/), z enakimi argumenti - preverjeno 25. 10. 2026 v
Linux delo-133 d13659b in Windows delo-windows 45ba26a (scripts/most_pregled.py, primerjava teles metod). Gostitelj
(safeer_os.py, os_app.py, namizje_qml.py) ustvari Dispecer s kontekstom (objekt z atributi sporocila, scit, lupa)
in z imeni svojih metod; zmoznosti() pove vmesniku, kaj ta platforma zna (ima() v assets/os/most.js), zato vmesnik
gumb za neznano metodo skrije namesto da bi ga pokazal pokvarjenega.

Nit: »glavna« = gostitelj klic izvede v glavni niti (kot na Linuxu danes), »ozadje« = v delovni niti.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

#: Metode mostu, po katerih je indeks imen datotek (core/os_iskalnik.py) zastarel - isti seznam kot
#: safeer_os.SafeerOS.SPREMINJAJO_DATOTEKE (Linux), da ga uporabi tudi Windows.
SPREMINJAJO_DATOTEKE = frozenset({"novaMapa", "novaDatoteka", "preimenujDatoteko", "vSmeti", "vSmetiVec",
                                  "prilepiDatoteke", "obnoviIzSmeti", "razveljaviDatoteke", "nadaljujTukaj",
                                  "prenesiDatotekoNaprave"})


class Metoda(NamedTuple):
    funkcija: Callable[[Any, list], Any]
    nit: str                       # "glavna" ali "ozadje"
    potrebuje: Tuple[str, ...]     # atributi konteksta (sporocila, scit, lupa); brez njih metode ni


def _s(a: list, i: int = 0, privzeto: str = "") -> str:
    """Argument kot niz; manjkajoc ali null -> privzeto (kot namizje_win._s na Windows)."""
    return str(a[i]) if len(a) > i and a[i] is not None else privzeto


def _b(a: list, i: int, privzeto: bool = False) -> bool:
    return bool(a[i]) if len(a) > i else privzeto


def magnet_klic(delo: Callable[[], Any]) -> dict:
    """Klic motorja za magnet: napaka gre strani kot kratka koda (prevede jo stran). Prej dvakrat (safeer_os._magnet_klic
    in os_app._magnet_klic), enako."""
    from core import os_torrent
    try:
        izid = delo()
        return dict(izid, ok=True) if isinstance(izid, dict) else {"ok": bool(izid)}
    except os_torrent.NapakaTorrenta as e:
        return {"ok": False, "koda": str(e)}
    except Exception as e:  # noqa: BLE001
        print("[SafeerOS] magnet:", e, flush=True)
        return {"ok": False, "koda": "napaka"}


def _meja_iskanja(a: list) -> int:
    from core import os_datoteke
    if len(a) > 1 and isinstance(a[1], (int, float)) and not isinstance(a[1], bool):
        return min(300, max(1, int(a[1])))
    return os_datoteke.NAJVEC_ZADETKOV


def _datoteke():
    from core import os_datoteke
    return os_datoteke


def _torrenti():
    from core import os_torrent
    return os_torrent.torrenti()


SKUPNE: Dict[str, Metoda] = {}


def _m(ime: str, funkcija: Callable[[Any, list], Any], nit: str = "ozadje", potrebuje: Tuple[str, ...] = ()) -> None:
    SKUPNE[ime] = Metoda(funkcija, nit, tuple(potrebuje))


# ------------------------------------------------------------------ datoteke (core/os_datoteke, os_iskalnik)
_m("novaMapa", lambda k, a: _datoteke().ustvari_mapo(_s(a), _s(a, 1)))
_m("novaDatoteka", lambda k, a: _datoteke().ustvari_datoteko(_s(a), _s(a, 1), _s(a, 2, "prazna"), _s(a, 3)))
_m("preimenujDatoteko", lambda k, a: _datoteke().preimenuj(_s(a), _s(a, 1)))
_m("lastnostiDatoteke", lambda k, a: _datoteke().lastnosti(_s(a)))
_m("prilepiDatoteke", lambda k, a: _datoteke().prilepi(a[0] if a and isinstance(a[0], list) else [], _s(a, 1), _b(a, 2)))
_m("razveljaviDatoteke", lambda k, a: _datoteke().razveljavi(a[0] if a and isinstance(a[0], dict) else {}))
_m("najvecjeDatoteke", lambda k, a: _datoteke().najvecje())
# »Pokazi v mapi«: os_datoteke.pokazi_v_mapi gre prek core/platforma.py (Nemo / Raziskovalec z oznaceno datoteko).
_m("pokaziVMapi", lambda k, a: _datoteke().pokazi_v_mapi(_s(a)))
_m("isciDatoteke", lambda k, a: __import__("core.os_iskalnik", fromlist=["isci"]).isci(_s(a), _meja_iskanja(a)))
# ------------------------------------------------------------------ sistem (core/sistem_podatki: Linux in Windows veja)
_m("diski", lambda k, a: __import__("core.sistem_podatki", fromlist=["diski"]).diski())
_m("sistemPodatki", lambda k, a: __import__("core.sistem_podatki", fromlist=["podatki"]).podatki())
_m("dvdPogoni", lambda k, a: __import__("core.os_dvd", fromlist=["pogoni"]).pogoni(), nit="glavna")
# ------------------------------------------------------------------ lupa (core/os_lupa.Ucenje gostitelja)
_m("lupaUcenje", lambda k, a: k.lupa.podatki(), nit="glavna", potrebuje=("lupa",))
_m("lupaZapomni", lambda k, a: k.lupa.zapomni(*(list(a or [])[:3])), nit="glavna", potrebuje=("lupa",))
# ------------------------------------------------------------------ Scit (core/os_scit.Scit ali scit_odjemalec gostitelja)
_m("scit", lambda k, a: k.scit.stanje(), potrebuje=("scit",))
# ------------------------------------------------------------------ magnet (core/os_torrent)
_m("magnetPreberi", lambda k, a: magnet_klic(lambda: _torrenti().preberi(_s(a))))
_m("magnetPremor", lambda k, a: _torrenti().premor(int(a[0])))
_m("magnetNadaljuj", lambda k, a: magnet_klic(lambda: _torrenti().nadaljuj(int(a[0]))))
_m("magnetOdstrani", lambda k, a: _torrenti().odstrani(int(a[0]), _b(a, 1)))
_m("magnetDeliNaprej", lambda k, a: _torrenti().deli_naprej(str(a[0]), _b(a, 1)) or True)
_m("magnetPovezava", lambda k, a: magnet_klic(lambda: {"uri": _torrenti().magnet(int(a[0]))}))
# ------------------------------------------------------------------ Sporocila (core/os_sporocila.SporocilaOS gostitelja)
# Samo metode z enakim podpisom v obeh kopijah core/os_sporocila.py (preverjeno z ast 25. 10. 2026). Poslji in
# Ponudniki se se razlikujeta (Linux: priloge, jezik) - pridejo sem po uskladitvi jedra (krog 3).
_SP = ("sporocila",)
_m("sporocilaSeznam", lambda k, a: k.sporocila.seznam(_s(a)), nit="glavna", potrebuje=_SP)
_m("sporocilaPogovor", lambda k, a: k.sporocila.pogovor(str(a[0]), str(a[1]), a[2] is not False if len(a) > 2 else True),
   potrebuje=_SP)
_m("sporocilaDodaj", lambda k, a: k.sporocila.dodaj_kanal(a[0] if a and isinstance(a[0], dict) else {}), potrebuje=_SP)
_m("sporocilaIsci", lambda k, a: k.sporocila.isci(_s(a)), potrebuje=_SP)
_m("sporocilaIsciPri", lambda k, a: k.sporocila.isci_pri_osebi(str(a[0]), str(a[1]), _s(a, 2), _s(a, 3)), potrebuje=_SP)
_m("sporocilaIzbrisi", lambda k, a: k.sporocila.izbrisi_sporocilo(str(a[0]), str(a[1]), str(a[2]), _b(a, 3)), potrebuje=_SP)
_m("sporocilaNaprave", lambda k, a: k.sporocila.naprave_za_klepet(), potrebuje=_SP)
_m("sporocilaOdstrani", lambda k, a: k.sporocila.odstrani_kanal(str(a[0])), potrebuje=_SP)
_m("sporocilaOsebe", lambda k, a: k.sporocila.osebe(), potrebuje=_SP)
_m("sporocilaOznake", lambda k, a: k.sporocila.nastavi_oznake(str(a[0]), str(a[1]), a[2] if len(a) > 2 else []),
   potrebuje=_SP)
_m("sporocilaPreimenuj", lambda k, a: k.sporocila.preimenuj_osebo(str(a[0]), str(a[1])), potrebuje=_SP)
_m("sporocilaRazdruzi", lambda k, a: k.sporocila.razdruzi_osebo(str(a[0]), a[1]), potrebuje=_SP)
_m("sporocilaSinhroniziraj", lambda k, a: k.sporocila.sinhroniziraj(), potrebuje=_SP)
_m("sporocilaSkrivnost", lambda k, a: k.sporocila.nastavi_skrivnost(str(a[0]), str(a[1])), potrebuje=_SP)
_m("sporocilaStreznik", lambda k, a: k.sporocila.privzeta_streznika(_s(a)), potrebuje=_SP)
_m("sporocilaZacni", lambda k, a: k.sporocila.zacni_klepet(str(a[0]), _s(a, 1)), potrebuje=_SP)
_m("sporocilaZdruzi", lambda k, a: k.sporocila.zdruzi_osebi(str(a[0]), str(a[1])), potrebuje=_SP)


class Dispecer:
    """Skupne metode + imena metod gostitelja. Gostitelj klice zna() / nit() / klic(); zmoznosti() gre vmesniku.

    kontekst: objekt z atributi, ki jih metode potrebujejo (sporocila, scit, lupa) - manjkajoc atribut (None) pomeni,
    da te metode na tej napravi ni (npr. Scit izklopljen v paketu brez Scita). platformne: imena metod, ki jih
    gostitelj izvede sam (platformne razlike, okna, motor) - vstopijo samo v zmoznosti()."""

    def __init__(self, kontekst: Any = None, platformne: Iterable[str] = (), platforma: Optional[str] = None) -> None:
        self.kontekst = kontekst
        self._platformne = frozenset(str(x) for x in platformne)
        if platforma is None:
            from core import platforma as _p
            platforma = _p.IME
        self.platforma = platforma

    def _ima_kontekst(self, m: Metoda) -> bool:
        return all(getattr(self.kontekst, ime, None) is not None for ime in m.potrebuje)

    def zna(self, metoda: str) -> bool:
        """Ali metodo izvede ta dispecer (skupna metoda, za katero ima kontekst vse potrebno)."""
        m = SKUPNE.get(metoda)
        return metoda == "zmoznosti" or (m is not None and self._ima_kontekst(m))

    def nit(self, metoda: str) -> str:
        m = SKUPNE.get(metoda)
        return m.nit if m is not None else "ozadje"

    def klic(self, metoda: str, a: Optional[list] = None) -> Any:
        """Izvede skupno metodo. Neznana (ali brez konteksta): KeyError - gostitelj jo izvede sam ali vrne »neznano«."""
        a = list(a) if isinstance(a, (list, tuple)) else []
        if metoda == "zmoznosti":
            return self.odgovor_zmoznosti()
        m = SKUPNE.get(metoda)
        if m is None or not self._ima_kontekst(m):
            raise KeyError(metoda)
        return m.funkcija(self.kontekst, a)

    def zmoznosti(self) -> List[str]:
        """Vse metode, ki jih platforma zna: skupne (s kontekstom) + gostiteljeve + »zmoznosti«."""
        skupne = {ime for ime, m in SKUPNE.items() if self._ima_kontekst(m)}
        return sorted(skupne | self._platformne | {"zmoznosti"})

    def odgovor_zmoznosti(self) -> dict:
        """Odgovor metode »zmoznosti« za assets/os/most.js: platforma (za html[data-platforma]) in seznam metod."""
        return {"platforma": self.platforma, "metode": self.zmoznosti()}
