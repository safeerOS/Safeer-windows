"""Izvirni jezik filmov in serij za izbiro jezika vsebine (Medijski center).

Katalogi dodatkov jezika naslova ne povedo. Vprasamo Wikidato - prosto zbirko znanja, brez kljuca in brez racuna: po
id-ju IMDb vrne jezike naslova (P364) in drzave izvora (P495). Naslov ima lahko vec jezikov (film, v katerem govorijo
anglesko, francosko in japonsko); izbira velja za GLAVNEGA: jezik, ki je doma v eni od drzav izvora.

Ista pravila in isti seznam jezikov kot Safeer OS za Android (os/IzvirniJezik.kt, os/IzvirniJeziki.kt); preizkus
tests/test_izvirni_jezik.py ima iste primere.

Kaj gre iz racunalnika: samo javni id-ji naslovov (IMDb) iz kataloga na zaslonu - in to sele, ko uporabnik izbere
jezik. O uporabniku, njegovih dodatkih ali tem, kaj gleda, Wikidata ne izve nicesar.

Modul nima odvisnosti od drugih delov Safeerja (isti je v Safeer OS za Windows).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Collection, Dict, Iterable, List, NamedTuple, Optional

_dnevnik = logging.getLogger("safeer")


class Jezik(NamedTuple):
    """koda = ISO 639-1; predmeti = jezik v Wikidati (Q...); drzave = drzave (Q...), kjer je to jezik domacih filmov."""
    koda: str
    predmeti: tuple
    drzave: tuple


#: Jeziki, ki jih ponudi izbira. Predmeti so preverjeni v Wikidati (4. 10. 2026).
#:
#: Prvi predmet je jezik sam, ostali so njegove razlicice, kot jih Wikidata res uporablja pri filmih in serijah
#: (vseh 220 najpogostejsih vrednosti P364, 4. 10. 2026): »American English« (Breaking Bad), »Brazilian Portuguese«,
#: »Swiss German«, »Egyptian Arabic«, »Putonghua« ... Brez njih bi tak naslov veljal za naslov neznanega jezika in
#: se med izbiro jezika ne bi pokazal. Narecja, ki jih katalogi vodijo pod jezikom drzave (neapeljscina, sicilscina,
#: bavarscina, kitajski jeziki), sodijo pod ta jezik - tako jih vodi tudi TMDB.
JEZIKI: tuple = (
    Jezik("sl", ("Q9063",), ("Q215", "Q36704", "Q83286")),
    Jezik("en", ("Q1860", "Q7976", "Q7979", "Q44679", "Q44676", "Q665624", "Q44661", "Q1156228", "Q1553250"),
          ("Q30", "Q145", "Q16", "Q408", "Q27", "Q664")),
    Jezik("de", ("Q188", "Q387066", "Q306626", "Q8077088", "Q56474", "Q29540"),
          ("Q183", "Q713750", "Q16957", "Q40", "Q39")),
    Jezik("fr", ("Q150", "Q979914", "Q1450506", "Q3083196"), ("Q142", "Q31", "Q39", "Q16")),
    Jezik("es", ("Q1321", "Q616620", "Q56649449", "Q4477330"),
          ("Q29", "Q96", "Q414", "Q739", "Q298", "Q419", "Q717", "Q241", "Q77")),
    Jezik("it", ("Q652", "Q33845", "Q33973"), ("Q38", "Q39")),
    Jezik("pt", ("Q5146", "Q750553"), ("Q45", "Q155")),
    # Srbohrvascina (Q9301) je jezik starejsih jugoslovanskih filmov: sodi k hrvascini, srbscini in bosanscini.
    Jezik("hr", ("Q6654", "Q9301"), ("Q224", "Q36704", "Q83286")),
    Jezik("sr", ("Q9299", "Q9301"), ("Q403", "Q37024", "Q838261", "Q236", "Q36704", "Q83286")),
    Jezik("bs", ("Q9303", "Q9301"), ("Q225", "Q36704", "Q83286")),
    Jezik("mk", ("Q9296",), ("Q221", "Q36704", "Q83286")),
    Jezik("ru", ("Q7737",), ("Q159", "Q15180")),
    Jezik("pl", ("Q809",), ("Q36",)),
    Jezik("cs", ("Q9056",), ("Q213", "Q33946")),
    Jezik("sk", ("Q9058",), ("Q214", "Q33946")),
    Jezik("hu", ("Q9067",), ("Q28",)),
    Jezik("nl", ("Q7411", "Q34147", "Q1404296"), ("Q55", "Q31")),
    Jezik("sv", ("Q9027",), ("Q34",)),
    Jezik("da", ("Q9035",), ("Q35",)),
    Jezik("no", ("Q9043", "Q25167", "Q25164"), ("Q20",)),
    Jezik("fi", ("Q1412",), ("Q33",)),
    Jezik("is", ("Q294",), ("Q189",)),
    Jezik("tr", ("Q256",), ("Q43",)),
    Jezik("el", ("Q9129", "Q36510"), ("Q41",)),
    Jezik("ro", ("Q7913",), ("Q218",)),
    Jezik("bg", ("Q7918",), ("Q219",)),
    Jezik("sq", ("Q8748",), ("Q222", "Q1246")),
    Jezik("uk", ("Q8798",), ("Q212",)),
    Jezik("ja", ("Q5287",), ("Q17",)),
    Jezik("ko", ("Q9176",), ("Q884",)),
    Jezik("zh", ("Q7850", "Q9192", "Q727694", "Q9186", "Q7033959", "Q24841726", "Q262828", "Q1048980", "Q5894342",
                 "Q13414913", "Q2278732", "Q4380827", "Q36778", "Q36495", "Q3846528", "Q33375", "Q2391532"),
          ("Q148", "Q8646", "Q865")),
    Jezik("hi", ("Q1568",), ("Q668",)),
    Jezik("ta", ("Q5885",), ("Q668",)),
    Jezik("te", ("Q8097",), ("Q668",)),
    Jezik("th", ("Q9217",), ("Q869",)),
    Jezik("ar", ("Q13955", "Q29919", "Q56426", "Q56240", "Q56499", "Q56232", "Q2143071", "Q1516642", "Q6448936"),
          ("Q79",)),
    Jezik("he", ("Q9288", "Q8141"), ("Q801",)),
    Jezik("fa", ("Q9168", "Q178440"), ("Q794",)),
)

KODE: tuple = tuple(j.koda for j in JEZIKI)

#: Kode, pod katerimi katalogi (TMDB) vodijo isti jezik izbire: sh = srbohrvascina, cn = kantonscina,
#: nb/nn = norvescina (bokmal, nynorsk), iw = stara koda za hebrejscino.
SORODNE: Dict[str, tuple] = {"hr": ("sh",), "sr": ("sh",), "bs": ("sh",), "zh": ("cn",), "no": ("nb", "nn"), "he": ("iw",)}

#: Najvec naslovov v enem vprasanju (dolzina naslova poizvedbe ostane pod 4 kB).
NAJVEC_V_PAKETU = 80
#: Najvec naslovov, za katere vprasamo ob enem klicu (ostali pridejo na vrsto ob naslednjem pogledu).
NAJVEC_NA_KLIC = 1200

_IMDB = re.compile(r"^tt[0-9]{5,10}$")
_PREDMET = re.compile(r"^Q[0-9]{1,10}$")

#: Znan jezik se ne spreminja; neznanega vprasamo znova cez nekaj dni (Wikidata se dopolnjuje). Sekunde.
ZNAN_VELJA = 180 * 86_400
NEZNAN_VELJA = 7 * 86_400


def po_kodi(koda: str) -> Optional[Jezik]:
    return next((j for j in JEZIKI if j.koda == koda), None)


def kode_vira(koda: str) -> tuple:
    """Vse kode, pod katerimi katalog vodi jezik izbire (prva je koda sama)."""
    return (koda,) + SORODNE.get(koda, ())


def ustreza(jezik_vnosa, izbrani: str) -> bool:
    """Ali vnos z jezikom, kot ga pove vir (koda ISO 639-1 ali sorodna), sodi pod izbrani jezik."""
    return bool(jezik_vnosa) and str(jezik_vnosa) in kode_vira(izbrani)


def veljaven_imdb(ident) -> bool:
    return isinstance(ident, str) and bool(_IMDB.match(ident))


def glavni(jeziki: Collection[str], drzave: Collection[str]) -> List[str]:
    """Glavni jezik naslova. `jeziki` in `drzave` sta predmeta Wikidate (jeziki naslova, drzave izvora). Vrne kode
    ponujenih jezikov, pod katere naslov sodi - obicajno eno; prazno = ne vemo ali jezika ni med ponujenimi.

    - jezik, ki je doma v kateri od drzav izvora, ima prednost (film ameriske izdelave z nekaj francoscine je angleski);
    - med vec domacimi jeziki zmaga anglescina (ameriski film z nemskim soproducentom ostane angleski);
    - srbohrvaski jugoslovanski film sodi pod hrvascino, srbscino in bosanscino hkrati.
    """
    jeziki, drzave = set(jeziki), set(drzave)
    vsi = [j for j in JEZIKI if any(p in jeziki for p in j.predmeti)]
    if not vsi:
        return []
    domaci = [j for j in vsi if any(d in drzave for d in j.drzave)]
    izbrani = domaci or vsi
    # Vec razlicnih jezikov in anglescina med njimi: anglescina. (Vec kod istega jezika - srbohrvascina - ostane.)
    razlicni = len({frozenset(p for p in j.predmeti if p in jeziki) for j in izbrani})
    if razlicni > 1 and any(j.koda == "en" for j in izbrani):
        return ["en"]
    return [j.koda for j in izbrani]


def poizvedba_paket(idji: Iterable[str]) -> str:
    """Jeziki in drzave izvora za naslove z danimi id-ji IMDb (SPARQL). Neveljavni id-ji izpadejo."""
    cisti = list(dict.fromkeys(i for i in idji if veljaven_imdb(i)))[:NAJVEC_V_PAKETU]
    vrednosti = " ".join('"%s"' % i for i in cisti)
    return ("SELECT ?imdb ?jezik ?drzava WHERE { VALUES ?imdb { %s } ?f wdt:P345 ?imdb . "
            "OPTIONAL { ?f wdt:P364 ?jezik } OPTIONAL { ?f wdt:P495 ?drzava } }" % vrednosti)


def celica(surova: str) -> str:
    """Celica TSV: "niz" (z ubeznimi znaki, lahko z oznako jezika ali vrste), <naslov predmeta> ali gola vrednost."""
    s = surova.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1].rsplit("/", 1)[-1]
    if not s.startswith('"'):
        return s
    izhod = []
    i = 1
    while i < len(s):
        c = s[i]
        if c == '"':
            break
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in "tn":
                izhod.append(" ")
            elif n != "r":
                izhod.append(n)
            i += 2
            continue
        izhod.append(c)
        i += 1
    return "".join(izhod)


def _vrstice(tsv: str) -> List[List[str]]:
    return [[celica(c) for c in v.split("\t")] for v in tsv.split("\n")[1:] if v.strip()]


def iz_paketa(tsv: str) -> Dict[str, List[str]]:
    """Odgovor na `poizvedba_paket`: id IMDb -> kode glavnega jezika. Naslov, ki ga Wikidata ne pozna, v izidu manjka."""
    jeziki: Dict[str, set] = {}
    drzave: Dict[str, set] = {}
    for v in _vrstice(tsv):
        ident = v[0] if v else ""
        if not veljaven_imdb(ident):
            continue
        jeziki.setdefault(ident, set())
        if len(v) > 1 and _PREDMET.match(v[1]):
            jeziki[ident].add(v[1])
        if len(v) > 2 and _PREDMET.match(v[2]):
            drzave.setdefault(ident, set()).add(v[2])
    return {ident: glavni(j, drzave.get(ident, ())) for ident, j in jeziki.items()}


def v_zapis(kode: Iterable[str], cas: float) -> str:
    """Zapis v predpomnilniku: "kode,locene,z,vejico;cas" (prazne kode = neznan jezik)."""
    return ",".join(k for k in kode if k in KODE) + ";" + str(int(cas))


def iz_zapisa(zapis: Optional[str], zdaj: float) -> Optional[List[str]]:
    """Kode iz zapisa, ce se velja; None = zapisa ni, je poskodovan ali je potekel (vprasati je treba znova)."""
    if not zapis:
        return None
    deli = zapis.split(";")
    if len(deli) != 2:
        return None
    try:
        cas = int(deli[1])
    except ValueError:
        return None
    kode = [k for k in deli[0].split(",") if k in KODE]
    velja = ZNAN_VELJA if kode else NEZNAN_VELJA
    return kode if 0 <= zdaj - cas <= velja else None


class IzvirniJeziki:
    """Glavni jezik naslovov iz Wikidate s predpomnilnikom na disku (TSV: id IMDb <tab> zapis)."""

    NASLOV = "https://query.wikidata.org/sparql"
    NAJVEC_ZAPISOV = 20_000
    CAKAJ = 8           # s na en odgovor Wikidate; katalog ne sme viseti na njej
    PREMOR_PO_NAPAKI = 60   # s brez vprasanj, ko Wikidata ne odgovori (izpad omrezja: katalog ne caka znova in znova)

    def __init__(self, datoteka: str, razlicica: str = "", odpri: Optional[Callable] = None,
                 ura: Callable[[], float] = time.time):
        self._datoteka = str(datoteka)
        self._agent = "SafeerOS/%s (https://safeer.si)" % (razlicica or "1.0")
        self._odpri = odpri or urllib.request.urlopen
        self._ura = ura
        self._zapisi: Dict[str, str] = {}
        self._nalozeno = False
        self._kljuc = threading.RLock()
        #: Wikidata dovoli le nekaj socasnih vprasanj z enega naslova.
        self._socasno = threading.BoundedSemaphore(4)
        #: Po odgovoru »prevec vprasanj« (429) ali izpadu do takrat ne sprasujemo.
        self._premor_do = 0.0

    # ------------------------------------------------------------------ predpomnilnik
    def _nalozi(self) -> None:
        with self._kljuc:
            if self._nalozeno:
                return
            self._nalozeno = True
            try:
                with open(self._datoteka, encoding="utf-8") as d:
                    for v in d:
                        ident, _, zapis = v.rstrip("\n").partition("\t")
                        if veljaven_imdb(ident) and zapis:
                            self._zapisi[ident] = zapis
            except OSError:
                pass

    def _shrani(self) -> None:
        with self._kljuc:
            if len(self._zapisi) > self.NAJVEC_ZAPISOV:
                # Prevec zapisov: najstarejsi gredo (cas je zadnji del zapisa).
                def cas(z: str) -> int:
                    try:
                        return int(z.rsplit(";", 1)[-1])
                    except ValueError:
                        return 0
                odvec = len(self._zapisi) - self.NAJVEC_ZAPISOV * 9 // 10
                for ident in sorted(self._zapisi, key=lambda i: cas(self._zapisi[i]))[:odvec]:
                    self._zapisi.pop(ident, None)
            try:
                os.makedirs(os.path.dirname(self._datoteka) or ".", exist_ok=True)
                # Edinstvena zacasna (mkstemp) kot core/shramba_json.atomsko_odpri - modul je brez uvozov Safeerja
                # (Safeer OS za Windows), zato tu sam (pregled 4. 11. 2026: prej stalni <pot>.tmp).
                import tempfile
                rocaj, zacasna = tempfile.mkstemp(prefix="." + os.path.basename(self._datoteka) + ".", suffix=".tmp",
                                                  dir=os.path.dirname(self._datoteka) or ".")
                try:
                    with os.fdopen(rocaj, "w", encoding="utf-8") as d:
                        for ident, zapis in self._zapisi.items():
                            d.write(ident + "\t" + zapis + "\n")
                    os.replace(zacasna, self._datoteka)
                except BaseException:
                    try:
                        os.unlink(zacasna)
                    except OSError:
                        pass
                    raise
            except OSError as e:
                _dnevnik.info("Izvirni jeziki: zapis ni uspel (%s)", type(e).__name__)

    def znani(self, imdb: str) -> Optional[List[str]]:
        """Kar o naslovu ze vemo, brez omrezja: kode glavnega jezika (prazno = neznan), None = se nismo vprasali."""
        self._nalozi()
        return iz_zapisa(self._zapisi.get(imdb), self._ura())

    # ------------------------------------------------------------------ omrezje
    def _vprasaj(self, poizvedba: str) -> Optional[str]:
        if self._ura() < self._premor_do:
            return None
        if not self._socasno.acquire(timeout=20):
            return None
        try:
            if self._ura() < self._premor_do:      # medtem je drugo vprasanje naletelo na izpad
                return None
            zahteva = urllib.request.Request(
                self.NASLOV + "?" + urllib.parse.urlencode({"query": poizvedba}),
                # Wikidata prosi za prepoznaven opis odjemalca z naslovom za stik.
                headers={"User-Agent": self._agent, "Accept": "text/tab-separated-values"})
            with self._odpri(zahteva, timeout=self.CAKAJ) as odgovor:
                if getattr(odgovor, "status", 200) != 200:
                    return None
                return odgovor.read(4 * 1024 * 1024 + 1).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    cakaj = min(3600, max(30, int(e.headers.get("Retry-After", "120"))))
                except (TypeError, ValueError):
                    cakaj = 120
                self._premor_do = self._ura() + cakaj
                _dnevnik.info("Izvirni jeziki: Wikidata prosi za premor %s s", cakaj)
            return None
        except Exception as e:  # noqa: BLE001 - izpad omrezja ne sme podreti kataloga
            self._premor_do = self._ura() + self.PREMOR_PO_NAPAKI
            _dnevnik.info("Izvirni jeziki: %s", type(e).__name__)
            return None
        finally:
            self._socasno.release()

    def jeziki(self, idji: Iterable[str]) -> Dict[str, List[str]]:
        """Glavni jezik naslovov (id IMDb -> kode). Kar je v predpomnilniku, pride takoj; ostalo vprasamo Wikidato v
        paketih (do stiri hkrati). Klic iz delovne niti (omrezje). Naslov, za katerega odgovora ni (izpad), v izidu
        manjka in ostane nevprasan; naslov, ki ga Wikidata ne pozna, je zapisan kot neznan (prazen seznam)."""
        self._nalozi()
        zdaj = self._ura()
        izid: Dict[str, List[str]] = {}
        manjkajo: List[str] = []
        for ident in dict.fromkeys(i for i in idji if veljaven_imdb(i)):
            kode = iz_zapisa(self._zapisi.get(ident), zdaj)
            if kode is None:
                manjkajo.append(ident)
            else:
                izid[ident] = kode
        manjkajo = manjkajo[:NAJVEC_NA_KLIC]
        paketi = [manjkajo[od:od + NAJVEC_V_PAKETU] for od in range(0, len(manjkajo), NAJVEC_V_PAKETU)]

        def vprasaj(paket: List[str]):
            return paket, self._vprasaj(poizvedba_paket(paket))

        if len(paketi) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(paketi))) as bazen:
                odgovori = list(bazen.map(vprasaj, paketi))
        else:
            odgovori = [vprasaj(p) for p in paketi]
        novih = 0
        for paket, tsv in odgovori:
            if tsv is None:
                continue
            odgovor = iz_paketa(tsv)
            with self._kljuc:
                for ident in paket:
                    kode = odgovor.get(ident, [])
                    self._zapisi[ident] = v_zapis(kode, zdaj)
                    izid[ident] = kode
                    novih += 1
        if novih:
            self._shrani()
        return izid
