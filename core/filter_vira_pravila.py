"""Filter vira v mrezi Filmi/Serije (izbira »⚡ Usenet«) - cista logika brez omrezja in GTK.

Prenos 1:1 Androidovega FilterViraPravila.kt (TV je vzorec; lastnik 10. 11. 2026: Medijski center se na namizju obnasa
ENAKO kot na TV). Primeri iz tests/FilterViraPravilaTest.kt so 1:1 v tests/test_filter_vira_pravila.py, da TV in namizje
dokazano odlocata enako. Na namizju odlocitev pade v jedru (core/usenet_filter.py, os_katalog._katalog), zato je tu Python.

Lastnik 5. 11. 2026 19:34: »Prikazemo samo takrat, ko so izpolnjeni VSI pogoji, da si ga uporabnik lahko ogleda.«
Odlocitev je ena funkcija [lahko_gleda]: AND vseh pogojev; pogoj, ki je neznan ali ni izpolnjen, naslov skrije. Izid
preverbe ima dve vrsti »nicesar«: NI - vir je odgovoril in nima ustreznega toka (negativno za ure); NE_VEMO - napaka,
rok, ni povezave, meja indeksatorja: naslov se ne pokaze, a se NE zapise kot negativen (omejene ponovitve z zamikom).
Kodek: »zna TV SAM ALI naprava v Linku, ki tok pretvori« - zapis hrani oboje loceno ([Zapis.pomoc]).
"""
from __future__ import annotations

import enum
import re
import threading
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

from core import kakovost_oznake as K
from core import tok_izbira, usenet_pravila


class Izid(enum.Enum):
    NA_VOLJO = "NA_VOLJO"
    NI = "NI"
    NE_VEMO = "NE_VEMO"


class Pogoj(enum.Enum):
    GESLO = "GESLO"
    MANJKA = "MANJKA"
    PREDVAJALNIK = "PREDVAJALNIK"
    JEZIK_ZVOKA = "JEZIK_ZVOKA"
    PODNAPISI = "PODNAPISI"
    LOCLJIVOST = "LOCLJIVOST"
    VELIKOST = "VELIKOST"


class Pot(enum.Enum):
    """Kdo izdajo predvaja: naprava sama, samo pomocnik v Linku (pretvori v H.264/AAC) ali nihce (slika diska)."""
    TV = "TV"
    POMOCNIK = "POMOCNIK"
    NE = "NE"


VIR_USENET = "usenet"


@dataclass(frozen=True)
class Pogoji:
    """Pogoji, ki jih je postavil uporabnik; None = pogoja ni. [vir] = kljuc vira filtra (npr. VIR_USENET)."""
    vir: str
    jezik_zvoka: Optional[str] = None
    jezik_podnapisov: Optional[str] = None
    najmanj_visina: Optional[int] = None
    najvec_gb: Optional[float] = None


@dataclass(frozen=True)
class Izdaja:
    """Ena izdaja vira. [geslo] / [manjka]: True = indeksator jo oznaci, False = cista, None = indeksator ne pove (pogoj
    izpolnjen)."""
    naslov: str
    gb: float
    geslo: Optional[bool] = None
    manjka: Optional[bool] = None


@dataclass(frozen=True)
class Odgovor:
    """Odgovor vira za en naslov: izdaje None = vir ni odgovoril (napaka, rok, meja, ni povezave)."""
    izdaje: Optional[List[Izdaja]]


@dataclass(frozen=True)
class Izidi:
    """[racun] = ponudnik ali kljuc vira je nastavljen in ga smemo klicati."""
    racun: Izid
    odgovor: Optional[Odgovor]


_SLIKA_DISKA = re.compile(r"(^|[^a-z0-9])(iso|bdmv|complete[ ._-]?(uhd[ ._-]?)?blu-?ray|bd(25|50|66|100))([^a-z0-9]|$)")


def pot(r: Izdaja, z: tok_izbira.Zmoznosti) -> Pot:
    """Kodek in zvok iz imena izdaje (tok_izbira.opisi): ime brez oznake kodeka je H.264/AAC. Slike diska ne predvaja nihce.
    3D izdaje tudi ne (lastnik 10. 11. 2026, tok_izbira.je_3d): naslov s samo 3D izdajami v filtru Usenet ni na voljo."""
    if _SLIKA_DISKA.search(r.naslov.lower()) or tok_izbira.je_3d(r.naslov):
        return Pot.NE
    o = tok_izbira.opisi(r.naslov)
    video = not (o.hevc and not z.hevc) and not (o.desetbitni and not z.hevc10) and not (o.av1 and not z.av1)
    zvok = {"truehd": z.truehd, "dts": z.dts, "eac3": z.eac3, "ac3": z.ac3}.get(o.zvok, True)
    return Pot.TV if video and zvok else Pot.POMOCNIK


def pogoji_izdaje(r: Izdaja, p: Pogoji, z: tok_izbira.Zmoznosti, pomoc: bool = False) -> Dict[Pogoj, Izid]:
    """Pogoji ene izdaje (vsak posebej, za preizkuse in dnevnik)."""
    o = tok_izbira.opisi(r.naslov)
    t = r.naslov.lower()
    m: Dict[Pogoj, Izid] = {}
    m[Pogoj.GESLO] = Izid.NI if r.geslo is True else Izid.NA_VOLJO
    m[Pogoj.MANJKA] = Izid.NI if r.manjka is True else Izid.NA_VOLJO
    pt = pot(r, z)
    m[Pogoj.PREDVAJALNIK] = (Izid.NA_VOLJO if pt == Pot.TV else
                             (Izid.NA_VOLJO if pomoc else Izid.NI) if pt == Pot.POMOCNIK else Izid.NI)
    if p.jezik_zvoka is not None:
        jezik = tok_izbira.jezik_zvoka(r.naslov)
        # »vec«, »izvirnik«, »sinhronizacija« ali neoznaceno: jezika ne vemo.
        m[Pogoj.JEZIK_ZVOKA] = Izid.NA_VOLJO if jezik == p.jezik_zvoka else Izid.NI if len(jezik) == 2 else Izid.NE_VEMO
    if p.jezik_podnapisov is not None:
        j = re.escape(p.jezik_podnapisov)
        # Ime izdaje podnapise navede le izjemoma (»SLSUBS«, »Subs.SL«): brez navedbe ne vemo.
        m[Pogoj.PODNAPISI] = (Izid.NA_VOLJO if re.search(r"(^|[^a-z])(%ssubs?|subs?[ ._-]?%s)([^a-z]|$)" % (j, j), t)
                              else Izid.NE_VEMO)
    if p.najmanj_visina is not None:
        m[Pogoj.LOCLJIVOST] = (Izid.NE_VEMO if o.visina == 0 else
                               Izid.NA_VOLJO if o.visina >= p.najmanj_visina else Izid.NI)
    if p.najvec_gb is not None:
        m[Pogoj.VELIKOST] = Izid.NE_VEMO if r.gb <= 0.0 else Izid.NA_VOLJO if r.gb <= p.najvec_gb else Izid.NI
    return m


def ustrezne(izdaje: Sequence[Izdaja], p: Pogoji, z: tok_izbira.Zmoznosti, pomoc: bool = False) -> List[Izdaja]:
    """Izdaje, ki izpolnijo VSE pogoje (vrstni red indeksatorja ostane)."""
    return [r for r in izdaje if all(v == Izid.NA_VOLJO for v in pogoji_izdaje(r, p, z, pomoc).values())]


def izid(izidi: Izidi, p: Pogoji, z: tok_izbira.Zmoznosti, pomoc: bool = False) -> Izid:
    """NA_VOLJO - vsaj ena izdaja izpolni vse; NI - vir je odgovoril brez take izdaje; NE_VEMO - ni odgovora ali racuna."""
    if izidi.racun != Izid.NA_VOLJO:
        return Izid.NE_VEMO
    if izidi.odgovor is None or izidi.odgovor.izdaje is None:
        return Izid.NE_VEMO
    return Izid.NA_VOLJO if ustrezne(izidi.odgovor.izdaje, p, z, pomoc) else Izid.NI


def lahko_gleda(p: Pogoji, izidi: Izidi, z: tok_izbira.Zmoznosti, pomocnik: bool = False) -> bool:
    """Naslov sodi v filter samo, ce je pot do predvajanja s tem virom izpolnjena v celoti."""
    return izid(izidi, p, z, pomocnik) == Izid.NA_VOLJO


@dataclass(frozen=True)
class Preverba:
    izid: Izid
    pomoc: bool
    oznaka: Optional[K.Oznaka]


def oznaka(izdaje: Sequence[Izdaja], p: Pogoji, z: tok_izbira.Zmoznosti, pomoc: bool = False) -> Optional[K.Oznaka]:
    """Znacka kartice v filtru: najboljsa kakovost USTREZNIH izdaj tega vira, nikoli iz drugih virov ali kataloga."""
    return K.najboljsa([r.naslov for r in ustrezne(izdaje, p, z, pomoc)])


def preverba(izidi: Izidi, p: Pogoji, z: tok_izbira.Zmoznosti) -> Preverba:
    sam = izid(izidi, p, z)
    izdaje = (izidi.odgovor.izdaje if izidi.odgovor is not None else None) or []
    if sam == Izid.NA_VOLJO:
        return Preverba(sam, False, oznaka(izdaje, p, z))
    pomoc = sam == Izid.NI and izid(izidi, p, z, pomoc=True) == Izid.NA_VOLJO
    return Preverba(sam, pomoc, oznaka(izdaje, p, z, pomoc=True) if pomoc else None)


# ------------------------------------------------------------------ serije (katero epizodo vprasamo)

def epizoda_za_preverbo(naslednja: Optional[str], prva: Optional[str]) -> Optional[str]:
    """Naslednja za gledanje, sicer prva (S1E1). Ena poizvedba na serijo; None = serije ne moremo preveriti."""
    if naslednja and naslednja.strip():
        return naslednja
    return prva if prva and prva.strip() else None


@dataclass(frozen=True)
class Ogled:
    sezona: int
    epizoda: int
    odgledano: bool


@dataclass(frozen=True)
class Epizoda:
    id: str
    sezona: int
    epizoda: int


def naslednja_epizoda(epizode: Sequence[Tuple[int, int]], sezona: int, epizoda: int) -> Optional[Tuple[int, int]]:
    """Kot Android OsPravila.naslednjaEpizoda: posebne (sezona 0) samo za posebno, sicer redne po vrsti."""
    kandidati = sorted({e for e in epizode if e[1] >= 1 and (e[0] == 0 if sezona == 0 else e[0] >= 1)})
    return next((e for e in kandidati if e[0] > sezona or (e[0] == sezona and e[1] > epizoda)), None)


def epizoda_za_ogled(epizode: Sequence[Epizoda], ogled: Optional[Ogled]) -> Optional[Epizoda]:
    """Epizoda, ki jo bo uporabnik zares predvajal (kot »Nadaljuj«)."""
    prva = next((e for e in epizode if e.sezona >= 1), epizode[0] if epizode else None)
    if ogled is None:
        return prva
    zadnja = next((e for e in epizode if e.sezona == ogled.sezona and e.epizoda == ogled.epizoda), None)
    if not ogled.odgledano:
        return zadnja or prva
    n = naslednja_epizoda([(e.sezona, e.epizoda) for e in epizode], ogled.sezona, ogled.epizoda)
    if n is None:
        return prva
    return next((e for e in epizode if e.sezona == n[0] and e.epizoda == n[1]), prva)


def kljuc_ogleda(kljuc_: str, ogled: Optional[Ogled]) -> str:
    """Zapis serije velja za epizodo, ki se bo predvajala: zadnji ogled je del kljuca."""
    if ogled is None:
        return kljuc_
    return kljuc_ + "|S%dE%d" % (ogled.sezona, ogled.epizoda) + ("+" if ogled.odgledano else "")


def _je_imdb(ident: Optional[str]) -> bool:
    return ident is not None and len(ident) > 2 and ident.startswith("tt") and ident[2:].isdigit()


def id_epizode_po_imdb(imdb: Optional[str], id_epizode: str, sezona: int, epizoda: int) -> Optional[str]:
    """Kot Android SerijePravila.idEpizodePoImdb: `tt…:S:E`, ce se razlikuje od id-ja dodatka."""
    if not _je_imdb(imdb) or sezona < 1 or epizoda < 1:
        return None
    v = "%s:%d:%d" % (imdb, sezona, epizoda)
    return v if v != id_epizode else None


def id_iskanja(idji: Sequence[Optional[str]]) -> Optional[str]:
    """Id iskanja Usenet - ENA funkcija za filter in predvajanje: prvi id, ki ga indeksator zna (usenet_pravila.iscemo)."""
    return next((i for i in idji if i is not None and usenet_pravila.iscemo(i)), None)


def id_iskanja_epizode(e: Epizoda, imdb_serije: Optional[str]) -> Optional[str]:
    return id_iskanja([e.id, id_epizode_po_imdb(imdb_serije, e.id, e.sezona, e.epizoda)])


def razlog_ne_vemo(racun: Izid, iden: Optional[str], iscemo: bool, poslano: bool, odgovor: Optional[str]) -> Optional[str]:
    """Razlog izida NE_VEMO za dnevnik: kratek niz brez kljuca in naslova."""
    if racun != Izid.NA_VOLJO:
        return "ni_racuna"
    if iden is None:
        return "ni_iden"
    if not iscemo:
        return "ni_imdb"
    if not poslano:
        return "kvota"
    return odgovor


# ------------------------------------------------------------------ proracun preverb mreze

@dataclass(frozen=True)
class Proracun:
    zahteva: int
    ostalo: int
    vnaprej: bool = False


#: Novih naslovov na zahtevo uporabnika (odprtje mreze, Nalozi vec) in prednalaganje naslednje strani (enkrat).
PRORACUN_MREZE = 40
VNAPREJ_MREZE = 20


def proracun(prej: Optional[Proracun], ista_mreza: bool, zahteva: int) -> Proracun:
    """Vsaka zahteva uporabnika da nov PRORACUN_MREZE; ko ga porabi, enkrat se VNAPREJ_MREZE v ozadju."""
    if prej is None or not ista_mreza or zahteva != prej.zahteva:
        return Proracun(zahteva, PRORACUN_MREZE)
    if prej.ostalo <= 0 and not prej.vnaprej:
        return replace(prej, ostalo=VNAPREJ_MREZE, vnaprej=True)
    return prej


# ------------------------------------------------------------------ zapisi (kljuc: vir + racun + naslov)

_MINUTA = 60_000
_URA = 60 * _MINUTA
#: NA_VOLJO nima izteka (velja, dokler je vsebina pri viru); odstrani ga klik z 0 izdajami (pozabi).
NA_VOLJO_VELJA = 2 ** 63 - 1
NI_VELJA = 6 * _URA
NAJVEC_PONOVITEV = 3
PRVI_ZAMIK_MS = 2 * _MINUTA


@dataclass(frozen=True)
class Zapis:
    izid: Izid
    cas: int
    oznaka: Optional[K.Oznaka] = None
    poskusov: int = 0
    pomoc: bool = False


def kljuc(vir: str, odtis_racuna: str, kljuc_naslova: str) -> str:
    return "%s|%s|%s" % (vir, odtis_racuna, kljuc_naslova)


def svez(z: Zapis, zdaj: int) -> bool:
    """Ura naprave se lahko premakne nazaj: zapis »iz prihodnosti« ni svez."""
    s = zdaj - z.cas
    if z.izid == Izid.NA_VOLJO:
        return 0 <= s <= NA_VOLJO_VELJA
    if z.izid == Izid.NI:
        return 0 <= s <= NI_VELJA
    return False


def pokazi(zapis: Optional[Zapis], zdaj: int, pomocnik: bool = False) -> bool:
    """Neznan ali zastarel naslov se ne pokaze; izdaja samo za pomocnika le, dokler je pomocnik v Linku."""
    return (zapis is not None and svez(zapis, zdaj)
            and (zapis.izid == Izid.NA_VOLJO or (zapis.izid == Izid.NI and zapis.pomoc and pomocnik)))


def zapisi(prej: Optional[Zapis], izid_: Izid, oznaka_: Optional[K.Oznaka], zdaj: int, pomoc: bool = False) -> Zapis:
    """Pravi odgovor (NA_VOLJO, NI) nadomesti vse; »ne vemo« ne povozi svezega odgovora."""
    if izid_ == Izid.NA_VOLJO:
        return Zapis(izid_, zdaj, oznaka_)
    if izid_ == Izid.NI:
        return Zapis(izid_, zdaj, oznaka_ if pomoc else None, 0, pomoc)
    if prej is not None and prej.izid != Izid.NE_VEMO and svez(prej, zdaj):
        return prej
    poskusov = prej.poskusov if prej is not None and prej.izid == Izid.NE_VEMO else 0
    return Zapis(Izid.NE_VEMO, zdaj, None, poskusov + 1)


def vprasati(z: Optional[Zapis], zdaj: int) -> bool:
    """Brez zapisa ali po izteku da; po »ne vemo« sele po zamiku 2^(n-1)*PRVI_ZAMIK_MS in najvec NAJVEC_PONOVITEV-krat."""
    if z is None:
        return True
    if z.izid != Izid.NE_VEMO:
        return not svez(z, zdaj)
    s = zdaj - z.cas
    if s < 0:
        return False
    if z.poskusov >= NAJVEC_PONOVITEV:
        return s > NI_VELJA
    return s >= PRVI_ZAMIK_MS * (1 << max(0, min(10, z.poskusov - 1)))


def se_iscemo(z: Optional[Zapis], zdaj: int) -> bool:
    """Napis »Iscem …«: ni svezega odgovora in naslov bomo se vprasali."""
    if z is None:
        return True
    if z.izid != Izid.NE_VEMO:
        return not svez(z, zdaj)
    return z.poskusov < NAJVEC_PONOVITEV


def v_niz(z: Zapis) -> str:
    """»izid;cas;oznaka;poskusov;pomoc« - ista oblika kot na TV."""
    return "%s;%d;%s;%d;%s" % (z.izid.value, z.cas, z.oznaka.napis if z.oznaka else "", z.poskusov, "1" if z.pomoc else "0")


def iz_niza(s: Optional[str]) -> Optional[Zapis]:
    """Tudi zapis prejsnje razlicice (stiri polja, brez pomoci)."""
    if not isinstance(s, str):
        return None
    d = s.split(";")
    if len(d) not in (4, 5):
        return None
    p = d[4] if len(d) == 5 else None
    if p not in (None, "0", "1"):
        return None
    try:
        izid_ = Izid(d[0])
    except ValueError:
        return None
    try:
        cas = int(d[1])
        poskusov = int(d[3])
    except ValueError:
        return None
    if cas < 0 or not 0 <= poskusov <= 100:
        return None
    oznaka_ = None
    if d[2]:
        oznaka_ = K.Oznaka.iz_napisa(d[2])
        if oznaka_ is None:
            return None
    return Zapis(izid_, cas, oznaka_, poskusov, p == "1" and izid_ == Izid.NI)


# ------------------------------------------------------------------ kvota indeksatorja

class StevecKlikov:
    """Prekrivajoca se iskanja klika: prvo, ki konca, ne sprosti premora, dokler tece drugo."""

    def __init__(self) -> None:
        self._tece = 0
        self._zaklep = threading.Lock()

    def zacni(self) -> None:
        with self._zaklep:
            self._tece += 1

    def konec(self) -> bool:
        with self._zaklep:
            if self._tece > 0:
                self._tece -= 1
            return self._tece == 0


#: Lastnik 6. 11. 2026 (NZBFinder ~60/min, najvec 2 hkrati, razmik pod 1 s, premor ob meji od 5 s).
NA_MINUTO = 60
HKRATI = 2
RAZMIK_MS = 500
PRVI_PREMOR_MS = 5_000
REZERVIRANO_UPORABNIKU = 5
PREMOR_PREVERB_MS = 60_000
#: Rok enega iskanja - isti kot ob predvajanju (UsenetPravila.ISKANJE_ROK_MS na TV, 8 s).
ROK_MS = 8_000


class Omejevalnik:
    """Najvec [na_minuto] zahtev v drsecem oknu minute (vse mreze skupaj); ura je podana, zato je preizkusljiv. Meja
    indeksatorja (429, Newznab 500/501) ustavi vse za narascajoc premor (5 s, 10 s ... do 15 min)."""

    def __init__(self, na_minuto: int, prvi_premor_ms: int = PRVI_PREMOR_MS, najvec_premor_ms: int = 15 * _MINUTA,
                 razmik_ms: int = RAZMIK_MS, zadrzano: int = 0) -> None:
        self._na_minuto = int(na_minuto)
        self._prvi = int(prvi_premor_ms)
        self._najvec = int(najvec_premor_ms)
        self._razmik = int(razmik_ms)
        self._zadrzano = int(zadrzano)
        self._casi: deque = deque()
        self._premor_do = 0
        self._premor_preverb_do = 0
        self._zaporednih_mej = 0
        self._zaklep = threading.Lock()

    def _meja_preverb(self) -> int:
        return max(1, self._na_minuto - self._zadrzano)

    def _odrezi(self, zdaj: int) -> None:
        while self._casi and zdaj - self._casi[0] >= _MINUTA:
            self._casi.popleft()

    def smem(self, zdaj: int) -> bool:
        with self._zaklep:
            if zdaj < self._premor_do or zdaj < self._premor_preverb_do:
                return False
            self._odrezi(zdaj)
            if len(self._casi) >= self._meja_preverb():
                return False
            self._casi.append(zdaj)
            return True

    def razmik(self, zdaj: int) -> int:
        with self._zaklep:
            return max(0, self._casi[-1] + self._razmik - zdaj) if self._casi else 0

    def rezerviraj(self, zdaj: int) -> Optional[int]:
        """Razmik in poraba v ENEM koraku; vrne ms cakanja ali None (premor, kvota)."""
        with self._zaklep:
            if zdaj < self._premor_do or zdaj < self._premor_preverb_do:
                return None
            self._odrezi(zdaj)
            if len(self._casi) >= self._meja_preverb():
                return None
            ob = max(zdaj, self._casi[-1] + self._razmik) if self._casi else zdaj
            self._casi.append(ob)
            return ob - zdaj

    def meja(self, zdaj: int) -> None:
        with self._zaklep:
            if zdaj < self._premor_do:
                return
            korak = min(self._prvi << max(0, min(20, self._zaporednih_mej)), self._najvec)
            if self._zaporednih_mej < 20:
                self._zaporednih_mej += 1
            self._premor_do = zdaj + korak

    def uspeh(self, zdaj: int) -> None:
        """Uspesen odgovor ponastavi stopnjevanje - ne med premorom (zapozneli odgovor)."""
        with self._zaklep:
            if zdaj >= self._premor_do:
                self._zaporednih_mej = 0

    def v_premoru(self, zdaj: int) -> bool:
        with self._zaklep:
            return zdaj < self._premor_do

    def premor_se(self, zdaj: int) -> int:
        with self._zaklep:
            return max(0, self._premor_do - zdaj)

    def lahko(self, zdaj: int) -> bool:
        """Ali bi smem() zdaj dovolil - brez porabe (kvoto porabi samo poslana zahteva)."""
        with self._zaklep:
            if zdaj < self._premor_do or zdaj < self._premor_preverb_do:
                return False
            self._odrezi(zdaj)
            return len(self._casi) < self._meja_preverb()

    def rezerviraj_uporabniku(self, zdaj: int) -> Optional[int]:
        """Iskanje ob kliku: mesto iz CELOTNE kvote, premor preverb ga ne ustavi (premor indeksatorja pa)."""
        with self._zaklep:
            if zdaj < self._premor_do:
                return None
            self._odrezi(zdaj)
            if len(self._casi) >= self._na_minuto:
                return None
            ob = max(zdaj, self._casi[-1] + self._razmik) if self._casi else zdaj
            self._casi.append(ob)
            return ob - zdaj

    def ustavi_preverbe(self, zdaj: int, ms: int) -> None:
        with self._zaklep:
            self._premor_preverb_do = max(self._premor_preverb_do, zdaj + ms)

    def premor_preverb_se(self, zdaj: int) -> int:
        with self._zaklep:
            return max(0, self._premor_preverb_do - zdaj)

    def sprosti_preverbe(self) -> None:
        with self._zaklep:
            self._premor_preverb_do = 0

    def zabelezi(self, zdaj: int) -> None:
        with self._zaklep:
            self._odrezi(zdaj)
            self._casi.append(zdaj)


def poslji(racun: Izid, iden: Optional[str], iscemo: bool) -> bool:
    """Preverba poslje zahtevo samo z racunom, znanim id in naslovom, ki ga iscemo."""
    return racun == Izid.NA_VOLJO and iden is not None and iscemo


class Prazno(enum.Enum):
    ISCEM = "iscem"
    NE_ODGOVARJA = "ne_odgovarja"
    NI_NASLOVOV = "ni_naslovov"


def prazno(iscemo: bool, ne_odgovarja: bool) -> Prazno:
    if iscemo:
        return Prazno.ISCEM
    if ne_odgovarja:
        return Prazno.NE_ODGOVARJA
    return Prazno.NI_NASLOVOV


# ------------------------------------------------------------------ predvajanje (OsPravila, UsenetIskanjePravila)

def samo_usenet_izbran(usenet_izbran: bool, debrid_aktiven: bool, rocno: bool) -> bool:
    """»⚡ Usenet« (lasten ponudnik, brez debrida) omeji samodejno predvajanje na Usenet; »Vsi viri« in rocno ne."""
    return usenet_izbran and not debrid_aktiven and not rocno


class RazlogIskanja(enum.Enum):
    OK = "OK"
    NI_IZDAJ = "NI_IZDAJ"
    MEJA = "MEJA"
    NI_ODGOVORA = "NI_ODGOVORA"
    NI_INDEKSATORJA = "NI_INDEKSATORJA"


def razlog_iskanja(izdaj: Optional[int], meja_: bool) -> RazlogIskanja:
    if izdaj is None:
        return RazlogIskanja.MEJA if meja_ else RazlogIskanja.NI_ODGOVORA
    return RazlogIskanja.NI_IZDAJ if izdaj == 0 else RazlogIskanja.OK


def pozabi_zapis(razlog: RazlogIskanja) -> bool:
    """Zapis filtra se pozabi (kartica izgine) samo ob pravih 0 izdajah - ne ob meji ali izpadu."""
    return razlog == RazlogIskanja.NI_IZDAJ
