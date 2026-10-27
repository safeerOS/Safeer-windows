"""NZB za lasten pogon Usenet (lastnik 25. 10. 2026 22:10: neposredno predvajanje z Useneta na vseh platformah).

Varna razclenitev NZB v datoteke in segmente (message-id) - brez omrezja. Pravila so skupna z Android-tv (Kotlin):
tests/skupni-primeri/usenet-pogon.json (nzb_razcleni, nzb_ime, varno_ime, nntp_id).

Varnost (NZB pride od indeksatorja, ki ga izbere uporabnik - lahko je zlonameren):
- XXE in eksplozija entitet: '<!ENTITY', '<!ELEMENT', '<!ATTLIST', '<!NOTATION' kjerkoli = zavrnjeno. Dovoljen je samo
  standardni '<!DOCTYPE nzb PUBLIC ".." "..">' (skoraj vsak NZB ga ima) brez notranjega dela; ne nalaga se, pred
  razclenitvijo se nadomesti s presledki (odstranitev bi z lepljenjem »<!DOC<!DOCTYPE nzb>TYPE ...« sestavila nov
  DOCTYPE - pregled Grok 37 C4) in nato nobenega '<!' s crko ne sme biti vec; expat ne vidi nobenega DTD.
- Kodiranje samo UTF-8 ali ISO-8859-1 in brez bajta NUL: pregled zgoraj bi pri UTF-16 zgresil '<!ENTITY'.
- Meje: NZB do 20 MiB, 5000 datotek, 500 000 segmentov, 1 000 000 elementov; razclenjujemo sproti (XMLPullParser) in
  sproti brisemo obdelane datoteke - cel ElementTree iz 20 MiB '<a/>' bi zasedel stotine MiB.
- message-id je samo ASCII 0x21-0x7E brez '<' '>' (nikoli CR/LF: ukaz NNTP »BODY <id>« se ne da podaljsati).
- Ime datoteke iz subject je samo ime (brez poti, brez '..', brez znakov, ki jih Windows ne dovoli, brez vodilne pike,
  najvec 240 bajtov UTF-8).
- Skupine samo po RFC 3977 (ASCII brez presledkov in CR/LF - korak 2 jih lahko uporabi v ukazu GROUP); naslov brez
  znakov Cc in Cf (npr. U+202E obrne smer besedila v vmesniku).
- message-id in geslo arhiva nista v repr (pravilo: nikoli v dnevnik).
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from .usenet_pravila import NAJVEC_NZB_BAJTOV

NAJVEC_DATOTEK = 5000
NAJVEC_SEGMENTOV = 500_000
NAJVEC_ELEMENTOV = 1_000_000
NAJVEC_SEGMENTOV_DATOTEKE = 200_000
NAJVEC_IME_ZNAKOV = 200
NAJVEC_IME_BAJTOV = 240  # ext4/f2fs: ime najvec 255 bajtov; 200 kodnih tock CJK bi bilo 600 B (ENAMETOOLONG)
NAJVEC_NASLOV_ZNAKOV = 200
NAJVEC_SKUPIN = 50
NAJVEC_SKUPINA_ZNAKOV = 200
NAJVEC_ID_ZNAKOV = 248  # RFC 3977 3.6: message-id z '<' '>' najvec 250 oktetov

OK = "ok"
PREVELIK = "prevelik"
ZAVRNJENO_DTD = "zavrnjeno_dtd"
NAPAKA_XML = "napaka_xml"
NI_NZB = "ni_nzb"
PRAZEN = "prazen"


class NapakaNzb(ValueError):
    """Izid razclenitve brez vsebine NZB v sporocilu (vsebina lahko nosi zasebne podatke)."""

    def __init__(self, izid: str):
        super().__init__("nzb: " + izid)
        self.izid = izid


@dataclass(frozen=True)
class Segment:
    stevilka: int
    bajtov: int  # velikost clanka iz NZB (kodiran, z glavami) - NE velikost podatkov
    id: str = field(repr=False)


@dataclass(frozen=True)
class Datoteka:
    ime: Optional[str]
    skupine: tuple
    segmenti: tuple = field(repr=False)
    manjka: int = 0

    @property
    def bajtov_nzb(self) -> int:
        return sum(s.bajtov for s in self.segmenti)


@dataclass(frozen=True)
class Nzb:
    naslov: Optional[str]
    datoteke: tuple
    geslo: Optional[str] = field(default=None, repr=False)

    @property
    def ima_geslo(self) -> bool:
        return bool(self.geslo)


# ------------------------------------------------------------------ imena in message-id

_DOVOLJENI = frozenset(" ._-()[]+,!&'#@~")
_REZERVIRANA = frozenset({"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)}
                         | {"LPT%d" % i for i in range(1, 10)})


def _dovoljen(z: str) -> bool:
    if z in _DOVOLJENI:
        return True
    k = unicodedata.category(z)
    return k[0] == "L" or k == "Nd"


def varno_ime(vnos: object) -> Optional[str]:
    """Ime datoteke iz NZB ali glave yEnc: samo zadnji del poti, NFC, crke/stevke in nekaj locil (drugo '_'), najvec
    200 kodnih tock in 240 bajtov UTF-8 (koncnica do 9 znakov ostane), brez presledkov in pik na koncu, vodilna pika ->
    '_' (skrita datoteka), rezervirana imena Windows z '_'. None = ni imena."""
    s = str(vnos or "").replace("\\", "/").rsplit("/", 1)[-1]
    s = unicodedata.normalize("NFC", s)
    s = "".join(z if _dovoljen(z) else "_" for z in s)
    if len(s) > NAJVEC_IME_ZNAKOV:
        p = s.rfind(".")
        konc = s[p:] if p >= 0 and len(s) - p <= 10 else ""
        s = s[:NAJVEC_IME_ZNAKOV - len(konc)] + konc
    if len(s.encode("utf-8")) > NAJVEC_IME_BAJTOV:
        p = s.rfind(".")
        konc = s[p:] if p >= 0 and len(s) - p <= 10 else ""
        osnova = s[:len(s) - len(konc)]
        while osnova and len((osnova + konc).encode("utf-8")) > NAJVEC_IME_BAJTOV:
            osnova = osnova[:-1]
        s = osnova + konc
    s = s.rstrip(" .").lstrip(" ")
    if not s:
        return None
    if s.startswith("."):
        s = "_" + s[1:]
    if s.split(".", 1)[0].upper() in _REZERVIRANA:
        s = "_" + s
    return s


def id_clanka(vnos: object) -> Optional[str]:
    """message-id brez '<' '>': veljaven je samo 1-248 znakov ASCII 0x21-0x7E brez '<' in '>'. None = neveljaven."""
    s = str(vnos or "").strip()
    if len(s) >= 2 and s[0] == "<" and s[-1] == ">":
        s = s[1:-1]
    if not 1 <= len(s) <= NAJVEC_ID_ZNAKOV:
        return None
    if any(not ("\x21" <= z <= "\x7e") or z in "<>" for z in s):
        return None
    return s


_NAREKOVAJI = re.compile(r'"([^"]+)"')
_DEL = re.compile(r"\(([0-9]+)/([0-9]+)\)")


def ime_iz_subject(subject: object) -> Optional[str]:
    """Ime iz subject: prvi neprazen niz v narekovajih, sicer zadnja beseda s piko (brez »(1/9)« in »yEnc«)."""
    s = str(subject or "")
    m = _NAREKOVAJI.search(s)
    if m:
        return varno_ime(m.group(1))
    for beseda in reversed([b for b in _DEL.sub(" ", s).split() if b.lower() != "yenc"]):
        if "." in beseda:
            return varno_ime(beseda)
    return None


def _celota_iz_subject(subject: str) -> int:
    deli = _DEL.findall(subject)
    if deli and len(deli[-1][1]) <= 6:
        b = int(deli[-1][1])
        if 1 <= b <= NAJVEC_SEGMENTOV_DATOTEKE:
            return b
    return 0


# ------------------------------------------------------------------ razclenitev

_KODIRANJA = {"utf-8": "utf-8", "utf8": "utf-8", "us-ascii": "utf-8", "ascii": "utf-8",
              "iso-8859-1": "latin-1", "iso_8859-1": "latin-1", "latin1": "latin-1", "latin-1": "latin-1"}
_DEKLARACIJA = re.compile(r"\A\s*<\?xml\s[^>]*\?>")
_KODIRANJE = re.compile(r"""\sencoding\s*=\s*["']([^"']*)["']""")
_PREPOVEDANO = re.compile(r"<!\s*(ENTITY|ELEMENT|ATTLIST|NOTATION)", re.I)
_DOCTYPE = re.compile(r"<!DOCTYPE", re.I)
_LIT = r"""(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')"""
_DOVOLJEN_DOCTYPE = re.compile(r"<!DOCTYPE\s+nzb(?:\s+PUBLIC\s+" + _LIT + r"\s+" + _LIT + r"|\s+SYSTEM\s+" + _LIT
                               + r")?\s*>")
_STEVILKA = re.compile(r"[0-9]{1,6}\Z")
_SKUPINA = re.compile(r"[\x22-\x29\x2b\x2d-\x3e\x40-\x5a\x5e-\x7e]{1,200}\Z")  # RFC 3977 wildmat-exact (ASCII)
_ODPRTJE = re.compile(r"<![A-Za-z]")
_PRESLEDKI = frozenset(" \t\n\r\f\v")
_BAJTOV = re.compile(r"[0-9]{1,9}\Z")
_KOS = 64 * 1024


def _lokalno(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _besedilo(podatki: bytes) -> str:
    """Bajti -> besedilo brez deklaracije XML in brez dovoljenega DOCTYPE; napake kot NapakaNzb."""
    if len(podatki) > NAJVEC_NZB_BAJTOV:
        raise NapakaNzb(PREVELIK)
    if b"\x00" in podatki:
        raise NapakaNzb(NAPAKA_XML)
    if podatki.startswith(b"\xef\xbb\xbf"):
        podatki = podatki[3:]
    kodiranje = "utf-8"
    m = _DEKLARACIJA.match(podatki[:1024].decode("latin-1"))
    if m:
        k = _KODIRANJE.search(m.group(0))
        if k:
            kodiranje = _KODIRANJA.get(k.group(1).strip().lower())
            if kodiranje is None:
                raise NapakaNzb(NAPAKA_XML)
    besedilo = podatki.decode(kodiranje, "replace")
    besedilo = _DEKLARACIJA.sub("", besedilo, count=1)
    if _PREPOVEDANO.search(besedilo):
        raise NapakaNzb(ZAVRNJENO_DTD)
    dt = [x.start() for x in _DOCTYPE.finditer(besedilo)]
    if dt:
        m = _DOVOLJEN_DOCTYPE.match(besedilo, dt[0]) if len(dt) == 1 else None
        if not m:
            raise NapakaNzb(ZAVRNJENO_DTD)
        # Presledki enake dolzine, ne odstranitev: »<!DOC<!DOCTYPE nzb>TYPE ...« bi sestavil nov DOCTYPE.
        besedilo = besedilo[:m.start()] + " " * (m.end() - m.start()) + besedilo[m.end():]
        if _ODPRTJE.search(besedilo):
            raise NapakaNzb(ZAVRNJENO_DTD)
    return besedilo


def _naslov(besedilo: str) -> str:
    """ASCII presledki -> ' ', znaki Cc in Cf (npr. U+202E obrat smeri) proc, strnjeno, najvec 200 kodnih tock."""
    s = "".join(" " if z in _PRESLEDKI else ("" if unicodedata.category(z) in ("Cc", "Cf") else z) for z in besedilo)
    return " ".join(x for x in s.split(" ") if x)[:NAJVEC_NASLOV_ZNAKOV]


def _datoteka(el) -> Optional[Datoteka]:
    subject = str(el.get("subject") or "")
    skupine, segmenti = [], {}
    for otrok in el:
        ime = _lokalno(otrok.tag)
        if ime == "groups":
            for g in otrok:
                t = (g.text or "").strip() if _lokalno(g.tag) == "group" else ""
                if _SKUPINA.match(t) and len(t) <= NAJVEC_SKUPINA_ZNAKOV and len(skupine) < NAJVEC_SKUPIN:
                    skupine.append(t)
        elif ime == "segments":
            for s in otrok:
                if _lokalno(s.tag) != "segment":
                    continue
                st = str(s.get("number") or "")
                mid = id_clanka(s.text)
                if not _STEVILKA.match(st) or mid is None:
                    continue
                n = int(st)
                if not 1 <= n <= NAJVEC_SEGMENTOV_DATOTEKE or n in segmenti:
                    continue
                b = str(s.get("bytes") or "")
                segmenti[n] = Segment(n, int(b) if _BAJTOV.match(b) else 0, mid)
    if not segmenti:
        return None
    vrsta = tuple(segmenti[n] for n in sorted(segmenti))
    celota = max(_celota_iz_subject(subject), vrsta[-1].stevilka)
    return Datoteka(ime_iz_subject(subject), tuple(skupine), vrsta, celota - len(vrsta))


def razcleni(podatki: bytes) -> Nzb:
    """NZB (bajti) -> Nzb z datotekami v vrstnem redu dokumenta in segmenti po stevilki. Napaka: NapakaNzb(izid)."""
    besedilo = _besedilo(bytes(podatki))
    razclenjevalnik = ET.XMLPullParser(events=("start", "end"))
    koren = None
    globina = elementov = datotek = segmentov = 0
    naslov, geslo, datoteke = None, None, []

    def dogodki() -> None:
        nonlocal koren, globina, elementov, datotek, segmentov, naslov, geslo
        for dogodek, el in razclenjevalnik.read_events():
            if dogodek == "start":
                elementov += 1
                ime = _lokalno(el.tag)
                if globina == 0:
                    if ime != "nzb":
                        raise NapakaNzb(NI_NZB)
                    koren = el
                elif globina == 1 and ime == "file":
                    datotek += 1
                elif ime == "segment":
                    segmentov += 1
                if elementov > NAJVEC_ELEMENTOV or datotek > NAJVEC_DATOTEK or segmentov > NAJVEC_SEGMENTOV:
                    raise NapakaNzb(PREVELIK)
                globina += 1
                continue
            globina -= 1
            if globina != 1:
                continue
            ime = _lokalno(el.tag)
            if ime == "file":
                d = _datoteka(el)
                if d is not None:
                    datoteke.append(d)
            elif ime == "head":
                for meta in el:
                    vrsta = str(meta.get("type") or "").lower() if _lokalno(meta.tag) == "meta" else ""
                    t = _naslov(meta.text or "")
                    if vrsta == "title" and naslov is None and t:
                        naslov = t
                    elif vrsta == "password" and geslo is None and t:
                        geslo = (meta.text or "").strip()  # geslo arhiva ostane, kot je (brez strnjevanja)
            del koren[:]  # obdelano - ne drzimo celega drevesa v pomnilniku

    try:
        for od in range(0, len(besedilo), _KOS):
            razclenjevalnik.feed(besedilo[od:od + _KOS])
            dogodki()
        # Expat >= 2.6 odlozi delni zeton (reparse deferral): dogodki pridejo sele ob flush()/close() - brez branja
        # tu bi se zadnja <file> tiho izgubila (Grok 37 C5; prenosnik ima expat 2.6.1, Python 3.12.3).
        if hasattr(razclenjevalnik, "flush"):
            razclenjevalnik.flush()
            dogodki()
        razclenjevalnik.close()
        dogodki()
    except ET.ParseError:
        raise NapakaNzb(NAPAKA_XML) from None
    if koren is None:
        raise NapakaNzb(NAPAKA_XML)
    if not datoteke:
        raise NapakaNzb(PRAZEN)
    return Nzb(naslov, tuple(datoteke), geslo)
