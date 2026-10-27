"""Preslikava odmikov za lasten pogon Usenet, korak 2 (lastnik 26. 10. 2026: »dokoncajmo Usenet za nase naprave«).

Datoteka iz NZB je zaporedje segmentov (clankov); vsak clanek je del yEnc z '=ypart begin= end=' (od 1, vkljucno) in
'=ybegin size=' (velikost CELE datoteke). NZB pove samo velikost clankov (kodiranih, z glavami) - ne odmikov. Zato:
1. Prvi segment datoteke (z najnizjo stevilko) da velikost datoteke in velikost dela (end - begin + 1).
2. Kodirniki (Nyuu, ngPost, newsmangler ...) delijo datoteko na enake dele, zadnji je krajsi: odmik o lezi v segmentu
   o // del + 1, na odmiku o % del. To je samo UGIB: vsak prebran segment pove svoj pravi razpon (vnesi), ugib pa
   se popravi med znanimi razponi (sidri) z enakomerno razdelitvijo vmesnih segmentov - neenakomerna objava (npr.
   dve objavi zdruzeni v en NZB) se tako najde v nekaj branjih, namesto da bi brali napacne bajte.
3. Luknje: segment, ki ga v NZB ni (stevilka manjka med 1 in celoto) - branje odmika v njem da LUKNJA (pri pretakanju
   ni popravila par2: preklop na drugo izdajo je odlocitev klicatelja). Clanek, ki ga ponudnik nima (430), je luknja,
   ki jo odkrije sele branje (bralnik).

Pregled Grok 58: T1 - yEnc total iz clanka je omejen (NZB dovoli najvec 200 000 segmentov datoteke), manjkajoci so
samo stevilo; T6 - sidra so urejena (Sidra), vnos in iskanje O(log n) namesto kopije in urejanja vseh ob vsakem branju.

Pravila so skupna z Android-tv (Kotlin): tests/skupni-primeri/usenet-pogon.json (tok_odmik, tok_segmenti,
tok_preslikava). Brez omrezja; message-id ni v repr ali izjemi.
"""

from __future__ import annotations

import threading
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Optional

from .usenet_nzb import NAJVEC_SEGMENTOV_DATOTEKE, Datoteka, Segment
from .usenet_yenc import NAJVEC_DEL_BAJTOV, DelYenc

OK = "ok"
IZVEN = "izven"  # odmik zunaj datoteke
LUKNJA = "luknja"  # segment manjka (v NZB ali pri ponudniku)
NESKLADNO = "neskladno"  # razponi segmentov si nasprotujejo (pokvarjen ali zlonameren NZB/clanek)
POKVARJEN = "pokvarjen"  # clanek ni veljaven yEnc ali CRC se ne ujema (bralnik)
ZAPRTO = "zaprto"  # bralnik je zaprt
PREVEC = "prevec"  # presezena meja (promet priprave ali iskanja glav, zvezkov)
PREKINJENO = "prekinjeno"  # branje vec kot NAJVEC_PREKLICEV krat preklicano (dva bralca drug drugemu)

#: Najvec branj, s katerimi bralnik isce segment za odmik (enakomerna objava: 1; dve zdruzeni objavi: nekaj).
NAJVEC_ISKANJ = 24


class NapakaToka(ValueError):
    """Izid brez message-id in brez imena datoteke v sporocilu."""

    def __init__(self, izid: str):
        super().__init__("usenet tok: " + izid)
        self.izid = izid


@dataclass(frozen=True)
class Ugib:
    stevilka: int  # segment (od 1)
    odmik: int  # odmik v segmentu (dekodiranem delu)
    natancno: bool  # razpon segmenta je znan (prebran), ne ugibamo


class Sidra:
    """Znani razponi segmentov, urejeni po stevilki (in zato po odmiku): vnos preveri samo soseda, iskanje z bisect -
    O(log n) na branje (pregled Grok 58 T6; prej je vsako branje uredilo in kopiralo vse znane - izmerjeno 26. 10. 2026
    pri 10^5 sidrih 1,08 s na branje). Pravila so ista kot prej: vsak vmesni segment ima vsaj en bajt, sosednja segmenta
    se stikata, zadnji znan pusti prostor za ostale in segment [celota] konca na velikosti datoteke."""

    def __init__(self, velikost: int, celota: int):
        self.velikost, self.celota = velikost, celota
        self._st: list = []
        self._z: list = []
        self._d: list = []

    def __len__(self) -> int:
        return len(self._st)

    @classmethod
    def iz_slovarja(cls, velikost: int, celota: int, znani: dict) -> "Sidra":
        s = cls(velikost, celota)
        for st, (z, d) in sorted(znani.items()):
            s.dodaj(st, z, d)
        return s

    @staticmethod
    def _par(st_a: int, konec_a: int, st_b: int, zac_b: int) -> bool:
        return zac_b - konec_a >= st_b - st_a - 1 and (st_b != st_a + 1 or zac_b == konec_a)

    def dodaj(self, st: int, z: int, d: int) -> None:
        if not 1 <= st <= self.celota or d < 1 or z < 0 or z + d > self.velikost:
            raise NapakaToka(NESKLADNO)
        i = bisect_left(self._st, st)
        enak = i < len(self._st) and self._st[i] == st
        if enak and (self._z[i], self._d[i]) == (z, d):
            return
        lst, lkon = (self._st[i - 1], self._z[i - 1] + self._d[i - 1]) if i > 0 else (0, 0)
        j = i + 1 if enak else i
        if not self._par(lst, lkon, st, z):
            raise NapakaToka(NESKLADNO)
        if j < len(self._st):
            if not self._par(st, z + d, self._st[j], self._z[j]):
                raise NapakaToka(NESKLADNO)
        elif self.velikost - (z + d) < self.celota - st or (st == self.celota and z + d != self.velikost):
            raise NapakaToka(NESKLADNO)
        if enak:
            self._z[i], self._d[i] = z, d
        else:
            self._st.insert(i, st)
            self._z.insert(i, z)
            self._d.insert(i, d)

    def znan(self, st: int) -> Optional[tuple]:
        i = bisect_left(self._st, st)
        return (self._z[i], self._d[i]) if i < len(self._st) and self._st[i] == st else None

    def okoli_odmika(self, odmik: int) -> tuple:
        """('znan', st, odmik v njem) ali ('vrzel', levo_st, levo_konec, desno_st, desno_zacetek)."""
        i = bisect_right(self._z, odmik) - 1
        if i >= 0 and odmik < self._z[i] + self._d[i]:
            return ("znan", self._st[i], odmik - self._z[i])
        lst, lkon = (self._st[i], self._z[i] + self._d[i]) if i >= 0 else (0, 0)
        dst, dzac = (self._st[i + 1], self._z[i + 1]) if i + 1 < len(self._st) else (self.celota + 1, self.velikost)
        return ("vrzel", lst, lkon, dst, dzac)

    def okoli_stevilke(self, st: int) -> tuple:
        """(levo_st, levo_konec, desno_st, desno_zacetek) za neznano stevilko."""
        i = bisect_left(self._st, st)
        lst, lkon = (self._st[i - 1], self._z[i - 1] + self._d[i - 1]) if i > 0 else (0, 0)
        dst, dzac = (self._st[i], self._z[i]) if i < len(self._st) else (self.celota + 1, self.velikost)
        return lst, lkon, dst, dzac

    def kot_slovar(self) -> dict:
        return {st: (z, d) for st, z, d in zip(self._st, self._z, self._d)}


def _enakomerno(lst: int, lkon: int, dst: int, dzac: int, del_bajtov: Optional[int], celota: int) -> bool:
    """Ali je vrzel med sidroma skladna z enakimi deli [del_bajtov] (zadnji del datoteke je lahko krajsi)."""
    if not del_bajtov or del_bajtov <= 0 or lkon != lst * del_bajtov:
        return False
    if dst == celota + 1:
        return (celota - 1) * del_bajtov < dzac <= celota * del_bajtov
    return dzac == (dst - 1) * del_bajtov


def _poisci(s: Sidra, del_bajtov: Optional[int], odmik: int) -> Ugib:
    if not 0 <= odmik < s.velikost:
        raise NapakaToka(IZVEN)
    if s.celota < 1 or s.velikost < s.celota:
        raise NapakaToka(NESKLADNO)
    o = s.okoli_odmika(odmik)
    if o[0] == "znan":
        return Ugib(o[1], o[2], True)
    _, lst, lkon, dst, dzac = o
    if _enakomerno(lst, lkon, dst, dzac, del_bajtov, s.celota):
        st = odmik // del_bajtov + 1
        return Ugib(st, odmik - (st - 1) * del_bajtov, False)
    na = (dzac - lkon) / (dst - lst - 1)  # vsaj en vmesni (preverjeno ob vnosu)
    st = min(dst - 1, max(lst + 1, lst + 1 + int((odmik - lkon) // na)))
    return Ugib(st, odmik - (lkon + int((st - lst - 1) * na)), False)


def _razpon(s: Sidra, del_bajtov: Optional[int], stevilka: int) -> tuple:
    if not 1 <= stevilka <= s.celota:
        raise NapakaToka(IZVEN)
    znan = s.znan(stevilka)
    if znan is not None:
        return znan[0], znan[1], True
    lst, lkon, dst, dzac = s.okoli_stevilke(stevilka)
    if _enakomerno(lst, lkon, dst, dzac, del_bajtov, s.celota):
        z = (stevilka - 1) * del_bajtov
        return z, min(del_bajtov, dzac - z), False
    na = (dzac - lkon) / (dst - lst - 1)
    z = lkon + int((stevilka - lst - 1) * na)
    k = lkon + int((stevilka - lst) * na) if stevilka + 1 < dst else dzac
    return z, max(1, k - z), False


def _segmenti_okna(s: Sidra, del_bajtov: Optional[int], odmik: int, dolzina: int) -> list:
    if dolzina <= 0 or not 0 <= odmik < s.velikost:
        return []
    konec = min(s.velikost, odmik + dolzina)
    st = _poisci(s, del_bajtov, odmik).stevilka
    izid = []
    while st <= s.celota:
        z, _d, _ = _razpon(s, del_bajtov, st)
        if z >= konec:
            break
        izid.append(st)
        st += 1
    return izid


def poisci(velikost: int, celota: int, del_bajtov: Optional[int], znani: dict, odmik: int) -> Ugib:
    """Segment za odmik (skupni primeri tok_odmik). [del_bajtov] = velikost dela iz prvega segmenta (None = ni znana),
    [znani] = {stevilka: (odmik, dolzina)} prebranih segmentov. Ugib: odmik // del + 1, ce je vrzel med sidroma
    skladna z enakimi deli (_enakomerno), sicer enakomerna razdelitev vrzeli na vmesne segmente. Napaka:
    NapakaToka(IZVEN / NESKLADNO)."""
    if not 0 <= odmik < velikost:
        raise NapakaToka(IZVEN)
    if celota < 1 or velikost < celota:
        raise NapakaToka(NESKLADNO)
    return _poisci(Sidra.iz_slovarja(velikost, celota, znani), del_bajtov, odmik)


def razpon(velikost: int, celota: int, del_bajtov: Optional[int], znani: dict, stevilka: int) -> tuple:
    """(odmik, dolzina, natancno) segmenta - znan ali ocenjen enako kot v poisci (za okno vnaprej)."""
    if not 1 <= stevilka <= celota:
        raise NapakaToka(IZVEN)
    return _razpon(Sidra.iz_slovarja(velikost, celota, znani), del_bajtov, stevilka)


def segmenti_okna(velikost: int, celota: int, del_bajtov: Optional[int], znani: dict, odmik: int,
                  dolzina: int) -> list:
    """Stevilke segmentov, ki (po znanem ali ocenjenem razponu) pokrivajo [odmik, odmik + dolzina) - skupni primeri
    tok_segmenti. Konec datoteke okno prireze."""
    if dolzina <= 0 or not 0 <= odmik < velikost:
        return []
    return _segmenti_okna(Sidra.iz_slovarja(velikost, celota, znani), del_bajtov, odmik, dolzina)


def meje_preslikave(stevil_v_nzb: int, manjka_v_nzb: int, velikost: int, skupaj: Optional[int]) -> int:
    """Celota segmentov datoteke iz NZB in glave prvega clanka (skupni primeri tok_preslikava). yEnc total napise
    posiljatelj (do 999 999 999): nad NAJVEC_SEGMENTOV_DATOTEKE = NESKLADNO, sicer celota = max(NZB, total). Vsak del
    ima 1 do NAJVEC_DEL_BAJTOV bajtov, zato velikost < celota ali > celota * NAJVEC_DEL_BAJTOV = NESKLADNO."""
    celota = stevil_v_nzb + manjka_v_nzb
    if skupaj is not None:
        if skupaj > NAJVEC_SEGMENTOV_DATOTEKE:
            raise NapakaToka(NESKLADNO)
        celota = max(celota, skupaj)
    if velikost < celota or velikost > celota * NAJVEC_DEL_BAJTOV:
        raise NapakaToka(NESKLADNO)
    return celota


class Preslikava:
    """Odmiki ene datoteke iz NZB. Varna za vec niti (bralnik vnasa prebrane segmente vzporedno)."""

    def __init__(self, datoteka: Datoteka, prvi: DelYenc, stevilka_prvega: Optional[int] = None):
        """[prvi] = dekodiran segment z najnizjo stevilko v NZB (ali [stevilka_prvega])."""
        st = stevilka_prvega if stevilka_prvega is not None else datoteka.segmenti[0].stevilka
        self._segmenti = {s.stevilka: s for s in datoteka.segmenti}
        if st not in self._segmenti:
            raise NapakaToka(NESKLADNO)
        self.ime = datoteka.ime
        self.velikost = prvi.velikost
        self.celota = meje_preslikave(len(datoteka.segmenti), datoteka.manjka, prvi.velikost, prvi.skupaj)
        self.manjka = self.celota - len(self._segmenti)  # stevilke v NZB so vse <= celota; nikoli seznam (T1)
        # del iz segmenta, ki ni zadnji (zadnji je krajsi); enodelna datoteka: del = velikost
        self.del_bajtov: Optional[int] = len(prvi.podatki) if st < self.celota or self.celota == 1 else None
        self._sidra = Sidra(self.velikost, self.celota)
        self._zaklep = threading.Lock()
        self.vnesi(st, prvi)

    def __repr__(self) -> str:
        return "Preslikava(%d B, %d segmentov, %d manjka)" % (self.velikost, self.celota, self.manjka)

    @property
    def ima_luknje(self) -> bool:
        return self.manjka > 0

    def manjkajoci(self, najvec: int = 100) -> list:
        """Prvih [najvec] manjkajocih stevilk (diagnostika) - nikoli seznam vseh."""
        izid = []
        n = 1
        while n <= self.celota and len(izid) < najvec and len(izid) < self.manjka:
            if n not in self._segmenti:
                izid.append(n)
            n += 1
        return izid

    def segment(self, stevilka: int) -> Segment:
        s = self._segmenti.get(stevilka)
        if s is None:
            raise NapakaToka(LUKNJA)
        return s

    def znani(self) -> dict:
        with self._zaklep:
            return self._sidra.kot_slovar()

    def vnesi(self, stevilka: int, d: DelYenc) -> None:
        """Prebran segment: njegov pravi razpon postane sidro. Druga velikost datoteke ali razpon, ki nasprotuje
        znanim, je NESKLADNO (segment druge datoteke ali pokvarjen NZB)."""
        if d.velikost != self.velikost or not d.podatki:
            raise NapakaToka(NESKLADNO)
        self._vnesi_razpon(stevilka, d.odmik, len(d.podatki))

    def _vnesi_razpon(self, stevilka: int, z: int, n: int) -> None:
        with self._zaklep:
            self._sidra.dodaj(stevilka, z, n)

    def poisci(self, odmik: int) -> Ugib:
        """Segment za odmik; manjkajoc segment = NapakaToka(LUKNJA)."""
        with self._zaklep:
            u = _poisci(self._sidra, self.del_bajtov, odmik)
        if u.stevilka not in self._segmenti:
            raise NapakaToka(LUKNJA)
        return u

    def razpon(self, stevilka: int) -> tuple:
        with self._zaklep:
            return _razpon(self._sidra, self.del_bajtov, stevilka)

    def segmenti_okna(self, odmik: int, dolzina: int) -> list:
        """Segmenti okna brez manjkajocih (teh ni smiselno brati vnaprej - branje jih javi kot luknjo)."""
        with self._zaklep:
            st = _segmenti_okna(self._sidra, self.del_bajtov, odmik, dolzina)
        return [n for n in st if n in self._segmenti]
