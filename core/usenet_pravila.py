"""Usenet prek TorBoxa za namizje (Linux, Windows) - enako kot Safeer OS za Android (naloga 141, UsenetPravila.kt).

NZB najde uporabnikov indeksator (Newznab), prenese in pretaka ga TorBox (paket Pro). Tu so samo ciste odlocitve brez
omrezja (preizkus: tests/test_usenet.py); odjemalec je v core/debrid.py.

Iz dokumentacije (prebrano 24. 10. 2026, ne ugibano):
- Newznab: `t=movie&imdbid=0058935` (IMDb brez »tt«), `t=tvsearch&imdbid=…&season=…&ep=…`, `apikey` v naslovu; izid je RSS -
  `item` z `title`, `enclosure url` (naslov NZB s kljucem uporabnika) in `newznab:attr name="size"`; napaka je
  `<error code="…" description="…"/>`: 100 napacni podatki, 101 racun zaustavljen, 102 ni pravic, 500 meja zahtev, 501 meja
  prenosov, 900 neznano.
- TorBox: `usenet/createusenetdownload` (multipart: `file`, `name`, `add_only_if_cached`), `usenet/mylist?id=`,
  `usenet/requestdl?token&usenet_id&file_id`. TorBox Search ne obstaja vec, zato je potreben lasten indeksator.

Zasebnost: kljuc indeksatorja ostane na racunalniku - NZB prenese racunalnik sam in TorBoxu poslje samo datoteko. Povezave
NZB (s kljucem) niso v toku, zgodovini ne dnevniku; tok nosi samo id »usenet:<16 heks>«.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Sequence

from . import debrid_pravila as P

VRSTA = "usenet"
PREDPONA = "usenet:"

#: Indeksator ni vrnil NZB (napacen kljuc, meja, napaka) - za sporocilo uporabniku.
NAPAKA_INDEKSATOR = "indeksator"

NAJVEC_ZADETKOV = 40
NAJVEC_ODGOVORA_BAJTOV = 4 * 1024 * 1024
NAJVEC_NZB_BAJTOV = 20 * 1024 * 1024

#: Usenet prenos pri TorBoxu je hiter (streznik do streznika): izmerjeno na TV 24. 10. 2026 2,2 GB v 36 s.
CAKAJ_PRENOSA_S = 600.0

#: Samodejna izbira: najvec toliko GB (vecje izdaje ostanejo za rocno izbiro) in toliko poskusov.
NAJVEC_GB_SAMODEJNO = 15.0
POSKUSOV_SAMODEJNO = 2

OSNOVA_TORBOX = "https://api.torbox.app/v1/api/usenet"


def _je_lokalni_gostitelj(h: str) -> bool:
    g = (h or "").lower().strip("[]")
    if g == "localhost" or g.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(g)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def osnova(vnos: object) -> Optional[str]:
    """Naslov indeksatorja, kot ga uporabnik vpise (»https://api.indeksator.example/api?«): osnova brez `/api`, poizvedbe
    in koncne posevnice. Samo https - kljuc gre v naslovu; http samo do naprave v domacem omrezju (NZBHydra, Prowlarr).
    Brez uporabniskega imena v naslovu. None = ni veljaven."""
    v = str(vnos or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    try:
        u = urllib.parse.urlsplit(v)
    except ValueError:
        return None
    if not u.hostname or "@" in u.netloc or any(c.isspace() for c in v):
        return None
    shema = (u.scheme or "").lower()
    if shema != "https" and not (shema == "http" and _je_lokalni_gostitelj(u.hostname)):
        return None
    o = shema + v[len(u.scheme):]
    if o.endswith("/api"):
        o = o[:-4]
    return o.rstrip("/")


_KLJUC = re.compile(r"[A-Za-z0-9_-]{8,128}")


def ocisti_kljuc(vnos: object) -> Optional[str]:
    """Kljuc API indeksatorja: 8-128 znakov, crke, stevke, '-', '_' (Newznab: obicajno 32 heks)."""
    k = str(vnos or "").strip()
    return k if _KLJUC.fullmatch(k) else None


def _deli_id(ident: object) -> Optional[tuple]:
    d = str(ident or "").strip().split(":")
    imdb = d[0].lower()
    if not (3 <= len(imdb) <= 12 and imdb.startswith("tt") and imdb[2:].isdigit()):
        return None
    if len(d) == 1:
        return imdb[2:], None, None
    if len(d) == 3 and d[1].isdigit() and d[2].isdigit() and int(d[2]) >= 1:
        return imdb[2:], int(d[1]), int(d[2])
    return None


def iscemo(ident: object) -> bool:
    """Ali za id Stremio sploh iscemo (film `tt…` ali epizoda `tt…:S:E`). Drugi id-ji (tmdb:, kitsu:) ne."""
    return _deli_id(ident) is not None


def naslov_iskanja(osn: str, kljuc: str, ident: object) -> Optional[str]:
    """POZOR: vsebuje kljuc indeksatorja - samo za klic, nikoli v dnevnik."""
    d = _deli_id(ident)
    if d is None:
        return None
    imdb, sezona, epizoda = d
    skupno = "%s/api?apikey=%s&imdbid=%s&limit=100&extended=1" % (osn, urllib.parse.quote(kljuc, safe=""), imdb)
    return skupno + "&t=movie" if sezona is None else skupno + "&t=tvsearch&season=%d&ep=%d" % (sezona, epizoda)


def napaka(xml: str) -> Optional[str]:
    """Napaka Newznab (`<error code=…>`) v nase vrste napak; None = ni napake."""
    m = re.search(r'<error\s+code="(\d+)"', xml or "")
    if not m:
        return None
    koda = int(m.group(1))
    if koda in (100, 101, 102):
        return P.NAPAKA_KLJUC
    if koda in (500, 501):
        return P.NAPAKA_MEJA
    return NAPAKA_INDEKSATOR


@dataclass(frozen=True)
class Zadetek:
    naslov: str
    povezava: str
    velikost: int


def _dovoljena_povezava(p: str, gost_indeksatorja: Optional[str]) -> bool:
    try:
        u = urllib.parse.urlsplit(p)
    except ValueError:
        return False
    gost = (u.hostname or "").lower()
    if not gost or "@" in u.netloc:
        return False
    shema = (u.scheme or "").lower()
    if shema == "https":
        return True
    return shema == "http" and gost == gost_indeksatorja and _je_lokalni_gostitelj(gost)


def _lokalno(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def zadetki(xml: str, osn: str) -> list:
    """Zadetki iz odgovora RSS. DOCTYPE/ENTITY zavrnemo pred razclenitvijo (XXE, eksplozija entitet). Povezava NZB je
    `enclosure url`, sicer `link`; samo https ali http do istega gostitelja v domacem omrezju. Ponovljene povezave in
    izdaje (isti naslov in velikost) enkrat; najvec NAJVEC_ZADETKOV."""
    besedilo = str(xml or "")
    if len(besedilo) > NAJVEC_ODGOVORA_BAJTOV or re.search(r"<!(DOCTYPE|ENTITY)", besedilo, re.I):
        return []
    try:
        koren = ET.fromstring(besedilo)
    except (ET.ParseError, ValueError):
        return []
    gost_ix = (urllib.parse.urlsplit(osn).hostname or "").lower() if osn else None
    izid, videne = [], set()
    for el in koren.iter():
        if _lokalno(el.tag) != "item":
            continue
        naslov, povezava, velikost, dolzina = "", "", 0, 0
        for o in el:
            ime = _lokalno(o.tag)
            if ime == "title":
                naslov = " ".join((o.text or "").split())[:200]
            elif ime == "enclosure":
                povezava = (o.get("url") or "").strip() or povezava
                try:
                    dolzina = int(o.get("length") or 0)
                except ValueError:
                    dolzina = 0
            elif ime == "link" and not povezava:
                povezava = (o.text or "").strip()
            elif ime == "attr" and o.get("name") == "size":
                try:
                    velikost = int(o.get("value") or 0)
                except ValueError:
                    velikost = 0
        if not naslov or not _dovoljena_povezava(povezava, gost_ix) or povezava in videne:
            continue
        videne.add(povezava)
        velikost = max(0, velikost if velikost > 0 else dolzina)
        kljuc_izdaje = "%s|%d" % (naslov, velikost)
        if kljuc_izdaje in videne:
            continue
        videne.add(kljuc_izdaje)
        izid.append(Zadetek(naslov, povezava, velikost))
        if len(izid) >= NAJVEC_ZADETKOV:
            break
    return izid


def id_toka(povezava: str) -> str:
    """»usenet:« + prvih 16 heks SHA-1 povezave - povezava (s kljucem) ostane samo v pomnilniku."""
    return PREDPONA + hashlib.sha1(povezava.encode("utf-8")).hexdigest()[:16]


def je_usenet(url: object) -> bool:
    return str(url or "").startswith(PREDPONA)


def opis(z: Zadetek) -> str:
    """Opis toka v obliki dodatkov (»… 💾 12.7 GB«), da ga tok_izbira razbere (locljivost, kodek, velikost)."""
    return z.naslov if z.velikost <= 0 else "%s\n💾 %.1f GB" % (z.naslov, z.velikost / 1073741824.0)


def je_nzb(zacetek: object) -> bool:
    """Ali je odgovor res NZB (XML z elementom `nzb`) - indeksator lahko namesto datoteke vrne napako ali stran HTML."""
    z = str(zacetek or "").lower()
    return "<nzb" in z and "<!entity" not in z and "<!doctype html" not in z


def ni_predpomnjeno(samo_takoj: bool, vrsta_napake: str) -> bool:
    """createusenetdownload z add_only_if_cached, ko prenosa ni v predpomnilniku: kljuc, paket in meja ostanejo svoje
    napake; vse drugo pri »samo takoj« pomeni »ni pripravljeno«."""
    return bool(samo_takoj) and vrsta_napake not in (P.NAPAKA_KLJUC, P.NAPAKA_PAKET, P.NAPAKA_MEJA)


def za_samodejno(gb: Sequence[float]) -> list:
    """Indeksi zadetkov (po vrstnem redu kakovosti) za samodejno predvajanje: do NAJVEC_GB_SAMODEJNO (neznana velikost 0
    je dovoljena), najvec POSKUSOV_SAMODEJNO."""
    return [i for i, g in enumerate(gb) if g <= NAJVEC_GB_SAMODEJNO][:POSKUSOV_SAMODEJNO]


def naslov_seznam(uid: int) -> str:
    return "%s/mylist?id=%d&bypass_cache=true" % (OSNOVA_TORBOX, uid)


def naslov_prenosa(kljuc: str, uid: int, datoteka_id: int) -> str:
    """POZOR: vsebuje kljuc TorBox (token) - samo za klic, nikoli v dnevnik, predvajalnik ali zgodovino."""
    return OSNOVA_TORBOX + "/requestdl?" + urllib.parse.urlencode({"token": kljuc, "usenet_id": uid, "file_id": datoteka_id})


def vecdelni_obrazec(polja: Sequence[tuple], datoteka: tuple, meja: str) -> bytes:
    """multipart/form-data: [polja] (ime, vrednost), [datoteka] (ime polja, ime datoteke, bajti)."""
    if not re.fullmatch(r"[A-Za-z0-9'()+_,./:=?-]{1,70}", meja):
        raise ValueError("meja")
    deli = []
    for ime, vrednost in polja:
        # Vrednost (npr. ime izdaje) ne sme prekiniti obrazca: brez novih vrstic in brez meje.
        vrednost = " ".join(str(vrednost).replace("--" + meja, " ").split())
        deli.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (meja, ime, vrednost)).encode("utf-8"))
    polje, ime_dat, vsebina = datoteka
    deli.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                 "Content-Type: application/x-nzb\r\n\r\n" % (meja, polje, ime_dat)).encode("utf-8"))
    deli.append(bytes(vsebina))
    deli.append(("\r\n--%s--\r\n" % meja).encode("utf-8"))
    return b"".join(deli)
