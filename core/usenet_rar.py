"""RAR samo v nacinu »store« za lasten pogon Usenet, korak 2 (lastnik 26. 10. 2026).

Izdaje na Usenetu so pogosto v RAR (vec zvezkov .rar/.r00/.part01.rar). Shranjen RAR (metoda store, RAR4 0x30, RAR5
metoda 0) ima film v zvezkih nespremenjen - pretakamo ga z odmikom; stisnjenega (RAR4 m1-m5, RAR5 metoda 1-5),
sifriranega ali s sifriranimi glavami NE moremo predvajati. Prototip 25. 10. 2026: 2 od 4 izdaj BBB sta bili stisnjeni,
dodatek je predvajal nadomestni video - zato preveri() odloci iz prvih bajtov PRED ponudbo.

Napisano po objavljeni specifikaciji oblike (RARLAB technote.txt za RAR 2.9-4 in »RAR 5.0 archive format«), brez kode
UnRAR, junrar ali GPL. Preverjeno 26. 10. 2026 proti pravim arhivom WinRAR 7 (RAR5: store, -m3, -p, -hp, vec zvezkov);
WinRAR 7 RAR4 ne ustvarja vec, zato RAR4 preizkusi sestavijo glave po specifikaciji.

Skupni primeri z Android-tv: tests/skupni-primeri/usenet-pogon.json v5 (rar_glava, rar_zvezki, rar_sestavi).
Varnost: glave pridejo od neznanega objavitelja - meje (stevilo blokov, velikost glave, vint), odmik vsakega naslednjega
bloka mora rasti, ime gre skozi usenet_nzb.varno_ime, CRC glav se preveri.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from typing import Callable, List, Optional, Union

from .usenet_nzb import varno_ime

OK = "ok"
NI_RAR = "ni_rar"
STISNJEN = "stisnjen"
SIFRIRAN = "sifriran"
SIFRIRANE_GLAVE = "sifrirane_glave"
POSKODOVAN = "poskodovan"  # CRC glave, nemogoca velikost, preseg meje
NEPOPOLNO = "nepopolno"  # glava sega cez prebrane bajte (preveri: odloci sele z vec bajti)
NESKLADNO = "neskladno"  # zvezki se ne sestavijo (manjka zvezek, napacen vrstni red, druga datoteka)
NI_DATOTEKE = "ni_datoteke"  # arhiv nima datoteke (samo mape ali prazen)

PODPIS4 = b"Rar!\x1a\x07\x00"
PODPIS5 = b"Rar!\x1a\x07\x01\x00"
NAJVEC_BLOKOV = 10_000
NAJVEC_GLAVA5 = 2 * 1024 * 1024  # RAR5: glava najvec 2 MiB (specifikacija)
NAJVEC_IME = 4096
NAJVEC_VINT = (1 << 63) - 1
NAJVEC_ZVEZKOV = 1_000_000

_BeriT = Callable[[int, int], bytes]


class NapakaRar(ValueError):
    """Izid brez imen datotek v sporocilu."""

    def __init__(self, izid: str):
        super().__init__("usenet rar: " + izid)
        self.izid = izid


@dataclass(frozen=True)
class Vnos:
    ime: Optional[str]
    odmik: int  # zacetek podatkov v zvezku
    dolzina: int  # podatkov v tem zvezku
    velikost: int  # cela (nestisnjena) datoteka; RAR5 brez znane velikosti: -1
    razdeljen_pred: bool  # se nadaljuje iz prejsnjega zvezka
    razdeljen_po: bool  # se nadaljuje v naslednjem zvezku
    mapa: bool
    store: bool
    sifriran: bool


@dataclass(frozen=True)
class Zvezek:
    razlicica: int  # 4 ali 5
    vnosi: tuple
    stevilka: Optional[int]  # RAR5: stevilka zvezka (prvi 0); RAR4: None
    vec_zvezkov: bool  # arhiv je del vec zvezkov
    nepopolno: bool  # glave po zadnjem vnosu niso bile v prebranih bajtih


@dataclass(frozen=True)
class Kos:
    zvezek: int  # indeks v seznamu zvezkov
    odmik: int  # odmik v zvezku
    dolzina: int


def _bralnik(vir: Union[bytes, _BeriT]) -> _BeriT:
    if callable(vir):
        return vir
    podatki = bytes(vir)
    return lambda o, n: podatki[o:o + n]


def _vint(b: bytes, i: int) -> tuple:
    """RAR5 vint: 7 bitov na bajt, najvec 10 bajtov. (vrednost, nov indeks)."""
    v, premik = 0, 0
    for k in range(10):
        if i + k >= len(b):
            raise NapakaRar(NEPOPOLNO)
        c = b[i + k]
        v |= (c & 0x7F) << premik
        if not c & 0x80:
            # Vrednost nad 2^63 - 1 je nesmisel (Kotlin Long bi bil negativen - pregled Grok 61 W1): enako na obeh straneh.
            if v > NAJVEC_VINT:
                raise NapakaRar(POSKODOVAN)
            return v, i + k + 1
        premik += 7
    raise NapakaRar(POSKODOVAN)


def _ime(b: bytes, unicode4: bool = False) -> Optional[str]:
    if unicode4 and b"\x00" in b:
        b = b.split(b"\x00", 1)[0]  # RAR4: ASCII del pred stisnjenim Unicode
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        s = b.decode("latin-1")
    return varno_ime(s)


# ------------------------------------------------------------------ RAR4

def _rar4(beri: _BeriT, velikost: int) -> Zvezek:
    i, vnosi, vec, prvi_blok = len(PODPIS4), [], False, True
    for _ in range(NAJVEC_BLOKOV):
        if i >= velikost:
            return Zvezek(4, tuple(vnosi), None, vec, False)
        g = beri(i, 7)
        if len(g) < 7:
            return Zvezek(4, tuple(vnosi), None, vec, True)
        crc, vrsta, zast, vel = struct.unpack("<HBHH", g)
        if vel < 7:
            raise NapakaRar(POSKODOVAN)
        glava = beri(i, vel)
        if len(glava) < vel:
            return Zvezek(4, tuple(vnosi), None, vec, True)
        if zlib.crc32(glava[2:]) & 0xFFFF != crc:
            raise NapakaRar(POSKODOVAN)
        dodatno = 0
        if zast & 0x8000 or vrsta == 0x74:
            if vel < 11:
                raise NapakaRar(POSKODOVAN)
            dodatno = struct.unpack_from("<I", glava, 7)[0]
        if vrsta == 0x73:
            if zast & 0x0080:
                raise NapakaRar(SIFRIRANE_GLAVE)
            vec = bool(zast & 0x0001)
        elif prvi_blok:
            raise NapakaRar(POSKODOVAN)  # za podpisom mora biti glavna glava
        elif vrsta == 0x74:
            if vel < 32:
                raise NapakaRar(POSKODOVAN)
            paket, nestisnjeno, _os, _crc, _cas, _ver, metoda, n_ime, _atr = struct.unpack_from("<IIBIIBBHI", glava, 7)
            o = 32
            if zast & 0x0100:
                if vel < 40:
                    raise NapakaRar(POSKODOVAN)
                vp, vn = struct.unpack_from("<II", glava, 32)
                if vp & 0x80000000 or vn & 0x80000000:
                    raise NapakaRar(POSKODOVAN)  # nad 2^63 (Kotlin: negativna dolzina - Grok 61 W1)
                paket, nestisnjeno, o = paket | vp << 32, nestisnjeno | vn << 32, 40
                dodatno = paket
            if paket > velikost - (i + vel):
                raise NapakaRar(POSKODOVAN)  # podatki datoteke ne morejo segati cez zvezek
            if n_ime > NAJVEC_IME or o + n_ime > vel:
                raise NapakaRar(POSKODOVAN)
            vnosi.append(Vnos(_ime(glava[o:o + n_ime], bool(zast & 0x0200)), i + vel, paket, nestisnjeno,
                              bool(zast & 0x01), bool(zast & 0x02), zast & 0xE0 == 0xE0, metoda == 0x30,
                              bool(zast & 0x04)))
        elif vrsta == 0x7B:
            return Zvezek(4, tuple(vnosi), None, vec, False)
        prvi_blok = False
        nasl = i + vel + dodatno
        if nasl <= i:
            raise NapakaRar(POSKODOVAN)
        i = nasl
    raise NapakaRar(POSKODOVAN)


# ------------------------------------------------------------------ RAR5

def _rar5(beri: _BeriT, velikost: int) -> Zvezek:
    i, vnosi, vec, stevilka, prvi_blok = len(PODPIS5), [], False, None, True
    for _ in range(NAJVEC_BLOKOV):
        if i >= velikost:
            return Zvezek(5, tuple(vnosi), stevilka, vec, False)
        g = beri(i, 4 + 3)
        if len(g) < 5:
            return Zvezek(5, tuple(vnosi), stevilka, vec, True)
        # Glava do 2 MiB ima velikost v najvec 3 bajtih vint; daljsa je poskodovana (ne »nepopolna«).
        if len(g) == 7 and all(c & 0x80 for c in g[4:7]):
            raise NapakaRar(POSKODOVAN)
        try:
            vel, z = _vint(g, 4)
        except NapakaRar as e:
            if e.izid == NEPOPOLNO:
                return Zvezek(5, tuple(vnosi), stevilka, vec, True)
            raise
        if vel < 2 or vel > NAJVEC_GLAVA5:
            raise NapakaRar(POSKODOVAN)
        cela = beri(i, z + vel)
        if len(cela) < z + vel:
            return Zvezek(5, tuple(vnosi), stevilka, vec, True)
        if zlib.crc32(cela[4:]) != struct.unpack_from("<I", cela, 0)[0]:
            raise NapakaRar(POSKODOVAN)
        h = cela[z:]
        try:
            vrsta, k = _vint(h, 0)
            zast, k = _vint(h, k)
            dod = pod = 0
            if zast & 0x0001:
                dod, k = _vint(h, k)
            if zast & 0x0002:
                pod, k = _vint(h, k)
        except NapakaRar:
            raise NapakaRar(POSKODOVAN) from None
        if dod > len(h) - k or pod > velikost - (i + z + vel):
            raise NapakaRar(POSKODOVAN)  # dodatni del v glavi, podatki v zvezku (Grok 61 W1)
        if vrsta == 4:
            raise NapakaRar(SIFRIRANE_GLAVE)
        if prvi_blok and vrsta != 1:
            raise NapakaRar(POSKODOVAN)
        try:
            if vrsta == 1:
                af, k = _vint(h, k)
                vec = bool(af & 0x1)
                if af & 0x2:
                    stevilka, k = _vint(h, k)
                    if stevilka > NAJVEC_ZVEZKOV:
                        raise NapakaRar(POSKODOVAN)
                elif vec:
                    stevilka = 0
            elif vrsta == 2:
                ff, k = _vint(h, k)
                nest, k = _vint(h, k)
                _atr, k = _vint(h, k)
                k += (4 if ff & 0x2 else 0) + (4 if ff & 0x4 else 0)
                ci, k = _vint(h, k)
                _os, k = _vint(h, k)
                n_ime, k = _vint(h, k)
                if n_ime > NAJVEC_IME or k + n_ime > len(h) - dod:
                    raise NapakaRar(POSKODOVAN)
                ime = _ime(h[k:k + n_ime])
                sifriran = _ima_zapis(h[len(h) - dod:], 0x01) if dod else False
                vnosi.append(Vnos(ime, i + z + vel, pod, -1 if ff & 0x8 else nest, bool(zast & 0x0008),
                                  bool(zast & 0x0010), bool(ff & 0x1), (ci >> 7) & 0x7 == 0, sifriran))
            elif vrsta == 5:
                return Zvezek(5, tuple(vnosi), stevilka, vec, False)
        except NapakaRar as e:
            raise NapakaRar(POSKODOVAN if e.izid == NEPOPOLNO else e.izid) from None
        prvi_blok = False
        nasl = i + z + vel + pod
        if nasl <= i:
            raise NapakaRar(POSKODOVAN)
        i = nasl
    raise NapakaRar(POSKODOVAN)


def _ima_zapis(dodatno: bytes, vrsta: int) -> bool:
    """Ali dodatni del glave RAR5 vsebuje zapis [vrsta] (0x01 = sifriranje datoteke)."""
    i = 0
    while i < len(dodatno):
        vel, j = _vint(dodatno, i)
        if vel < 1 or j + vel > len(dodatno):
            raise NapakaRar(POSKODOVAN)
        t, _ = _vint(dodatno, j)
        if t == vrsta:
            return True
        i = j + vel
    return False


# ------------------------------------------------------------------ javno

def razcleni_zvezek(vir: Union[bytes, _BeriT], velikost: Optional[int] = None) -> Zvezek:
    """Glave enega zvezka. [vir] = bajti zacetka zvezka ali beri(odmik, n); [velikost] = velikost zvezka.
    Napaka: NapakaRar(NI_RAR / SIFRIRANE_GLAVE / POSKODOVAN)."""
    beri = _bralnik(vir)
    if velikost is None:
        if callable(vir):
            raise ValueError("velikost zvezka je obvezna pri bralniku")
        velikost = len(vir)
    zacetek = beri(0, 8)
    if zacetek.startswith(PODPIS5):
        return _rar5(beri, velikost)
    if zacetek.startswith(PODPIS4):
        return _rar4(beri, velikost)
    raise NapakaRar(NI_RAR)


def glavni_vnos(z: Zvezek) -> Optional[Vnos]:
    """Najvecja datoteka (ne mapa) - film; vzorci in .nfo so manjsi."""
    datoteke = [v for v in z.vnosi if not v.mapa]
    return max(datoteke, key=lambda v: (v.velikost, v.dolzina)) if datoteke else None


def preveri(prvi_bajti: bytes, velikost: Optional[int] = None) -> str:
    """Odlocitev PRED ponudbo iz prvih bajtov prvega zvezka (prvi segment): ok, stisnjen, sifriran, sifrirane_glave,
    ni_rar, poskodovan, nepopolno, ni_datoteke. Skupni primeri rar_glava.
    Pregled Grok 58 T2: ce glave segajo cez prebrane bajte, odloci samo datoteka, ki je ocitno film - razdeljena cez
    zvezke ali vsaj pol zvezka [velikost]; sicer (npr. store vzorec pred filmom) NEPOPOLNO in klicatelj prebere naprej
    glave (z mejo) - prej je manjsi store vzorec dal OK in stisnjen film za njim ni bil nikoli preverjen."""
    try:
        z = razcleni_zvezek(prvi_bajti, velikost if velikost is not None else 1 << 62)
    except NapakaRar as e:
        return e.izid
    return odloci(z, velikost)


def odloci(z: Zvezek, velikost: Optional[int] = None) -> str:
    """Odlocitev iz razclenjenih glav (preveri; pri celem seznamu glav tudi bralnik po branju naprej)."""
    v = glavni_vnos(z)
    if v is None:
        return NEPOPOLNO if z.nepopolno else NI_DATOTEKE
    if z.nepopolno and not (v.razdeljen_po or (velikost is not None and v.velikost * 2 >= velikost)):
        return NEPOPOLNO
    if v.sifriran:
        return SIFRIRAN
    if not v.store:
        return STISNJEN
    return OK


_DEL = re.compile(r"\A(.*)\.part0*(\d{1,4})\.rar\Z", re.I)
_RAR = re.compile(r"\A(.*)\.rar\Z", re.I)
_RNN = re.compile(r"\A(.*)\.([r-z])(\d{2})\Z", re.I)


def vrstni_red_zvezkov(imena: List[str]) -> Optional[List[int]]:
    """Indeksi imen zvezkov v pravem vrstnem redu (skupni primeri rar_zvezki): .part1.rar, .part2.rar ... ali .rar,
    .r00 ... .r99, .s00 ... Vsi morajo imeti isto osnovo in shemo, brez lukenj in dvojnikov; sicer None."""
    deli, star = [], []
    for i, ime in enumerate(imena):
        m = _DEL.match(ime or "")
        if m:
            deli.append((m.group(1).lower(), int(m.group(2)), i))
            continue
        m = _RNN.match(ime or "")
        if m:
            star.append((m.group(1).lower(), 1 + (ord(m.group(2).lower()) - ord("r")) * 100 + int(m.group(3)), i))
            continue
        m = _RAR.match(ime or "")
        if m:
            star.append((m.group(1).lower(), 0, i))
            continue
        return None
    if deli and star or not (deli or star):
        return None
    vrsta = sorted(deli or star, key=lambda x: x[1])
    if len({x[0] for x in vrsta}) != 1:
        return None
    zacetek = 1 if deli else 0
    if [x[1] for x in vrsta] != list(range(zacetek, zacetek + len(vrsta))):
        return None
    return [x[2] for x in vrsta]


def sestavi(zvezki: List[Zvezek]) -> tuple:
    """(ime, velikost, [Kos]) glavne datoteke iz zvezkov v vrstnem redu (skupni primeri rar_sestavi). Prvi zvezek
    odloci, katera datoteka; vsak naslednji mora nadaljevati isto datoteko. Napaka: NapakaRar(STISNJEN, SIFRIRAN,
    NESKLADNO, NI_DATOTEKE)."""
    if not zvezki:
        raise NapakaRar(NI_DATOTEKE)
    v = glavni_vnos(zvezki[0])
    if v is None:
        raise NapakaRar(NI_DATOTEKE)
    if v.sifriran:
        raise NapakaRar(SIFRIRAN)
    if not v.store:
        raise NapakaRar(STISNJEN)
    if v.razdeljen_pred:
        raise NapakaRar(NESKLADNO)  # prvi zvezek ni prvi
    kosi, skupaj, trenutni = [Kos(0, v.odmik, v.dolzina)], v.dolzina, v
    for n, z in enumerate(zvezki[1:], 1):
        if not trenutni.razdeljen_po:
            break  # datoteka je koncana; naslednji zvezki nosijo druge datoteke
        if z.razlicica != zvezki[0].razlicica:
            raise NapakaRar(NESKLADNO)
        if z.stevilka is not None and zvezki[0].stevilka is not None and z.stevilka != zvezki[0].stevilka + n:
            raise NapakaRar(NESKLADNO)
        nasl = next((x for x in z.vnosi if x.razdeljen_pred and not x.mapa), None)
        if nasl is None or nasl.ime != v.ime or (v.velikost >= 0 and nasl.velikost != v.velikost):
            raise NapakaRar(NESKLADNO)
        if nasl.sifriran:
            raise NapakaRar(SIFRIRAN)
        if not nasl.store:
            raise NapakaRar(STISNJEN)
        kosi.append(Kos(n, nasl.odmik, nasl.dolzina))
        skupaj += nasl.dolzina
        trenutni = nasl
    if trenutni.razdeljen_po or (v.velikost >= 0 and skupaj != v.velikost):
        raise NapakaRar(NESKLADNO)  # manjka zvezek ali store s podatki, ki niso cela datoteka
    return v.ime, skupaj, kosi
