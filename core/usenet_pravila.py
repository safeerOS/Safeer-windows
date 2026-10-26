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


#: Grokov pregled 31, H1 (26. 10. 2026, kot Android bed1134): kljuc, prilepljen v polje za naslov, ne sme postati
#: gostitelj https://<kljuc> - ime gostitelja gre pred povezavo necifrirano v DNS (tudi s pripono omrezja, <kljuc>.home).
#: Kljuci: Newznab 32 heks, TorBox UUID, Real-Debrid 52 znakov, AllDebrid ~20 znakov - nobeden nima pike.
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEKS_DOLG = re.compile(r"[0-9a-f]{24,}")
_ZNAKI_KLJUCA = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")

#: Izid vnosa indeksatorja (most ["usenet", ...]): v polju za naslov je kljuc - ni shranjen in ni poslan nikamor.
PREVERBA_NASLOV_JE_KLJUC = "naslov_kljuc"


def _oznaka_je_kljuc(oznaka: str) -> bool:
    """Del imena, ki je kljuc in ne ime: UUID ali vsaj 24 heks znakov."""
    o = oznaka.lower()
    return bool(_UUID.fullmatch(o) or _HEKS_DOLG.fullmatch(o))


def _je_ime_gostitelja(gost: str) -> bool:
    """Gostitelj indeksatorja je ime s piko brez oznake, ki je kljuc (javni CA za ime brez pike ne izda potrdila, zato
    tako ime tudi s https ne bi delalo), ali localhost oziroma naslov IP (IPv6 v oklepajih - urlsplit jih odstrani)."""
    g = (gost or "").lower().rstrip(".")
    if g == "localhost":
        return True
    try:
        ipaddress.ip_address(g)
        return True
    except ValueError:
        pass
    return "." in g and not any(not d or _oznaka_je_kljuc(d) for d in g.split("."))


def naslov_je_kljuc(vnos: object) -> bool:
    """Ali je v polju za naslov videti kljuc (sporocilo »prilepi ga v polje za kljuc«; Android naslovJeKljuc): gostitelj
    brez pike, dolg vsaj 16 znakov s stevko (32 heks, UUID, zeton), ali oznaka imena, ki je kljuc (_oznaka_je_kljuc)."""
    v = str(vnos or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    gost = v.split("://", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0].lower()
    if "." in gost:
        return any(_oznaka_je_kljuc(d) for d in gost.split("."))
    return bool(_UUID.fullmatch(gost)) or (len(gost) >= 16 and any(c.isdigit() for c in gost)
                                          and all(c in _ZNAKI_KLJUCA for c in gost))


def osnova(vnos: object) -> Optional[str]:
    """Naslov indeksatorja, kot ga uporabnik vpise (»https://api.indeksator.example/api?«): osnova brez `/api`, poizvedbe
    in koncne posevnice. Samo https - kljuc gre v naslovu; http samo do naprave v domacem omrezju (NZBHydra, Prowlarr).
    Brez uporabniskega imena v naslovu. None = ni veljaven.
    Lastnik 25. 10. 2026 (kot Android): uporabnik vpise kar ime (»nzbfinder.ws«) - gola domena brez sheme dobi https://
    sama (http:// na internet ostane zavrnjen). Grokov pregled 31, H1: gostitelj mora biti ime s piko brez oznake, ki je
    kljuc (_je_ime_gostitelja) - kljuc v polju za naslov in tipkarske napake (»http//x«, »https:/x«, »nzbfinder«) so
    zavrnjeni, preden gre karkoli v DNS. Velja tudi za shranjen naslov (Debrid.indeksator)."""
    v = str(vnos or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if v and "://" not in v:
        v = "https://" + v
    try:
        u = urllib.parse.urlsplit(v)
        u.port                                  # neveljavna vrata (»:abc«, nad 65535) -> ValueError
    except ValueError:
        return None
    if not u.hostname or "@" in u.netloc or any(c.isspace() for c in v) or not _je_ime_gostitelja(u.hostname):
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
    """Kljuc API indeksatorja: 8-128 znakov, crke, stevke, '-', '_' (Newznab: obicajno 32 heks). Vnos uporabnika gre
    skozi P.kljuc_iz_vnosa (ista oblika in se zavrnitev vzorca)."""
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


def naslov_preverbe(osn: str, kljuc: str) -> str:
    """Preverba kljuca ob vnosu: eno iskanje z enim zadetkom (`t=caps` kljuca ne preveri - Newznab ga ne zahteva).
    POZOR: vsebuje kljuc indeksatorja - samo za klic, nikoli v dnevnik."""
    return "%s/api?t=search&q=safeer&limit=1&apikey=%s" % (osn, urllib.parse.quote(kljuc, safe=""))


def preverba_indeksatorja(http: int, zacetek: str) -> str:
    """Odgovor naslov_preverbe -> P.PREVERBA_*: RSS brez napake je veljaven, napaka Newznab 100/102 neveljaven,
    500/501 (in 429) meja; vse drugo (5xx, stran HTML, ni odgovora) ni_odgovora - kljuca zaradi izpada ne zavrnemo.
    403 brez napake Newznab ni zavrnjen kljuc: izmerjeno 25. 10. 2026 na nzbfinder.ws s streznikov - Cloudflare vrne 403
    s stranjo »Just a moment« (skupni primeri kljuci-preverba.json). Enako 401 brez napake Newznab (pregled Grok 28 L2,
    skupni primeri v3): vrne ga lahko posrednik ali prijavna stran omrezja; nzbfinder.ws napacen kljuc vrne 401 Z napako
    100 (izmerjeno 25. 10. 2026), zato pravi zavrnjen kljuc ostane »neveljaven«."""
    n = napaka(zacetek)
    if n == P.NAPAKA_ZAKLENJEN:
        return P.PREVERBA_ZAKLENJEN
    if n == P.NAPAKA_KLJUC:
        return P.PREVERBA_NEVELJAVEN
    if n == P.NAPAKA_MEJA or http == 429:
        return P.PREVERBA_MEJA
    if 200 <= http < 300 and n is None and re.search(r"<(rss|channel)\b", zacetek or "", re.I):
        return P.PREVERBA_VELJAVEN
    return P.PREVERBA_NI_ODGOVORA


def napaka(xml: str) -> Optional[str]:
    """Napaka Newznab (`<error code=…>`) v nase vrste napak; None = ni napake."""
    m = re.search(r'<error\s+code="(\d+)"', xml or "")
    if not m:
        return None
    koda = int(m.group(1))
    if koda == 101:
        return P.NAPAKA_ZAKLENJEN               # »account suspended« (lastnik 26. 10. 2026: zaklep racuna)
    if koda in (100, 102):
        return P.NAPAKA_KLJUC
    if koda in (500, 501):
        return P.NAPAKA_MEJA
    return NAPAKA_INDEKSATOR


@dataclass(frozen=True)
class Zadetek:
    naslov: str
    povezava: str
    velikost: int


def _ni_javni(gost: str) -> bool:
    """Ime ali naslov IP, ki ni na internetu: ta racunalnik, domace omrezje, povezava (169.254 - tudi metapodatki
    oblaka), rezervirano, skupinsko. Ime, ki se razresi v tak naslov, tu ni zaznano (DNS se ne sprasuje)."""
    g = (gost or "").lower().rstrip(".")
    if g == "localhost" or g.endswith((".local", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(g)
    except ValueError:
        return False
    return not ip.is_global or ip.is_multicast


def _dovoljena_povezava(p: str, gost_indeksatorja: Optional[str]) -> bool:
    """Povezava NZB (zadetek ali skok preusmeritve): https; http samo do istega gostitelja v domacem omrezju. Grokov
    pregled 36, D5: indeksator z interneta ne sme dati povezave v domace omrezje ali na ta racunalnik (https://192.168.…,
    https://127.0.0.1:…) - racunalnik bi poslal slepo zahtevo GET v domace omrezje. Lokalni indeksator (NZBHydra) sme."""
    try:
        u = urllib.parse.urlsplit(p)
    except ValueError:
        return False
    gost = (u.hostname or "").lower().rstrip(".")
    if not gost or "@" in u.netloc:
        return False
    shema = (u.scheme or "").lower()
    if shema == "https":
        return not _ni_javni(gost) or _ni_javni(gost_indeksatorja or "")
    return shema == "http" and gost == (gost_indeksatorja or "").rstrip(".") and _je_lokalni_gostitelj(gost)


def _vrata(u: urllib.parse.SplitResult) -> Optional[int]:
    try:
        return u.port or {"http": 80, "https": 443}.get((u.scheme or "").lower())
    except ValueError:
        return None


def dovoljen_skok(od: str, do: str) -> bool:
    """Preusmeritev prenosa NZB (naslov nosi kljuc indeksatorja; AGENTS.md: prenosi preverijo VSAK skok): cilj mora biti
    dovoljena povezava NZB (_dovoljena_povezava) glede na gostitelja prejsnjega skoka, nikoli s https na http - Location
    lahko nosi kljuc, http ga pokaze vsem na poti."""
    try:
        a, b = urllib.parse.urlsplit(str(od or "")), urllib.parse.urlsplit(str(do or ""))
    except ValueError:
        return False
    if (a.scheme or "").lower() == "https" and (b.scheme or "").lower() != "https":
        return False
    if (b.scheme or "").lower() == "http" and (_vrata(a) is None or _vrata(a) != _vrata(b)):
        return False                            # http samo na ista vrata istega lokalnega gostitelja (Grok 36, D5)
    return _dovoljena_povezava(str(do or ""), (a.hostname or "").lower())


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
    return bool(samo_takoj) and vrsta_napake not in (P.NAPAKA_KLJUC, P.NAPAKA_PAKET, P.NAPAKA_MEJA, P.NAPAKA_ZAKLENJEN)


def za_samodejno(gb: Sequence[float]) -> list:
    """Indeksi zadetkov (po vrstnem redu kakovosti) za samodejno predvajanje: do NAJVEC_GB_SAMODEJNO (neznana velikost 0
    je dovoljena), najvec POSKUSOV_SAMODEJNO."""
    return [i for i, g in enumerate(gb) if g <= NAJVEC_GB_SAMODEJNO][:POSKUSOV_SAMODEJNO]


# ---------------------------------------------------------------------- vrstni red virov (lastnik, 25. 10. 2026 07:25)
#: Usenet je najboljsi vir (placan, kakovost in hitrost): ce je indeksator vpisan, gre prvi. Preverba »pri TorBoxu
#: pripravljen« tece hkrati s preverbo ⚡ in ima rok TAKOJ_ROK_S (z iskanjem pri indeksatorju), za prve TAKOJ_IZDAJ izdaj.
TAKOJ_IZDAJ = 3
TAKOJ_ROK_S = 6.0

KORAK_USENET_TAKOJ = "usenet_takoj"
KORAK_PREDPOMNJEN = "predpomnjen"
KORAK_NEPOSREDNI = "neposredni"
KORAK_USENET_CAKAJ = "usenet_cakaj"
KORAK_WEBTOR = "webtor"
KORAK_DEBRID_CAKAJ = "debrid_cakaj"


def vrstni_red_virov(usenet: bool, webtor: bool) -> list:
    """Samodejna izbira vira (skupno pravilo za Android, Linux in Windows; tests/skupni-primeri): (1) Usenet, ki ga ima
    TorBox pripravljenega, (2) ⚡ torrent pri debridu, (3) neposredna povezava, (4) Usenet s cakanjem na prenos, (5) Webtor,
    (6) debrid s cakanjem. [usenet] = indeksator in kljuc TorBox sta vpisana; [webtor] = rezerva Webtor je na voljo."""
    red = [KORAK_USENET_TAKOJ] if usenet else []
    red += [KORAK_PREDPOMNJEN, KORAK_NEPOSREDNI]
    if usenet:
        red.append(KORAK_USENET_CAKAJ)
    if webtor:
        red.append(KORAK_WEBTOR)
    red.append(KORAK_DEBRID_CAKAJ)
    return red


def za_takojsnjo(gb: Sequence[float]) -> list:
    """Indeksi izdaj (po vrstnem redu kakovosti - najboljsa predvajljiva prva) za preverbo »pri TorBoxu pripravljen«: prvih
    TAKOJ_IZDAJ do NAJVEC_GB_SAMODEJNO (neznana velikost 0 je dovoljena)."""
    return [i for i, g in enumerate(gb) if g <= NAJVEC_GB_SAMODEJNO][:TAKOJ_IZDAJ]


#: izberi_usenet: boljsa izdaja se ni odgovorila (cakaj) / nobena ni in ne bo pripravljena.
CAKAJ = -1
NOBENA = -2


def izberi_usenet(izidi: Sequence[Optional[bool]], rok_potekel: bool) -> int:
    """Skupno pravilo (Android WebtorPravila.izberiUsenet, tests/skupni-primeri/webtor-rezerva.json): preverbe
    »pri TorBoxu pripravljen« po kakovosti (najboljsa prva) - True pripravljena, False ne, None se brez odgovora.
    Pripravljena zmaga, ko so vse boljse odgovorile »ne«; dokler boljsa se ni odgovorila, CAKAJ. Po roku izdaje brez
    odgovora ne stejejo. NOBENA: nobena pripravljena."""
    for i, x in enumerate(izidi):
        if x is True:
            return i
        if x is None and not rok_potekel:
            return CAKAJ
    return NOBENA


def najboljsa_pripravljena(pripravljene: Sequence[bool]) -> int:
    """Med preverjenimi izdajami (po kakovosti) prva pripravljena; -1 = nobena."""
    return next((i for i, da in enumerate(pripravljene) if da), -1)


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
