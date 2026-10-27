"""Bralnik za lasten pogon Usenet, korak 2: bajti filma z nakljucnim dostopom iz NZB (lastnik 26. 10. 2026).

Prototip 25. 10. 2026 (NzbDAV): za 60 s ogleda (~50 MiB s predpomnilnikom predvajalnika) je slo z Useneta 167-344 MiB,
tudi po zaprtju povezave - za TV in mobilne podatke nesprejemljivo. Tu:
- Okno vnaprej je OMEJENO in raste z zaporednim branjem: po odprtju ali skoku samo zacetno okno (predvajalnik pogosto
  prebere le glavo, indeks na koncu datoteke ali nekaj KiB po skoku), nato dvakratnik zaporedno prebranega do meje
  profila (okno_vnaprej; skupni primeri tok_okno). Ob skoku se cakajoca branja vnaprej zunaj novega okna zavrzejo.
- Segmenti hkrati prek bazena (usenet_nntp.Bazen) z lastnimi nitmi: zahtevano branje ima prednost pred branjem vnaprej.
- LRU v RAM z mejo po profilu naprave; zapri() ne caka na zahteve v teku (na Windows Bazen.zapri() zahteve v teku ne
  prekine - izmerjeno 26. 10. 2026, preizkusa test_zapiranje_prekine_* padeta) - niti so demonske in odvrzejo izid.
- message-id in imena niso v repr, izjemi ali dnevniku.

Naloga 76 (pregleda 71 L1 in 72 N1): ali izdaja gre v mejo prometa priprave, odloci preveri_izdajo PRED ponudbo (iz NZB
brez omrezja in po prvem clanku); priprava rezervira promet pred vsakim zvezkom in ne bere zvezkov za koncem filma.
"""

from __future__ import annotations

import heapq
from bisect import bisect_right
import itertools
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from . import usenet_rar as R
from .usenet_nntp import NI_CLANKA, NapakaNntp
from .usenet_nzb import Datoteka, Nzb
from .usenet_tok import (IZVEN, LUKNJA, NAJVEC_ISKANJ, NESKLADNO, POKVARJEN, PREKINJENO, PREVEC, ZAPRTO, NapakaToka,
                         Preslikava)
from .usenet_yenc import NapakaYenc, dekodiraj

_log = logging.getLogger("safeer.usenet")

MiB = 1024 * 1024


@dataclass(frozen=True)
class Profil:
    okno_bajtov: int  # najvecje okno vnaprej
    zacetno_okno: int  # okno po odprtju ali skoku
    lru_bajtov: int  # dekodirani segmenti v RAM
    vzporedno: int  # hkratnih branj segmentov


#: Po profilu naprave (lastnik: 8-16 MiB vnaprej; TV ima malo RAM - Philips: heapgrowthlimit 192 MB).
PROFILI = {
    "tv": Profil(8 * MiB, 1 * MiB, 32 * MiB, 4),
    "telefon": Profil(8 * MiB, 1 * MiB, 48 * MiB, 6),
    "namizje": Profil(16 * MiB, 1 * MiB, 96 * MiB, 8),
}


def okno_vnaprej(zaporedno_prebrano: int, zacetno: int, najvec: int) -> int:
    """Okno vnaprej (skupni primeri tok_okno): dvakratnik zaporedno prebranega od zadnjega skoka, najmanj zacetno,
    najvec meja profila. Predvajalnik, ki bere zaporedno, ima okno pred sabo; skok ga vrne na zacetno."""
    return max(int(zacetno), min(int(najvec), 2 * max(0, int(zaporedno_prebrano))))


@dataclass(frozen=True)
class KosVira:
    datoteka: int  # indeks v Vir.preslikave
    odmik: int  # odmik v datoteki NZB (zvezku)
    dolzina: int


class Vir:
    """Film kot zaporedje kosov datotek iz NZB (gola datoteka: en kos; RAR store: kos v vsakem zvezku)."""

    def __init__(self, preslikave: List[Preslikava], kosi: List[KosVira], ime: Optional[str] = None):
        self.preslikave = list(preslikave)
        self.kosi = list(kosi)
        self.ime = ime
        self._zacetki = list(itertools.accumulate([0] + [k.dolzina for k in self.kosi]))
        self.velikost = self._zacetki[-1]
        for k in self.kosi:
            p = self.preslikave[k.datoteka]
            if k.dolzina <= 0 or k.odmik < 0 or k.odmik + k.dolzina > p.velikost:
                raise NapakaToka(NESKLADNO)

    def __repr__(self) -> str:
        return "Vir(%d B, %d kosov)" % (self.velikost, len(self.kosi))

    def kje(self, odmik: int) -> Tuple[int, int]:
        """(datoteka, odmik v datoteki) za odmik v filmu."""
        if not 0 <= odmik < self.velikost:
            raise NapakaToka(IZVEN)
        i = self._kos_za(odmik)
        k = self.kosi[i]
        return k.datoteka, k.odmik + (odmik - self._zacetki[i])

    def razponi(self, odmik: int, dolzina: int) -> List[Tuple[int, int, int]]:
        """[(datoteka, odmik v datoteki, dolzina)] za [odmik, odmik + dolzina) v filmu."""
        izid, konec = [], min(self.velikost, odmik + dolzina)
        while odmik < konec:
            d, o = self.kje(odmik)
            i = self._kos_za(odmik)
            n = min(konec, self._zacetki[i + 1]) - odmik
            izid.append((d, o, n))
            odmik += n
        return izid

    def _kos_za(self, odmik: int) -> int:
        return bisect_right(self._zacetki, odmik, 0, len(self.kosi)) - 1


class Bralnik:
    """Branje filma z omejenim oknom vnaprej. Varno za vec niti. [telo] = Bazen.telo (message-id -> telo clanka)."""

    def __init__(self, telo: Callable[[str], bytes], vir: Vir, profil: Profil = PROFILI["namizje"]):
        self._telo = telo
        self.vir = vir
        self.profil = profil
        # LRU mora drzati vsaj okno in segment ob njem, sicer bi branje vnaprej izrinilo samo sebe.
        self._lru_meja = max(profil.lru_bajtov, 2 * profil.okno_bajtov + 8 * MiB)
        self._lru: "OrderedDict[tuple, bytes]" = OrderedDict()
        self._lru_bajtov = 0
        self._v_teku: Dict[tuple, Future] = {}
        self._vrsta: list = []  # (prednost, zaporedje, kljuc)
        self._cakajo: Dict[tuple, Future] = {}
        #: Pregled Grok 58 T3: segment, ki je padel (luknja, pokvarjen, neskladen), se do konca seje ne prenese znova;
        #: napaka omrezja dobi se en poskus. Prej ga je okno vnaprej ob vsakem branju postavilo v vrsto znova.
        self._napake: Dict[tuple, BaseException] = {}
        self._poskusi: Dict[tuple, int] = {}
        #: Koliko bralcev caka na kljuc (zahtevano branje): okno drugega bralca ga ne sme preklicati (Grok 61 W3).
        self._zahtevani: Dict[tuple, int] = {}
        self._zap = itertools.count()
        self._pogoj = threading.Condition(threading.Lock())
        self._zaprt = False
        self._konec = 0  # konec zadnjega branja (za zaporednost)
        self._zaporedno = 0
        self.z_omrezja = 0  # bajti teles clankov z Useneta
        self.segmentov = 0
        self.postrezeno = 0
        self._niti = [threading.Thread(target=self._delavec, name="safeer-usenet-bralnik", daemon=True)
                      for _ in range(max(1, profil.vzporedno))]
        for t in self._niti:
            t.start()

    def __repr__(self) -> str:
        return "Bralnik(%r, z omrezja %d B)" % (self.vir, self.z_omrezja)

    # -------------------------------------------------------------- niti
    def _delavec(self) -> None:
        while True:
            with self._pogoj:
                while not self._vrsta and not self._zaprt:
                    self._pogoj.wait()
                if self._zaprt:
                    return
                _p, _z, kljuc = heapq.heappop(self._vrsta)
                f = self._cakajo.pop(kljuc, None)
                if f is None:
                    continue  # zavrzeno ob skoku
            try:
                podatki = self._prenesi(kljuc)
            except BaseException as e:  # noqa: BLE001 - izid gre bralcu
                with self._pogoj:
                    self._v_teku.pop(kljuc, None)
                    self._zapomni(kljuc, e)
                    if not f.done():  # zapri() je morda ze nastavil ZAPRTO
                        f.set_exception(e)
                continue
            with self._pogoj:
                self._v_teku.pop(kljuc, None)
                if not self._zaprt:
                    self._v_lru(kljuc, podatki)
                if not f.done():
                    f.set_result(podatki)

    def _zapomni(self, kljuc: tuple, e: BaseException) -> None:
        """Pod self._pogoj: trajna napaka segmenta takoj, napaka omrezja po NAJVEC_POSKUSOV."""
        if isinstance(e, (NapakaToka, R.NapakaRar)):
            self._napake[kljuc] = e
            return
        self._poskusi[kljuc] = self._poskusi.get(kljuc, 0) + 1
        if self._poskusi[kljuc] >= NAJVEC_POSKUSOV:
            self._napake[kljuc] = e

    def _prenesi(self, kljuc: tuple) -> bytes:
        d, st = kljuc
        p = self.vir.preslikave[d]
        seg = p.segment(st)
        try:
            surovo = self._telo(seg.id)
        except NapakaNntp as e:
            raise NapakaToka(LUKNJA if e.izid == NI_CLANKA else e.izid) from None
        with self._pogoj:
            self.z_omrezja += len(surovo)
            self.segmentov += 1
        try:
            del_ = dekodiraj(surovo)
        except NapakaYenc:
            raise NapakaToka(POKVARJEN) from None
        p.vnesi(st, del_)
        return del_.podatki

    def _v_lru(self, kljuc: tuple, podatki: bytes) -> None:
        if kljuc in self._lru:
            self._lru.move_to_end(kljuc)
            return
        self._lru[kljuc] = podatki
        self._lru_bajtov += len(podatki)
        while self._lru_bajtov > self._lru_meja and len(self._lru) > 1:
            _k, staro = self._lru.popitem(last=False)
            self._lru_bajtov -= len(staro)

    def _zahtevaj(self, kljuc: tuple, prednost: int) -> Optional[Future]:
        """Future segmenta (None = ze v LRU ali, pri branju vnaprej, segment ze padel). Pod self._pogoj."""
        if kljuc in self._lru:
            return None
        napaka = self._napake.get(kljuc)
        if napaka is not None:
            if prednost > 0:
                return None  # ne znova vnaprej (T3)
            f = Future()
            f.set_exception(napaka)
            return f
        f = self._v_teku.get(kljuc)
        if f is not None:
            if prednost == 0 and kljuc in self._cakajo:
                heapq.heappush(self._vrsta, (0, next(self._zap), kljuc))  # vnaprej -> zahtevano: naprej v vrsti
                self._pogoj.notify()
            return f
        f = Future()
        self._v_teku[kljuc] = f
        self._cakajo[kljuc] = f
        heapq.heappush(self._vrsta, (prednost, next(self._zap), kljuc))
        self._pogoj.notify()
        return f

    def _segment(self, kljuc: tuple) -> bytes:
        for _ in range(NAJVEC_PREKLICEV):
            with self._pogoj:
                if self._zaprt:
                    raise NapakaToka(ZAPRTO)
                if kljuc in self._lru:
                    self._lru.move_to_end(kljuc)
                    return self._lru[kljuc]
                f = self._zahtevaj(kljuc, 0)
                self._zahtevani[kljuc] = self._zahtevani.get(kljuc, 0) + 1
            try:
                return f.result()
            except CancelledError:
                pass  # branje vnaprej, na katero smo cakali, je skok iz druge povezave zavrgel: znova zahtevano
            finally:
                with self._pogoj:
                    n = self._zahtevani.get(kljuc, 1) - 1
                    if n > 0:
                        self._zahtevani[kljuc] = n
                    else:
                        self._zahtevani.pop(kljuc, None)
        raise NapakaToka(PREKINJENO)  # meja ponovitev (Grok 61 W3: prej while True brez meje)

    # -------------------------------------------------------------- branje
    def _beri_datoteko(self, d: int, odmik: int, n: int) -> bytes:
        """Do [n] bajtov iz datoteke [d] od [odmik] (iz enega segmenta)."""
        p = self.vir.preslikave[d]
        for _ in range(NAJVEC_ISKANJ):
            u = p.poisci(odmik)
            podatki = self._segment((d, u.stevilka))
            u2 = p.poisci(odmik)  # segment je zdaj sidro: natancen odmik ali nov ugib
            if u2.natancno and u2.stevilka == u.stevilka:
                return podatki[u2.odmik:u2.odmik + n]
        raise NapakaToka(NESKLADNO)

    def _vnaprej(self, od: int) -> None:
        okno = okno_vnaprej(self._zaporedno, self.profil.zacetno_okno, self.profil.okno_bajtov)
        kljuci = []
        for d, o, n in self.vir.razponi(od, okno):
            kljuci += [(d, st) for st in self.vir.preslikave[d].segmenti_okna(o, n)]
        with self._pogoj:
            zelja = set(kljuci)
            # skok: cakajoca branja vnaprej zunaj okna proc - ne pa tista, na katera caka kak bralec (W3)
            for k in [k for k in self._cakajo if k not in zelja and not self._zahtevani.get(k)]:
                f = self._cakajo.pop(k)
                self._v_teku.pop(k, None)
                f.cancel()
            for i, k in enumerate(kljuci):
                self._zahtevaj(k, 1 + i)

    def beri(self, odmik: int, n: int) -> bytes:
        """Do [n] bajtov filma od [odmik]; b"" na koncu. Napaka: NapakaToka (luknja, pokvarjen, zaprto ...)."""
        if odmik >= self.vir.velikost or n <= 0:
            return b""
        if odmik < 0:
            raise NapakaToka(IZVEN)
        with self._pogoj:
            if self._zaprt:
                raise NapakaToka(ZAPRTO)
            if abs(odmik - self._konec) <= self.profil.zacetno_okno:
                self._zaporedno += max(0, odmik + n - max(odmik, self._konec))
            else:
                self._zaporedno = 0  # skok
        d, o = self.vir.kje(odmik)
        razpon = self.vir.razponi(odmik, n)[0]
        podatki = self._beri_datoteko(d, o, razpon[2])
        konec = odmik + len(podatki)
        with self._pogoj:
            self._konec = konec
            self.postrezeno += len(podatki)
        self._vnaprej(konec)
        return podatki

    def zapri(self) -> None:
        """Konec predvajanja: vrsta proc, LRU sproscen, niti koncajo; zahteve v teku se ne caka, bralci, ki nanje
        cakajo, pa se takoj zbudijo z ZAPRTO (pregled Grok 58 T9). Prenos v teku se konca v bazenu (na Windows ga
        Bazen.zapri ne prekine), njegov izid se zavrze."""
        with self._pogoj:
            self._zaprt = True
            for f in self._v_teku.values():
                if not f.done():
                    f.set_exception(NapakaToka(ZAPRTO))
            for f in self._cakajo.values():
                f.cancel()
            self._cakajo.clear()
            self._vrsta.clear()
            self._lru.clear()
            self._lru_bajtov = 0
            self._pogoj.notify_all()

    @property
    def zaprt(self) -> bool:
        return self._zaprt


# ------------------------------------------------------------------ priprava iz NZB

VIDEO = R.VIDEO  # ista pravila za imena v NZB in v arhivu (N1)
NI_VSEBINA = R.NI_VSEBINA
NI_PODPRTO = "ni_podprto"  # 7z, zip, gnezden arhiv, vec zvezkov z zakritimi imeni ... (F2)
NI_FILMA = "ni_filma"

#: T3: napaka omrezja pri istem segmentu - po toliko poskusih se ne prenasa vec.
NAJVEC_POSKUSOV = 2
#: W3: zahtevano branje, ki ga okno drugega bralca preklice, se ponovi najvec toliko krat.
NAJVEC_PREKLICEV = 3
#: T4: priprava bere hkrati najvec toliko zvezkov in zacetek vsakega sprosti takoj po razclenitvi glav.
PRIPRAVA_HKRATI = 4
#: T4: meja prometa priprave (prvi segmenti zvezkov in iskanje glav); vec = PREVEC (600 zvezkov po 700 KiB = 410 MiB).
NAJVEC_PRIPRAVE_BAJTOV = 512 * MiB
#: T5: glave, ki niso v prvem segmentu zvezka: najvec toliko segmentov in bajtov na zvezek, sicer PREVEC.
NAJVEC_GLAV_SEGMENTOV = 8
NAJVEC_GLAV_BAJTOV = 16 * MiB
#: L1: preverba pred ponudbo samo odloca, zato ima za glave prvega zvezka manjso mejo kot priprava.
NAJVEC_PREVERBE_GLAV_BAJTOV = 8 * MiB

#: T13: vzorec je samostojna beseda v imenu (»Film.Sample.mkv«, »sample-film.mkv«), ne podniz (»Samplers.2026.mkv«).
_VZOREC = R._VZOREC


def je_vzorec(ime: str) -> bool:
    """Ali je datoteka vzorec (skupni primeri tok_vzorec)."""
    return R.je_vzorec(ime)


def _clen(clanek: int, najmanj: int) -> int:
    # vsak clen omejen: ze en tak preseze mejo, vsota pa ne more narasti cez vse meje
    return min(max(0, clanek, najmanj), NAJVEC_PRIPRAVE_BAJTOV + 1)


def ocena_priprave(prebrano: int, clanki_nzb: List[int], najmanj: int) -> int:
    """Promet priprave pred prvim bajtom (skupni primeri tok_priprava): [prebrano] + prvi clanek vsakega zvezka, ki se
    ga se bere. Velikost clanka iz NZB napise posiljatelj, zato vsaj [najmanj] (prvi prebrani clanek - zvezki so enaki).
    L1: prej je priprava to izvedela sele po do 512 MiB prometa in po ponudbi."""
    return min(max(0, prebrano), NAJVEC_PRIPRAVE_BAJTOV + 1) + sum(_clen(b, najmanj) for b in clanki_nzb)


def _clanek_nzb(d: Datoteka) -> int:
    """Povprecen clanek datoteke po NZB (bytes v NZB ima najvec 9 stevk) - ocena prvega clanka brez omrezja."""
    return max(0, d.bajtov_nzb) // max(1, len(d.segmenti))


def _je_zvezek(ime: str) -> bool:
    k = os.path.splitext(ime)[1].lower()
    return R.vrstni_red_zvezkov([ime]) is not None or k == ".rar" or (len(k) == 4 and k[1] == "r" and k[2:].isdigit())


def izberi_datoteke(nzb: Nzb) -> Tuple[str, List[int]]:
    """('rar' | 'video', indeksi datotek v vrstnem redu) - skupni primeri tok_izbira. 'video' z zakritim imenom je
    najvecja datoteka; ali je RAR, pove sele prvi segment (_prvi). Napaka: NapakaToka(NI_FILMA / NI_PODPRTO)."""
    imena = [d.ime or "" for d in nzb.datoteke]
    rar = [i for i, ime in enumerate(imena) if _je_zvezek(ime) and not je_vzorec(ime)]
    if rar:
        red = R.vrstni_red_zvezkov([imena[i] for i in rar])
        if red is None:
            raise NapakaToka(NI_PODPRTO)  # vec arhivov ali nepopolna vrsta - par2/deobfuskacija je F2
        return "rar", [rar[i] for i in red]
    video = [i for i, ime in enumerate(imena) if ime.lower().endswith(VIDEO) and not je_vzorec(ime)]
    if video:
        return "video", [max(video, key=lambda i: (nzb.datoteke[i].bajtov_nzb, -i))]
    if any(ime.lower().endswith((".7z", ".zip", ".001")) for ime in imena):
        raise NapakaToka(NI_PODPRTO)
    kandidati = [i for i, ime in enumerate(imena) if not ime.lower().endswith(NI_VSEBINA)]
    if not kandidati:
        raise NapakaToka(NI_FILMA)
    return "video", [max(kandidati, key=lambda i: (nzb.datoteke[i].bajtov_nzb, -i))]


def _prvi_segment(telo: Callable[[str], bytes], d: Datoteka) -> Tuple[Preslikava, bytes, int]:
    s = d.segmenti[0]
    try:
        surovo = telo(s.id)
    except NapakaNntp as e:
        raise NapakaToka(LUKNJA if e.izid == NI_CLANKA else e.izid) from None
    try:
        del_ = dekodiraj(surovo)
    except NapakaYenc:
        raise NapakaToka(POKVARJEN) from None
    return Preslikava(d, del_, s.stevilka), del_.podatki if del_.odmik == 0 else b"", len(surovo)


def _je_rar(zacetek: bytes) -> bool:
    return zacetek.startswith(R.PODPIS4) or zacetek.startswith(R.PODPIS5)


def _glave(telo: Callable[[str], bytes], p: Preslikava, zacetek: bytes, celo: bool,
           najvec_bajtov: int = NAJVEC_GLAV_BAJTOV) -> Tuple[R.Zvezek, int]:
    """Glave zvezka iz zacetka (prvi segment); ce segajo cez in jih rabimo ([celo] ali ni nobene datoteke), branje
    naprej prek bralnika brez okna vnaprej z mejo NAJVEC_GLAV_* (T5; prej brez meje - do 10 000 blokov). (zvezek,
    bajti z omrezja)."""
    z = R.razcleni_zvezek(zacetek, p.velikost) if zacetek else None
    if z is not None and not (z.nepopolno and (celo or not z.vnosi)):
        return z, 0
    b = Bralnik(telo, Vir([p], [KosVira(0, 0, p.velikost)]), Profil(0, 0, 8 * MiB, 1))

    def meja() -> None:
        if b.segmentov > NAJVEC_GLAV_SEGMENTOV or b.z_omrezja > najvec_bajtov:
            raise NapakaToka(PREVEC)

    def beri(o: int, k: int) -> bytes:
        if o + k <= len(zacetek):
            return zacetek[o:o + k]  # prvi segment je ze tu
        meja()
        x = _beri_vse(b, o, k)
        meja()
        return x
    try:
        return R.razcleni_zvezek(beri, p.velikost), b.z_omrezja
    finally:
        b.zapri()


def _odloci_prvega(telo: Callable[[str], bytes], p: Preslikava, zacetek: bytes,
                   najvec_glav: int = NAJVEC_GLAV_BAJTOV) -> Tuple[R.Zvezek, int]:
    """Prvi zvezek: odlocitev store/stisnjen/sifriran na celem seznamu glav, ce prvi segment ne zadosca (T2, N1)."""
    izid = R.preveri(zacetek, p.velikost)
    bajtov = 0
    if izid == R.NEPOPOLNO:
        z, bajtov = _glave(telo, p, zacetek, True, najvec_glav)
        izid = R.odloci(z, p.velikost)
    else:
        z = R.razcleni_zvezek(zacetek, p.velikost) if izid == R.OK else None
    if izid != R.OK:
        raise R.NapakaRar(izid)
    return z, bajtov


def _prvi(nzb: Nzb, telo: Callable[[str], bytes], najvec_glav: int = NAJVEC_GLAV_BAJTOV) -> tuple:
    """Skupna odlocitev za preveri_izdajo in pripravi (T13): (vrsta, izbrane, preslikava, zvezek ali None, bajti,
    bajti prvega clanka). Zakrito ime s podpisom RAR je RAR z enim zvezkom (vec zvezkov z zakritimi imeni ne znamo
    urediti: NI_PODPRTO)."""
    vrsta, izbrane = izberi_datoteke(nzb)
    p, zacetek, bajtov = _prvi_segment(telo, nzb.datoteke[izbrane[0]])
    if vrsta == "video" and not _je_rar(zacetek):
        return vrsta, izbrane, p, None, bajtov, bajtov
    z, b2 = _odloci_prvega(telo, p, zacetek, najvec_glav)
    if vrsta == "video":
        if z.vec_zvezkov:
            raise NapakaToka(NI_PODPRTO)
        vrsta = "rar"
    return vrsta, izbrane, p, z, bajtov + b2, bajtov


def _v_meji(nzb: Nzb, ostali: List[int], prebrano: int, najmanj: int, najvec_bajtov: int) -> None:
    """L1: PREVEC, ce ocena priprave preseze mejo - pred prometom za ostale zvezke."""
    if ocena_priprave(prebrano, [_clanek_nzb(nzb.datoteke[i]) for i in ostali], najmanj) > najvec_bajtov:
        raise NapakaToka(PREVEC)


def pripravi(nzb: Nzb, telo: Callable[[str], bytes], vzporedno: int = PRIPRAVA_HKRATI,
             najvec_bajtov: int = NAJVEC_PRIPRAVE_BAJTOV) -> Tuple[Vir, int]:
    """NZB -> (Vir filma, bajti z omrezja za pripravo). Prvi zvezek odloci (T2), ostali zvezki se berejo najvec
    [vzporedno] hkrati, zacetek se sprosti takoj po razclenitvi (T4), skupni promet najvec [najvec_bajtov] (PREVEC).
    Stisnjen ali sifriran RAR = NapakaRar PRED ponudbo.
    L1: prevelika izdaja pade iz NZB brez prometa in po prvem clanku brez branja ostalih zvezkov (enako kot
    preveri_izdajo); promet zvezka se rezervira PRED oddajo (prej je preverba po koncanem zvezku dovolila preseg za do
    4 zvezke); zvezki za koncem filma se ne berejo (prej vsi)."""
    _vrsta, izbrane = izberi_datoteke(nzb)
    _v_meji(nzb, izbrane, 0, 0, najvec_bajtov)
    vrsta, izbrane, p0, z0, bajtov, prvi_surovo = _prvi(nzb, telo)
    if vrsta == "video":
        return Vir([p0], [KosVira(0, 0, p0.velikost)], nzb.datoteke[izbrane[0]].ime), bajtov
    _v_meji(nzb, izbrane[1:], bajtov, prvi_surovo, najvec_bajtov)
    ocene = [0] + [_clen(_clanek_nzb(nzb.datoteke[i]), prvi_surovo) for i in izbrane[1:]]
    preslikave: list = [None] * len(izbrane)
    zvezki: list = [None] * len(izbrane)
    preslikave[0], zvezki[0] = p0, z0
    v0 = R.glavni_vnos(z0)
    # film, ki se ne nadaljuje, ne rabi naslednjih zvezkov; sicer se meja premakne, ko zvezek film konca
    potrebnih = len(izbrane) if v0 is not None and v0.razdeljen_po else 1

    def obdelaj(n: int) -> tuple:
        p, zacetek, b = _prvi_segment(telo, nzb.datoteke[izbrane[n]])
        z, b2 = _glave(telo, p, zacetek, False)
        return p, z, b + b2  # zacetek gre stran tu

    hkrati = max(1, vzporedno)
    with ThreadPoolExecutor(max_workers=hkrati) as ex:
        tecejo: dict = {}
        naslednji, preverjen, rezervirano = 1, 1, 0
        try:
            while naslednji < potrebnih or any(n < potrebnih for n in tecejo.values()):
                while naslednji < potrebnih and len(tecejo) < hkrati:
                    if bajtov + rezervirano + ocene[naslednji] > najvec_bajtov:
                        raise NapakaToka(PREVEC)  # rezervacija pred oddajo: zvezki v teku ne gredo cez mejo
                    rezervirano += ocene[naslednji]
                    tecejo[ex.submit(obdelaj, naslednji)] = naslednji
                    naslednji += 1
                koncani, _ = wait(list(tecejo), return_when=FIRST_COMPLETED)
                for f in koncani:
                    n = tecejo.pop(f)
                    rezervirano -= ocene[n]
                    if n >= potrebnih:
                        continue  # zvezek za koncem filma: izid ni pomemben
                    preslikave[n], zvezki[n], b = f.result()
                    bajtov += b
                if bajtov + rezervirano > najvec_bajtov:
                    raise NapakaToka(PREVEC)
                while preverjen < potrebnih and zvezki[preverjen] is not None:
                    x = R.nadaljevanje(zvezki[preverjen])
                    if x is None or not x.razdeljen_po:
                        potrebnih = preverjen + 1  # film se tu konca (ali sestavi javi NESKLADNO)
                    preverjen += 1
        finally:
            for f in tecejo:
                f.cancel()
    ime, _velikost, kosi = R.sestavi(zvezki[:potrebnih])
    return Vir(preslikave[:potrebnih], [KosVira(k.zvezek, k.odmik, k.dolzina) for k in kosi], ime), bajtov


def _beri_vse(b: Bralnik, odmik: int, n: int) -> bytes:
    deli = []
    while n > 0:
        kos = b.beri(odmik, n)
        if not kos:
            break
        deli.append(kos)
        odmik += len(kos)
        n -= len(kos)
    return b"".join(deli)


def preveri_izdajo(nzb: Nzb, telo: Callable[[str], bytes], najvec_bajtov: int = NAJVEC_PRIPRAVE_BAJTOV) -> str:
    """Pred ponudbo: ali izdajo lahko predvajamo. Prvi segment prve datoteke ali zvezka (in pri RAR, ce glave segajo
    cez, se nekaj segmentov z mejo NAJVEC_PREVERBE_GLAV_BAJTOV - T2/T5/L1). OK ali izid (stisnjen, sifriran,
    sifrirane_glave, poskodovan, ni_podprto, ni_filma, luknja, prevec ...). Izdaja brez segmenta 1 ali z luknjami v NZB
    ni ponujena (W6). L1: izdaja, katere priprava bi presegla [najvec_bajtov] (enako kot pripravi), je PREVEC tu - iz NZB
    brez prometa ali po prvem clanku - in ne sele po ponudbi. STAT vzorca segmentov je korak 3."""
    try:
        vrsta, izbrane = izberi_datoteke(nzb)
        d = nzb.datoteke[izbrane[0]]
        if d.segmenti[0].stevilka != 1 or d.manjka:
            return LUKNJA
        _v_meji(nzb, izbrane, 0, 0, najvec_bajtov)
        _vrsta, izbrane, p, _z, bajtov, prvi_surovo = _prvi(nzb, telo, NAJVEC_PREVERBE_GLAV_BAJTOV)
        if p.ima_luknje:
            return LUKNJA
        _v_meji(nzb, izbrane[1:], bajtov, prvi_surovo, najvec_bajtov)
    except NapakaToka as e:
        return e.izid
    except R.NapakaRar as e:
        return e.izid
    return R.OK
