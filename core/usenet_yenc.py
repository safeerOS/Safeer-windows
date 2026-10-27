"""yEnc za lasten pogon Usenet (lastnik 25. 10. 2026 22:10): dekodiranje clanka s preverbo CRC32 - brez omrezja.

Pravila so skupna z Android-tv (Kotlin): tests/skupni-primeri/usenet-pogon.json (yenc_dekodiraj, yenc_iz_nntp).
yEnc 1.3 (yenc.org): bajt b je zapisan kot (b + 42) & 255; NUL, LF, CR in '=' (kodirniki tudi TAB, presledek in piko na
robu vrstice) so ubezani kot '=' + (o + 64) & 255. Glava '=ybegin [part= total=] line= size= name=<do konca vrstice>',
pri vecdelnem '=ypart begin= end=' (od 1, vkljucno), konec '=yend size= [part= pcrc32=] [crc32=]'.

Hitrost: zanka po bajtih v Pythonu je prepocasna, zato CR/LF izpusti bytes.translate, '=' razdeli bytes.split,
popravek ubeznih znakov je ena operacija na ubezni znak (~1,6 % bajtov), odmik -42 pa spet translate - vse razen
popravka tece v C.
Izmerjeno 25. 10. 2026 22:51 na prenosniku (i5-1135G7, obremenitev 2,1; tools/meri_yenc.py: 50 MiB nakljucnih
podatkov v delih po 750 KiB, s CRC32, 3 ponovitve): 129,6 / 142,6 / 140,7 MB/s na eni niti (cilj 50 MB/s; tok 4K pri
80 Mbit/s je 10 MB/s). Kodo GPL (sabyenc, sabctools) namenoma ne uporabljamo.

kodiraj() je za preizkuse in meritev (lazni streznik NNTP) - Safeer clankov ne objavlja.
"""

from __future__ import annotations

import itertools
import re
import zlib
from dataclasses import dataclass, field
from typing import Optional

from .usenet_nzb import varno_ime

#: Najvecji del (dekodiran) - enako kot usenet_nntp.NAJVEC_TELO_BAJTOV (clanki 384-719 KiB, merjeno 25. 10. 2026).
NAJVEC_DEL_BAJTOV = 4 * 1024 * 1024

OK = "ok"
NI_YENC = "ni_yenc"
NAPAKA_OBLIKE = "napaka_oblike"
PRIREZANO = "prirezano"
NAPAKA_VELIKOSTI = "napaka_velikosti"
NAPAKA_CRC = "napaka_crc"
PREVELIK = "prevelik"

_ODMIK = bytes((c - 42) & 255 for c in range(256))
_KODIRAJ = bytes((c + 42) & 255 for c in range(256))
_UBEZNI = [bytes(((c - 64) & 255,)) for c in range(256)]  # nato se -42: skupaj (c - 106) & 255
_CEL = re.compile(rb"[0-9]{1,12}\Z")
_DEL = re.compile(rb"[0-9]{1,9}\Z")  # part, total (skupni primeri v3)
_HEX = re.compile(rb"[0-9A-Fa-f]{1,8}\Z")
_UBEZI = {c: bytes((61, (c + 64) & 255)) for c in range(256)}


class NapakaYenc(ValueError):
    """Clanek ni uporaben; izid je ena od konstant zgoraj (brez vsebine clanka v sporocilu)."""

    def __init__(self, izid: str):
        super().__init__("yenc: " + izid)
        self.izid = izid


@dataclass(frozen=True)
class DelYenc:
    ime: Optional[str]
    del_: Optional[int]
    skupaj: Optional[int]
    velikost: int  # velikost cele datoteke iz =ybegin
    zacetek: int  # od 1 (yEnc); odmik v datoteki je zacetek - 1
    crc32: int
    crc_preverjen: bool
    podatki: bytes = field(repr=False)

    @property
    def konec(self) -> int:
        return self.zacetek + len(self.podatki) - 1

    @property
    def odmik(self) -> int:
        return self.zacetek - 1


def _vrstica(telo: bytes, od: int) -> tuple:
    """(konec vsebine vrstice brez CR, zacetek naslednje vrstice)."""
    lf = telo.find(b"\n", od)
    if lf < 0:
        return len(telo), len(telo)
    return (lf - 1 if lf > od and telo[lf - 1] == 13 else lf), lf + 1


def _polja(vrstica: bytes, z_imenom: bool = False) -> tuple:
    ime = None
    if z_imenom:
        k = vrstica.find(b" name=")
        if k >= 0:
            vrstica, ime = vrstica[:k], vrstica[k + 6:]
    polja: dict = {}
    for zeton in vrstica.split()[1:]:
        kljuc, enak, vrednost = zeton.partition(b"=")
        if enak:
            polja.setdefault(kljuc.lower(), vrednost)
    return polja, ime


def _cel(polja: dict, kljuc: bytes, obvezno: bool) -> Optional[int]:
    v = polja.get(kljuc)
    if v is None:
        if obvezno:
            raise NapakaYenc(NAPAKA_OBLIKE)
        return None
    if not (_DEL if kljuc in (b"part", b"total") else _CEL).match(v):
        raise NapakaYenc(NAPAKA_OBLIKE)
    n = int(v)
    if kljuc in (b"part", b"total") and n < 1:
        raise NapakaYenc(NAPAKA_OBLIKE)
    return n


def _crc(polja: dict, kljuc: bytes) -> Optional[int]:
    v = polja.get(kljuc)
    if v is None:
        return None
    if not _HEX.match(v):
        raise NapakaYenc(NAPAKA_OBLIKE)
    return int(v, 16)


def _vrstica_z(telo: bytes, oznaka: bytes, od: int) -> int:
    """Zacetek prve vrstice od [od], ki se zacne z [oznaka] in ji sledi presledek, CR, LF ali konec; -1 = je ni."""
    i = od
    while True:
        if telo.startswith(oznaka, i):
            j = i
        else:
            j = telo.find(b"\n" + oznaka, i)
            if j < 0:
                return -1
            j += 1
        za = j + len(oznaka)
        if za >= len(telo) or telo[za] in b" \r\n":
            return j
        i = j + 1


def _odpakiraj(blok: bytes) -> bytes:
    """Podatki brez CR/LF -> dekodirani bajti. Ubeznik velja za naslednji znak (tudi '=' -> 211); osamljen na koncu
    odpade."""
    if b"=" not in blok:
        return blok.translate(_ODMIK)
    if b"==" not in blok:
        if blok.endswith(b"="):
            blok = blok[:-1]
        kosi = blok.split(b"=")
        izid = bytearray(b"".join(kosi))
        for p in itertools.accumulate(map(len, kosi[:-1])):
            izid[p] = (izid[p] - 64) & 255
        return bytes(izid).translate(_ODMIK)
    # Splosna pot (pokvarjen kodirnik, »==«): po kosih, pocasneje, a redko.
    kosi = blok.split(b"=")
    izid_kosi = [kosi[0]]
    i, n = 1, len(kosi)
    while i < n:
        k = kosi[i]
        if k:
            izid_kosi.append(_UBEZNI[k[0]])
            izid_kosi.append(k[1:])
            i += 1
        elif i + 1 < n:  # »==«: drugi '=' je ubezni znak, kos za njim je navaden
            izid_kosi.append(_UBEZNI[61])
            izid_kosi.append(kosi[i + 1])
            i += 2
        else:  # osamljen ubeznik na koncu
            i += 1
    return b"".join(izid_kosi).translate(_ODMIK)


def dekodiraj(telo: bytes) -> DelYenc:
    """Telo clanka (po NNTP, brez podvojenih pik) -> DelYenc. Napaka: NapakaYenc(izid) - nikoli delno dekodiranih
    bajtov."""
    telo = bytes(telo)
    i = _vrstica_z(telo, b"=ybegin", 0)
    if i < 0 or not telo.startswith(b"=ybegin ", i):
        raise NapakaYenc(NI_YENC)
    konec, nasl = _vrstica(telo, i)
    polja, ime_b = _polja(telo[i:konec], True)
    velikost = _cel(polja, b"size", True)
    del_ = _cel(polja, b"part", False)
    skupaj = _cel(polja, b"total", False)
    if del_ is not None and skupaj is not None and del_ > skupaj:
        raise NapakaYenc(NAPAKA_OBLIKE)
    if del_ is not None:
        if not telo.startswith(b"=ypart ", nasl):
            raise NapakaYenc(NAPAKA_OBLIKE)
        konec, nasl2 = _vrstica(telo, nasl)
        pp, _ = _polja(telo[nasl:konec])
        zacetek, zadnji = _cel(pp, b"begin", True), _cel(pp, b"end", True)
        if not 1 <= zacetek <= zadnji <= velikost:
            raise NapakaYenc(NAPAKA_OBLIKE)
        pricakovano, nasl = zadnji - zacetek + 1, nasl2
    else:
        zacetek, pricakovano = 1, velikost
    if pricakovano > NAJVEC_DEL_BAJTOV:
        raise NapakaYenc(PREVELIK)
    k = _vrstica_z(telo, b"=yend", nasl)
    if k < 0:
        raise NapakaYenc(PRIREZANO)
    konec, _ = _vrstica(telo, k)
    yp, _ = _polja(telo[k:konec])
    yvelikost = _cel(yp, b"size", True)
    ydel = _cel(yp, b"part", False)
    pcrc, crc = _crc(yp, b"pcrc32"), _crc(yp, b"crc32")
    if ydel is not None and del_ is not None and ydel != del_:
        raise NapakaYenc(NAPAKA_OBLIKE)
    blok = telo[nasl:k].translate(None, b"\r\n")
    if len(blok) > 2 * pricakovano + 1:  # vsak bajt je najvec 2 znaka - dekodirano bi bilo predolgo
        raise NapakaYenc(NAPAKA_VELIKOSTI)
    podatki = _odpakiraj(blok)
    if len(podatki) != pricakovano or len(podatki) != yvelikost:
        raise NapakaYenc(NAPAKA_VELIKOSTI)
    izracunan = zlib.crc32(podatki)
    preveri = pcrc if pcrc is not None else (crc if del_ is None else None)
    if preveri is not None and preveri != izracunan:
        raise NapakaYenc(NAPAKA_CRC)
    if ime_b is not None:
        try:
            ime_s = ime_b.decode("utf-8")
        except UnicodeDecodeError:
            ime_s = ime_b.decode("latin-1")
    else:
        ime_s = None
    return DelYenc(varno_ime(ime_s), del_, skupaj, velikost, zacetek, izracunan, preveri is not None, podatki)


def kodiraj(podatki: bytes, ime: str, velikost: Optional[int] = None, del_: Optional[int] = None,
            skupaj: Optional[int] = None, zacetek: int = 1, dolzina: int = 128) -> bytes:
    """Clanek yEnc (CRLF) kot yencode/Nyuu - za preizkuse in meritev. Pri del_ je [zacetek] odmik dela od 1."""
    o = re.sub(rb"[\x00\n\r=]", lambda m: _UBEZI[m.group()[0]], bytes(podatki).translate(_KODIRAJ))
    vrstice, i, n = [], 0, len(o)
    while i < n:
        j = min(i + dolzina, n)
        if o[j - 1] == 61 and j < n:  # ubezni par ostane v isti vrstici
            j += 1
        v = o[i:j]
        if v[0] in (9, 32, 46):
            v = _UBEZI[v[0]] + v[1:]
        if len(v) > 1 and v[-1] in (9, 32) and v[-2] != 61 or len(v) == 1 and v[0] in (9, 32):
            v = v[:-1] + _UBEZI[v[-1]]
        vrstice.append(v)
        i = j
    vel = len(podatki) if velikost is None else velikost
    glava = b"=ybegin " + (b"part=%d " % del_ if del_ else b"") + (b"total=%d " % skupaj if skupaj else b"")
    glava += b"line=%d size=%d name=%s" % (dolzina, vel, ime.encode("utf-8"))
    deli = [glava]
    if del_:
        deli.append(b"=ypart begin=%d end=%d" % (zacetek, zacetek + len(podatki) - 1))
    deli += vrstice
    crc = zlib.crc32(podatki)
    deli.append(b"=yend size=%d part=%d pcrc32=%08x" % (len(podatki), del_, crc) if del_ else
                b"=yend size=%d crc32=%08x" % (len(podatki), crc))
    return b"\r\n".join(deli) + b"\r\n"
