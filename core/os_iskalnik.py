"""Iskanje datotek po imenu z indeksom v pomnilniku (Safeer OS).

Prej je vsaka poizvedba - vsaka vtipkana črka - znova hodila po disku, največ 1,5 s in do 60 zadetkov, po širini od
domače mape: globlje datoteke niso bile nikoli najdene, zadetki pa so bili v vrstnem redu hoje, ne po ujemanju.

Zdaj Safeer OS ob prvem iskanju v ozadju enkrat prehodi domačo mapo (brez skritih map, map s programsko kodo in drugih
diskov), si zapomni imena in išče po njih v pomnilniku: takoj, po vsej globini, brez šumnikov (»porocilo« najde
»Poročilo«), z več besedami (»racun 2024«) in razvrščeno po ujemanju. Imena so strnjena v en niz bajtov (okoli 60
bajtov na datoteko), ne v sto tisoč predmetov. Indeks se obnovi v ozadju, ko je star ali ko Safeer sam kaj premakne;
dokler prvega ni, odgovarja staro iskanje po disku. Zadetek, ki ga na disku ni več, izpade.
"""

from __future__ import annotations

import os
import threading
import time
from array import array
from bisect import bisect_right
from collections import deque
from typing import List, Optional, Tuple

from core import os_datoteke

#: Po toliko sekundah je indeks star: naslednje iskanje ga v ozadju obnovi (odgovori še iz starega).
STAROST_S = 600.0
#: Po spremembi, ki jo naredi Safeer sam (premik, novo, preimenovanje), obnovimo prej - a ne pogosteje kot na toliko.
NAJMANJ_MED_GRADNJAMA_S = 20.0
#: Največ imen v indeksu in najdaljša gradnja; kar ne gre noter, najde staro iskanje po disku.
NAJVEC_VNOSOV = 400_000
ROK_GRADNJE_S = 120.0
NAJVEC_GLOBINA = 14
#: Koliko ujemanj ocenimo pri eni poizvedbi (pogosta črka se ujema povsod).
NAJVEC_KANDIDATOV = 4000
#: Prvo raven uporabnikovih map (Prejemi, Namizje ...) ob iskanju pogledamo v živo; v zelo polni mapi največ toliko vnosov.
NAJVEC_V_MAPI_V_ZIVO = 5000

#: Prvo iskanje počaka na indeks največ toliko (majhna domača mapa je prehojena v delčku sekunde); sicer hoja po disku.
CAKAJ_PRVI_INDEKS_S = 1.5
_MEJE = b" -_.([{+,;"

#: Ime za primerjavo: male črke brez šumnikov in naglasov - isto pravilo kot pri hoji po disku.
kljuc = os_datoteke.kljuc_imena


class Indeks:
    """Imena datotek in map pod `koren`; gradi se v ozadju, išče v pomnilniku."""

    def __init__(self, koren: Optional[str] = None, najvec: int = NAJVEC_VNOSOV, rok_s: float = ROK_GRADNJE_S) -> None:
        self.koren = os.path.abspath(koren or os.path.expanduser("~"))
        self.najvec, self.rok_s = int(najvec), float(rok_s)
        #: (ključi, začetki ključev, imena, začetki imen, mapa vnosa, je mapa, mape, globine map) ali None.
        self._podatki = None
        self._zaklep = threading.Lock()
        self._gradi = False
        self._konec_gradnje = threading.Event()
        self.zgrajen = 0.0          # time.monotonic() konca zadnje gradnje
        self.zgrajen_ura = 0.0      # time.time() začetka zadnje gradnje: kar je novejše, v indeksu morda ni
        self.zastarel_ob = 0.0      # time.monotonic() zadnje znane spremembe (Safeer je kaj premaknil)
        self.nepopoln = False       # gradnja se je ustavila pri meji vnosov ali časa
        self.vnosov = 0

    # ------------------------------------------------------------------ gradnja
    def pripravljen(self) -> bool:
        return self._podatki is not None

    def star(self) -> bool:
        if self._podatki is None:
            return True
        zdaj = time.monotonic()
        if zdaj - self.zgrajen > STAROST_S:
            return True
        return self.zastarel_ob > self.zgrajen and zdaj - self.zgrajen > NAJMANJ_MED_GRADNJAMA_S

    def zastarel(self) -> None:
        """Safeer je sam kaj ustvaril, premaknil ali preimenoval: naslednje iskanje naj indeks obnovi."""
        self.zastarel_ob = time.monotonic()

    def zgradi_v_ozadju(self) -> bool:
        """Začne gradnjo v svoji niti, če še ne teče. Vrne, ali jo je začel."""
        with self._zaklep:
            if self._gradi:
                return False
            self._gradi = True
            self._konec_gradnje.clear()
        threading.Thread(target=self._zgradi_varno, name="safeer-iskalnik", daemon=True).start()
        return True

    def pocakaj(self, najvec_s: float) -> bool:
        """Počaka na konec gradnje, ki teče (največ `najvec_s`). Vrne, ali je indeks pripravljen."""
        if self._gradi:
            self._konec_gradnje.wait(max(0.0, najvec_s))
        return self.pripravljen()

    def _zgradi_varno(self) -> None:
        try:
            self.zgradi()
        except Exception as e:  # noqa: BLE001 - iskanje ne sme podreti Safeer OS; ostane staro iskanje po disku
            print("[SafeerOS] indeks datotek:", e)
        finally:
            with self._zaklep:
                self._gradi = False
            self._konec_gradnje.set()

    def zgradi(self) -> int:
        """Prehodi drevo po širini (plitve datoteke najprej - če zmanjka prostora, ostanejo te) in zamenja indeks."""
        zacetek, zacetek_ura = time.monotonic(), time.time()
        try:
            naprava = os.stat(self.koren).st_dev
        except OSError:
            naprava = None
        kljuci, imena = bytearray(), bytearray()
        zac_k, zac_i, mapa_vnosa = array("I"), array("I"), array("I")
        je_mapa = bytearray()
        mape: List[str] = []
        globine = bytearray()
        vrsta = deque([(self.koren, 0)])
        n, nepopoln, obdelanih = 0, False, 0
        while vrsta:
            mapa, globina = vrsta.popleft()
            try:
                with os.scandir(mapa) as vsebina:
                    vnosi = list(vsebina)
            except OSError:
                continue
            indeks_mape = len(mape)
            mape.append(mapa)
            globine.append(min(globina, 255))
            for v in vnosi:
                ime = v.name
                if ime.startswith(".") or "\n" in ime:
                    continue
                try:
                    mapa_je = v.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if mapa_je and ime not in os_datoteke.PRESKOCI and globina < NAJVEC_GLOBINA:
                    try:
                        # Drug disk ali omrežno mesto pod domačo mapo: ne hodimo vanj (počasno, lahko ogromno).
                        if naprava is None or v.stat(follow_symlinks=False).st_dev == naprava:
                            vrsta.append((v.path, globina + 1))
                    except OSError:
                        pass
                zac_k.append(len(kljuci))
                kljuci += kljuc(ime).encode("utf-8", "surrogateescape")
                kljuci += b"\n"
                zac_i.append(len(imena))
                imena += ime.encode("utf-8", "surrogateescape")
                imena += b"\n"
                mapa_vnosa.append(indeks_mape)
                je_mapa.append(1 if mapa_je else 0)
                n += 1
            obdelanih += 1
            if n >= self.najvec or time.monotonic() - zacetek > self.rok_s:
                nepopoln = bool(vrsta)
                break
            if obdelanih % 200 == 0:
                time.sleep(0)          # prepusti izvajanje vmesniku (GIL)
        self._podatki = (bytes(kljuci), zac_k, bytes(imena), zac_i, mapa_vnosa, bytes(je_mapa), mape, bytes(globine))
        self.vnosov, self.nepopoln, self.zgrajen, self.zgrajen_ura = n, nepopoln, time.monotonic(), zacetek_ura
        return n

    # ------------------------------------------------------------------ iskanje
    def isci(self, niz: str, meja: int = 60) -> List[Tuple[str, str, bool, float]]:
        """Najboljših `meja` zadetkov kot (pot, ime, je_mapa, ocena). Vse besede poizvedbe morajo biti v imenu."""
        podatki = self._podatki
        besede = [b.encode("utf-8", "surrogateescape") for b in kljuc(niz).split() if b]
        if podatki is None or not besede:
            return []
        kljuci, zac_k, imena, zac_i, mapa_vnosa, je_mapa, mape, globine = podatki
        n = len(zac_k)
        glavna = max(besede, key=len)
        ostale = [b for b in besede if b is not glavna]
        cela = kljuc(niz).strip().encode("utf-8", "surrogateescape")
        kandidati: List[Tuple[float, int]] = []
        poz = kljuci.find(glavna)
        while poz >= 0 and len(kandidati) < NAJVEC_KANDIDATOV:
            i = bisect_right(zac_k, poz) - 1
            zacetek = zac_k[i]
            konec = (zac_k[i + 1] if i + 1 < n else len(kljuci)) - 1
            if poz + len(glavna) <= konec:                  # ujemanje ne sega čez mejo med imenoma
                ime_k = kljuci[zacetek:konec]
                if all(o in ime_k for o in ostale):
                    kandidati.append((self._ocena(ime_k, poz - zacetek, glavna, cela, globine[mapa_vnosa[i]], je_mapa[i]), i))
            poz = kljuci.find(glavna, konec + 1)
        kandidati.sort(key=lambda k: (-k[0], k[1]))
        izid = []
        for ocena, i in kandidati[:max(1, int(meja))]:
            konec = (zac_i[i + 1] if i + 1 < n else len(imena)) - 1
            ime = imena[zac_i[i]:konec].decode("utf-8", "surrogateescape")
            izid.append((os.path.join(mape[mapa_vnosa[i]], ime), ime, bool(je_mapa[i]), ocena))
        return izid

    @staticmethod
    def _ocena(ime_k: bytes, kje: int, beseda: bytes, cela: bytes, globina: int, mapa: int) -> float:
        """Višje je bolje: celo ime > začetek imena > začetek besede v imenu > sredina; plitvejše in krajše prej."""
        brez_koncnice = ime_k.rsplit(b".", 1)[0] if b"." in ime_k[1:] else ime_k
        if cela in (ime_k, brez_koncnice):
            ocena = 100.0
        elif kje == 0:
            ocena = 80.0
        elif ime_k[kje - 1] in _MEJE:
            ocena = 60.0
        else:
            ocena = 40.0
        return ocena - min(globina, 10) * 1.5 - min(len(ime_k), 80) / 40.0 + (1.0 if mapa else 0.0)

    def stanje(self) -> dict:
        return {"pripravljen": self.pripravljen(), "vnosov": self.vnosov, "nepopoln": self.nepopoln,
                "starost": round(time.monotonic() - self.zgrajen, 1) if self._podatki is not None else None}


_indeks: Optional[Indeks] = None


def indeks() -> Indeks:
    global _indeks
    if _indeks is None:
        _indeks = Indeks()
    return _indeks


def zastarel() -> None:
    """Safeer je sam spremenil datoteke (novo, premik, preimenovanje, Smeti): indeks naj se ob naslednjem iskanju obnovi."""
    if _indeks is not None:
        _indeks.zastarel()


def _sveze(niz: str, idx: Indeks, ze: set) -> List[Tuple[float, dict]]:
    """Datoteke in mape, ki so se na prvi ravni uporabnikovih map (domača mapa, Namizje, Dokumenti, Prejemi ...)
    pojavile po gradnji indeksa - prenos, ki se je pravkar končal v brskalniku, posnetek zaslona, datoteka z druge
    naprave. Indeks se obnavlja največ na STAROST_S; brez tega take datoteke iskanje do takrat ne bi našlo, čeprav
    je v mapi vidna. Vrne (ocena, vnos) za zadetke, ki jih v `ze` (poti iz indeksa) še ni."""
    besede = [b for b in kljuc(niz).split() if b]
    if not besede or not idx.zgrajen_ura:
        return []
    glavna = max(besede, key=len).encode("utf-8", "surrogateescape")
    cela = kljuc(niz).strip().encode("utf-8", "surrogateescape")
    od = idx.zgrajen_ura - 2.0
    najdeni: List[Tuple[float, dict]] = []
    for m in os_datoteke.uporabniske_mape(idx.koren):
        mapa = os.path.abspath(m["pot"])
        if mapa != idx.koren and not mapa.startswith(idx.koren.rstrip(os.sep) + os.sep):
            continue                                    # mapa zunaj domače (drug disk): indeks je ne pokriva
        globina = 0 if mapa == idx.koren else len(os.path.relpath(mapa, idx.koren).split(os.sep))
        try:
            with os.scandir(mapa) as vsebina:
                for stevec, v in enumerate(vsebina):
                    if stevec >= NAJVEC_V_MAPI_V_ZIVO:
                        break
                    ime = v.name
                    if ime.startswith(".") or "\n" in ime or v.path in ze:
                        continue
                    ime_k = kljuc(ime)
                    if not all(b in ime_k for b in besede):
                        continue
                    try:
                        st = v.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if max(st.st_mtime, st.st_ctime) < od:       # ctime: tudi datoteka, premaknjena sem s starim datumom
                        continue
                    e = os_datoteke._element(v.path, ime)
                    if e is None:
                        continue
                    ime_b = ime_k.encode("utf-8", "surrogateescape")
                    najdeni.append((Indeks._ocena(ime_b, ime_b.find(glavna), glavna, cela, globina, 1 if e["mapa"] else 0), e))
        except OSError:
            continue
    return najdeni


def isci(niz: str, meja: int = os_datoteke.NAJVEC_ZADETKOV) -> List[dict]:
    """Datoteke in mape v domači mapi po imenu - enaka oblika kot os_datoteke.isci. Iz indeksa, ko je pripravljen;
    prvo iskanje (in kar v indeks ni šlo) odgovori hoja po disku, indeks pa se medtem gradi v ozadju."""
    niz = str(niz or "").strip()
    if len(niz) < 2:
        return []
    idx = indeks()
    if not idx.pripravljen():
        idx.zgradi_v_ozadju()
        if not idx.pocakaj(CAKAJ_PRVI_INDEKS_S):
            return os_datoteke.isci(niz, idx.koren)         # velika mapa, hladen disk: tokrat še hoja po disku
    elif idx.star():
        idx.zgradi_v_ozadju()
    ocenjeni: List[Tuple[float, int, dict]] = []
    zdaj = time.time()
    for mesto, (pot, ime, _mapa, ocena) in enumerate(idx.isci(niz, meja * 2)):   # rezerva: česar na disku ni več, izpade
        e = os_datoteke._element(pot, ime)
        if e is not None:
            ocenjeni.append((ocena + svezina(zdaj - float(e.get("spremenjeno") or 0)), mesto, e))
    # Kar je drug program pravkar shranil v uporabnikove mape (prenos, posnetek zaslona), indeks še ne pozna.
    sveze = _sveze(niz, idx, {e["pot"] for _ocena, _mesto, e in ocenjeni})
    if sveze:
        idx.zastarel()                                  # indeks se obnovi v ozadju (ob naslednjem iskanju)
        ocenjeni.extend((ocena + svezina(zdaj - float(e.get("spremenjeno") or 0)), -1, e) for ocena, e in sveze)
    if not ocenjeni and idx.nepopoln:
        return os_datoteke.isci(niz, idx.koren)             # indeks ni zajel vsega: poskusi še hoja po disku
    ocenjeni.sort(key=lambda o: (-o[0], o[1]))
    return [e for _ocena, _mesto, e in ocenjeni[:meja]]


def svezina(starost_s: float) -> float:
    """Dodatek k oceni za nedavno spremenjene datoteke: s čimer si pravkar delal, je verjetneje to, kar iščeš.
    Manjši od razlike med vrstami ujemanja (začetek imena ostane pred sredino)."""
    if starost_s < 0:
        return 0.0
    if starost_s < 86400:
        return 8.0
    if starost_s < 7 * 86400:
        return 6.0
    if starost_s < 30 * 86400:
        return 4.0
    if starost_s < 365 * 86400:
        return 2.0
    return 0.0
