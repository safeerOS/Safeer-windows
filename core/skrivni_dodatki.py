"""Dodatki Stremio s poverilnico v naslovu (skupna koda Linux in Windows, brez GTK in brez omrezja).

Osebni dodatek Webtor (»https://webtor.io/token/<zeton>/stremio«, kratka povezava »/s/<koda>«), Torrentio z debrid
kljucem v nastavitvah (»/realdebrid=<kljuc>|sort=...«), nastavitve JSON ali base64 s kljucem (»tmdbApiKey«) ali
uporabnik in geslo v naslovu: tak naslov je geslo racuna. Do 25. 10. 2026 je bil na namizju shranjen v cistopisu
(media.json) in je z usklajevanjem virov (lists.get) sel VSEM napravam v Safeer Linku. Zdaj (kot Safeer OS za Android,
SkrivnostiPravila.kt in SkrivniDodatki.kt na veji webtor-rezerva):
  - pravi naslov je samo sifriran (sistemska zbirka skrivnosti / DPAPI, isti sifrirnik kot gesla streznikov);
  - povsod drugje (media.json, katalog, police, seznami, dnevnik, Link) velja NADOMESTEK brez skrivnosti
    »https://<gostitelj>/safeer-skrito-<odtis>/...«; pravi naslov vstavi `dejanski()` tik pred omreznim klicem
    (core/media_servers._request) in ga nikamor ne zapise;
  - drugim napravam ga z navadnim usklajevanjem virov ne posljemo (core/viri_sink.cist_vir); ozjega kroga za kljuce
    namizje se nima (secrets.sync) - do takrat ostane samo na tej napravi.
Odtis je prvih 16 znakov SHA-256 skrivne predpone, enak kot na Androidu (skupni primeri
tests/skupni-primeri/webtor-rezerva.json) - isti dodatek ima na vseh napravah isti nadomestek.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional

OZNAKA = "safeer-skrito-"
_RX_NADOMESTEK = re.compile(r"^(https?://[^/?#@\s]+/" + OZNAKA + r"[0-9a-f]{16})(?=$|[/?#])")

#: Debrid in podobne storitve: ime polja z njihovim kljucem ali odsek poti pred kljucem (»/realdebrid/<kljuc>/«).
STORITVE = frozenset({"realdebrid", "real-debrid", "alldebrid", "torbox", "premiumize", "debridlink", "debrid-link",
                      "offcloud", "putio", "easydebrid", "stremthru"})
#: Besede v imenu polja (po delih imena: »tmdbApiKey« = tmdb, api, key).
BESEDE = frozenset({"key", "apikey", "token", "secret", "password", "passwd", "pass", "auth", "cookie", "session",
                    "credential", "credentials", "jwt", "bearer", "sig", "signature", "authorization"})
#: Konec imena polja, ki je kljuc (»rpdbkey«, »mdblistapikey«, »accesstoken«).
KONCNICE = ("key", "token", "secret", "password")
#: Odsek za temi je skrivnost (»/token/<zeton>/«, »/key/<kljuc>/«, »/realdebrid/<kljuc>/«).
PREDHODNIKI = frozenset({"token", "key", "apikey", "api_key", "api-key", "auth", "secret"}) | STORITVE
NAJMANJ_DOLG = 20
_PRAZNE_VREDNOSTI = frozenset({"null", "none", "false", "true", "0", "undefined"})

_RX_POLJE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]{0,63})\"?\s*[=:]\s*\"?([^\"|&;,}\]\s]*)")
_RX_UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_RX_HEX = re.compile(r"^[0-9a-fA-F]+$")
_RX_ZETON = re.compile(r"^[A-Za-z0-9_\-+/=.~]+$")
_RX_DELI = re.compile(r"([a-z0-9])([A-Z])")


def _deli_imena(ime: str) -> list:
    """»tmdbApiKey« -> tmdb, api, key; »rpdb_key« -> rpdb, key."""
    return [d.lower() for d in re.split(r"[ _-]", _RX_DELI.sub(r"\1 \2", ime)) if d]


def je_kljucno_ime(ime: str) -> bool:
    """Ime polja pove, da je vrednost skrivnost."""
    m = ime.lower()
    if m in STORITVE:
        return True
    deli = _deli_imena(ime)
    if any(d in BESEDE or d in STORITVE for d in deli):
        return True
    return any(m.endswith(k) for k in KONCNICE) or any(d.endswith(k) for d in deli for k in KONCNICE)


def ima_kljucno_polje(besedilo: str) -> bool:
    """Besedilo (nastavitve dodatka, poizvedba) ima polje s kljucnim imenom in neprazno vrednostjo."""
    for m in _RX_POLJE.finditer(besedilo):
        v = m.group(2).strip()
        if je_kljucno_ime(m.group(1)) and v and v.lower() not in _PRAZNE_VREDNOSTI:
            return True
    return False


def base64_besedilo(s: str) -> Optional[str]:
    """Base64 (navaden ali za naslove, z dopolnilom ali brez), ki se razbere v berljivo besedilo (nastavitve) - to
    besedilo; sicer None (nakljucni zeton, binarno). Enako kot java.util.Base64 na Androidu."""
    t = s.strip().rstrip("=")
    if len(t) < 8 or not all(c.isalnum() or c in "+/-_" for c in t):
        return None
    try:
        if "-" in t or "_" in t:
            if "+" in t or "/" in t:
                return None
            t = t.replace("-", "+").replace("_", "/")
        bajti = base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
        b = bajti.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not b:
        return None
    berljivih = sum(1 for c in b if c in "\n\t" or (c >= " " and c not in ("\x7f", "\ufffd")))
    return b if berljivih * 10 >= len(b) * 9 and any(c.isalpha() for c in b) else None


def je_neprozoren_zeton(s: str) -> bool:
    """Dolg nerazberljiv zeton (kljuc, zeton, sifrirane nastavitve). Ni zeton: UUID, hash (32/40/64 hex), niz brez crk
    ali brez stevk, base64 z berljivim besedilom - tam odloca kljucno polje v njem."""
    if len(s) < NAJMANJ_DOLG or not _RX_ZETON.match(s):
        return False
    if _RX_UUID.match(s):
        return False
    if _RX_HEX.match(s) and len(s) in (32, 40, 64):
        return False
    if not any(c.isdigit() for c in s) or not any(c.isalpha() for c in s):
        return False
    besedilo = base64_besedilo(s)
    return ima_kljucno_polje(besedilo) if besedilo is not None else True


def je_skriven_odsek(odsek: str, prejsnji: str = "", webtor: bool = False) -> bool:
    """Odsek poti (brez »/«) je skrivnost. `prejsnji` = odsek pred njim, `webtor` = gostitelj webtor.io (»/s/<koda>«)."""
    if not odsek or odsek.startswith(OZNAKA):
        return False
    if prejsnji.lower() in PREDHODNIKI:
        return True
    if webtor and prejsnji == "s":
        return True
    d = odkodiraj(odsek)
    if ima_kljucno_polje(d):
        return True
    return je_neprozoren_zeton(d)


def je_webtor_gostitelj(gostitelj: str) -> bool:
    g = gostitelj.lower().split(":", 1)[0].rstrip(".")
    return g == "webtor.io" or g.endswith(".webtor.io")


class _Deli:
    __slots__ = ("shema", "z_uporabnikom", "gostitelj", "zacetek_poti", "pot", "konec_poti", "poizvedba", "konec_poizvedbe")

    def __init__(self, *vrednosti) -> None:
        for ime, v in zip(self.__slots__, vrednosti):
            setattr(self, ime, v)


def _razcleni(naslov: str) -> Optional[_Deli]:
    i = naslov.find("://")
    if i <= 0:
        return None
    shema = naslov[:i].lower()
    if shema not in ("http", "https"):
        return None
    zacetek = i + 3
    konec_avt = next((j for j in range(zacetek, len(naslov)) if naslov[j] in "/?#"), len(naslov))
    avtoriteta = naslov[zacetek:konec_avt]
    afna = avtoriteta.rfind("@")
    gostitelj = (avtoriteta[afna + 1:] if afna >= 0 else avtoriteta).lower()
    if not gostitelj or any(c <= " " for c in gostitelj):
        return None
    konec_poti = next((j for j in range(konec_avt, len(naslov)) if naslov[j] in "?#"), len(naslov))
    konec_poizvedbe = konec_poti
    if konec_poti < len(naslov) and naslov[konec_poti] == "?":
        h = naslov.find("#", konec_poti)
        konec_poizvedbe = len(naslov) if h < 0 else h
    poizvedba = naslov[konec_poti + 1:konec_poizvedbe] if konec_poizvedbe > konec_poti else ""
    return _Deli(shema, afna >= 0, gostitelj, konec_avt, naslov[konec_avt:konec_poti], konec_poti, poizvedba,
                 konec_poizvedbe)


def _skrivni_konci(d: _Deli) -> list:
    """Konci skrivnih odsekov poti (indeks v naslovu za odsekom)."""
    webtor = je_webtor_gostitelj(d.gostitelj)
    izid, prejsnji, konec = [], "", d.zacetek_poti
    for k, o in enumerate(d.pot.split("/")):
        if k == 0:
            continue
        if webtor and o == "resolve":
            # Webtor: »/resolve/<JWT>« ni zeton (JWT nosi samo exp, hash, idx - izmerjeno 25. 10. 2026); skrivnost je
            # pred njim. Sicer nadomestek kratke povezave `/s/<koda>` izgubi /resolve/ in tok ni prepoznan kot Webtor.
            break
        konec += 1 + len(o)
        if je_skriven_odsek(o, prejsnji, webtor):
            izid.append(konec)
        if o:
            prejsnji = o
    return izid


def _pot_nastavitev(pot: str) -> str:
    """Pot brez »/manifest.json« in brez koncnih »/«: nastavitve dodatka."""
    p = pot.rstrip("/")
    if p.lower().endswith("/manifest.json"):
        p = p[:-len("/manifest.json")]
    return p.rstrip("/")


def skrivna_predpona_dodatka(naslov: str) -> Optional[str]:
    """Dodatek (naslov manifesta ali osnova): ce kjerkoli nosi skrivnost, je skrivna CELA osnova - vse pred
    »/manifest.json« (brez poizvedbe). None = ni skrivnosti ali je ze nadomestek."""
    n = str(naslov or "").strip()
    if _RX_NADOMESTEK.match(n):
        return None
    d = _razcleni(n)
    if d is None:
        return None
    osnova = n[:d.zacetek_poti] + _pot_nastavitev(d.pot)
    if d.z_uporabnikom:
        return osnova
    if d.poizvedba and ima_kljucno_polje(odkodiraj(d.poizvedba)):
        return osnova
    # Nastavitve v base64 (lahko razsekane z »/«): odloca samo kljucno polje v razbranem besedilu.
    cele = odkodiraj(_pot_nastavitev(d.pot).strip("/"))
    besedilo = base64_besedilo(cele) if len(cele) >= 8 else None
    if besedilo is not None:
        return osnova if ima_kljucno_polje(besedilo) else None
    return osnova if _skrivni_konci(d) else None


def skrivna_predpona_toka(naslov: str) -> Optional[str]:
    """Tok: del do vkljucno ZADNJEGA skrivnega odseka poti; zeton v poizvedbi: cel naslov brez fragmenta;
    uporabnik/geslo: vsaj »shema://u:g@gostitelj«. None = brez skrivnosti ali ze nadomestek."""
    n = str(naslov or "").strip()
    if _RX_NADOMESTEK.match(n):
        return None
    d = _razcleni(n)
    if d is None:
        return None
    if d.poizvedba and ima_kljucno_polje(odkodiraj(d.poizvedba)):
        return n[:d.konec_poizvedbe]
    konci = _skrivni_konci(d)
    if konci:
        return n[:konci[-1]]
    return n[:d.zacetek_poti] if d.z_uporabnikom else None


def je_skriven_naslov(naslov: str) -> bool:
    return skrivna_predpona_dodatka(naslov) is not None or skrivna_predpona_toka(naslov) is not None


def odtis(s: str) -> str:
    """Prvih 16 znakov SHA-256 (hex): enak na vseh napravah, iz njega se zetona ne da izracunati."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def nadomestek(predpona: str) -> Optional[str]:
    """Nadomestna osnova za skrivno predpono: »https://webtor.io/safeer-skrito-<odtis>« (brez uporabnika in zetona)."""
    d = _razcleni(predpona)
    return None if d is None else "%s://%s/%s%s" % (d.shema, d.gostitelj, OZNAKA, odtis(predpona))


def v_nadomestek(naslov: str) -> str:
    """Naslov dodatka -> isti naslov z nadomestkom cele osnove (»/manifest.json« ostane); brez skrivnosti nespremenjen."""
    n = str(naslov or "").strip()
    p = skrivna_predpona_dodatka(n)
    z = nadomestek(p) if p else None
    if not p or not z:
        return n
    return z + n[len(p):].split("?", 1)[0].split("#", 1)[0]


def nadomestna_osnova(naslov: str) -> Optional[str]:
    m = _RX_NADOMESTEK.match(str(naslov or "").strip())
    return m.group(1) if m else None


def je_nadomestek(naslov: str) -> bool:
    return nadomestna_osnova(naslov) is not None


def sme_med_vse_naprave(naslov: str) -> bool:
    """Vir sme z navadnim usklajevanjem virov na vse naprave v Linku: ne nosi skrivnosti in ni nadomestek."""
    return skrivna_predpona_dodatka(naslov) is None and not je_nadomestek(naslov)


def odstrani_tok_ob_shranjevanju(osnova_kartice: str, tok: str) -> bool:
    """Tok kartice dodatka s poverilnico se ob shranjevanju izbrise samo, ce ima se pravo skrivnost."""
    return ((je_nadomestek(osnova_kartice) or skrivna_predpona_dodatka(osnova_kartice) is not None)
            and bool(str(tok or "").strip()) and not je_nadomestek(tok) and skrivna_predpona_toka(tok) is not None)


def za_prikaz(naslov: str) -> str:
    """Za zaslon in dnevnik: »https://webtor.io/…/manifest.json« - skrivnost ali nadomestek zakrit z »…«."""
    n = str(naslov or "").strip()
    osnova = nadomestna_osnova(n) or skrivna_predpona_dodatka(n) or skrivna_predpona_toka(n)
    if not osnova:
        return n
    d = _razcleni(osnova)
    if d is None:
        return "…"
    return "%s://%s/…" % (d.shema, d.gostitelj) + n[min(len(osnova), len(n)):].split("?", 1)[0].split("#", 1)[0]


def veljaven_skrivni_dodatek(n: str) -> bool:
    """Pregled Grok U5 (25. 10. 2026): naslov, ki nosi skrivnost, samo po https - po http bi zeton sel v cistopisu."""
    n = str(n or "")
    return 12 <= len(n) <= 2048 and n.startswith("https://") and not any(c < " " for c in n) \
        and skrivna_predpona_dodatka(n) is not None


def odkodiraj(s: str) -> str:
    """Odstotkovno kodiranje (%XX, UTF-8) brez »+« -> presledek; neveljavno ostane, kot je."""
    if "%" not in s:
        return s
    izid, bajti, i = [], bytearray(), 0
    hexa = "0123456789abcdefABCDEF"
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s) and s[i + 1] in hexa and s[i + 2] in hexa:
            bajti.append(int(s[i + 1:i + 3], 16))
            i += 3
        else:
            if bajti:
                izid.append(bajti.decode("utf-8", "replace"))
                bajti = bytearray()
            izid.append(s[i])
            i += 1
    if bajti:
        izid.append(bajti.decode("utf-8", "replace"))
    return "".join(izid)


def zamenjaj(besedilo: str, zamenjave: dict) -> str:
    """Prave skrivne predpone -> nadomestki (daljse najprej; JSON lahko pise »/« tudi kot »\\/«)."""
    for k in sorted(zamenjave, key=len, reverse=True):
        if k:
            v = zamenjave[k]
            besedilo = besedilo.replace(k, v).replace(k.replace("/", "\\/"), v.replace("/", "\\/"))
    return besedilo


def vsebuje_katero(besedilo: str, pravi) -> bool:
    return any(p and (p in besedilo or p.replace("/", "\\/") in besedilo) for p in pravi)


# ------------------------------------------------------------------ odklenjeni dodatki (samo v pomnilniku procesa)

class NeodklenjenDodatek(ValueError):
    """Naslov je nadomestek, pravega v tem procesu ni (zbirka skrivnosti zaklenjena): zahteve ne posljemo."""


_ZAKLEP = threading.Lock()
#: nadomestna osnova -> prava skrivna predpona (samo v pomnilniku; nikoli v datoteko ali dnevnik).
_PRAVI: dict = {}
#: Isto za tokove dodatka s kljucem, ki se ne zacnejo s predpono dodatka (Torrentio z debrid kljucem:
#: `/resolve/realdebrid/<kljuc>/...`, pregled Grok N2) - samo zadnjih NAJVEC_TOKOV, v pomnilniku.
_PRAVI_TOKOV: "OrderedDict[str, str]" = OrderedDict()
NAJVEC_TOKOV = 500
#: Nadomestek toka -> skrivne vrednosti dodatka, ki jih tok nosi v obliki, ki je skrivna_predpona_toka ne prepozna
#: (Grok 19, M2) - nosi_skrivnost jih isce tudi v koncnem naslovu. Samo v pomnilniku, skupaj z _PRAVI_TOKOV.
_VREDNOSTI_TOKOV: dict = {}
#: Klic, ki za nadomestno osnovo vrne pravi naslov dodatka (MediaCenter ga odklene iz zbirke skrivnosti) ali None.
_odklepalnik: Optional[Callable[[str], Optional[str]]] = None
#: nadomestna osnova -> cas neuspelega odklepa: zaklenjena zbirka ne odpre okna za geslo ob vsaki zahtevi (Grok N16).
_NEUSPEH: dict = {}
NEUSPEH_VELJA_S = 60.0


def nastavi_odklepalnik(fn: Optional[Callable[[str], Optional[str]]]) -> None:
    global _odklepalnik
    _odklepalnik = fn


def odkleni(pravi_naslov: str) -> str:
    """Pravi naslov dodatka zapomni (v pomnilniku) in vrne njegov nadomestek; brez skrivnosti vrne naslov."""
    p = skrivna_predpona_dodatka(pravi_naslov)
    z = nadomestek(p) if p else None
    if not p or not z:
        return str(pravi_naslov or "").strip()
    with _ZAKLEP:
        _PRAVI[z] = p
    return v_nadomestek(pravi_naslov)


def pozabi_vse() -> None:
    """Vse odklenjene naslove pozabi (preizkusi, odjava)."""
    with _ZAKLEP:
        _PRAVI.clear()
        _PRAVI_TOKOV.clear()
        _VREDNOSTI_TOKOV.clear()
        _NEUSPEH.clear()


def pozabi(nadomestni_naslov: str) -> None:
    o = nadomestna_osnova(nadomestni_naslov)
    if o:
        with _ZAKLEP:
            _PRAVI.pop(o, None)
            _NEUSPEH.pop(o, None)


def dejanski(naslov: str) -> str:
    """Nadomestek -> pravi naslov tik pred omreznim klicem (rezultata ne shranjuj in ne zapisuj). Naslov brez
    nadomestka ostane enak. Neodklenjen nadomestek: NeodklenjenDodatek (zahteva ne gre na streznik)."""
    n = str(naslov or "")
    o = nadomestna_osnova(n)
    if not o:
        return n
    with _ZAKLEP:
        p = _PRAVI.get(o) or _PRAVI_TOKOV.get(o)
        nedavno = time.monotonic() - _NEUSPEH.get(o, -1e9) < NEUSPEH_VELJA_S
    if p is None and _odklepalnik is not None and not nedavno:
        try:
            pravi = _odklepalnik(o)
        except Exception:  # noqa: BLE001 - zaklenjena zbirka: kot da dodatka ni
            pravi = None
        if pravi and nadomestek(skrivna_predpona_dodatka(pravi) or "") == o:
            odkleni(pravi)
        with _ZAKLEP:
            p = _PRAVI.get(o)
            if p is None:
                _NEUSPEH[o] = time.monotonic()
    if p is None:
        raise NeodklenjenDodatek("Dodatek z osebnim žetonom ni odklenjen.")
    return p + n.strip()[len(o):]


def _pari() -> list:
    with _ZAKLEP:
        pari = list(_PRAVI.items()) + list(_PRAVI_TOKOV.items())
    return sorted(pari, key=lambda kv: len(kv[1]), reverse=True)


def skrij(naslov: str) -> str:
    """Pravi naslov (npr. tok, ki ga je vrnil dodatek) -> z nadomestkom, ce se zacne s pravo predpono znanega dodatka."""
    n = str(naslov or "")
    for z, p in _pari():
        if n.startswith(p) and (len(n) == len(p) or n[len(p)] in "/?#"):
            return z + n[len(p):]
    return n


def skrij_tok(naslov: str, skrivnosti: tuple = ()) -> str:
    """Tok dodatka z osebnim kljucem: predpona dodatka -> nadomestek (skrij); ce tok nosi kljuc v drugi obliki
    (Torrentio: `/resolve/realdebrid/<kljuc>/...`, kljuc v poizvedbi), dobi nadomestek tudi ta predpona toka
    (pregled Grok N2). `skrivnosti` (skrivne_vrednosti dodatka): tok, ki nosi kljuc dodatka v obliki, ki je
    skrivna_predpona_toka ne prepozna (kratek kljuc za »/play/«, kljuc iz nastavitev base64), dobi nadomestek CEL
    (Grok 19, M2 - prej je sel s kljucem v predpomnilnik, sondo in predvajalnik). Pravi naslov samo v pomnilniku."""
    n = skrij(naslov)
    if je_nadomestek(n):
        return n
    p = skrivna_predpona_toka(n)
    ostanek = n[len(p):] if p else n            # kar bi ostalo vidno za nadomestkom
    if any(o and (o in ostanek or odkodiraj(o) in odkodiraj(ostanek)) for o in skrivnosti):
        p = n.split("#", 1)[0]
    z = nadomestek(p) if p else None
    if not p or not z:
        return n
    with _ZAKLEP:
        _PRAVI_TOKOV[z] = p
        _PRAVI_TOKOV.move_to_end(z)
        if skrivnosti:
            _VREDNOSTI_TOKOV[z] = tuple(o for o in skrivnosti if o)
        while len(_PRAVI_TOKOV) > NAJVEC_TOKOV:
            _VREDNOSTI_TOKOV.pop(_PRAVI_TOKOV.popitem(last=False)[0], None)
    return z + n[len(p):]


def skrivne_vrednosti(naslov: str) -> tuple:
    """Skrivnosti dodatka za iskanje v drugem naslovu (Grok 19, M2): skrivni odseki poti in vrednosti kljucnih polj v
    njih (»realdebrid=<kljuc>|sort=...«, nastavitve base64 s »torboxKey«). Vrednosti krajse od 6 znakov ne iscemo."""
    izid = list(_skrivni_odseki(naslov))
    for o in list(izid):
        d = odkodiraj(o)
        for besedilo in (d, base64_besedilo(d) or ""):
            for m in _RX_POLJE.finditer(besedilo):
                v = m.group(2).strip()
                if je_kljucno_ime(m.group(1)) and len(v) >= 6 and v.lower() not in _PRAZNE_VREDNOSTI:
                    izid.append(v)
    return tuple(dict.fromkeys(izid))


def _skrivni_odseki(naslov: str) -> list:
    """Odseki poti (in uporabnik:geslo), ki so skrivnost - za iskanje zetona v drugem naslovu."""
    d = _razcleni(naslov)
    if d is None:
        return []
    webtor = je_webtor_gostitelj(d.gostitelj)
    izid, prejsnji = [], ""
    for k, o in enumerate(d.pot.split("/")):
        if webtor and o == "resolve":
            break       # kot _skrivni_konci: JWT toka Webtor ni zeton (koncni naslov z JWT se sme predvajati)
        if k and je_skriven_odsek(o, prejsnji, webtor):
            izid.append(o)
        if k and o:
            prejsnji = o
    if d.z_uporabnikom:
        izid.append(naslov[naslov.find("://") + 3:d.zacetek_poti].rpartition("@")[0])
    return [o for o in izid if len(o) >= 4]


def nosi_skrivnost(naslov: str, izvor: str) -> bool:
    """Ali `naslov` (npr. koncni po preusmeritvi toka) nosi zeton dodatka, iz katerega je `izvor` (tok dodatka):
    zacne se s pravo predpono dodatka ali vsebuje njen skrivni odsek. Webtor: predpona je vse pred »/resolve/«."""
    n, izvor = str(naslov or ""), str(izvor or "")
    pari = [(z, p) for z, p in _pari() if izvor.startswith(p)]
    pravi = [p for _z, p in pari]
    predpona = max(pravi, key=len) if pravi else izvor.split("/resolve/", 1)[0] if "/resolve/" in izvor \
        else (skrivna_predpona_toka(izvor) or "")
    if not predpona:
        return False
    if n.startswith(predpona):
        return True
    with _ZAKLEP:
        dodatne = [v for z, _p in pari for v in _VREDNOSTI_TOKOV.get(z, ())]
    return any(o in n or odkodiraj(o) in odkodiraj(n) for o in list(skrivne_vrednosti(predpona)) + dodatne)


def zakrij(besedilo: object) -> str:
    """Besedilo za dnevnik ali sporocilo: prave predpone znanih dodatkov -> nadomestki, druge skrivnosti v naslovih
    (`/token/...`, kljuc v poizvedbi) zakrite z »…«."""
    s = str(besedilo or "")
    s = zamenjaj(s, {p: z for z, p in _pari()})
    return re.sub(r"https?://[^\s\"'<>]+", lambda m: za_prikaz(m.group(0)), s)
