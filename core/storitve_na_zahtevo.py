"""Storitve na zahtevo, hisna opravila in ena ura za ves proces (lastnik, 18. 10. 2026; ideja iz lahkega IDE Lithe:
storitev se zazene sele, ko jo rabis).

Safeer OS je en proces (lupina, Control, Splet, predvajalnik - core/en_proces.py). Kar ta proces dela v ozadju, je
tu na enem mestu, da ga stran safeer://procesi pokaze (tece / ustavljena, kdaj nazadnje uporabljena, kdaj se ustavi):

* VEDNO       varuje uporabnika ali mora biti takoj dosegljivo od drugih naprav: Scit, sprejem Safeer Linka, varuh
              pomnilnika, posodobitve, Sporocila (obvestila ob prijavi - lastnik, 15. 10. 2026). V registru samo za prikaz.
* NA_ZAHTEVO  zazene se ob prvi rabi (storitev sama, ob klicu `rabi`) in se ustavi, ko je `mirovanje_s` ni nihce
              uporabljal in `zaposlena()` ne pravi drugace (prenos, predvajanje, deljenje ...).
* opravilo    hisno opravilo na `razmik_s` (ciscenje prenosov, ki jih nihce ne gleda): tece v kratki niti samo takrat,
              ko je na vrsti. Prej je imelo vsako opravilo svojo nit, ki je ves dan spala (2 niti na proces).

Ura je ena: GLib.timeout_add_seconds na glavni zanki (Safeer OS) ali, brez GLib, ena nit. Vsakih TIK_S preveri
mirovanje storitev in rok opravil ter vzame vzorec porabe za zgodovino strani procesov (core/poraba_zgodovina.py).
Meritev (vsebnik, Xvfb, 18. 10. 2026): vzorec drevesa stane ~0,09 ms na proces (Safeer OS z Linkom 0,8 ms, 108 procesov
9 ms), na 30 s je to pod 0,03 % jedra; zgodovina ure je 17 kB na proces.

Klici `tece`, `zaposlena` in `pidi` morajo biti poceni in ne smejo cakati na omrezje (ura tece na glavni niti);
ustavljanje (lahko caka na konec podprocesa) gre v kratko nit. Brez GTK - preizkusljivo.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

#: Ura registra (s). 30 s: rok mirovanja storitev je v minutah, zgodovina porabe ima 120 vzorcev na uro.
TIK_S = 30

VEDNO = "vedno"
NA_ZAHTEVO = "zahteva"

#: Zakaj storitev ostane vedno (kljuci besedil na strani procesov).
VARUJE = "varuje"            # Scit, varuh pomnilnika, posodobitve
DOSEGLJIVOST = "dosegljivost"  # sprejem Safeer Linka: druge naprave morajo racunalnik najti in doseci
OBVESTILA = "obvestila"      # Sporocila: nova sporocila in obvestila takoj po prijavi
TAKOJ = "takoj"              # indeks iskanja: prvo iskanje brez cakanja


class Storitev:
    """Ena storitev v registru. `zadnja_raba` je time.time() zadnje rabe (0 = v tem zagonu se ni bila uporabljena)."""

    def __init__(self, ime: str, vrsta: str = NA_ZAHTEVO, mirovanje_s: float = 0.0,
                 tece: Optional[Callable[[], bool]] = None, ustavi: Optional[Callable[[], None]] = None,
                 zaposlena: Optional[Callable[[], bool]] = None, pidi: Optional[Callable[[], List[int]]] = None,
                 razlog: str = "") -> None:
        self.ime = ime
        self.vrsta = vrsta
        self.mirovanje_s = float(mirovanje_s or 0.0)
        self._tece = tece
        self._ustavi = ustavi
        self._zaposlena = zaposlena
        self._pidi = pidi
        self.razlog = razlog
        self.zadnja_raba = 0.0
        self.ustavljena_ob = 0.0
        self.ustavitev = 0
        self._ustavljam = False

    def tece(self) -> bool:
        if self._tece is None:
            return self.vrsta == VEDNO
        try:
            return bool(self._tece())
        except Exception:  # noqa: BLE001 - prikaz in ura ne smeta pasti zaradi ene storitve
            return False

    def zaposlena(self) -> bool:
        if self._zaposlena is None:
            return False
        try:
            return bool(self._zaposlena())
        except Exception:  # noqa: BLE001 - pri dvomu storitve ne ustavimo
            return True

    def pidi(self) -> List[int]:
        if self._pidi is None:
            return []
        try:
            return [int(p) for p in (self._pidi() or []) if int(p) > 0]
        except Exception:  # noqa: BLE001
            return []

    def podatki(self, zdaj: Optional[float] = None) -> dict:
        """Za stran procesov: ime, vrsta, tece, zadnja raba (s nazaj ali None), rok mirovanja, razlog, PID-i."""
        zdaj = time.time() if zdaj is None else zdaj
        tece = self.tece()
        return {"ime": self.ime, "vrsta": self.vrsta, "tece": tece,
                "zadnja_raba_s": (max(0.0, zdaj - self.zadnja_raba) if self.zadnja_raba else None),
                "mirovanje_s": self.mirovanje_s, "razlog": self.razlog, "pidi": self.pidi() if tece else [],
                "ustavitev": self.ustavitev}


class _Opravilo:
    def __init__(self, ime: str, delo: Callable[[], None], razmik_s: float, zamik_s: float) -> None:
        self.ime = ime
        self.delo = delo
        self.razmik_s = float(razmik_s)
        self.naslednje = time.monotonic() + float(zamik_s)
        self.tece = False
        self.zadnje = 0.0       # time.time() konca zadnjega teka


_zaklep = threading.RLock()
_storitve: Dict[str, Storitev] = {}
_opravila: Dict[str, _Opravilo] = {}
_ura: dict = {"glib": None, "id": 0, "nit": None, "stop": None, "ime": ""}
#: Kaj klice ura ob vsakem tiku poleg storitev in opravil (zgodovina porabe): [fn()].
_ob_tiku: List[Callable[[], None]] = []


def registriraj(ime: str, vrsta: str = NA_ZAHTEVO, mirovanje_s: float = 0.0, tece=None, ustavi=None,
                zaposlena=None, pidi=None, razlog: str = "") -> Storitev:
    """Doda storitev (ali zamenja klice obstojece z istim imenom - zadnja raba ostane). Vrne storitev."""
    with _zaklep:
        prej = _storitve.get(ime)
        s = Storitev(ime, vrsta, mirovanje_s, tece, ustavi, zaposlena, pidi, razlog)
        if prej is not None:
            s.zadnja_raba, s.ustavljena_ob, s.ustavitev = prej.zadnja_raba, prej.ustavljena_ob, prej.ustavitev
        _storitve[ime] = s
    return s


def odjavi(ime: str) -> None:
    with _zaklep:
        _storitve.pop(ime, None)


def rabi(ime: str, zdaj: Optional[float] = None) -> None:
    """Storitev je bila pravkar uporabljena (ali se je zagnala): rok mirovanja se zacne znova."""
    with _zaklep:
        s = _storitve.get(ime)
        if s is not None:
            s.zadnja_raba = time.time() if zdaj is None else zdaj


def storitev(ime: str) -> Optional[Storitev]:
    with _zaklep:
        return _storitve.get(ime)


def stanje(zdaj: Optional[float] = None) -> List[dict]:
    """Vse storitve za stran procesov, najprej tiste, ki tecejo."""
    with _zaklep:
        vse = list(_storitve.values())
    izid = [s.podatki(zdaj) for s in vse]
    return sorted(izid, key=lambda d: (not d["tece"], d["vrsta"] != VEDNO, d["ime"]))


def opravilo(ime: str, delo: Callable[[], None], razmik_s: float, zamik_s: float = 0.0) -> None:
    """Hisno opravilo: prvic po `zamik_s`, nato vsakih `razmik_s` - v kratki niti, ki se po koncu konca. Ce ura se ne
    tece, jo zazene (nit; Safeer OS jo pozneje preklopi na GLib, glej zacni)."""
    with _zaklep:
        if ime not in _opravila:
            _opravila[ime] = _Opravilo(ime, delo, razmik_s, zamik_s)
    _zagotovi_uro()


def opravila() -> List[dict]:
    with _zaklep:
        return [{"ime": o.ime, "razmik_s": o.razmik_s, "tece": o.tece, "zadnje": o.zadnje} for o in _opravila.values()]


def ob_tiku(fn: Callable[[], None]) -> None:
    """`fn()` ob vsakem tiku ure (zgodovina porabe). Enkrat na funkcijo."""
    with _zaklep:
        if fn not in _ob_tiku:
            _ob_tiku.append(fn)


def ime_procesa() -> str:
    """Kako se proces imenuje na strani procesov (»Safeer OS«, »Safeer Control«); '' = brez registra (Safeer Browser)."""
    return _ura["ime"]


# ---------------------------------------------------------------------- ura
def tik(zdaj_mono: Optional[float] = None, zdaj: Optional[float] = None) -> None:
    """En pregled: mirujoce storitve ustavi (v kratki niti), opravila na vrsti zazene, poklice ob_tiku."""
    zdaj_mono = time.monotonic() if zdaj_mono is None else zdaj_mono
    zdaj = time.time() if zdaj is None else zdaj
    with _zaklep:
        storitve = list(_storitve.values())
        opr = list(_opravila.values())
        dodatno = list(_ob_tiku)
    for s in storitve:
        if s.vrsta != NA_ZAHTEVO or s.mirovanje_s <= 0 or s._ustavi is None or s._ustavljam or not s.tece():
            continue
        if s.zaposlena():
            s.zadnja_raba = zdaj          # dela (prenos, predvajanje): rok mirovanja steje od konca dela
            continue
        if not s.zadnja_raba:
            s.zadnja_raba = zdaj          # tece, a ni javila rabe: rok steje od prvega pregleda
            continue
        if zdaj - s.zadnja_raba >= s.mirovanje_s:
            _ustavi_v_ozadju(s)
    for o in opr:
        if not o.tece and zdaj_mono >= o.naslednje:
            o.tece = True
            o.naslednje = zdaj_mono + o.razmik_s
            threading.Thread(target=_tek_opravila, args=(o,), name="safeer-opravilo", daemon=True).start()
    for fn in dodatno:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - ura ne sme obstati
            print("[Storitve] ob tiku:", e, flush=True)


def _ustavi_v_ozadju(s: Storitev) -> None:
    s._ustavljam = True

    def delo() -> None:
        try:
            s._ustavi()
            s.ustavljena_ob = time.time()
            s.ustavitev += 1
            print("[Storitve] %s: ustavljena po %d s mirovanja" % (s.ime, int(s.mirovanje_s)), flush=True)
        except Exception as e:  # noqa: BLE001
            print("[Storitve] %s: ustavitev ni uspela: %s" % (s.ime, e), flush=True)
        finally:
            s._ustavljam = False
    threading.Thread(target=delo, name="safeer-storitev-ustavi", daemon=True).start()


def _tek_opravila(o: _Opravilo) -> None:
    try:
        o.delo()
    except Exception as e:  # noqa: BLE001 - opravilo se ponovi ob naslednjem roku
        print("[Storitve] opravilo %s: %s" % (o.ime, e), flush=True)
    finally:
        o.zadnje = time.time()
        o.tece = False


def zacni(GLib=None, ime: str = "") -> None:
    """Zazene uro procesa (enkrat). Z GLib na glavni zanki (brez niti); brez nje ena nit. Ce je ura ze tekla kot nit
    (opravilo je bilo dodano pred zagonom aplikacije), jo GLib zamenja."""
    with _zaklep:
        if ime and not _ura["ime"]:
            _ura["ime"] = ime
        if GLib is not None and _ura["glib"] is None:
            stop = _ura["stop"]
            if stop is not None:
                stop.set()
                _ura["nit"] = _ura["stop"] = None
            _ura["glib"] = GLib

            def tik_glib() -> bool:
                tik()
                return True
            _ura["id"] = GLib.timeout_add_seconds(TIK_S, tik_glib)
            return
    _zagotovi_uro()


def _zagotovi_uro() -> None:
    with _zaklep:
        if _ura["glib"] is not None or _ura["nit"] is not None:
            return
        stop = threading.Event()

        def zanka() -> None:
            while not stop.wait(TIK_S):
                try:
                    tik()
                except Exception as e:  # noqa: BLE001
                    print("[Storitve] ura:", e, flush=True)
        _ura["stop"] = stop
        _ura["nit"] = threading.Thread(target=zanka, name="safeer-storitve", daemon=True)
        _ura["nit"].start()


def ustavi_uro() -> None:
    """Za preizkuse in konec procesa: ura se ustavi, register ostane."""
    with _zaklep:
        glib, ident, stop = _ura["glib"], _ura["id"], _ura["stop"]
        _ura.update(glib=None, id=0, nit=None, stop=None)
    if stop is not None:
        stop.set()
    if glib is not None and ident:
        try:
            glib.source_remove(ident)
        except Exception:  # noqa: BLE001
            pass


def _za_preizkus() -> None:
    """Prazen register in ustavljena ura (preizkusi)."""
    ustavi_uro()
    with _zaklep:
        _storitve.clear()
        _opravila.clear()
        _ob_tiku.clear()
        _ura["ime"] = ""


# ---------------------------------------------------------------------- Safeer OS
def vezi_safeer_os(app, GLib) -> None:
    """Safeer OS (do_startup): ura na glavni zanki, zgodovina porabe od zagona in storitve, ki tecejo VEDNO (samo za
    prikaz - zakaj ostanejo, je v VARUJE/DOSEGLJIVOST/OBVESTILA/TAKOJ). Storitve na zahtevo (torrent, Teamwork), indeks
    iskanja (os_iskalnik) in hisna opravila se registrirajo same v svojih modulih. Klici berejo samo atribute (brez
    D-Bus in omrezja)."""
    zacni(GLib, "Safeer OS")
    from core import poraba_zgodovina
    poraba_zgodovina.skupna()

    def scit_tece() -> bool:
        r = getattr(getattr(app, "scit", None), "razresevalnik", None)
        return bool(r is not None and getattr(r, "vrata", 0))

    def link_tece() -> bool:
        from core import en_proces
        c = en_proces.control_app()
        link = getattr(c, "link", None) if c is not None else None
        if link is None:
            return False
        g = getattr(link, "_hub_gostitelj", None)
        return getattr(link, "povezava", None) is not None or bool(g is not None and g.streznik.tece())

    def sporocila_tecejo() -> bool:
        return getattr(app, "_kanali_sporocil", None) is not None

    registriraj("scit", VEDNO, tece=scit_tece, razlog=VARUJE)
    registriraj("link", VEDNO, tece=link_tece, razlog=DOSEGLJIVOST)
    registriraj("varuh", VEDNO, razlog=VARUJE)
    registriraj("posodobitve", VEDNO, razlog=VARUJE)
    registriraj("sporocila", VEDNO, tece=sporocila_tecejo, razlog=OBVESTILA)
    # Torrent se zares registrira ob prvi rabi (os_torrent.Torrenti); do takrat ga stran pokaze kot »ni zagnan«.
    from core import os_torrent
    if storitev("torrent") is None:
        registriraj("torrent", NA_ZAHTEVO, os_torrent.MIROVANJE_S, tece=lambda: False)
    if storitev("torrent_naprave") is None:
        registriraj("torrent_naprave", NA_ZAHTEVO, os_torrent.MIROVANJE_S, tece=lambda: False)
