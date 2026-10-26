"""Kanali iz seznamov IPTV (M3U): razclenitev #EXTINF, razvrstitev in preverba, ali kanal res oddaja.

Skupno za Linux in Windows (klice ga core/os_media.py); brez GTK in brez Windows posebnosti.

Lastnik, 25. 10. 2026: v Serijah je bilo polno kanalov TV v zivo (Exodus TV, H2, Kanal A, Star Crime ...), klik je
pokazal »Sezone niso na voljo«. Izmerjen vzrok: _parse_m3u je vrstico #EXTINF razrezal pri PRVI vejici, atribut
http-user-agent pa vejico vsebuje (»(KHTML, like Gecko)«) - naslov je postal ostanek glave (»like Gecko) Chrome/...
group-title="Documentary",H2 HD«), group-title in tvg-logo za vejico sta se izgubila, os_media._kind pa je iz podniza
»tv« v naslovu ali v naslovu toka naredil serijo. Na lastnikovih seznamih (iptv-org si + eng) je bilo tako 664 serij,
473 filmov in le 324 kanalov TV v zivo.

Pravila (lastnik, 25. 10. 2026):
- kanal iz seznama IPTV je samo TV v zivo; serija samo, kar ima sezono in epizodo; film samo datoteka (VOD);
- »[Not 24/7]« se izloci povsod (ne prikaz, ne preverba);
- kanal se pokaze samo, ce preverba vrne veljaven tok (HLS z razlicico in kosom ali magicni bajti TS/MP4/MKV);
  zaklenjen (401/403/451) se v TV v zivo ne pokaze, v Virih pa pise, koliko jih je;
- javni seznami (iptv-org) privzeto samo kanali drzave uporabnika in kanali v anglescini.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------------------------------------- razclenitev #EXTINF

#: Razlicica razclenitve seznamov M3U v media.json; vir s starejso se v ozadju prebere znova (os_media).
RAZCLENITEV = 2

# Vsak vzorec zacne samo na zacetku niza crk oziroma presledkov (lookbehind): brez tega je bil cas kvadraten v dolzini
# vrstice - izmerjeno 26. 10. 2026 (pregled 30, J4): vrstica z 20 KB crk 5,7 s, s 1 MB bi bile ure ob vsakem zagonu.
_ATRIBUT = re.compile(r'(?<![A-Za-z0-9_-])([A-Za-z0-9_-]+)="([^"]*)"')
_NE_24_7 = re.compile(r"\[\s*not\s*24\s*/\s*7\s*\]", re.IGNORECASE)
_OPOMBE = re.compile(r"(?<!\s)\s*\[\s*(?:geo-?blocked|offline|not\s*24\s*/\s*7)\s*\]", re.IGNORECASE)
_LOCLJIVOST_V_IMENU = re.compile(r"(?<!\s)\s*\((?:\d{3,4}[pi]|4k|uhd|hd|sd)\)", re.IGNORECASE)
_SEZONA_EPIZODA = re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})\s*[Ee](\d{1,3})(?!\d)")
# »1x02«: epizoda vedno z vsaj dvema stevkama, da ime kanala »4x4 TV« ni serija.
_SEZONA_X = re.compile(r"(?<![\d])(\d{1,2})x(\d{2,3})(?![\d])")

#: Oznake vrstice #EXTINF, po katerih vemo, da je vnos kanal seznama IPTV (iptv-org, Xtream m3u_plus, TVHeadend).
OZNAKE_KANALA = frozenset({"tvg-id", "tvg-name", "tvg-logo", "tvg-country", "tvg-language", "tvg-chno", "tvg-shift",
                           "group-title", "catchup", "catchup-days", "catchup-source", "channel-id", "channel-number"})
#: Datoteke (VOD): film ali epizoda, ne kanal. .ts in .m3u8 sta tok v zivo.
VOD_KONCNICE = frozenset({".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".mpg", ".mpeg", ".wmv", ".divx", ".ogv"})
ZVOK_KONCNICE = frozenset({".mp3", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".wav", ".wma"})
_BESEDE_RADIA = re.compile(r"\b(?:radio|radijsk\w*)\b", re.IGNORECASE)


def vejica_imena(vrstica: str) -> int:
    """Mesto vejice, ki loci atribute od imena: prva ZUNAJ narekovajev (»(KHTML, like Gecko)« v http-user-agent in
    group-title="News,Sport" ne stejeta). -1 = je ni. Enako kot Android IptvPravila.vejicaImena."""
    v_narekovajih = False
    for i, znak in enumerate(vrstica):
        if znak == '"':
            v_narekovajih = not v_narekovajih
        elif znak == "," and not v_narekovajih:
            return i
    return -1


def razcleni_extinf(vrstica: str) -> tuple:
    """(trajanje ali None, atributi z malimi imeni, ime) iz vrstice #EXTINF. Ime je vse za vejico zunaj narekovajev;
    ce ga ni, tvg-name."""
    telo = vrstica.strip()
    if telo[:8].upper() == "#EXTINF:":
        telo = telo[8:]
    i = vejica_imena(telo)
    glava, ime = (telo, "") if i < 0 else (telo[:i], telo[i + 1:])
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", glava)
    trajanje = float(m.group(1)) if m else None
    atributi = {k.lower(): v.strip() for k, v in _ATRIBUT.findall(glava)}
    ime = ime.strip() or atributi.get("tvg-name", "").strip()
    return trajanje, atributi, ime


def ni_24_7(ime: str, atributi: Optional[dict] = None) -> bool:
    """Oznaka »[Not 24/7]« (iptv-org): kanal ne oddaja ves cas - lastnik: izloci povsod."""
    return bool(_NE_24_7.search(ime or "") or _NE_24_7.search(str((atributi or {}).get("tvg-name") or "")))


def cisto_ime(ime: str) -> str:
    """Ime kanala brez tehnicnih pripon seznama (»(720p)«, »[Geo-blocked]«) - locljivost je v polju kakovosti."""
    return re.sub(r"\s+", " ", _LOCLJIVOST_V_IMENU.sub("", _OPOMBE.sub("", ime or ""))).strip()


def _pot(url: str) -> str:
    try:
        return urllib.parse.unquote(urllib.parse.urlsplit(url).path or "").lower()
    except ValueError:
        return ""


def _koncnica(url: str) -> str:
    return os.path.splitext(_pot(url))[1]


def sezona_epizoda(ime: str) -> tuple:
    """(sezona, epizoda) iz imena (»S01E02«, »S01 E02«, »1x02«); (0, 0) = ni epizoda."""
    for vzorec in (_SEZONA_EPIZODA, _SEZONA_X):
        m = vzorec.search(ime or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    return 0, 0


def vrsta_vnosa(atributi: dict, url: str, ime: str, trajanje: Optional[float] = None) -> str:
    """Kam sodi vnos seznama M3U: »tv-v-zivo«, »film«, »serija«, »radio« ali »glasba«.

    Serija samo z znano sezono in epizodo (ime ali pot Xtream /series/), film samo datoteka (VOD: .mp4, .mkv ... ali
    pot Xtream /movie/), vse ostalo z oznakami IPTV ali tokom (.m3u8, .ts, /live/) je kanal TV v zivo - group-title
    »Movies«, »Series«, »Music« je zvrst KANALA, ne vrsta vsebine. Radio: atribut radio="true", beseda »radio« v
    group-title ali zvocni tok. Vnos brez oznak IPTV in brez koncnice je radijski tok (kot Android OsPravila.jeRadijskiVnos)."""
    pot = _pot(url)
    koncnica = _koncnica(url)
    sezona, epizoda = sezona_epizoda(ime)
    if sezona and epizoda:
        return "serija"
    if "/series/" in pot:
        return "film"                             # datoteka brez znane sezone in epizode: predvajljiva, a ne serija
    if "/movie/" in pot or "/movies/" in pot or koncnica in VOD_KONCNICE:
        return "film"
    skupina = str(atributi.get("group-title") or "")
    if str(atributi.get("radio") or "").lower() == "true" or _BESEDE_RADIA.search(skupina):
        return "radio"
    if koncnica in ZVOK_KONCNICE:
        # Zvocna datoteka s trajanjem je skladba; tok (trajanje -1) je radio.
        return "glasba" if (trajanje is not None and trajanje > 0) else "radio"
    if any(k in atributi for k in OZNAKE_KANALA) or koncnica in (".m3u8", ".ts") or "/live/" in pot:
        return "tv-v-zivo"
    return "radio"


# ---------------------------------------------------------------------------------------------- drzava in jezik

_DRZAVA_ID = re.compile(r"\.([a-z]{2})(?:@|$)", re.IGNORECASE)
_DRZAVA_SEZNAMA = re.compile(r"/countries/([a-z]{2})(?:\.m3u8?)?(?:[?#]|$)", re.IGNORECASE)
_JEZIK_SEZNAMA = re.compile(r"/languages/([a-z]{2,3})(?:\.m3u8?)?(?:[?#]|$)", re.IGNORECASE)
#: iptv-org v tvg-id pise Zdruzeno kraljestvo kot ».uk« (ISO 3166-1: GB).
_DRZAVA_POPRAVKI = {"UK": "GB"}

#: ISO 639-2/3 -> 639-1 (seznami po jezikih iptv-org: »languages/eng.m3u«). Enako kot Android IptvPravila.JEZIKI3.
JEZIKI3 = {
    "eng": "en", "slv": "sl", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "ita": "it", "spa": "es",
    "por": "pt", "hrv": "hr", "srp": "sr", "bos": "bs", "mkd": "mk", "mac": "mk", "bul": "bg", "rus": "ru",
    "ukr": "uk", "pol": "pl", "ces": "cs", "cze": "cs", "slk": "sk", "slo": "sk", "hun": "hu", "ron": "ro",
    "rum": "ro", "nld": "nl", "dut": "nl", "swe": "sv", "nor": "no", "dan": "da", "fin": "fi", "ell": "el",
    "gre": "el", "tur": "tr", "ara": "ar", "heb": "he", "hin": "hi", "zho": "zh", "chi": "zh", "jpn": "ja",
    "kor": "ko", "sqi": "sq", "alb": "sq", "fas": "fa", "per": "fa", "urd": "ur", "vie": "vi", "tha": "th",
    "ind": "id", "msa": "ms", "may": "ms", "cat": "ca", "eus": "eu", "baq": "eu", "glg": "gl", "lit": "lt",
    "lav": "lv", "est": "et", "isl": "is", "ice": "is", "gle": "ga", "cym": "cy", "wel": "cy",
}
_IMENA_JEZIKOV = {
    "english": "en", "slovenian": "sl", "slovene": "sl", "german": "de", "french": "fr", "italian": "it",
    "spanish": "es", "portuguese": "pt", "croatian": "hr", "serbian": "sr", "bosnian": "bs", "macedonian": "mk",
    "bulgarian": "bg", "russian": "ru", "ukrainian": "uk", "polish": "pl", "czech": "cs", "slovak": "sk",
    "hungarian": "hu", "romanian": "ro", "dutch": "nl", "swedish": "sv", "norwegian": "no", "danish": "da",
    "finnish": "fi", "greek": "el", "turkish": "tr", "arabic": "ar", "hebrew": "he", "hindi": "hi",
    "chinese": "zh", "japanese": "ja", "korean": "ko", "albanian": "sq", "persian": "fa", "urdu": "ur",
}
#: Glavni jezik drzave (ISO 3166 -> ISO 639-1), kadar seznam jezika ne pove. Enako kot Android IptvPravila.JEZIK_DRZAVE.
#: »Drzave z anglescino« so tiste, ki imajo tu »en« (ANGLESKE_DRZAVE).
JEZIK_DRZAVE = {
    "SI": "sl", "HR": "hr", "RS": "sr", "BA": "bs", "ME": "sr", "MK": "mk", "XK": "sq", "AL": "sq", "AT": "de",
    "DE": "de", "CH": "de", "IT": "it", "HU": "hu", "CZ": "cs", "SK": "sk", "PL": "pl", "FR": "fr", "BE": "nl",
    "NL": "nl", "LU": "fr", "ES": "es", "PT": "pt", "BR": "pt", "MX": "es", "AR": "es", "DK": "da", "SE": "sv",
    "FI": "fi", "GR": "el", "CY": "el", "TR": "tr", "RO": "ro", "BG": "bg", "UA": "uk", "RU": "ru", "US": "en",
    "GB": "en", "CA": "en", "AU": "en", "IE": "en", "NZ": "en", "IN": "hi", "JP": "ja", "CN": "zh", "KR": "ko",
}


def koda_jezika(oznaka: str) -> str:
    """ISO 639-1 iz »English«, »eng« ali »en«; "" = neznan."""
    o = str(oznaka or "").strip().lower()
    if not o:
        return ""
    if o in _IMENA_JEZIKOV:
        return _IMENA_JEZIKOV[o]
    if len(o) == 3 and o in JEZIKI3:
        return JEZIKI3[o]
    return o if re.fullmatch(r"[a-z]{2}", o) else ""


def iz_naslova_seznama(url: str) -> tuple:
    """(drzava, jezik) iz naslova seznama: ».../countries/si.m3u« -> ("SI", ""), ».../languages/eng.m3u« -> ("", "en")."""
    m = _DRZAVA_SEZNAMA.search(url or "")
    drzava = _DRZAVA_POPRAVKI.get(m.group(1).upper(), m.group(1).upper()) if m else ""
    m = _JEZIK_SEZNAMA.search(url or "")
    return drzava, (koda_jezika(m.group(1)) if m else "")


def drzava_in_jezik(atributi: dict, drzava_seznama: str = "", jezik_seznama: str = "") -> tuple:
    """Drzava kanala: tvg-country, sicer pripona tvg-id (»PopTV.si@SD«), sicer drzava seznama. Jezik: tvg-language,
    sicer jezik seznama, sicer glavni jezik drzave (JEZIK_DRZAVE)."""
    drzava = ""
    for del_ in re.split(r"[;,|]", str(atributi.get("tvg-country") or "")):
        if re.fullmatch(r"[A-Za-z]{2}", del_.strip()):
            drzava = del_.strip().upper()
            break
    if not drzava:
        m = _DRZAVA_ID.search(str(atributi.get("tvg-id") or ""))
        drzava = m.group(1).upper() if m else (drzava_seznama or "").upper()
    drzava = _DRZAVA_POPRAVKI.get(drzava, drzava)
    jezik = next((k for k in (koda_jezika(d) for d in re.split(r"[;,|]", str(atributi.get("tvg-language") or ""))) if k), "")
    return drzava, jezik or jezik_seznama or JEZIK_DRZAVE.get(drzava, "")


#: Javni seznami kanalov: tem velja privzeti izbor drzav in jezikov. Rocno dodanih seznamov (npr. ponudnikov)
#: ne filtriramo po drzavi.
JAVNI_GOSTITELJI = ("iptv-org.github.io",)


def je_javni_seznam(url: str) -> bool:
    try:
        deli = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return False
    gostitelj = (deli.hostname or "").lower()
    if gostitelj in JAVNI_GOSTITELJI:
        return True
    return gostitelj == "raw.githubusercontent.com" and deli.path.lower().startswith("/iptv-org/")


# ---------------------------------------------------------------------------------------------- zascita racuna

#: Lastnik, 26. 10. 2026 (»Nevarnost zaklepa racuna je prioriteta«): preverba odpre tok pri ponudniku. Racuni s
#: poverilnicami (Xtream .../live/<uporabnik>/<geslo>/..., get.php?username=, uporabnik:geslo@) imajo pogosto najvec 1-2
#: hkratni povezavi in tisoc odprtij toka vodi v zaklep (pregled 30, J3: seznam Xtream s 5000 kanali je bil vsakih 6 h
#: v celoti preverjen). Take sezname v ozadju NE preverjamo: kanal je viden, o delovanju odloci pravo predvajanje.
#:
#: Pregled 39, I1 (odlocitev: ob dvomu ne): v ozadju preverjamo SAMO pozitivno znane javne brezplacne sezname
#: (iptv-org - je_javni_seznam - in ZNANI_JAVNI_VIRI) in sezname, ki jih je uporabnik v Virih izrecno oznacil kot
#: javne (vir["javni"]). Vse ostalo velja za racun: tudi gist, *.github.io, GitLab ali Codeberg brez zetona (tja si
#: uporabniki shranijo seznam ponudnika, da ga imajo na vseh napravah) - prej se je tak seznam preverjal (do 200
#: odprtij na gostitelja na dan, tudi med gledanjem na drugi napravi istega racuna).
#: (gostitelj, zacetek odkodirane poti z malimi crkami) - enako kot Android IptvPravila.JAVNI_SEZNAMI in skupni primeri
#: tests/skupni-primeri/iptv-racun.json. Free-TV/IPTV: »samo uradno brezplacni kanali« (github.com/Free-TV/IPTV,
#: preverjeno 26. 10. 2026).
ZNANI_JAVNI_VIRI = (("iptv-org.github.io", "/"), ("raw.githubusercontent.com", "/iptv-org/"),
                    ("raw.githubusercontent.com", "/free-tv/iptv/"))
_XTREAM_POT = re.compile(r"/(?:live|movie|movies|series|timeshift)/[^/]+/[^/]+/", re.IGNORECASE)
#: Kratka oblika Xtream (get.php ... output=ts): /<uporabnik>/<geslo>/<id>[.ts] (pregled 39, I1).
_XTREAM_KRATKA = re.compile(r"^/[^/]+/[^/]+/\d+(?:\.[a-z0-9]{1,5})?$", re.IGNORECASE)
_XTREAM_DATOTEKE = ("/get.php", "/player_api.php", "/xmltv.php", "/panel_api.php")
#: Imena parametrov, ki v naslovu nosijo racun (mac: portal Stalker/MAG). Za naslov seznama tudi zetoni (zasebni
#: seznam), za naslov kanala ne: javni CDN pogosto podpise tok z zetonom, ki ni racun uporabnika.
_RACUN_PARAMETRI = frozenset({"username", "password", "user", "pass", "passwd", "pwd", "login", "mac"})
_ZETON_PARAMETRI = frozenset({"token", "access_token", "private_token", "auth", "key", "apikey", "api_key"})


def s_poverilnicami(url: str, seznam: bool = False) -> bool:
    """Ali naslov nosi racun pri ponudniku (`seznam`: naslov seznama - tudi zeton). Nerazumljiv naslov: da."""
    try:
        deli = urllib.parse.urlsplit(str(url or ""))
        if deli.username or deli.password:
            return True
        kljuci = {k.lower() for k, _v in urllib.parse.parse_qsl(deli.query, keep_blank_values=True)}
    except ValueError:
        return True
    pot = (deli.path or "").lower()
    if _XTREAM_POT.search(pot) or _XTREAM_KRATKA.match(pot) or pot.endswith(_XTREAM_DATOTEKE):
        return True
    return bool(kljuci & (_RACUN_PARAMETRI | (_ZETON_PARAMETRI if seznam else frozenset())))


def znan_javni_vir(url_seznama: str) -> bool:
    """Pozitivno znan javni brezplacni seznam (ZNANI_JAVNI_VIRI; pregled 39, I1). Pot odkodirana in brez ../ ali //
    (kot Android): »/iptv-org/../moj/seznam« ni iptv-org."""
    try:
        deli = urllib.parse.urlsplit(str(url_seznama or ""))
    except ValueError:
        return False
    if deli.scheme not in ("http", "https"):
        return False
    pot = urllib.parse.unquote(deli.path or "").lower()
    if ".." in pot or "//" in pot:
        return False
    gostitelj = (deli.hostname or "").lower()
    return any(gostitelj == g and pot.startswith(z) for g, z in ZNANI_JAVNI_VIRI)


def javni_brezplacni(url_seznama: str, oznacen: bool = False) -> bool:
    """Seznam, ki ga smemo preverjati v ozadju - ob dvomu ne (pregled 39, I1): v naslovu ni racuna IN je pozitivno
    znan javni vir (znan_javni_vir) ali ga je uporabnik izrecno oznacil kot javnega (`oznacen`: vir["javni"] is True)."""
    if s_poverilnicami(url_seznama, seznam=True):
        return False
    return znan_javni_vir(url_seznama) or oznacen is True


def oznacljiv_javni(url_seznama: str) -> bool:
    """Ali sme uporabnik seznam oznaciti kot javni brezplacni: ni znan javni vir in v naslovu ni racuna."""
    return not znan_javni_vir(url_seznama) and not s_poverilnicami(url_seznama, seznam=True)


def preverba_dovoljena(url_seznama: str, url_kanala: str, oznacen: bool = False) -> bool:
    """Kanal sme v preverbo v ozadju: javni brezplacni seznam in kanal brez racuna v naslovu."""
    return javni_brezplacni(url_seznama, oznacen) and not s_poverilnicami(url_kanala)


#: Lastnik, 25. 10. 2026 (»mojo drzavo in angleske«, »TV Uganda niti ne rabimo«): privzeta »anglescina« so kanali
#: drzav z anglescino, ne vsi kanali v anglescini (seznam languages/eng.m3u ima kanale iz 110 drzav). Ostale drzave,
#: tudi tiste z angleskimi kanali, uporabnik vklopi v Virih pod »Drzave in jeziki«.
ANGLESKE_DRZAVE = ("US", "GB", "CA", "AU", "IE", "NZ")


def privzeta_izbira(drzava_uporabnika: str) -> dict:
    """Privzeto kanali drzave uporabnika in drzav z anglescino (ANGLESKE_DRZAVE); sosednjih drzav in jezikov ne."""
    d = str(drzava_uporabnika or "").upper()
    lastna = [d] if re.fullmatch(r"[A-Z]{2}", d) else []
    return {"drzave": lastna + [x for x in ANGLESKE_DRZAVE if x not in lastna], "jeziki": []}


def v_izbiri(item: dict, izbira: dict) -> bool:
    """Ali kanal javnega seznama ustreza izbiri drzav in jezikov uporabnika."""
    drzave = {str(x).upper() for x in (izbira or {}).get("drzave") or []}
    jeziki = {str(x).lower() for x in (izbira or {}).get("jeziki") or []}
    drzava = str(item.get("drzava") or "").upper()
    jezik = str(item.get("jezik") or "").lower()
    return (bool(drzava) and drzava in drzave) or (bool(jezik) and jezik in jeziki)


# ---------------------------------------------------------------------------------------------- preverba toka

DELUJE, ZAKLENJEN, MRTEV = "deluje", "zaklenjen", "mrtev"
#: Ena preverba kanala (vse zahteve skupaj) najvec toliko sekund (lastnik: ~4 s).
ROK_S = 4.0
#: Toliko kanalov hkrati; na istega gostitelja nikoli vec kot ena zahteva (ne bremenimo vira).
VZPOREDNO = 4
#: Med dvema preverbama istega gostitelja (tudi javnega) premor; na dan najvec toliko odprtij toka na gostitelja
#: (lastnik, 26. 10. 2026: zascita pred zaklepom in blokado). Kar ostane, je vidno z oznako »preverjam«.
PREMOR_GOSTITELJA_S = 3.0
NAJVEC_NA_GOSTITELJA_DAN = 200
#: Ko uporabnik zacne predvajati, preverba stoji toliko sekund (platforma brez signala konca predvajanja); Linux jo
#: med predvajanjem podaljsuje in ob koncu sprosti (gleda, ne_gleda).
GLEDANJE_S = 3 * 3600
#: Ponovna tiha preverba mrtvih kanalov: ena konstanta. Lastnik, 25. 10. 2026: vklopljena, dokler meritev ne pokaze,
#: da se mrtvi kanali ne vracajo (orodje tools/kanali_preverba.py zapise izid vsakega kanala za primerjavo).
PONOVNO_PREVERI_MRTVE = True
#: Kako dolgo velja izid; nato kanal preverimo znova v ozadju (do takrat velja stari izid).
VELJA_S = {DELUJE: 6 * 3600, ZAKLENJEN: 24 * 3600, MRTEV: 24 * 3600}
#: Brez odgovora v roku ali prekinjena povezava je lahko le trenutna obremenitev (izmerjeno 25. 10. 2026: od 50 kanalov z
#: »rok« pri 4 s jih je 14 ob ponovni preverbi delovalo, 12 v manj kot 3,5 s). Tak kanal je skrit, a ga po PONOVI_PO_S
#: enkrat preverimo znova z daljsim rokom; sele drugi neuspeh velja za 24 h.
PONOVI_KODE = frozenset({"rok", "povezava"})
PONOVI_PO_S = 10 * 60
ROK_PONOVNO_S = 8.0
NAJVEC_PREUSMERITEV = 5
NAJVEC_SEZNAM = 256 * 1024
BAJTOV_KOSA = 2048
#: Toliko bajtov neposrednega toka preberemo za magicne bajte (TS paket je 188 bajtov).
ZACETEK_TOKA = 4096
#: Brskalnik, kadar seznam ne doloci svojega (nekateri strezniki zavrnejo Pythonov privzeti odjemalec).
PRIVZETI_ODJEMALEC = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/18.0 Safari/605.1.15")


class _Napaka(Exception):
    def __init__(self, izid: str, koda: str):
        super().__init__(koda)
        self.izid, self.koda = izid, koda


_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def dovoljen_ip(naslov: str, domace: bool) -> bool:
    """Javni naslov vedno; zasebni in link-local samo, ce je seznam sam v domacem omrezju (AGENTS: brez zasebnih IP
    razen domacega omrezja). Loopback (ta racunalnik) nikoli: kanal s seznama ne sme do storitev tega racunalnika
    (pregled 30, J2). IPv4 v IPv6 (::ffff:, NAT64 64:ff9b::, 6to4 2002::) se preveri kot vgrajeni IPv4 (J10).
    Multicast, nedoloceni in rezervirani nikoli.

    Od 26. 10. 2026 (J3) gre v preverbo samo javni brezplacni seznam (domace=False): zasebnih naslovov preverba sploh ne
    odpira; `domace` ostane za orodja in preizkuse."""
    try:
        a = ipaddress.ip_address(str(naslov).split("%", 1)[0])
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    if a.version == 6:
        if any(a in mreza for mreza in _NAT64):
            a = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
        elif a.sixtofour is not None:
            a = a.sixtofour
    if a.is_multicast or a.is_unspecified or a.is_reserved or a.is_loopback:
        return False
    if a.is_global:
        return True
    return domace and (a.is_private or a.is_link_local)


def _razresi_v_roku(razresi, gostitelj: str, vrata: int, konec: Optional[float]) -> list:
    """getaddrinfo z rokom: sistemski razresevalnik lahko caka 5-30 s in ga ni mogoce prekiniti, zato tece v svoji
    niti - ce do `konec` ne odgovori, je izid »rok« (pregled 30, J1). Naslov IP se razresi takoj, brez niti."""
    try:
        ipaddress.ip_address(str(gostitelj).split("%", 1)[0])
        je_ip = True
    except ValueError:
        je_ip = False
    if je_ip or konec is None:
        return razresi(gostitelj, vrata, type=socket.SOCK_STREAM)
    izid: dict = {}

    def delo() -> None:
        try:
            izid["naslovi"] = razresi(gostitelj, vrata, type=socket.SOCK_STREAM)
        except BaseException as napaka:  # noqa: BLE001 - napako dobi klicatelj
            izid["napaka"] = napaka
    nit = threading.Thread(target=delo, name="safeer-kanali-dns", daemon=True)
    nit.start()
    nit.join(max(0.0, konec - time.monotonic()))
    if nit.is_alive():
        raise _Napaka(MRTEV, "rok")
    if "napaka" in izid:
        raise izid["napaka"]
    return izid["naslovi"]


def _razresi_ip(gostitelj: str, vrata: int, domace: bool, razresi=socket.getaddrinfo,
                konec: Optional[float] = None) -> list:
    """Dovoljeni naslovi gostitelja (vrstni red razresevalnika). Povezemo se na TE naslove (ne znova po imenu): DNS med
    preverbo in povezavo ne more podtakniti zasebnega naslova."""
    try:
        naslovi = list(dict.fromkeys(info[4][0] for info in _razresi_v_roku(razresi, gostitelj, vrata, konec)))
    except (OSError, UnicodeError):
        raise _Napaka(MRTEV, "dns") from None
    dovoljeni = [n for n in naslovi if dovoljen_ip(n, domace)]
    if not dovoljeni:
        raise _Napaka(MRTEV, "zasebni-naslov")
    return dovoljeni


def _vticnica(naslovi: list, vrata: int, cas: float) -> socket.socket:
    """Povezava na prvi dosegljiv naslov (IPv6 brez poti ne sme pokvariti preverbe kanala z naslovom IPv4)."""
    konec = time.monotonic() + cas
    zadnja: Optional[OSError] = None
    for naslov in naslovi:
        ostane = konec - time.monotonic()
        if ostane <= 0:
            break
        try:
            return socket.create_connection((naslov, vrata), ostane)
        except OSError as napaka:
            zadnja = napaka
    raise zadnja or socket.timeout("rok")


class _Straza:
    """Skupni rok ene zahteve (pregled 30, J1): ob `konec` zapre vticnico (shutdown), ne glede na to, kje zahteva caka -
    rokovanje TLS, vrstica statusa, glave ali telo po kapljicah. Rok posamezne operacije vticnice tega ne naredi:
    streznik, ki poslje bajt vsake 3 s, ga ne sprozi nikoli, in stirje taki gostitelji so ustavili vso preverbo."""

    def __init__(self, konec: float):
        self._zaklep = threading.Lock()
        self._vticnice: list = []
        self._ustavljena = False
        self.potekel = False
        self._casovnik = threading.Timer(max(0.0, konec - time.monotonic()), self._potece)
        self._casovnik.daemon = True
        self._casovnik.name = "safeer-kanali-rok"
        self._casovnik.start()

    @staticmethod
    def _zapri(vticnica) -> None:
        try:
            # Osnovni shutdown tudi za SSLSocket: njegov shutdown bi med branjem v drugi niti izbrisal _sslobj.
            socket.socket.shutdown(vticnica, socket.SHUT_RDWR)
        except OSError:
            pass

    def dodaj(self, vticnica) -> None:
        with self._zaklep:
            self._vticnice.append(vticnica)
            if self.potekel:
                self._zapri(vticnica)

    def _potece(self) -> None:
        with self._zaklep:
            if self._ustavljena:
                return
            self.potekel = True
            for vticnica in self._vticnice:
                self._zapri(vticnica)

    def ustavi(self) -> None:
        """Pred zaprtjem vticnice: casovnik ne sme zapreti stevilke datoteke, ki jo je medtem dobila druga vticnica."""
        self._casovnik.cancel()
        with self._zaklep:
            self._ustavljena = True


class _Povezava(http.client.HTTPConnection):
    def __init__(self, gostitelj: str, vrata: int, naslovi: list, cas: float, straza: _Straza):
        super().__init__(gostitelj, vrata, timeout=cas)
        self._naslovi, self._straza = naslovi, straza

    def connect(self) -> None:
        self.sock = _vticnica(self._naslovi, self.port, self.timeout)
        self._straza.dodaj(self.sock)


class _PovezavaTLS(http.client.HTTPSConnection):
    def __init__(self, gostitelj: str, vrata: int, naslovi: list, cas: float, kontekst: ssl.SSLContext,
                 straza: _Straza):
        super().__init__(gostitelj, vrata, timeout=cas, context=kontekst)
        self._naslovi, self._straza = naslovi, straza

    def connect(self) -> None:
        sock = _vticnica(self._naslovi, self.port, self.timeout)
        self._straza.dodaj(sock)
        tls = self._context.wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False)
        self._straza.dodaj(tls)                 # rokovanje TLS je pod skupnim rokom
        self.sock = tls
        tls.do_handshake()


_TLS = None


def _tls() -> ssl.SSLContext:
    global _TLS
    if _TLS is None:
        _TLS = ssl.create_default_context()
    return _TLS


#: Stevec zahtev preverbe v tej niti (PreverbaKanalov._delaj): dnevna meja steje vsako zahtevo na gostitelja - seznam,
#: razlicice, kos, kljuc in vsak skok preusmeritve, ne samo izbire kanala (pregled 39, I8).
_NIT = threading.local()


def _zahteva(url: str, glave: dict, konec: float, domace: bool, najvec: int, obseg: str = "",
             razresi=socket.getaddrinfo) -> tuple:
    """GET z rokom `konec` (time.monotonic) in rocnimi preusmeritvami: VSAK skok preverimo (shema, dovoljen IP).
    Vrne (status, koncni naslov, vrsta vsebine, prvih `najvec` bajtov).

    Glave seznama kot brskalnik (pregled 30, J8): Cookie samo izvornemu gostitelju, po preusmeritvi s https na http
    nobene (Referer, Origin, Cookie)."""
    izvor, znizano, prej_https = None, False, False
    for _ in range(NAJVEC_PREUSMERITEV + 1):
        deli = urllib.parse.urlsplit(url)
        if deli.scheme not in ("http", "https") or not deli.hostname or deli.username or deli.password:
            raise _Napaka(MRTEV, "naslov")
        gostitelj = deli.hostname.lower()
        izvor = gostitelj if izvor is None else izvor
        znizano = znizano or (prej_https and deli.scheme == "http")
        prej_https = deli.scheme == "https"
        try:
            vrata = deli.port or (443 if deli.scheme == "https" else 80)
        except ValueError:
            raise _Napaka(MRTEV, "naslov") from None
        ostane = konec - time.monotonic()
        if ostane <= 0.05:
            raise _Napaka(MRTEV, "rok")
        naslovi = _razresi_ip(deli.hostname, vrata, domace, razresi, konec)
        ostane = max(0.05, konec - time.monotonic())
        straza = _Straza(konec)
        povezava = (_PovezavaTLS(deli.hostname, vrata, naslovi, ostane, _tls(), straza) if deli.scheme == "https"
                    else _Povezava(deli.hostname, vrata, naslovi, ostane, straza))
        pot = (deli.path or "/") + ("?" + deli.query if deli.query else "")
        zaglavje = {"User-Agent": glave.get("User-Agent") or PRIVZETI_ODJEMALEC, "Accept": "*/*",
                    "Accept-Encoding": "identity", "Connection": "close"}
        for ime, vrednost in glave.items():
            nizko = ime.lower()
            if nizko in ("referer", "origin", "cookie") and vrednost and not znizano \
                    and (nizko != "cookie" or gostitelj == izvor):
                zaglavje[ime] = vrednost
        if obseg:
            zaglavje["Range"] = obseg
        stej = getattr(_NIT, "stej", None)
        if stej is not None:
            stej(gostitelj)
        try:
            povezava.request("GET", pot, headers=zaglavje)
            odgovor = povezava.getresponse()
            status = odgovor.status
            if status in (301, 302, 303, 307, 308):
                lokacija = odgovor.getheader("Location") or ""
                povezava.close()
                if not lokacija:
                    raise _Napaka(MRTEV, "preusmeritev")
                url = urllib.parse.urljoin(url, lokacija.strip())
                continue
            vrsta = (odgovor.getheader("Content-Type") or "").lower()
            vsebina = bytearray()
            while len(vsebina) < najvec and 200 <= status < 300:
                if time.monotonic() > konec:
                    if vsebina:
                        break
                    raise _Napaka(MRTEV, "rok")
                kos = odgovor.read(min(8192, najvec - len(vsebina)))
                if not kos:
                    break
                vsebina += kos
                # Tok v zivo (TS) je neskoncen: za dokaz je dovolj zacetek; do `najvec` beremo samo seznam HLS.
                if len(vsebina) >= ZACETEK_TOKA and not _je_hls(bytes(vsebina[:64]), vrsta):
                    break
            if straza.potekel and not vsebina and 200 <= status < 300:
                raise _Napaka(MRTEV, "rok")
            return status, url, vrsta, bytes(vsebina)
        except _Napaka:
            raise
        except Exception as napaka:  # noqa: BLE001 - razvrstitev spodaj, neznano naprej
            if straza.potekel:
                raise _Napaka(MRTEV, "rok") from None      # skupni rok je zaprl vticnico
            if isinstance(napaka, ssl.SSLError):
                raise _Napaka(MRTEV, "tls") from None
            if isinstance(napaka, (socket.timeout, TimeoutError)):
                raise _Napaka(MRTEV, "rok") from None
            if isinstance(napaka, (OSError, http.client.HTTPException)):
                raise _Napaka(MRTEV, "povezava") from None
            raise
        finally:
            straza.ustavi()
            povezava.close()
    raise _Napaka(MRTEV, "preusmeritve")


def _izid_statusa(status: int) -> None:
    if status in (401, 403, 451):
        raise _Napaka(ZAKLENJEN, "http-%d" % status)
    if not 200 <= status < 300:
        raise _Napaka(MRTEV, "http-%d" % status)


def vrsta_bajtov(podatki: bytes) -> str:
    """»ts«, »mp4«, »mkv«, »flv«, »id3«, »aac« ali "" po magicnih bajtih zacetka toka ali kosa."""
    if len(podatki) >= 8 and podatki[4:8] in (b"ftyp", b"styp", b"moof", b"sidx", b"emsg", b"prft", b"moov"):
        return "mp4"
    if podatki[:4] == b"\x1a\x45\xdf\xa3":
        return "mkv"
    if podatki[:3] == b"FLV":
        return "flv"
    if podatki[:3] == b"ID3":
        return "id3"
    # MPEG-TS: sinhronizacijski bajt 0x47 na vsakih 188 bajtov (strezniki vcasih zacnejo sredi paketa).
    for i in range(min(188, len(podatki))):
        if podatki[i] == 0x47 and i + 188 < len(podatki) and podatki[i + 188] == 0x47:
            return "ts"
    if len(podatki) >= 2 and podatki[0] == 0xFF and podatki[1] & 0xF6 == 0xF0:
        return "aac"
    return ""


def _je_hls(vsebina: bytes, vrsta: str) -> bool:
    return vsebina.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"#EXTM3U") or "mpegurl" in vrsta


def _vrstice(vsebina: bytes) -> list:
    besedilo = vsebina.decode("utf-8", "replace")
    vrstice = besedilo.split("\n")
    if len(vsebina) >= NAJVEC_SEZNAM and not besedilo.endswith("\n"):
        vrstice = vrstice[:-1]          # odrezana zadnja vrstica bi dala lazen naslov
    return [v.strip() for v in vrstice if v.strip()]


def _preveri_hls(url: str, vsebina: bytes, glave: dict, konec: float, domace: bool, razresi) -> str:
    vrstice = _vrstice(vsebina)
    if any(v.startswith("#EXT-X-STREAM-INF") for v in vrstice):
        razlicice = []
        for i, v in enumerate(vrstice):
            if v.startswith("#EXT-X-STREAM-INF"):
                naslednja = next((x for x in vrstice[i + 1:] if not x.startswith("#")), "")
                if naslednja:
                    razlicice.append(urllib.parse.urljoin(url, naslednja))
        if not razlicice:
            raise _Napaka(MRTEV, "vsebina")
        zadnja: Optional[_Napaka] = None
        for naslov in razlicice[:2]:              # mrtvo razlicico predvajalnik preskoci; dve sta dovolj za dokaz
            try:
                status, koncni, vrsta, telo = _zahteva(naslov, glave, konec, domace, NAJVEC_SEZNAM, razresi=razresi)
                _izid_statusa(status)
                if not _je_hls(telo, vrsta):
                    raise _Napaka(MRTEV, "vsebina")
                return _preveri_kos(koncni, _vrstice(telo), glave, konec, domace, razresi)
            except _Napaka as napaka:
                zadnja = napaka
                if napaka.koda == "rok":
                    break
        raise zadnja or _Napaka(MRTEV, "vsebina")
    return _preveri_kos(url, vrstice, glave, konec, domace, razresi)


def _preveri_kos(url: str, vrstice: list, glave: dict, konec: float, domace: bool, razresi) -> str:
    """Seznam kosov mora imeti vsaj en kos; zadnji kos (v zivo je najverjetneje se na strezniku) mora odgovoriti z
    zacetkom toka (TS, fMP4, ID3/AAC). Sifriran kos (EXT-X-KEY) mora imeti dosegljiv kljuc - bajtov ne beremo."""
    kosi = [x for i, x in enumerate(vrstice) if not x.startswith("#") and i > 0
            and any(p.startswith("#EXTINF") for p in vrstice[max(0, i - 3):i])]
    if not kosi:
        raise _Napaka(MRTEV, "vsebina")
    sifrirano = ""
    for v in vrstice:
        if v.startswith("#EXT-X-KEY") and "METHOD=NONE" not in v.upper():
            m = re.search(r'URI="([^"]+)"', v)
            sifrirano = urllib.parse.urljoin(url, m.group(1)) if m else "brez-uri"
    if sifrirano and sifrirano != "brez-uri" and not sifrirano.startswith(("http://", "https://")):
        sifrirano = "brez-uri"                    # skd:// ipd. (DRM): kljuca ne preverjamo
    if sifrirano and sifrirano != "brez-uri":
        status, _koncni, _vrsta, _telo = _zahteva(sifrirano, glave, konec, domace, 64, razresi=razresi)
        _izid_statusa(status)
    status, _koncni, _vrsta, telo = _zahteva(urllib.parse.urljoin(url, kosi[-1]), glave, konec, domace, BAJTOV_KOSA,
                                             obseg="bytes=0-%d" % (BAJTOV_KOSA - 1), razresi=razresi)
    _izid_statusa(status)
    if sifrirano:
        return "hls"
    if not vrsta_bajtov(telo):
        raise _Napaka(MRTEV, "vsebina")
    return "hls"


def preveri_tok(url: str, glave: Optional[dict] = None, rok: float = ROK_S, domace: bool = False,
                razresi=socket.getaddrinfo) -> tuple:
    """(izid, koda): izid je DELUJE, ZAKLENJEN ali MRTEV; koda pove zakaj (»hls«, »ts«, »http-404«, »tls«, »rok« ...).

    Deluje samo veljaven tok: seznam HLS z razlicico in kosom ali magicni bajti TS/MP4/MKV/FLV. 401/403/451 je
    zaklenjen (naroznina ali geografska omejitev), 404/410, napaka TLS, brez odgovora ali napacna vsebina je mrtev."""
    konec = time.monotonic() + max(0.5, float(rok))
    glave = {str(k): str(v) for k, v in (glave or {}).items() if k and v}
    try:
        status, koncni, vrsta, telo = _zahteva(url, glave, konec, domace, NAJVEC_SEZNAM, razresi=razresi)
        _izid_statusa(status)
        if _je_hls(telo, vrsta):
            return DELUJE, _preveri_hls(koncni, telo, glave, konec, domace, razresi)
        oblika = vrsta_bajtov(telo)
        if oblika in ("ts", "mp4", "mkv", "flv"):
            return DELUJE, oblika
        return MRTEV, "vsebina"
    except _Napaka as napaka:
        return napaka.izid, napaka.koda
    except Exception:  # noqa: BLE001 - nepricakovan odgovor streznika: kanal ne deluje
        return MRTEV, "napaka"


def kljuc(url: str) -> str:
    """Kljuc kanala v predpomnilniku preverb: odtis naslova (naslovi lahko nosijo zetone - na disk jih ne pisemo)."""
    return hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()[:24]


class PreverbaKanalov:
    """Izidi preverb kanalov (na disku samo odtis naslova, izid, koda in cas) in preverba v ozadju: najvec VZPOREDNO
    kanalov hkrati, na istega gostitelja ena zahteva naenkrat, med dvema premor PREMOR_GOSTITELJA_S, na dan najvec
    NAJVEC_NA_GOSTITELJA_DAN; med predvajanjem (gleda) nic. Klicatelj v vrsto da samo kanale, za katere velja
    preverba_dovoljena.

    `ob_spremembi()` se poklice (najvec vsakih nekaj sekund in na koncu), ko se je spremenilo, kateri kanali delujejo.
    """

    ZAPIS_S = 2.0
    OBVESTILO_S = 5.0

    def __init__(self, pot: Optional[Path], preveri: Optional[Callable] = None, ura: Callable[[], float] = time.time):
        self._pot = Path(pot) if pot else None
        self._preveri = preveri or preveri_tok
        self._ura = ura
        self._lock = threading.Condition()
        self._izidi: Optional[dict] = None
        self._vrsta: list = []                 # [(kljuc, url, glave, domace, ponovitev, gostitelj)]
        self._cakajo: set = set()
        self._gostitelji: set = set()
        self._prost_ob: dict = {}              # gostitelj -> time.monotonic(), ko je premor mimo
        self._gleda_do = 0.0                   # time.monotonic(): do takrat preverba stoji (uporabnik gleda)
        self._delavci = 0
        self._spremembe = 0
        self._zadnje_obvestilo = 0.0
        self._zadnji_zapis = 0.0
        self._meta: dict = {}
        self.ob_spremembi: Optional[Callable[[], None]] = None

    # --- stanje
    def _beri(self) -> dict:
        if self._izidi is None:
            podatki = {}
            if self._pot is not None:
                try:
                    podatki = json.loads(self._pot.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    podatki = {}
            self._izidi = {k: v for k, v in (podatki.get("kanali") or {}).items()
                           if isinstance(v, list) and len(v) >= 3} if isinstance(podatki, dict) else {}
            self._meta = dict(podatki.get("meta") or {}) if isinstance(podatki, dict) else {}
        return self._izidi

    def _pisi(self, takoj: bool = False) -> None:
        if self._pot is None:
            return
        zdaj = time.monotonic()
        if not takoj and zdaj - self._zadnji_zapis < self.ZAPIS_S:
            return
        self._zadnji_zapis = zdaj
        izidi = self._beri()
        besedilo = json.dumps({"razlicica": 1, "meta": self._meta, "kanali": izidi}, separators=(",", ":"))
        try:
            self._pot.parent.mkdir(parents=True, exist_ok=True)
            zacasna = self._pot.with_suffix(".tmp")
            zacasna.write_text(besedilo, encoding="utf-8")
            os.replace(zacasna, self._pot)
        except OSError:
            pass

    def izid(self, url: str) -> Optional[str]:
        with self._lock:
            zapis = self._beri().get(kljuc(url))
        return zapis[0] if zapis else None

    def deluje(self, url: str) -> bool:
        return self.izid(url) == DELUJE

    @staticmethod
    def _za_ponovitev(zapis: Optional[list]) -> bool:
        """Mrtev zaradi roka ali prekinjene povezave in se ni bil ponovljen z daljsim rokom."""
        return bool(zapis) and zapis[0] == MRTEV and zapis[1] in PONOVI_KODE and not (len(zapis) > 3 and zapis[3])

    def potrebuje_preverbo(self, url: str) -> bool:
        with self._lock:
            zapis = self._beri().get(kljuc(url))
        if not zapis:
            return True
        starost = self._ura() - float(zapis[2] or 0)
        if self._za_ponovitev(zapis):
            return starost >= PONOVI_PO_S
        if zapis[0] == MRTEV and not PONOVNO_PREVERI_MRTVE:
            return False
        return starost >= VELJA_S.get(zapis[0], VELJA_S[MRTEV])

    def zapisi(self, url: str, izid: str, koda: str = "", ponovljeno: bool = False) -> bool:
        """Zapise izid; vrne True, ce se je spremenilo, ali kanal deluje. `ponovljeno`: to je bila ponovitev z daljsim
        rokom (drugi neuspeh velja 24 h)."""
        k = kljuc(url)
        with self._lock:
            izidi = self._beri()
            prej = izidi.get(k)
            if prej and prej[0] == MRTEV and izid == DELUJE:
                self._meta["vrnjeni"] = int(self._meta.get("vrnjeni") or 0) + 1   # mrtev kanal je spet ziv
            if prej and prej[0] == MRTEV:
                self._meta["ponovno_preverjeni"] = int(self._meta.get("ponovno_preverjeni") or 0) + 1
            izidi[k] = [izid, str(koda)[:24], round(self._ura(), 1), 1 if ponovljeno else 0]
            spremenjeno = (prej[0] == DELUJE) != (izid == DELUJE) if prej else izid == DELUJE
            if spremenjeno:
                self._spremembe += 1
            self._pisi()
        return spremenjeno

    def oznaci_mrtev(self, url: str, koda: str = "predvajanje") -> None:
        """Kanal ob kliku ni zaigral: takoj skrit (do ponovne preverbe)."""
        self.zapisi(url, MRTEV, koda, ponovljeno=True)
        with self._lock:
            self._pisi(takoj=True)

    def pozabi(self, urlji: Iterable[str], izidi: Iterable[str] = (ZAKLENJEN,)) -> int:
        """Pozabi izid (privzeto »zaklenjen«) teh kanalov: ob rocni osvezitvi vira jih preverimo znova - uporabnik je
        morda pravkar placal naroznino pri ponudniku. Vrne stevilo pozabljenih."""
        izidi = set(izidi)
        n = 0
        with self._lock:
            vsi = self._beri()
            for u in urlji:
                k = kljuc(u)
                if k in vsi and vsi[k][0] in izidi:
                    del vsi[k]
                    n += 1
            if n:
                self._pisi(takoj=True)
        return n

    def povzetek(self, urlji: Iterable[str]) -> dict:
        stevci = {DELUJE: 0, ZAKLENJEN: 0, MRTEV: 0, "neznano": 0}
        with self._lock:
            izidi = self._beri()
            for u in urlji:
                zapis = izidi.get(kljuc(u))
                stevci[zapis[0] if zapis and zapis[0] in stevci else "neznano"] += 1
        return stevci

    def meta(self) -> dict:
        with self._lock:
            self._beri()
            return dict(self._meta)

    # --- predvajanje: preverba stoji (racun z 1-2 povezavama bi preverba med gledanjem prekinila ali zaklenila)
    def gleda(self, sekund: float = GLEDANJE_S) -> None:
        with self._lock:
            self._gleda_do = max(self._gleda_do, time.monotonic() + float(sekund))

    def ne_gleda(self) -> None:
        with self._lock:
            self._gleda_do = 0.0
            self._lock.notify_all()

    def _odprtja_danes(self) -> dict:
        """Klicati z zaklepom: stevilo odprtij toka danes po gostitelju (odtis imena, ne ime)."""
        dan = int(self._ura() // 86400)
        odprtja = self._meta.get("odprtja")
        if not isinstance(odprtja, dict) or odprtja.get("dan") != dan or not isinstance(odprtja.get("g"), dict):
            odprtja = {"dan": dan, "g": {}}
            self._meta["odprtja"] = odprtja
        return odprtja["g"]

    # --- preverba v ozadju
    def preveri_v_ozadju(self, kanali: Iterable[tuple]) -> int:
        """kanali: (url, glave, domace) v vrstnem redu prikaza. Doda tiste, ki jih je treba preveriti, PRED starejse
        (najprej kanali, ki jih uporabnik pravkar gleda na zaslonu); vrne stevilo novih v vrsti. Kanal, ki je bil mrtev
        zaradi roka ali povezave, se preveri z daljsim rokom (ROK_PONOVNO_S)."""
        novi = 0
        with self._lock:
            izidi = self._beri()
            spredaj = []
            for url, glave, domace in kanali:
                k = kljuc(url)
                if k in self._cakajo:
                    i = next((i for i, x in enumerate(self._vrsta) if x[0] == k), -1)
                    if i >= 0:
                        spredaj.append(self._vrsta.pop(i))      # ze v vrsti: zdaj je na zaslonu, naprej
                    continue
                self._cakajo.add(k)
                ponovitev = self._za_ponovitev(izidi.get(k))
                try:
                    gostitelj = (urllib.parse.urlsplit(url).hostname or "").lower()
                except ValueError:
                    gostitelj = ""
                spredaj.append((k, url, dict(glave or {}), bool(domace), ponovitev, gostitelj))
                novi += 1
            self._vrsta[:0] = spredaj
            while self._delavci < VZPOREDNO and self._delavci < len(self._vrsta):
                self._delavci += 1
                threading.Thread(target=self._delaj, name="safeer-kanali", daemon=True).start()
        return novi

    def v_teku(self) -> int:
        with self._lock:
            return len(self._cakajo)

    def odstrani_iz_vrste(self, urlji: Iterable[str]) -> int:
        """Kanali gredo iz vrste preverbe (uporabnik je seznamu umaknil oznako »javni«; pregled 39, I1): nov ne zacne,
        kanal, ki se ta hip preverja, konca. Vrne stevilo odstranjenih."""
        kljuci = {kljuc(u) for u in urlji if u}
        with self._lock:
            ostanejo = [x for x in self._vrsta if x[0] not in kljuci]
            for x in self._vrsta:
                if x[0] in kljuci:
                    self._cakajo.discard(x[0])
            odstranjeni = len(self._vrsta) - len(ostanejo)
            self._vrsta[:] = ostanejo
            self._lock.notify_all()
        return odstranjeni

    def _naslednji(self) -> Optional[tuple]:
        """Prvi kanal v vrsti, katerega gostitelja ta hip nihce ne sprasuje in je njegov premor mimo (z zaklepom).
        Med predvajanjem caka; gostitelj z izcrpano dnevno mejo gre iz vrste (kanali ostanejo neznani - vidni)."""
        while self._vrsta:
            zdaj = time.monotonic()
            if zdaj < self._gleda_do:
                self._lock.wait(min(5.0, self._gleda_do - zdaj))
                continue
            odprtja = self._odprtja_danes()
            cakaj, izcrpani = 1.0, []
            for i, (k, url, glave, domace, ponovitev, gostitelj) in enumerate(self._vrsta):
                if gostitelj in self._gostitelji:
                    continue
                prost = self._prost_ob.get(gostitelj, 0.0)
                if prost > zdaj:
                    cakaj = min(cakaj, prost - zdaj)
                    continue
                odtis = kljuc(gostitelj)[:12]
                if int(odprtja.get(odtis) or 0) >= NAJVEC_NA_GOSTITELJA_DAN:
                    izcrpani.append(i)
                    continue
                for j in reversed(izcrpani):
                    self._cakajo.discard(self._vrsta.pop(j)[0])
                del self._vrsta[i - len(izcrpani)]
                odprtja[odtis] = int(odprtja.get(odtis) or 0) + 1
                self._gostitelji.add(gostitelj)
                return k, url, glave, domace, ponovitev, gostitelj
            for j in reversed(izcrpani):
                self._cakajo.discard(self._vrsta.pop(j)[0])
            if izcrpani:
                self._lock.notify_all()
                continue
            self._lock.wait(max(0.05, cakaj))
        return None

    def _stej_zahteve(self, zahteve: dict, izbrani: str) -> None:
        """Klicati z zaklepom: dnevna meja steje vsako zahtevo preverbe na gostitelja (pregled 39, I8 - prej samo izbiro
        kanala, ena preverba HLS pa so 3-5 zahtev). Izbira (_naslednji) je ze stela eno na izbranega gostitelja.
        Stevec je v zapisu kanali-preverba.json (meta) in velja po ponovnem zagonu."""
        odprtja = self._odprtja_danes()
        for g, n in zahteve.items():
            dodaj = n - 1 if g == izbrani else n
            if dodaj > 0:
                odtis = kljuc(g)[:12]
                odprtja[odtis] = int(odprtja.get(odtis) or 0) + dodaj

    def _delaj(self) -> None:
        try:
            while True:
                with self._lock:
                    naslednji = self._naslednji()
                    if naslednji is None:
                        break
                k, url, glave, domace, ponovitev, gostitelj = naslednji
                zahteve: dict = {}
                _NIT.stej = lambda g: zahteve.__setitem__(g, zahteve.get(g, 0) + 1)
                try:
                    izid, koda = self._preveri(url, glave, ROK_PONOVNO_S if ponovitev else ROK_S, domace)
                except Exception:  # noqa: BLE001
                    izid, koda = MRTEV, "napaka"
                finally:
                    _NIT.stej = None
                self.zapisi(url, izid, koda, ponovljeno=ponovitev)
                with self._lock:
                    self._stej_zahteve(zahteve, gostitelj)
                    self._gostitelji.discard(gostitelj)
                    self._prost_ob[gostitelj] = time.monotonic() + PREMOR_GOSTITELJA_S
                    self._cakajo.discard(k)
                    self._lock.notify_all()
                self._obvesti(False)
        finally:
            with self._lock:
                self._delavci -= 1
                zadnji = self._delavci == 0
                if zadnji:
                    self._pisi(takoj=True)
                self._lock.notify_all()
            if zadnji:
                self._obvesti(True)

    def _obvesti(self, koncano: bool) -> None:
        with self._lock:
            if not self._spremembe:
                return
            zdaj = time.monotonic()
            if not koncano and zdaj - self._zadnje_obvestilo < self.OBVESTILO_S:
                return
            self._zadnje_obvestilo = zdaj
            self._spremembe = 0
            povratni = self.ob_spremembi
        if povratni is not None:
            try:
                povratni()
            except Exception:  # noqa: BLE001, S110 - obvestilo zaslona ne sme ustaviti preverbe
                pass

    def pocakaj(self, rok: float) -> bool:
        """Za orodja in preizkuse: pocaka, da je vrsta prazna (True) ali da poteece rok (False)."""
        konec = time.monotonic() + rok
        with self._lock:
            while self._cakajo or self._delavci:
                ostane = konec - time.monotonic()
                if ostane <= 0:
                    return False
                self._lock.wait(min(0.5, ostane))
        return True
