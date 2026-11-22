"""Filter vira Usenet v mrezi Medijskega centra (lastnik 10. 11. 2026: »vse uskladi tako kot je na TV«).

Izbira »⚡ Usenet« v izbirniku virov FILTRIRA mrezo Filmi/Serije: vidni so samo naslovi, za katere indeksator vrne izdajo,
ki jo ta naprava predvaja (core/filter_vira_pravila.lahko_gleda). Zrcali Android UsenetFilter.kt (zapisi, omejevalnik,
delavci) in GlasbaActivity.preveriUsenet/praznoUsenet (proracun mreze, vrstni red, napis prazne mreze). Cista pravila
so v filter_vira_pravila - tu je samo stanje (zapisi na disku, niti, ura).

Zakaj tako: indeksatorji stejejo klice API na dan in minuto (NZBFinder ~60/min). Namizje zato ne sme vprasati vec kot TV
za isto mrezo: najvec F.HKRATI hkrati, F.NA_MINUTO na minuto za vse mreze skupaj, F.PRORACUN_MREZE novih vprasanj na
zahtevo uporabnika (odprtje mreze, Nalozi vec) in enkrat se F.VNAPREJ_MREZE v ozadju. NA_VOLJO ne potece, negativni
zapis velja 6 h (F.NI_VELJA)."""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import filter_vira_pravila as F
from . import kakovost_oznake as K
from . import tok_izbira
from . import usenet_pravila as U

_log = logging.getLogger("safeer.usenet_filter")

IME_DATOTEKE = "usenet_filter.json"
NAJVEC_ZAPISOV = 3000
#: Ponoven poskus po kvoti ali zamiku »ne vemo« - en sam, kot TV (postDelayed 30 s).
PONOVNO_S = 30.0
#: Mrezo po izidu preverbe osvezimo zdruzeno (TV narociUmiri): vec izidov v tem casu = en dogodek.
UMIRI_S = 0.4


def _zdaj_ms() -> int:
    return int(time.time() * 1000)


def pogoji() -> F.Pogoji:
    """Pogoji, ki jih pot predvajanja »samo Usenet« res zahteva: samodejna izbira vzame izdaje do 15 GB (TV pogoji())."""
    return F.Pogoji(F.VIR_USENET, najvec_gb=U.NAJVEC_GB_SAMODEJNO)


class UsenetFilter:
    """Zapisi in preverbe v ozadju (Android UsenetFilter). [dbr] ima filter_racun(), filter_iskanje(id, rok) in
    odtis_racuna(); [ura] vrne ms, [spi] caka s (preizkusi ju podajo); [izvajalec] za preizkuse."""

    def __init__(self, pot: Optional[Path], dbr: Any, ura: Callable[[], int] = _zdaj_ms,
                 izvajalec: Optional[Any] = None, spi: Callable[[float], None] = time.sleep) -> None:
        self.pot = Path(pot) if pot else None
        self.dbr = dbr
        self.ura = ura
        self.spi = spi
        self._zapisi: Dict[str, F.Zapis] = {}
        self._nalozeno = False
        self._zaklep = threading.RLock()
        # Del A (TV 7. 11. 2026): zadnja mesta na minuto ostanejo za iskanje ob kliku uporabnika.
        self.omejevalnik = F.Omejevalnik(F.NA_MINUTO, zadrzano=F.REZERVIRANO_UPORABNIKU)
        self._v_teku: set = set()
        self._kliki = F.StevecKlikov()
        #: Zahtev indeksatorju od zagona (dnevnik in preizkus stevila klicev).
        self.porabljeno = 0
        self._izvajalec = izvajalec or ThreadPoolExecutor(max_workers=F.HKRATI, thread_name_prefix="usenet-filter")

    # ------------------------------------------------------------------ zapisi na disku
    def _nalozi(self) -> None:
        if self._nalozeno:
            return
        with self._zaklep:
            if self._nalozeno:
                return
            podatki: Dict[str, Any] = {}
            if self.pot is not None:
                try:
                    podatki = json.loads(self.pot.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    podatki = {}
            if isinstance(podatki, dict):
                for k, v in podatki.items():
                    z = F.iz_niza(v)
                    if z is not None and isinstance(k, str):
                        self._zapisi[k] = z
            if len(self._zapisi) > NAJVEC_ZAPISOV:
                for k, _ in sorted(self._zapisi.items(), key=lambda kv: kv[1].cas)[:len(self._zapisi) - NAJVEC_ZAPISOV]:
                    del self._zapisi[k]
            self._nalozeno = True

    def _shrani_disk(self) -> None:
        if self.pot is None:
            return
        try:
            from . import shramba_json
            self.pot.parent.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.pot, {k: F.v_niz(z) for k, z in self._zapisi.items()}, sinhrono=False)
        except Exception as e:  # noqa: BLE001 - zapis je predpomnilnik: brez diska se naslov preveri znova
            _log.warning("zapis: %s", type(e).__name__)

    def _shrani(self, k: str, z: F.Zapis) -> None:
        with self._zaklep:
            self._zapisi[k] = z
            self._shrani_disk()

    def zapis(self, k: str) -> Optional[F.Zapis]:
        self._nalozi()
        return self._zapisi.get(k)

    def pokazi(self, k: str) -> bool:
        # Pomocnika v Linku za Usenet namizje se nima (TV UsenetPomocniki): izdaje samo za pomocnika se ne pokazejo.
        return F.pokazi(self.zapis(k), self.ura(), False)

    def oznaka(self, k: str) -> Optional[K.Oznaka]:
        z = self.zapis(k)
        return z.oznaka if z is not None and F.pokazi(z, self.ura(), False) else None

    def se_iscemo(self, k: str) -> bool:
        return k in self._v_teku or F.se_iscemo(self.zapis(k), self.ura())

    def vprasati(self, k: str) -> bool:
        return k not in self._v_teku and F.vprasati(self.zapis(k), self.ura())

    def v_teku(self) -> int:
        return len(self._v_teku)

    def v_premoru(self) -> bool:
        return self.omejevalnik.v_premoru(self.ura())

    def pozabi(self, k: str) -> None:
        """Predvajanje samo Usenet ni naslo izdaje: zapis pozabimo, naslov izgine in se preveri znova."""
        self._nalozi()
        with self._zaklep:
            if self._zapisi.pop(k, None) is not None:
                self._shrani_disk()

    # ------------------------------------------------------------------ klik ima prednost (TV Del A)
    def zacni_klik(self) -> None:
        self._kliki.zacni()

    def prednost_klika(self) -> None:
        self.omejevalnik.ustavi_preverbe(self.ura(), F.PREMOR_PREVERB_MS)

    def prednost_klika_konec(self) -> None:
        if self._kliki.konec():
            self.omejevalnik.sprosti_preverbe()

    def rezerviraj_iskanje(self) -> Optional[int]:
        """Mesto za iskanje ob kliku: ms cakanja ali None = indeksator je v premoru (meja)."""
        ms = self.omejevalnik.rezerviraj_uporabniku(self.ura())
        if ms is not None:
            self.porabljeno += 1
        return ms

    def izid_klika(self, meja: bool, odgovoril: bool) -> None:
        if meja:
            self.omejevalnik.meja(self.ura())
        elif odgovoril:
            self.omejevalnik.uspeh(self.ura())

    # ------------------------------------------------------------------ preverba enega naslova
    def preveri(self, k: str, ident: Callable[[], Optional[str]], z: tok_izbira.Zmoznosti,
                se_velja: Callable[[], bool], ob_koncu: Callable[[], None]) -> bool:
        """Preveri naslov [k] v ozadju (TV UsenetFilter.preveri). False = zdaj ne smemo (kvota, ze v teku, polno) -
        takrat ni zapisa in ni klica [ob_koncu]."""
        self._nalozi()
        with self._zaklep:
            if not self.vprasati(k) or len(self._v_teku) >= F.HKRATI:
                return False
            # Tu kvote ne porabimo (samo pogledamo) - porabi jo zahteva, ki gre res indeksatorju.
            if not self.omejevalnik.lahko(self.ura()):
                return False
            self._v_teku.add(k)
        try:
            self._izvajalec.submit(self._delo, k, ident, z, se_velja, ob_koncu)
        except RuntimeError:
            with self._zaklep:
                self._v_teku.discard(k)
            return False
        return True

    def _delo(self, k: str, ident: Callable[[], Optional[str]], z: tok_izbira.Zmoznosti,
              se_velja: Callable[[], bool], ob_koncu: Callable[[], None]) -> None:
        try:
            if not se_velja():
                return
            racun = F.Izid.NA_VOLJO if self.dbr.filter_racun() else F.Izid.NE_VEMO
            try:
                iden = ident()
            except Exception:  # noqa: BLE001
                iden = None
            iscemo = iden is not None and U.iscemo(iden)
            poslji = F.poslji(racun, iden, iscemo)
            id_dnevnik = iden if iscemo else "-"      # v dnevnik samo id IMDb, nikoli kljuc ali naslov indeksatorja
            izdaje = None
            odgovor = None
            if poslji:
                cakaj = self.omejevalnik.rezerviraj(self.ura())
                if cakaj is None:
                    # Kvoto je med cakanjem v vrsti porabil kdo drug: brez zahteve in brez zapisa.
                    _log.info("preverba: id=%s, odlozeno (kvota)", id_dnevnik)
                    return
                if cakaj > 0:
                    self.spi(cakaj / 1000.0)        # razmik med zahtevami (F.RAZMIK_MS), delovna nit
                self.porabljeno += 1
                r = self.dbr.filter_iskanje(iden, F.ROK_MS / 1000.0)
                if r.meja:
                    self.omejevalnik.meja(self.ura())
                elif r.izdaje is not None:
                    self.omejevalnik.uspeh(self.ura())
                if r.izdaje is not None:
                    izdaje = [F.Izdaja(x.naslov, x.velikost / 1073741824.0, getattr(x, "geslo", None)) for x in r.izdaje]
                odgovor = r.razlog or None
            pv = F.preverba(F.Izidi(racun, F.Odgovor(izdaje)), pogoji(), z)
            self._shrani(k, F.zapisi(self._zapisi.get(k), pv.izid, pv.oznaka, self.ura(), pv.pomoc))
            razlog = (F.razlog_ne_vemo(racun, iden, iscemo, poslji, odgovor) or "?") if pv.izid == F.Izid.NE_VEMO else "-"
            _log.info("preverba: id=%s, izdaj=%d, izid=%s, razlog=%s, zahtev od zagona=%d", id_dnevnik,
                      -1 if izdaje is None else len(izdaje), pv.izid.value, razlog, self.porabljeno)
        except Exception as e:  # noqa: BLE001 - preverba v ozadju ne sme podreti mreze
            _log.warning("preverba: %s", type(e).__name__)
        finally:
            with self._zaklep:
                self._v_teku.discard(k)
            try:
                ob_koncu()
            except Exception as e:  # noqa: BLE001 - osvezitev mreze ne sme ustaviti delovne niti
                _log.warning("po preverbi: %s", type(e).__name__)


# ---------------------------------------------------------------------- mreza (TV GlasbaActivity.preveriUsenet)

def ident_vnosa(naslov: Optional[tuple]) -> Optional[str]:
    """Id iskanja kot ob predvajanju (os_media._usenet_mogoc): film tt…; serija prva epizoda tt…:1:1 (TV
    epizodaZaPreverbo brez znanega ogleda). Brez id-ja IMDb vrne None - preverba ne poslje zahteve (razlog ni_imdb)."""
    if naslov is None:
        return None
    _, tip, ident = naslov
    if tip == "movie":
        return ident
    if tip == "series" and ":" not in ident:
        return F.id_iskanja_epizode(F.Epizoda(ident + ":1:1", 1, 1), ident)
    return None


class Mreza:
    """Stanje odprte mreze s filtrom: kandidati po vrstnem redu mreze, proracun zahteve in strani za tiho osvezitev."""

    def __init__(self, ident: str) -> None:
        self.ident = ident
        self.zahteva = 0
        self.proracun: Optional[F.Proracun] = None
        self.kandidati: List[tuple] = []          # (kljuc zapisa, id iskanja ali None)
        self._znani: set = set()
        self.strani: Dict[int, tuple] = {}         # stran -> (neprecisceni rezultat, ob_osvezitvi)
        self.narocen = False
        self.umiri: Optional[threading.Timer] = None


class FilterMreze:
    """Uporabi filter na rezultat kataloga (os_katalog._katalog) in vodi preverbe kot TV (en filter, ena odprta mreza)."""

    def __init__(self, filt: UsenetFilter, kljuc_naslova: Callable[[dict], str], naslov: Callable[[dict], Optional[tuple]],
                 zmoznosti: Callable[[], tok_izbira.Zmoznosti]) -> None:
        self.filt = filt
        self._kljuc_naslova = kljuc_naslova
        self._naslov = naslov
        self._zmoznosti = zmoznosti
        self.mreza: Optional[Mreza] = None
        self._zaklep = threading.RLock()
        #: Za preizkuse: brez casovnikov (ponovni poskus, zdruzena osvezitev) - preizkus jih sprozi sam.
        self.casovniki = True

    def _kljuc(self, item: dict) -> Optional[str]:
        """Kljuc zapisa: vir + odtis racuna + naslov. Samo film ali serija iz dodatka (TV kljucUsenet: Stremio.razstavi) -
        drugo predvajanje samo Usenet ne zna, zato se v filtru ne pokaze."""
        kn = self._kljuc_naslova(item)
        if not kn or self._naslov(item) is None:
            return None
        return F.kljuc_ogleda(F.kljuc(F.VIR_USENET, self.filt.dbr.odtis_racuna(), kn), None)

    def prikazi(self, mreza: str, stran: int, rezultat: Any, od_uporabnika: bool,
                ob_osvezitvi: Optional[Callable[[dict], None]] = None) -> Any:
        """Precisceni rezultat strani; [od_uporabnika] = uporabnik je odprl mrezo ali zahteval naslednjo stran (nov
        proracun kot TV »Nalozi vec«), sicer tiha osvezitev kataloga (brez novega proracuna)."""
        if not isinstance(rezultat, dict) or not isinstance(rezultat.get("vnosi"), list):
            return rezultat
        with self._zaklep:
            m = self.mreza
            if m is None or m.ident != mreza:
                m = self.mreza = Mreza(mreza)
            if od_uporabnika:
                if stran <= 1:
                    # Odprtje mreze: zapomnjene strani ne veljajo (nov vrstni red), proracun od zacetka.
                    m.strani = {k: v for k, v in m.strani.items() if k == 1}
                    m.zahteva += 1
                elif stran not in m.strani and m.proracun is not None and m.proracun.ostalo <= 0 and m.proracun.vnaprej:
                    m.zahteva += 1                       # TV »Nalozi vec«: nova zahteva sele, ko je prejsnja porabljena
            m.strani[stran] = (rezultat, ob_osvezitvi)
            for item in rezultat["vnosi"]:
                if not isinstance(item, dict):
                    continue
                k = self._kljuc(item)
                if k is None or k in m._znani:
                    continue
                m._znani.add(k)
                m.kandidati.append((k, ident_vnosa(self._naslov(item))))
        self.preveri(m)
        return self.preciscen(m, rezultat)

    def preciscen(self, m: Mreza, rezultat: dict) -> dict:
        vnosi = []
        for item in rezultat.get("vnosi") or []:
            if not isinstance(item, dict):
                continue
            k = self._kljuc(item)
            if k is None or not self.filt.pokazi(k):
                continue
            o = self.filt.oznaka(k)
            # Znacka kartice: najboljsa ustrezna izdaja Useneta, nikoli kakovost iz kataloga ali drugih virov (TV 6707).
            vnosi.append(dict(item, oznaka_vira=K.napis_kartice(o) if o is not None else ""))
        novo = {k: v for k, v in rezultat.items() if k != "skupaj"}
        novo["vnosi"] = vnosi
        novo["usenet_filter"] = {"prazno": self.prazno(m).value}
        return novo

    def prazno(self, m: Mreza) -> F.Prazno:
        """TV praznoUsenet: Iscem / indeksator ne odgovarja / ni naslovov."""
        ustavljeno = not self.filt.dbr.filter_racun() or self.filt.v_premoru()
        p = m.proracun
        iscemo = self.filt.v_teku() > 0 or self.mreza is not m or (
            (p.ostalo if p else 0) > 0 and any(self.filt.se_iscemo(k) for k, _ in m.kandidati))
        ne_odgovarja = ustavljeno or any((self.filt.zapis(k) or F.Zapis(F.Izid.NA_VOLJO, 0)).izid == F.Izid.NE_VEMO
                                         for k, _ in m.kandidati)
        return F.prazno(iscemo and not ustavljeno, ne_odgovarja)

    def preveri(self, m: Mreza) -> None:
        """TV preveriUsenet: kandidati po vrsti, najvec HKRATI hkrati in proracun zahteve."""
        with self._zaklep:
            if self.mreza is not m:
                return
            ista = m.proracun is not None
            prej = m.proracun
            m.proracun = F.proracun(prej if ista else None, ista, m.zahteva)
            if not self.filt.dbr.filter_racun():
                _log.info("krog %d: brez preverb - racun Usenet ni na voljo", m.zahteva)
                return
            z = self._zmoznosti()
            pozneje = False
            zacetih = 0
            for k, iden in list(m.kandidati):
                p = m.proracun
                if p.ostalo <= 0 or self.filt.v_teku() >= F.HKRATI:
                    break
                if not self.filt.vprasati(k):
                    if self.filt.se_iscemo(k):
                        pozneje = True
                    continue
                # Proracun zmanjsamo PRED oddajo: izid lahko pride takoj (in sprozi naslednji krog) se pred vrnitvijo.
                m.proracun = F.Proracun(p.zahteva, p.ostalo - 1, p.vnaprej)
                if self.filt.preveri(k, (lambda i=iden: i), z, lambda: self.mreza is m, lambda: self._po_preverbi(m)):
                    zacetih += 1
                else:
                    q = m.proracun
                    m.proracun = F.Proracun(q.zahteva, q.ostalo + 1, q.vnaprej)
                    pozneje = True
                    break
            prednalozi = m.proracun.ostalo == 0 and not m.proracun.vnaprej
            if prednalozi and self.filt.v_teku() < F.HKRATI:
                self.preveri(m)                  # enkrat se VNAPREJ_MREZE (F.proracun)
            if pozneje and not m.narocen and m.proracun.ostalo > 0 and self.casovniki:
                m.narocen = True
                t = threading.Timer(PONOVNO_S, self._ponovno, args=(m,))
                t.daemon = True
                t.start()

    def _ponovno(self, m: Mreza) -> None:
        m.narocen = False
        self._po_preverbi(m)

    def _po_preverbi(self, m: Mreza) -> None:
        if self.mreza is not m:
            return
        self.preveri(m)
        if not self.casovniki:
            self.osvezi(m)
            return
        with self._zaklep:
            if m.umiri is not None:
                return
            m.umiri = threading.Timer(UMIRI_S, self._umirjeno, args=(m,))
            m.umiri.daemon = True
            m.umiri.start()

    def _umirjeno(self, m: Mreza) -> None:
        with self._zaklep:
            m.umiri = None
        self.osvezi(m)

    def osvezi(self, m: Mreza) -> None:
        """Strani te mreze znova (dogodek mediaKatalogOsvezen z istim kljucem: stran jih tiho zamenja)."""
        if self.mreza is not m:
            return
        for _, (rezultat, ob) in sorted(m.strani.items()):
            if ob is not None:
                try:
                    ob(self.preciscen(m, rezultat))
                except Exception as e:  # noqa: BLE001
                    _log.warning("osvezitev: %s", type(e).__name__)
