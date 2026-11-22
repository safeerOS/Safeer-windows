"""Enotni lokalni katalog in predvajalno jedro za Safeer Media.

Vir je lahko javni JSON API, RSS/Atom, M3U ali spletna stran/spletna aplikacija,
ki objavi medije v HTML, OpenGraph, JSON-LD ali vdelanem JSON-u. Viri in njihov
zadnji uspešni katalog ostanejo lokalno shranjeni. Elementi iz vseh virov se
normalizirajo, podvojeni naslovi združijo, za predvajanje pa se izbere najboljša
razpoložljiva različica.
"""

from __future__ import annotations

import hashlib
import difflib
import http.client
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date as _date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import zakoniti_viri
from . import izvirni_jezik
from . import debrid
from . import debrid_pravila
from . import usenet_pravila
from . import usenet_filter
from . import filter_vira_pravila
from . import media_servers
from . import tok_izbira
from . import os_torrent, os_torrent_tok
from . import knjiznica_kroga
from . import watch_providers
from . import uvoz_seznama
from . import youtube_racun
from . import twitch
from . import spotify_racun
from . import seznami_sink
from . import viri_sink
from . import meritve_virov
from . import kanali_iptv
from . import skrivni_dodatki
from . import webtor
from core import shramba_json

_log_media = logging.getLogger("safeer.usenet_filter.predvajanje")

AUDIO = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma"}
VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpeg", ".mpg", ".ts", ".m3u8"}
IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MEDIA_EXT = AUDIO | VIDEO | IMAGES
MAX_FILES = 500
#: ID posnetka YouTube (11 znakov).
YOUTUBE_ID_VZOREC = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_SOURCE_ITEMS = 1500
#: Seznam kanalov IPTV ima lahko vec vnosov kot splosen vir (iptv-org »languages/eng«: 3004 kanalov 25. 10. 2026);
#: prej je meja 1500 odrezala pol seznama po abecedi.
MAX_KANALOV_SEZNAMA = 5000
MAX_DOWNLOAD = 6 * 1024 * 1024
TRACKING_QUERY = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
TMDB_API_KEY = os.environ.get("SAFEER_TMDB_API_KEY", "844dba0bfd8f3a4f3799f6130ef9e335")
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"

# Uradne strani storitev; razsiritev preslikave ostane na enem mestu.
WATCH_PROVIDER_SEARCH = {
    "netflix": "https://www.netflix.com/search?q=",
    "hbo max": "https://www.max.com/search?q=",
    "max": "https://www.max.com/search?q=",
    "skyshowtime": "https://www.skyshowtime.com/search?q=",
    "disney plus": "https://www.disneyplus.com/search?query=",
    "disney+": "https://www.disneyplus.com/search?query=",
    "apple tv": "https://tv.apple.com/search?term=",
    "apple tv store": "https://tv.apple.com/search?term=",
    "rakuten tv": "https://rakuten.tv/search?q=",
    "amazon prime video": "https://www.primevideo.com/search?phrase=",
    "prime video": "https://www.primevideo.com/search?phrase=",
    "amazon video": "https://www.primevideo.com/search?phrase=",
    "voyo": "https://voyo.si/iskanje?q=",
    # Brezplacne storitve z oglasi: odpremo njihovo stran/aplikacijo (toka ne prevzemamo).
    "plex": "https://watch.plex.tv/search?q=",
    "plex channel": "https://watch.plex.tv/search?q=",
    "filmtap": "https://www.filmtap.com/search?q=",
    "arte": "https://www.arte.tv/de/search/?q=",
    "rakuten tv free": "https://www.rakuten.tv/search?q=",
}


def canonical_url(url: str) -> str:
    """Stabilna identiteta vira; sledilni parametri in fragment niso del nje."""
    value = str(url or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("Vir mora biti veljaven naslov HTTP ali HTTPS brez prijavnih podatkov.")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = host if not port or (scheme, port) in (("http", 80), ("https", 443)) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY:
            query.append((key, value))
    return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(sorted(query)), ""))


def _drzava_radia(koda: Any) -> str:
    """Koda drzave za radio (ISO 3166-1 alpha-2) ali "" - nic drugega ne pride do kljuca ali do Radio Browserja."""
    koda = str(koda or "").strip().upper()
    return koda if re.fullmatch(r"[A-Z]{2}", koda) else ""


def _text(value: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _dpapi_protect(secret: str) -> str:
    """Zaščiti poverilnico z Windows DPAPI, vezanim na trenutnega uporabnika."""
    if os.name != "nt":
        raise RuntimeError("Varno shranjevanje medijskih poverilnic zahteva Windows DPAPI.")
    import base64
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    raw = secret.encode("utf-8")
    source_buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(source_buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob),
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
    ok = crypt32.CryptProtectData(ctypes.byref(source), "SafeerOS Media", None, None, None, 0, ctypes.byref(target))
    if not ok:
        raise OSError("Windows DPAPI zaščita ni uspela.")
    try:
        return "dpapi:" + base64.b64encode(ctypes.string_at(target.pbData, target.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def _dpapi_unprotect(value: str) -> str:
    if os.name != "nt" or not value.startswith("dpapi:"):
        raise RuntimeError("Zaščitene poverilnice niso dostopne v tej napravi.")
    import base64
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    raw = base64.b64decode(value[6:])
    source_buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(source_buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
    ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
    if not ok:
        raise OSError("Windows DPAPI odklep poverilnice ni uspel.")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


# Datoteke, ki jih predvajalnik ne more predvajati (torrenti, arhivi, namestitveni paketi):
# takih vnosov v medijskem centru ne pokazemo, ker bi klik samo spodletel.
NEPREDVAJLJIVE_KONCNICE = (".torrent", ".nzb", ".iso", ".rar", ".zip", ".7z", ".exe", ".msi",
                           ".apk", ".dmg", ".img", ".bin")


def je_predvajljiv_naslov(url: str) -> bool:
    try:
        deli = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return False
    if deli.scheme not in ("http", "https", "file"):
        return False
    return not urllib.parse.unquote(deli.path).lower().endswith(NEPREDVAJLJIVE_KONCNICE)


def _absolute(base: str, value: Any) -> str:
    data_url = str(value or "").strip()
    if (len(data_url) <= 2 * 1024 * 1024
            and re.fullmatch(r"data:image/(?:jpeg|png|gif|webp);base64,[A-Za-z0-9+/]*={0,2}", data_url)):
        return data_url
    raw = _text(value, 4096)
    if not raw:
        return ""
    url = urllib.parse.urljoin(base, raw)
    return url if urllib.parse.urlsplit(url).scheme in ("http", "https", "file") else ""


_VDELANI_PREDVAJALNIKI = ("w.soundcloud.com", "bandcamp.com")
_ZVOCNE_VRSTE = ("audio/", "application/ogg", "application/x-ogg")


def je_neposredni_zvok(url: str, odpri=urllib.request.urlopen, cas: float = 4.0) -> bool:
    """Ali je http(s) naslov res zvočni tok (Jamendo, Icecast radio), ne spletna stran ali vdelava.

    Končnica .mp3/.ogg ... zadostuje. Brez nje vprašamo strežnik le za glavo (Range 0-0, telo se
    ne bere): Content-Type audio/* ali ogg pomeni tok. Uradne vdelave (SoundCloud, Bandcamp) in
    spletne strani (text/html) ostanejo strani - nikoli jih ne predstavljamo kot neposredni tok."""
    parsed = urllib.parse.urlsplit(url or "")
    if parsed.scheme not in ("http", "https"):
        return False
    host, pot = (parsed.hostname or "").casefold(), parsed.path.casefold()
    if any(host == h or host.endswith("." + h) for h in _VDELANI_PREDVAJALNIKI) or "/embed" in pot:
        return False
    if pot.endswith((".m3u8", ".mpd")):
        return False
    if Path(pot).suffix in AUDIO:
        return True
    try:
        zahteva = urllib.request.Request(url, headers={"User-Agent": "SafeerOS/1.0", "Range": "bytes=0-0",
                                                       "Icy-MetaData": "0"})
        with odpri(zahteva, timeout=cas) as odgovor:
            vrsta = str(odgovor.headers.get("Content-Type") or "").split(";")[0].strip().casefold()
    except Exception:  # noqa: BLE001
        return False
    return vrsta.startswith(_ZVOCNE_VRSTE)


def _official_music_embed(url: str, source_id: str, source_name: str) -> tuple[list[dict] | None, str]:
    """Prepozna samo SoundCloud in Bandcamp uradne vdelave; nikoli ne bere njihovih strani."""
    parsed = urllib.parse.urlsplit(url)
    host, path = (parsed.hostname or "").casefold(), parsed.path
    if host in ("soundcloud.com", "www.soundcloud.com"):
        encoded = urllib.parse.urlencode({"url": url, "auto_play": "false"})
        embed_url = "https://w.soundcloud.com/player/?" + encoded
    elif host == "w.soundcloud.com" and path.rstrip("/") == "/player":
        embed_url = url
    elif host == "bandcamp.com" and path.casefold().startswith("/embeddedplayer/"):
        embed_url = url
    elif host == "bandcamp.com" or host.endswith(".bandcamp.com"):
        return None, "Vnesi javni uradni Bandcamp EmbeddedPlayer naslov; strani ne beremo."
    else:
        return None, ""
    path_name = path.rstrip("/").split("/")[-1]
    title = source_name or urllib.parse.unquote(path_name).replace("-", " ") or host
    item = _item(title, embed_url, base=embed_url, source_id=source_id,
                 source_name="SoundCloud" if "soundcloud.com" in host else "Bandcamp",
                 kind="glasba", description="Uradni vdelani predvajalnik javne vsebine.")
    return ([item] if item else []), ""


def _kind(value: Any, url: str = "", title: str = "", season: int = 0, episode: int = 0) -> str:
    if season > 0 or episode > 0:
        return "serija"
    hint = f"{value or ''} {url} {title}".lower()
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if any(x in hint for x in ("podcast", "podkasta", "podcasti")):
        return "podcast"
    if any(x in hint for x in ("radio", "radijska", "radiostream", "icecast", "shoutcast")):
        return "radio"
    if (any(x in hint for x in ("live tv", "livetv", "live television", "televizija v živo", "/live/", "iptv"))
            or re.search(r"\btv\b", str(value or "").casefold())):
        return "tv-v-zivo"
    if ext in AUDIO or any(x in hint for x in ("audio", "music", "song", "track", "album", "glasba", "/music/")):
        return "glasba"
    if ext in IMAGES or any(x in hint for x in ("image", "slika", "photo", "fotografija")):
        return "slika"
    # Serija samo po besedi za serijo, sezono ali epizodo ali po poti /tv/, /series/ (lastnik, 25. 10. 2026: podniz »tv«
    # v imenu kanala - »Exodus TV« - ali v naslovu toka je kanale v zivo poslal v Serije).
    if (re.search(r"\b(?:series|episodes?|seasons?|serija|serije|epizod[ae]?|sezon[ae]?|tv[ -]?shows?)\b", hint)
            or any(x in hint for x in ("/tv/", "/series/"))):
        return "serija"
    return "film"


def _resolution(value: Any, *hints: str) -> int:
    joined = " ".join([_text(value)] + [_text(x) for x in hints]).lower()
    if "8k" in joined or "4320" in joined:
        return 4320
    if "4k" in joined or "2160" in joined or "uhd" in joined:
        return 2160
    matches = [int(x) for x in re.findall(r"(?<!\d)(360|480|576|720|1080|1440|2160|4320)p?", joined)]
    if matches:
        return max(matches)
    if re.search(r"\b(fhd|full[ -]?hd|auto|adaptive)\b", joined):
        return 1080
    if re.search(r"\bhd\b", joined):
        return 720
    if re.search(r"\bsd\b", joined):
        return 480
    return 0


def _quality_label(resolution: int) -> str:
    if resolution >= 2160:
        return "4K"
    if resolution >= 1080:
        return "1080p"
    if resolution >= 720:
        return "720p"
    return f"{resolution}p" if resolution else "Samodejno"


# Safeer nima vgrajenega kataloga komercialnih filmov in serij: naslove, plakate in ID-je da samo TMDb
# (metapodatki in uradni "Kje gledati") ali uporabnikov lasten vir. Prazna slovarja ostaneta zaradi
# zdruzljivosti klicev.
KNOWN_IMDB: dict = {}

ID_PAIRS: list = []
IMDB_TO_TMDB = dict(ID_PAIRS)
TMDB_TO_IMDB = {tmdb: imdb for imdb, tmdb in ID_PAIRS}

# TMDb aliasi omogočajo enako obogatitev za oba standardna identifikatorja.
for _imdb_k, _tmdb_k in ID_PAIRS:
    if _imdb_k in KNOWN_IMDB:
        KNOWN_IMDB[_tmdb_k] = KNOWN_IMDB[_imdb_k]


def _imdb_id(value: Any) -> str:
    """Vrne kanonični IMDb ID (tt + številke) ali prazen niz."""
    text = _text(value, 300).lower()
    match = re.search(r"(?<![a-z0-9])(tt\d{5,12})(?!\d)", text)
    return match.group(1) if match else ""


def _tmdb_id(value: Any) -> int:
    """Vrne pozitiven TMDb ID; letnic in poljubnih števil v besedilu ne ugiba."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and int(value) == value:
        number = int(value)
        return number if 0 < number <= 2_147_483_647 else 0
    text = _text(value, 300).lower().strip()
    match = re.fullmatch(r"(?:tmdb(?::|://)?)?(\d{1,10})", text)
    if not match:
        match = re.search(r"(?:[?&]tmdb=|/tmdb/|themoviedb\.org/(?:movie|tv)/)(\d{1,10})(?:\D|$)", text)
    if not match:
        return 0
    number = int(match.group(1))
    return number if 0 < number <= 2_147_483_647 else 0


def _external_ids(mapping: dict, inherited: Optional[dict] = None) -> tuple[str, int]:
    """Razbere pogoste IMDb/TMDb sheme brez zamenjave internega `id` za TMDb."""
    inherited = inherited or {}
    nested = []
    for key in ("external_ids", "externalIds", "ids", "identifiers"):
        value = mapping.get(key)
        if isinstance(value, dict):
            nested.append(value)

    imdb_values = [
        _first(mapping, ("imdb_id", "imdbId", "imdbID", "imdb", "imdb_key")),
        *[_first(value, ("imdb_id", "imdbId", "imdbID", "imdb")) for value in nested],
    ]
    tmdb_values = [
        _first(mapping, ("tmdb_id", "tmdbId", "tmdbID", "tmdb", "themoviedb_id")),
        *[_first(value, ("tmdb_id", "tmdbId", "tmdbID", "tmdb")) for value in nested],
    ]

    generic_id = mapping.get("id")
    imdb = next((found for found in (_imdb_id(value) for value in imdb_values) if found), "")
    if not imdb:
        imdb = _imdb_id(generic_id)
    tmdb = next((found for found in (_tmdb_id(value) for value in tmdb_values) if found), 0)
    # TMDb-jevi rezultati uporabljajo numerični `id` skupaj z značilnimi polji.
    looks_like_tmdb = any(key in mapping for key in (
        "media_type", "original_title", "original_name", "poster_path",
        "backdrop_path", "vote_average", "first_air_date", "release_date",
    ))
    if not tmdb and looks_like_tmdb:
        tmdb = _tmdb_id(generic_id)

    imdb = imdb or _imdb_id(inherited.get("imdb_id"))
    tmdb = tmdb or _tmdb_id(inherited.get("tmdb_id"))
    if imdb and not tmdb:
        tmdb = _tmdb_id(IMDB_TO_TMDB.get(imdb))
    if tmdb and not imdb:
        imdb = TMDB_TO_IMDB.get(str(tmdb), "")
    return imdb, tmdb


def _source_context(url: str) -> dict:
    """Iz identitete dokumentiranega API-endpointa razbere naslovni ID in epizodo."""
    parsed = urllib.parse.urlsplit(url or "")
    query = dict(urllib.parse.parse_qsl(parsed.query))
    context: dict[str, Any] = {}
    match = re.search(
        r"/(?:api/streams/(?:[^/]+/)?|embed/)?(movie|series|tv)/((?:tt)?\d+)(?:/|$)",
        parsed.path,
        re.IGNORECASE,
    )
    raw_id = match.group(2) if match else (query.get("tmdb") or query.get("imdb") or "")
    imdb, tmdb = _imdb_id(raw_id), _tmdb_id(raw_id)
    if imdb and not tmdb:
        tmdb = _tmdb_id(IMDB_TO_TMDB.get(imdb))
    if tmdb and not imdb:
        imdb = TMDB_TO_IMDB.get(str(tmdb), "")
    if imdb:
        context["imdb_id"] = imdb
    if tmdb:
        context["tmdb_id"] = tmdb
    if match:
        context["kind"] = "serija" if match.group(1).lower() in ("series", "tv") else "film"
    for source_key, target_key in (("season", "season"), ("episode", "episode"), ("s", "season"), ("e", "episode")):
        if str(query.get(source_key) or "").isdigit():
            context[target_key] = int(query[source_key])
    return context


def _safe_headers(value: Any) -> dict[str, str]:
    """Ohrani kratke enovrstične HTTP glave, ki jih vrne uporabnikov API."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for name, raw in list(value.items())[:20]:
        key = _text(name, 80)
        text = _text(raw, 2048)
        if key and text and "\n" not in key + text and "\r" not in key + text:
            result[key] = text
    return result


def _item(title: Any, url: Any, *, base: str, source_id: str, source_name: str,
          kind: Any = "", year: Any = 0, image: Any = "", artist: Any = "",
          quality: Any = "", resolution: Any = 0, bitrate: Any = 0,
          season: Any = 0, episode: Any = 0, description: Any = "",
          headers: Any = None, referer: Any = "", imdb_id: Any = "",
          tmdb_id: Any = 0) -> Optional[dict]:
    media_url = _absolute(base, url)
    clean_title = _text(title, 200)
    if not media_url or not clean_title or not je_predvajljiv_naslov(media_url):
        return None
    try:
        year_int = int(year or 0)
    except (TypeError, ValueError):
        match = re.search(r"\b(19\d{2}|20\d{2})\b", f"{year or ''} {clean_title}")
        year_int = int(match.group(1)) if match else 0
    try:
        bitrate_int = int(float(bitrate or 0))
    except (TypeError, ValueError):
        bitrate_int = 0

    season_int = int(season or 0) if str(season or "").isdigit() else 0
    episode_int = int(episode or 0) if str(episode or "").isdigit() else 0

    # Samodejno prepoznavanje sezone in epizode iz URL-ja ali naslova
    if season_int == 0 and episode_int == 0:
        match_tv = re.search(r"/(?:tv|series|embed/tv)/[^/]+(?:/(\d+)/(\d+))?", media_url)
        if match_tv and match_tv.group(1) and match_tv.group(2):
            season_int = int(match_tv.group(1))
            episode_int = int(match_tv.group(2))
        else:
            match_se = re.search(r"\b[sS](\d+)[eE](\d+)\b", clean_title + " " + media_url)
            if match_se:
                season_int = int(match_se.group(1))
                episode_int = int(match_se.group(2))
            else:
                match_x = re.search(r"\b(\d+)x(\d+)\b", clean_title + " " + media_url)
                if match_x:
                    season_int = int(match_x.group(1))
                    episode_int = int(match_x.group(2))

    normalized_imdb = _imdb_id(imdb_id) or _imdb_id(clean_title + " " + media_url)
    normalized_tmdb = _tmdb_id(tmdb_id)
    if not normalized_tmdb:
        known_numeric = re.search(r"/(?:movie|tv|series|embed/movie|embed/tv)/(\d{1,10})(?:/|\?|$)", media_url)
        if known_numeric and known_numeric.group(1) in KNOWN_IMDB:
            normalized_tmdb = int(known_numeric.group(1))
    if normalized_imdb and not normalized_tmdb:
        normalized_tmdb = _tmdb_id(IMDB_TO_TMDB.get(normalized_imdb))
    if normalized_tmdb and not normalized_imdb:
        normalized_imdb = TMDB_TO_IMDB.get(str(normalized_tmdb), "")

    # Obogatitev z majhno lokalno zbirko deluje za oba standardna ID-ja.
    lookup_id = normalized_imdb or (str(normalized_tmdb) if normalized_tmdb else "")
    if lookup_id in KNOWN_IMDB:
        k_info = KNOWN_IMDB[lookup_id]
        is_generic = (
            clean_title.lower().startswith("tt") or
            clean_title.isdigit() or
            clean_title == source_name or
            clean_title.lower() in ("film", "serija", "vir", "vsebina", "vdelani video", "vdelana vsebina")
        )
        if is_generic:
            if season_int > 0 and episode_int > 0:
                ep_name = ""
                for s, e, n in k_info.get("episodes", []):
                    if s == season_int and e == episode_int:
                        ep_name = f" - {n}"
                        break
                clean_title = f"{k_info.get('title', clean_title)} S{season_int:02d}E{episode_int:02d}{ep_name}"
            else:
                clean_title = k_info.get("title", clean_title)
        if not image and k_info.get("image"):
            image = k_info["image"]
        if not year_int and k_info.get("year"):
            year_int = k_info["year"]
        if not description and k_info.get("description"):
            description = k_info["description"]
        if not kind and k_info.get("kind"):
            kind = k_info["kind"]

    # Izboljšava naslova za IMDb ID-je ali generic vnose, če ni v KNOWN_IMDB
    if clean_title.lower().startswith("tt") and clean_title[2:].isdigit():
        if season_int > 0 and episode_int > 0:
            clean_title = f"{source_name or 'Serija'} S{season_int:02d}E{episode_int:02d} ({clean_title})"
        else:
            clean_title = f"{source_name or 'Film'} ({clean_title})"
    elif clean_title.lower() in ("film", "vir", "vsebina") and (season_int > 0 or episode_int > 0):
        clean_title = f"{source_name or 'Serija'} S{max(1, season_int):02d}E{max(1, episode_int):02d}"

    res = _resolution(resolution, quality, media_url, clean_title)
    safe_headers = _safe_headers(headers)
    header_referer = next((value for key, value in safe_headers.items()
                           if key.casefold() in ("referer", "referrer")), "")
    result = {
        "naslov": clean_title,
        "url": media_url,
        "vrsta": _kind(kind, media_url, clean_title, season_int, episode_int),
        "leto": year_int if 1900 <= year_int <= 2200 else 0,
        "slika": _absolute(base, image),
        "izvajalec": _text(artist, 160),
        "locljivost": res,
        "kakovost": _quality_label(res),
        "bitrate": max(0, bitrate_int),
        "sezona": season_int,
        "epizoda": episode_int,
        "opis": _text(description, 500),
        "vir_id": source_id,
        "vir": source_name,
        "glave": safe_headers,
        "referer": _text(referer, 2048) or header_referer,
        "imdb_id": normalized_imdb,
        "tmdb_id": normalized_tmdb,
    }
    return result


def _dvd_item(path: Path) -> Optional[dict]:
    """Vnos knjižnice za DVD brez zaščite: slika ISO z VIDEO_TS ali mapa diska (core/os_dvd.py).

    Naslov je ``dvd:///C:/...`` za LibVLC. _item sprejme le naslove http(s)/file in zavrne .iso (spletni viri
    ga ne smejo ponujati kot medij), zato vnos zgradimo na mapi diska in naslov nato zamenjamo."""
    from . import os_dvd
    try:
        if not os_dvd.je_dvd(str(path)):
            return None
        naslov = os_dvd.uri(str(path))
        modified = int(path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    found = _item(os_dvd.naslov(str(path)), path.parent.as_uri() + "/", base=path.parent.as_uri() + "/",
                  source_id="lokalno", source_name="Ta računalnik", kind="film", description=str(path))
    if not found:
        return None
    found.update({"url": naslov, "pot": str(path), "cas": modified, "mime": "", "dvd": True,
                  "album": "", "skupina": ""})
    return found


def _first(mapping: dict, names: Iterable[str]) -> Any:
    for name in names:
        if mapping.get(name) not in (None, "", []):
            return mapping[name]
    return ""


def _items_from_json(data: Any, base: str, source_id: str, source_name: str,
                     inherited: Optional[dict] = None) -> list[dict]:
    """Razbere običajne kataloge in tudi sezname različic znotraj enega vnosa."""
    out: list[dict] = []
    inherited = dict(inherited or {})
    if not inherited:
        inherited.update(_source_context(base))
    if isinstance(data, list):
        for value in data[:MAX_SOURCE_ITEMS]:
            out.extend(_items_from_json(value, base, source_id, source_name, inherited))
        return out
    if not isinstance(data, dict):
        return out

    title = _first(data, ("title", "name", "naslov", "label", "original_title", "original_name")) or inherited.get("title", "")
    imdb_id, tmdb_id = _external_ids(data, inherited)
    image = _first(data, ("image", "poster", "poster_url", "thumbnail", "artwork", "poster_path")) or inherited.get("image", "")
    if isinstance(image, str) and image.startswith("/") and "poster_path" in data:
        image = "https://image.tmdb.org/t/p/w500" + image
    context = {
        "title": title,
        "kind": _first(data, ("type", "kind", "media_type", "vrsta", "category")) or inherited.get("kind", ""),
        "year": _first(data, ("year", "release_year", "datePublished", "release_date", "first_air_date")) or inherited.get("year", 0),
        "image": image,
        "artist": _first(data, ("artist", "author", "creator", "albumArtist")) or inherited.get("artist", ""),
        "season": _first(data, ("season", "season_number")) or inherited.get("season", 0),
        "episode": _first(data, ("episode", "episode_number")) or inherited.get("episode", 0),
        "description": _first(data, ("description", "overview", "summary")) or inherited.get("description", ""),
        "headers": _first(data, ("headers", "http_headers", "request_headers")) or inherited.get("headers", {}),
        "referer": _first(data, ("referer", "referrer", "origin")) or inherited.get("referer", ""),
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
    }
    url = _first(data, ("stream_url", "playback_url", "media_url", "file", "src", "url", "contentUrl"))
    if title and url and not isinstance(url, (dict, list)):
        found = _item(title, url, base=base, source_id=source_id, source_name=source_name,
                      kind=context["kind"], year=context["year"], image=context["image"],
                      artist=context["artist"], season=context["season"], episode=context["episode"],
                      description=context["description"],
                      headers=context["headers"], referer=context["referer"],
                      imdb_id=context["imdb_id"], tmdb_id=context["tmdb_id"],
                      quality=_first(data, ("quality", "label", "resolution_name")),
                      resolution=_first(data, ("resolution", "height")),
                      bitrate=_first(data, ("bitrate", "bandwidth")))
        if found:
            out.append(found)

    for key, value in data.items():
        if key in ("image", "poster", "poster_url", "thumbnail", "artwork", "images"):
            continue
        if isinstance(value, (dict, list)):
            out.extend(_items_from_json(value, base, source_id, source_name, context))
        if len(out) >= MAX_SOURCE_ITEMS:
            break
    return out[:MAX_SOURCE_ITEMS]



NA_STRAN = 24  # kartic na stran v Medijskem centru

class _MediaHTMLParser(HTMLParser):
    def __init__(self, base: str, source_id: str, source_name: str):
        super().__init__(convert_charrefs=True)
        self.base, self.source_id, self.source_name = base, source_id, source_name
        self.title = ""
        self.in_title = False
        self.script_type = ""
        self.script_parts: list[str] = []
        self.items: list[dict] = []
        self.meta: dict[str, str] = {}
        self.current_a: Optional[dict] = None
        self.current_a_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        values = {k.lower(): v or "" for k, v in attrs}
        if tag == "title":
            self.in_title = True
        if tag == "script" and values.get("type", "").lower() in ("application/ld+json", "application/json"):
            self.script_type = values["type"].lower()
            self.script_parts = []
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key:
                self.meta[key] = values.get("content", "")
        if tag in ("video", "audio", "source") and values.get("src"):
            title = values.get("title") or values.get("aria-label") or self.meta.get("og:title") or self.title or self.source_name
            found = _item(title, values["src"], base=self.base, source_id=self.source_id,
                          source_name=self.source_name, kind=tag, image=values.get("poster", ""),
                          quality=values.get("data-quality", ""), resolution=values.get("height", 0))
            if found:
                self.items.append(found)
        if tag == "iframe" and values.get("src"):
            src = values["src"]
            if any(x in src.lower() for x in ("embed", "player", "youtube", "vimeo", "dailymotion", "stream")) or Path(urllib.parse.urlsplit(src).path).suffix.lower() in MEDIA_EXT:
                title = values.get("title") or values.get("aria-label") or self.meta.get("og:title") or self.title or self.source_name
                kind = _kind(values.get("kind"), src, title)
                poster = self.meta.get("og:image") or self.meta.get("twitter:image", "")
                found = _item(title, src, base=self.base, source_id=self.source_id,
                              source_name=self.source_name, kind=kind, image=poster)
                if found:
                    self.items.append(found)
        if tag == "a" and values.get("href"):
            self.current_a = values
            self.current_a_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.script_type:
            try:
                payload = json.loads("".join(self.script_parts))
                self.items.extend(_items_from_json(payload, self.base, self.source_id, self.source_name))
            except (ValueError, TypeError):
                pass
            self.script_type = ""
            self.script_parts = []
        if tag == "a" and self.current_a is not None:
            values = self.current_a
            inner_text = " ".join(self.current_a_text).strip()
            self.current_a = None
            self.current_a_text = []
            href = values.get("href", "")
            path = urllib.parse.urlsplit(href).path.lower()
            is_media = (
                Path(path).suffix in MEDIA_EXT or
                "/embed/" in href.lower() or
                any(x in href.lower() for x in ("watch", "stream", "video", "movie", "tv", "series", "epizoda", "sezona"))
            )
            if is_media:
                title = inner_text or values.get("title") or values.get("aria-label") or Path(path).stem
                found = _item(title, href, base=self.base, source_id=self.source_id,
                              source_name=self.source_name)
                if found:
                    self.items.append(found)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title = _text(self.title + " " + data, 200)
        if self.script_type:
            self.script_parts.append(data)
        if self.current_a is not None:
            self.current_a_text.append(data)

    def finish(self) -> list[dict]:
        og_type = self.meta.get("og:type", "").lower()
        for media_key, default_kind in (("og:video", "film"), ("og:video:url", "film"),
                                        ("og:audio", "glasba"), ("og:audio:url", "glasba")):
            if self.meta.get(media_key):
                kind = default_kind
                if "video" in media_key:
                    if any(x in og_type for x in ("tv", "episode", "series")):
                        kind = "serija"
                    elif "movie" in og_type:
                        kind = "film"
                found = _item(self.meta.get("og:title") or self.title or self.source_name,
                              self.meta[media_key], base=self.base, source_id=self.source_id,
                              source_name=self.source_name, kind=kind,
                              image=self.meta.get("og:image") or self.meta.get("twitter:image", ""),
                              description=self.meta.get("og:description") or self.meta.get("description", ""))
                if found:
                    self.items.append(found)
        return self.items[:MAX_SOURCE_ITEMS]


def _embed_url_for_provider(netloc: str, scheme: str, imdb_id: str,
                            tmdb_id: str, media_type: str,
                            season: int = 0, episode: int = 0) -> str:
    """Safeer ne sestavlja naslovov predvajalnikov neuradnih ponudnikov iz IMDb/TMDb ID-jev."""
    return ""


# Neuradni agregatorji filmov niso podprti (samo uradne vdelave: YouTube, Vimeo, PeerTube ...).
_EMBED_DOMAINS: tuple = ()

_PREDLOGA_TOKEN = re.compile(r"\{\s*(tmdb_?id|imdb_?id|season|episode|sezona|epizoda)\s*\}", re.I)


def _je_predloga_predvajalnika(url: str) -> bool:
    """Predloga z ID-jem je ponudnik predvajanja, ne medijska vsebina."""
    parsed = urllib.parse.urlsplit(url)
    return any(domain in parsed.netloc.lower() for domain in _EMBED_DOMAINS) and bool(_PREDLOGA_TOKEN.search(url))


def _je_korenski_predvajalni_vir(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (any(domain in parsed.netloc.lower() for domain in _EMBED_DOMAINS)
            and (not parsed.path or parsed.path in ("/", "/index.html", "/v2", "/v2/")))


def _je_predvajalni_vir(url: str) -> bool:
    return _je_predloga_predvajalnika(url) or _je_korenski_predvajalni_vir(url)


#: Imena parametrov poizvedbe in poti Xtream, ki nosijo uporabnika, geslo ali kljuc (pregled Grok 98, K3).
_PARAMETRI_POVERILNIC = frozenset({"username", "user", "usr", "login", "password", "pass", "passwd", "pwd",
                                   "token", "key", "apikey", "api_key", "auth", "mac"})
_POTI_S_POVERILNICAMI = frozenset({"live", "movie", "series", "timeshift"})


def _ima_poverilnice(url: object) -> bool:
    """Naslov nosi uporabnika, geslo ali kljuc (userinfo, parameter poizvedbe ali pot Xtream /live/<u>/<g>/...). Ob
    dvomu (naslova ni mogoce razcleniti) True - fail-closed."""
    besedilo = str(url or "")
    try:
        deli = urllib.parse.urlsplit(besedilo)
        if deli.username or deli.password:
            return True
        imena = {ime.casefold() for ime, _ in urllib.parse.parse_qsl(deli.query, keep_blank_values=True)}
    except ValueError:
        return True
    if imena & _PARAMETRI_POVERILNIC:
        return True
    pot = [d for d in deli.path.split("/") if d]
    return len(pot) >= 3 and pot[0].casefold() in _POTI_S_POVERILNICAMI


def _kljuc_racuna(url: object) -> tuple:
    """(gostitelj brez vrat, odtis uporabnika ali None) za zaklep socasnih osvezitev istega racuna (pregled Grok 98,
    K2). Uporabnik iz userinfo, parametra poizvedbe ali poti Xtream; v pomnilniku samo odtis, nikoli uporabnik ali
    geslo. None = uporabnika ni mogoce prebrati - tak klic caka na VSE osvezitve istega gostitelja (nikoli dve prijavi)."""
    besedilo = str(url or "")
    try:
        deli = urllib.parse.urlsplit(besedilo)
        gostitelj = (deli.hostname or "").casefold().rstrip(".") or "?"
        uporabnik = deli.username or ""
        if not uporabnik:
            poizvedba = {k.casefold(): v for k, v in urllib.parse.parse_qsl(deli.query, keep_blank_values=True)}
            uporabnik = next((poizvedba[k] for k in ("username", "user", "usr", "login") if poizvedba.get(k)), "")
        if not uporabnik:
            pot = [d for d in deli.path.split("/") if d]
            if len(pot) >= 3 and pot[0].casefold() in _POTI_S_POVERILNICAMI:
                uporabnik = pot[1]
    except ValueError:
        return ("?", None)
    odtis = hashlib.sha256(uporabnik.encode("utf-8", "surrogateescape")).hexdigest()[:16] if uporabnik else None
    return (gostitelj, odtis)


#: Platforme, ki jih Medijski center bere samo prek uradnih vdelav (_official_music_embed, _resolve_embed_or_direct_source):
#: nobena nima racuna pri ponudniku IPTV, zato zanje ne velja pravilo »neznano je racun« (MediaCenter._racun_vira).
_PLATFORME_BREZ_RACUNA = ("youtube.com", "youtu.be", "soundcloud.com", "bandcamp.com")


def _platforma_brez_racuna(url: object) -> bool:
    """Znana platforma brez racuna ali predvajalni vir - NIKOLI, ce naslov nosi poverilnice (pregled Grok 98, K3, iz
    Windows 26. 10. 2026: panel IPTV, ki ga ujame vzorec predvajalnega vira, bi sicer izklopil premor in prepoved
    rezervne zahteve z geslom)."""
    besedilo = str(url or "")
    if _ima_poverilnice(besedilo):
        return False
    try:
        gostitelj = (urllib.parse.urlsplit(besedilo).hostname or "").casefold()
    except ValueError:
        return False
    return (any(gostitelj == d or gostitelj.endswith("." + d) for d in _PLATFORME_BREZ_RACUNA)
            or _je_predvajalni_vir(besedilo))


def _je_neposredni_medijski_tok(url: str) -> bool:
    """Prepozna neposreden medijski URL, ki ga ne smemo prenesti kot katalog."""
    path = urllib.parse.urlsplit(url).path.lower()
    return Path(path).suffix in MEDIA_EXT or path.endswith((".m3u8", ".mpd", ".ts"))


def _izpolni_predlogo(url: str, imdb_id: str, tmdb_id: str,
                      season: int = 0, episode: int = 0) -> str:
    vrednosti = {
        "tmdbid": tmdb_id, "tmdb_id": tmdb_id,
        "imdbid": imdb_id, "imdb_id": imdb_id,
        "season": str(season or 1), "sezona": str(season or 1),
        "episode": str(episode or 1), "epizoda": str(episode or 1),
    }

    def zamenjaj(match: re.Match) -> str:
        return vrednosti.get(match.group(1).replace(" ", "").lower(), "")

    return _PREDLOGA_TOKEN.sub(zamenjaj, url)


def _katalog_iz_predloge(url: str, source_id: str, source_name: str) -> list[dict]:
    """Zgradi začetni katalog z resničnimi ID-ji za prepoznano predlogo."""
    series_template = bool(re.search(r"/(?:tv|series|embed/tv)/", url, re.I))
    items: list[dict] = []
    for imdb_id, meta in KNOWN_IMDB.items():
        if not imdb_id.startswith("tt"):
            continue
        tmdb_id = IMDB_TO_TMDB.get(imdb_id, "")
        if not tmdb_id:
            continue
        if series_template and meta.get("kind") != "serija":
            continue
        if not series_template and meta.get("kind") != "film":
            continue
        # Glavni katalog vsebuje eno kartico na serijo. Sezone in epizode se
        # naložijo šele v podrobnostih, zato se naslovi in plakati ne podvajajo.
        season, episode = (1, 1) if series_template else (0, 0)
        play_url = _izpolni_predlogo(url, imdb_id, tmdb_id, season, episode)
        item = _item(meta.get("title", "Vsebina"), play_url, base=play_url, source_id=source_id,
                     source_name=source_name, kind="serija" if series_template else "film",
                     year=meta.get("year", 0), image=meta.get("image", ""),
                     description=meta.get("description", ""), imdb_id=imdb_id, tmdb_id=int(tmdb_id))
        if item:
            if series_template:
                item["sezona"], item["epizoda"] = 0, 0
            items.append(item)
    return items


def _resolve_embed_or_direct_source(url: str, source_id: str, source_name: str) -> list[dict]:
    """Neposreden tok, uradna vdelava (YouTube) ali splosna vdelana stran uporabnikovega vira."""
    if _je_predloga_predvajalnika(url):
        return _katalog_iz_predloge(url, source_id, source_name)
    parsed = urllib.parse.urlsplit(url)
    netloc = parsed.netloc.lower()
    path = parsed.path

    if _je_neposredni_medijski_tok(url):
        kind = _kind("", url, source_name)
        item = _item(source_name or "Medijski tok", url, base=url,
                     source_id=source_id, source_name=source_name or netloc,
                     kind=kind, quality="adaptive" if path.lower().endswith((".m3u8", ".mpd")) else "")
        return [item] if item else []

    # YouTube Music je spletna aplikacija, ne javni katalog JSON. V Safeer Media
    # jo odpremo kot notranji glasbeni vir; posamezne povezave do videa pa
    # pretvorimo v embed, da ostanejo znotraj našega predvajalnika.
    # Ime gostitelja, ne podniz: "youtube.com.zlobni.si" ali "neyoutube.com" ni YouTube (pregled 4. 11. 2026).
    gostitelj = (parsed.hostname or "").lower().rstrip(".")
    je_youtube = gostitelj == "youtube.com" or gostitelj.endswith(".youtube.com")
    if je_youtube or gostitelj == "youtu.be":
        video_id = ""
        if gostitelj == "youtu.be":
            video_id = path.strip("/").split("/", 1)[0]
        else:
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            if not video_id:
                match = re.search(r"/(?:embed|shorts)/([^/?#]+)", path, re.I)
                video_id = match.group(1) if match else ""
        if video_id:
            video_id = re.sub(r"[^A-Za-z0-9_-]", "", video_id)[:32]
            embed = f"https://www.youtube.com/embed/{video_id}?autoplay=1&playsinline=1"
            image = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            item = _item(source_name or "YouTube Music", embed, base=embed,
                         source_id=source_id, source_name=source_name or "YouTube Music",
                         kind="glasba", image=image)
            return [item] if item else []
        if gostitelj == "music.youtube.com":
            item = _item("YouTube Music · brskanje", url, base=url,
                         source_id=source_id, source_name=source_name or "YouTube Music",
                         kind="glasba", description="Izberi glasbo v vgrajeni aplikaciji Safeer Media.")
            return [item] if item else []
    # Splošen neposredni tok ali vdelana stran
    kind = _kind("", url, source_name)
    title = source_name if source_name and source_name != parsed.netloc else (parsed.netloc or "Vdelana vsebina")
    it = _item(title, url, base=url, source_id=source_id, source_name=source_name, kind=kind)
    return [it] if it else []


def _parse_m3u(text: str, base: str, source_id: str, source_name: str, stevci: Optional[dict] = None) -> list[dict]:
    # HLS manifest je en prilagodljiv tok, ne katalog segmentov. LibVLC sam izbere
    # najboljšo različico glede na povezavo in zmogljivost naprave.
    if "#EXT-X-TARGETDURATION" in text or "#EXT-X-STREAM-INF" in text:
        found = _item(source_name, base, base=base, source_id=source_id,
                      source_name=source_name, kind=_kind("", base, source_name), quality="adaptive")
        return [found] if found else []
    # Seznam vnosov (#EXTINF): ime je za vejico ZUNAJ narekovajev, atributi so vsi pred njo (core/kanali_iptv.py).
    # Lastnik, 25. 10. 2026: razrez pri prvi vejici je iz http-user-agent »(KHTML, like Gecko)« naredil naslov in
    # izgubil group-title in tvg-logo; kanali so pristali v Serijah.
    drzava_seznama, jezik_seznama = kanali_iptv.iz_naslova_seznama(base)
    stevci = stevci if stevci is not None else {}
    out: list[dict] = []
    extinf, vlc, skupina = None, {}, ""
    # Samo CR/LF locita vrstici: str.splitlines deli tudi na U+2028, U+0085, \x0b ... v imenu kanala - drugi del je
    # postal lazen naslov, pravi naslov pa vnos brez atributov (pregled 30, J7).
    for raw in re.split(r"\r\n|\r|\n", text):
        line = raw.strip()
        if not line:
            continue
        glava = line[:12].upper()
        if glava.startswith("#EXTINF:"):
            extinf, vlc, skupina = kanali_iptv.razcleni_extinf(line), {}, ""
            continue
        if glava.startswith("#EXTVLCOPT:"):
            ime_opcije, _, vrednost = line[11:].partition("=")
            vlc[ime_opcije.strip().lower()] = vrednost.strip()
            continue
        if glava.startswith("#EXTGRP:"):
            skupina = line[8:].strip()
            continue
        if line.startswith("#"):
            continue
        trajanje, atributi, ime = extinf if extinf else (None, {}, "")
        extinf = None
        if skupina and "group-title" not in atributi:
            atributi = dict(atributi, **{"group-title": skupina})
        if kanali_iptv.ni_24_7(ime, atributi):
            # Lastnik, 25. 10. 2026: kanali »[Not 24/7]« se izlocijo povsod (ne prikaz, ne preverba).
            stevci["ne_24_7"] = stevci.get("ne_24_7", 0) + 1
            vlc = {}
            continue
        media_url = _absolute(base, line)
        vrsta = kanali_iptv.vrsta_vnosa(atributi, media_url or line, ime, trajanje)
        sezona, epizoda = kanali_iptv.sezona_epizoda(ime) if vrsta == "serija" else (0, 0)
        naslov = (kanali_iptv.cisto_ime(ime) if vrsta == "tv-v-zivo" else ime) \
            or Path(urllib.parse.urlsplit(line).path).stem or source_name
        odjemalec = vlc.get("http-user-agent") or atributi.get("http-user-agent", "")
        napotitelj = (vlc.get("http-referrer") or vlc.get("http-referer")
                      or atributi.get("http-referrer") or atributi.get("http-referer", ""))
        glave = {k: v for k, v in (("User-Agent", odjemalec), ("Referer", napotitelj)) if v}
        vlc = {}
        found = _item(naslov, line, base=base, source_id=source_id, source_name=source_name,
                      kind=vrsta, image=atributi.get("tvg-logo", ""),
                      quality=atributi.get("quality", "") or ime, headers=glave, referer=napotitelj,
                      season=sezona, episode=epizoda)
        if not found:
            continue
        # Vrsto je dolocil seznam (kanal, datoteka, epizoda); _kind je ugibal po besedah v imenu (»Radio Ga Ga TV«).
        found.update(vrsta=vrsta, sezona=sezona, epizoda=epizoda, iz_seznama=True)
        if vrsta == "tv-v-zivo":
            drzava, jezik = kanali_iptv.drzava_in_jezik(atributi, drzava_seznama, jezik_seznama)
            found.update(iptv=True, drzava=drzava, jezik=jezik,
                         kategorija_kanala=_text(atributi.get("group-title"), 60))
        out.append(found)
        if len(out) >= MAX_KANALOV_SEZNAMA:
            break
    return out


def _parse_pls(text: str, base: str, source_id: str, source_name: str) -> list[dict]:
    """Razčleni standardni PLS seznam radijskih tokov."""
    entries: dict[int, dict[str, str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        match = re.fullmatch(r"(File|Title|Length)(\d+)", key.strip(), re.IGNORECASE)
        if match:
            entries.setdefault(int(match.group(2)), {})[match.group(1).lower()] = value.strip()
    result = []
    for index in sorted(entries):
        row = entries[index]
        url = row.get("file", "")
        if not url:
            continue
        title = row.get("title") or Path(urllib.parse.urlsplit(url).path).stem or source_name
        item = _item(title, url, base=base, source_id=source_id, source_name=source_name,
                     kind="radio", quality=row.get("length", ""))
        if item:
            result.append(item)
        if len(result) >= MAX_SOURCE_ITEMS:
            break
    return result


def _parse_xml(text: str, base: str, source_id: str, source_name: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for entry in list(root.iter("item")) + list(root.iter("{*}entry")):
        def child(name: str) -> str:
            found = entry.find(name)
            if found is None:
                found = entry.find(f"{{*}}{name}")
            return _text(found.text if found is not None else "")
        title = child("title") or source_name
        enclosure = entry.find("enclosure")
        if enclosure is None:
            enclosure = entry.find("{*}enclosure")
        url = enclosure.get("url", "") if enclosure is not None else ""
        if not url:
            for link in entry.findall("{*}link"):
                if link.get("rel") == "enclosure":
                    url = link.get("href", "")
                    break
        itunes_image = entry.find("{*}image")
        image = itunes_image.get("href", "") if itunes_image is not None else ""
        if not image:
            media_image = entry.find("{*}thumbnail")
            image = media_image.get("url", "") if media_image is not None else ""
        hint = f"{source_name} {title} {child('category')}"
        found = _item(title, url, base=base, source_id=source_id, source_name=source_name,
                      kind=("podcast" if "podcast" in hint.casefold() else
                            enclosure.get("type", "") if enclosure is not None else ""),
                      image=image, artist=child("author") or child("creator"),
                      description=child("description") or child("summary"))
        if found:
            out.append(found)
    return out[:MAX_SOURCE_ITEMS]


def parse_payload(payload: bytes, content_type: str, source_url: str,
                  source_id: str = "vir", source_name: str = "Vir", stevci: Optional[dict] = None) -> list[dict]:
    """Razbere medijske vnose iz enega prenesenega odgovora brez izvajanja tuje kode."""
    text = payload.decode("utf-8", "replace")
    content = (content_type or "").lower()
    stripped = text.lstrip()
    if "scpls" in content or "playlist" in content and stripped.lower().startswith("[playlist]") or source_url.lower().endswith(".pls"):
        return _parse_pls(text, source_url, source_id, source_name)
    if "mpegurl" in content or source_url.lower().endswith((".m3u", ".m3u8")) or stripped.startswith("#EXTM3U"):
        if stevci is not None:
            stevci["m3u"] = True
        return _parse_m3u(text, source_url, source_id, source_name, stevci)
    if "json" in content or stripped.startswith(("{", "[")):
        try:
            return _items_from_json(json.loads(text), source_url, source_id, source_name)
        except ValueError:
            return []
    if "xml" in content or "rss" in content or stripped.startswith("<?xml"):
        return _parse_xml(text, source_url, source_id, source_name)
    parser = _MediaHTMLParser(source_url, source_id, source_name)
    try:
        parser.feed(text)
    except Exception:
        return []
    return parser.finish()


_KAKOVOST_KANALA = re.compile(r"\b(?:4k|8k|uhd|fhd|hd|sd|hevc|h26[45]|x26[45]|\d{3,4}[pi]|\d{2}fps|backup|geo[ -]?blocked)\b")
_PREDPONA_DRZAVE = re.compile(r"^\s*(?:\[([a-z]{2})\]|\(([a-z]{2})\)|([a-z]{2})\s*[:|])\s*")
_PRIPONA_DRZAVE = re.compile(r"\s*(?:\[([a-z]{2})\]|\(([a-z]{2})\))\s*$")


def ime_kanala(item: dict) -> tuple:
    """(normalizirano ime, drzava) kanala TV v zivo. Kanali nimajo uradnega id-ja, zato isti kanal iz TVHeadenda,
    dodatka Stremio, seznama M3U in javnega seznama spoznamo po imenu brez oznak kakovosti (HD, FHD, 1080p, HEVC)
    in drzave (»SI: POP TV HD« = »POP TV« iz Slovenije). Drzava je iz polja `drzava` ali iz oznake v imenu."""
    t = unicodedata.normalize("NFKD", _text(item.get("naslov"), 200)).encode("ascii", "ignore").decode().lower()
    drzava = str(item.get("drzava") or "").strip().lower()[:2]
    for vzorec in (_PREDPONA_DRZAVE, _PRIPONA_DRZAVE):
        m = vzorec.search(t)
        if m:
            drzava = drzava or next(g for g in m.groups() if g)
            t = t[:m.start()] + " " + t[m.end():]
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t).replace("+", " plus ")
    t = _KAKOVOST_KANALA.sub(" ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip(), (drzava if re.fullmatch(r"[a-z]{2}", drzava) else "")


def _identity(item: dict, include_year: bool = True) -> str:
    if item.get("vrsta") == "tv-v-zivo":
        ime, drzava = ime_kanala(item)
        return "|".join(("tv-v-zivo", ime) + ((drzava,) if include_year else ()))
    title = unicodedata.normalize("NFKD", _text(item.get("naslov"), 200)).encode("ascii", "ignore").decode().lower()
    title = re.sub(r"\b(4k|uhd|fhd|hd|1080p?|720p?|2160p?|webrip|bluray)\b", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    artist = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", _text(item.get("izvajalec"))).encode("ascii", "ignore").decode().lower()).strip()
    parts = [item.get("vrsta", "film"), title]
    if include_year:
        parts.append(str(item.get("leto") or ""))
    if item.get("vrsta") == "serija":
        parts.extend((str(item.get("sezona") or ""), str(item.get("epizoda") or "")))
    if item.get("vrsta") == "glasba":
        parts.append(artist)
    return "|".join(parts)


def _score(item: dict) -> int:
    url = str(item.get("url") or "")
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    return (int(item.get("locljivost") or 0) * 1000 + int(item.get("bitrate") or 0) // 1000
            + (150 if ext in MEDIA_EXT else 0) + (30 if url.startswith("https://") else 0)
            + (40 if url.startswith("file:") else 0))


def lastni_vir(item: dict) -> bool:
    """Vnos z uporabnikovega osebnega strežnika (Jellyfin, Plex, Kodi, TVHeadend ...): ima prednost pred istim
    naslovom iz dodatka ali s spleta - tok je doma, brez tujega strežnika in brez cakanja."""
    return bool(item.get("lastni")) or bool(media_servers.streznik_iz_id(item.get("id")))


def _id_scope(item: dict) -> str:
    parts = [str(item.get("vrsta") or "film")]
    if item.get("vrsta") == "serija":
        parts.extend((str(item.get("sezona") or 0), str(item.get("epizoda") or 0)))
    return "|".join(parts)


def _metadata_score(item: dict) -> int:
    title = _text(item.get("naslov"), 200)
    generic = title.casefold() in ("film", "serija", "vir", "vsebina") or bool(_imdb_id(title))
    return (0 if generic else 30) + (15 if item.get("slika") else 0) + (10 if item.get("opis") else 0) \
        + (8 if item.get("leto") else 0) + (5 if item.get("imdb_id") else 0) + (5 if item.get("tmdb_id") else 0)


def merge_duplicates(items: Iterable[dict]) -> list[dict]:
    """Združi po IMDb/TMDb ID-jih, nato varno še po naslovu, letniku in epizodi."""
    unique_by_url: dict[str, dict] = {}
    for item in items:
        url = str(item.get("url") or "")
        if not url:
            continue
        candidate = dict(item)
        imdb = _imdb_id(candidate.get("imdb_id")) or _imdb_id(f"{candidate.get('naslov', '')} {url}")
        tmdb = _tmdb_id(candidate.get("tmdb_id"))
        if imdb and not tmdb:
            tmdb = _tmdb_id(IMDB_TO_TMDB.get(imdb))
        if tmdb and not imdb:
            imdb = TMDB_TO_IMDB.get(str(tmdb), "")
        candidate["imdb_id"], candidate["tmdb_id"] = imdb, tmdb
        existing = unique_by_url.get(url)
        if existing is None:
            unique_by_url[url] = candidate
            continue
        # Isti tok iz dveh katalogov ostane enkrat, vendar ne izgubimo boljših metapodatkov.
        for field in ("imdb_id", "tmdb_id", "leto", "slika", "opis", "izvajalec", "referer", "glave"):
            if not existing.get(field) and candidate.get(field):
                existing[field] = candidate[field]

    normalized = list(unique_by_url.values())
    parent = list(range(len(normalized)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    # Uradni identifikator ima prednost pred naslovom. Oba ID-ja na enem vnosu
    # ustvarita most med katalogi, ki poznajo samo enega od njiju.
    id_owner: dict[str, int] = {}
    title_groups: dict[str, list[int]] = {}
    for index, item in enumerate(normalized):
        scope = _id_scope(item)
        imdb = _imdb_id(item.get("imdb_id"))
        tmdb = _tmdb_id(item.get("tmdb_id"))
        tvdb = _tmdb_id(item.get("tvdb_id"))
        for token in filter(None, (
            f"{scope}|imdb:{imdb}" if imdb else "",
            f"{scope}|tmdb:{tmdb}" if tmdb else "",
            f"{scope}|tvdb:{tvdb}" if tvdb else "",
        )):
            if token in id_owner:
                union(index, id_owner[token])
            else:
                id_owner[token] = index
        title_groups.setdefault(_identity(item, include_year=False), []).append(index)

    # Naslov je rezervna identiteta za vire brez ID-ja. Različnih predelav z
    # različnimi znanimi letnicami ne združimo; neznan letnik povežemo samo,
    # kadar obstaja natanko en možen znani letnik.
    # Kanali TV v zivo: namesto letnice drzava - isto ime iz dveh drzav ni isti kanal, neznana drzava se pridruzi
    # edini znani (kot neznan letnik).
    for indices in title_groups.values():
        by_year: dict = {}
        for index in indices:
            if normalized[index].get("vrsta") == "tv-v-zivo":
                year = ime_kanala(normalized[index])[1] or 0
            else:
                try:
                    year = int(normalized[index].get("leto") or 0)
                except (TypeError, ValueError):
                    year = 0
            by_year.setdefault(year, []).append(index)
        known_years = [year for year in by_year if year]

        def union_if_unambiguous(candidates: list[int]) -> None:
            imdb_ids = {_imdb_id(normalized[index].get("imdb_id")) for index in candidates
                        if _imdb_id(normalized[index].get("imdb_id"))}
            tmdb_ids = {_tmdb_id(normalized[index].get("tmdb_id")) for index in candidates
                        if _tmdb_id(normalized[index].get("tmdb_id"))}
            if len(imdb_ids) > 1 or len(tmdb_ids) > 1:
                return
            for index in candidates[1:]:
                union(candidates[0], index)

        if len(known_years) == 1:
            union_if_unambiguous(by_year[known_years[0]] + by_year.get(0, []))
        else:
            for same_year in by_year.values():
                union_if_unambiguous(same_year)

    groups: dict[int, list[dict]] = {}
    for index, item in enumerate(normalized):
        groups.setdefault(find(index), []).append(item)

    result = []
    for variants in groups.values():
        # Uporabnikov lastni strežnik pred vsem drugim, znotraj tega po kakovosti toka.
        variants.sort(key=lambda item: (lastni_vir(item), _score(item)), reverse=True)
        best = dict(variants[0])
        if lastni_vir(variants[0]):
            best["lastni"] = True
        metadata = max(variants, key=_metadata_score)
        if _metadata_score(metadata) > _metadata_score(best):
            best["naslov"] = metadata.get("naslov") or best.get("naslov")
        for field in ("imdb_id", "tmdb_id", "leto", "slika", "opis", "izvajalec"):
            if not best.get(field):
                best[field] = next((item.get(field) for item in variants if item.get(field)), best.get(field))
        for field in ("tvdb_id", "drzava"):
            if not best.get(field) and any(item.get(field) for item in variants):
                best[field] = next(item.get(field) for item in variants if item.get(field))
        # Jezik vsebine pove le kateri od virov (TMDB, PeerTube ...): zdruzena kartica ga obdrzi.
        if not best.get("jezik"):
            jezik_razlicice = next((item.get("jezik") for item in variants if item.get("jezik")), "")
            if jezik_razlicice:
                best["jezik"] = jezik_razlicice

        scope = _id_scope(best)
        imdb = next((_imdb_id(item.get("imdb_id")) for item in variants if _imdb_id(item.get("imdb_id"))), "")
        tmdb = next((_tmdb_id(item.get("tmdb_id")) for item in variants if _tmdb_id(item.get("tmdb_id"))), 0)
        if imdb:
            identity = f"{scope}|imdb:{imdb}"
        elif tmdb:
            identity = f"{scope}|tmdb:{tmdb}"
        else:
            identity = _identity(best, include_year=True)
        best["id"] = hashlib.sha256(identity.encode()).hexdigest()[:20]
        best["razlicice"] = [dict({k: value for k, value in item.items()
                                   if k in ("url", "vir", "vir_id", "kakovost", "locljivost", "bitrate",
                                            "glave", "referer", "imdb_id", "tmdb_id", "iptv")},
                                  **({"lastni": True} if lastni_vir(item) else {}))
                             for item in variants]
        best["stevilo_razlicic"] = len(variants)
        if any(item.get("preverjam") for item in variants):
            # »Preverjam« samo, ce nobena razlicica (znano) ne oddaja (core/kanali_iptv, J3).
            best["preverjam"] = all(item.get("preverjam") for item in variants)
        best["viri"] = list(dict.fromkeys(item.get("vir", "") for item in variants if item.get("vir")))
        result.append(best)
    return sorted(result, key=lambda item: (item.get("vrsta", ""), item.get("naslov", "").casefold()))


def _serijski_zetoni(item: dict) -> list:
    imdb, tmdb, tvdb = _imdb_id(item.get("imdb_id")), _tmdb_id(item.get("tmdb_id")), _tmdb_id(item.get("tvdb_id"))
    return [z for z in (imdb and "imdb:" + imdb, tmdb and "tmdb:%d" % tmdb, tvdb and "tvdb:%d" % tvdb) if z]


def zdruzi_epizode_v_serije(items: list) -> list:
    """Kartica serije (dodatek Stremio, Cinemeta, TMDB) in epizode iste serije z uporabnikovega strežnika: v katalogu
    ena kartica, ne serija in poleg nje se njene epizode (lastnik, 15. 10. 2026: brez podvajanja vsebine). Epizode
    nosijo id-je serije (media_servers._jellyfin_vrstica). Kartica dobi epizode kot vire; ce je med njimi lastni
    strežnik, kartica predvaja njegovo prvo epizodo (doma, brez tujega strežnika), izbira epizode v podrobnostih pa
    tudi uporabi strežnik (MediaCenter.episode_item)."""
    kartice: dict = {}
    for i, it in enumerate(items):
        if isinstance(it, dict) and it.get("vrsta") == "serija" and not int(it.get("sezona") or 0) and not int(it.get("epizoda") or 0):
            for z in _serijski_zetoni(it):
                kartice.setdefault(z, i)
    if not kartice:
        return items
    epizode: dict = {}
    for i, it in enumerate(items):
        if isinstance(it, dict) and it.get("vrsta") == "serija" and int(it.get("epizoda") or 0):
            cilj = next((kartice[z] for z in _serijski_zetoni(it) if z in kartice), None)
            if cilj is not None and cilj != i:
                epizode.setdefault(cilj, []).append(i)
    if not epizode:
        return items
    odstranjene = {j for seznam in epizode.values() for j in seznam}
    izid = []
    for i, it in enumerate(items):
        if i in odstranjene:
            continue
        if i in epizode:
            eps = sorted((items[j] for j in epizode[i]),
                         key=lambda e: (int(e.get("sezona") or 0) or 999, int(e.get("epizoda") or 0)))
            it = dict(it)
            lastne = [e for e in eps if lastni_vir(e) or any(r.get("lastni") for r in (e.get("razlicice") or []) if isinstance(r, dict))]
            razlicice = [r for r in (it.get("razlicice") or [{"url": it.get("url"), "vir": it.get("vir")}]) if isinstance(r, dict)]
            if lastne:
                prva = lastne[0]
                it["url"] = prva.get("url")
                it["lastni"] = True
                razlicice = [dict({k: prva.get(k) for k in ("url", "vir", "vir_id") if prva.get(k)}, lastni=True)] + razlicice
            for polje in ("imdb_id", "tmdb_id", "tvdb_id", "slika", "opis"):
                if not it.get(polje):
                    it[polje] = next((e.get(polje) for e in eps if e.get(polje)), it.get(polje))
            it["razlicice"] = razlicice
            it["stevilo_razlicic"] = len(razlicice)
            it["epizod_na_strezniku"] = len(lastne)
            it["viri"] = list(dict.fromkeys([v for v in (it.get("viri") or [it.get("vir")]) if v]
                                            + [str(e.get("vir")) for e in eps if e.get("vir")]))
        izid.append(it)
    return izid


def _series_catalog_card(item: dict) -> dict:
    """Stare epizodne predpomnilnike prikaže kot eno kartico serije.

    Prejšnje testne izdaje so v ``media.json`` shranile vsako epizodo posebej.
    Virov uporabniku ne brišemo; ob branju katalog poenotimo in popravimo znane
    metapodatke, zato nadgradnja učinkuje takoj.
    """
    if str(item.get("vrsta") or "") != "serija":
        return item
    out = dict(item)
    imdb = _imdb_id(out.get("imdb_id")) or _imdb_id(f"{out.get('naslov', '')} {out.get('url', '')}")
    tmdb = _tmdb_id(out.get("tmdb_id"))
    if imdb and not tmdb:
        tmdb = _tmdb_id(IMDB_TO_TMDB.get(imdb))
    if tmdb and not imdb:
        imdb = TMDB_TO_IMDB.get(str(tmdb), "")
    meta = KNOWN_IMDB.get(imdb) or KNOWN_IMDB.get(str(tmdb)) or {}
    title = _text(meta.get("title"), 200)
    if not title:
        title = re.sub(r"\s+[Ss]\d{1,2}[Ee]\d{1,3}(?:\s*[-–—:].*)?$", "",
                       _text(out.get("naslov"), 200)).strip()
    if title:
        out["naslov"] = title
    if meta.get("image"):
        out["slika"] = meta["image"]
    if meta.get("year"):
        out["leto"] = meta["year"]
    if meta.get("description"):
        out["opis"] = meta["description"]
    out["imdb_id"], out["tmdb_id"] = imdb, tmdb
    out["sezona"], out["epizoda"] = 0, 0
    return out


def _ujemanje_naslova(naslov: str, iskano: str) -> int:
    """0 = naslov je tocno iskano (brez locil, velikih crk in letnice v oklepaju), 1 = naslov se z njim zacne,
    2 = vse ostalo. Samo za razvrstitev zadetkov iskanja; kaj je zadetek, odloci ujema_iskanje."""
    def cisto(besedilo: str) -> str:
        besedilo = re.sub(r"\(\d{4}\)", " ", unicodedata.normalize("NFKC", besedilo).casefold())
        return " ".join(re.findall(r"\w+", besedilo))
    n, q = cisto(naslov), cisto(iskano)
    if not q:
        return 2
    if n == q:
        return 0
    return 1 if n.startswith(q + " ") else 2


def vir_za_stran(vir: dict) -> dict:
    """Vir za podatke strani (pregled 46, Ö8): naslov in link_naslov samo, ce je naslov pozitivno znan javen, sicer samo
    prikaz (gostitelj[:vrata]); napaka brez naslovov. Geslo ali kljuc v naslovu (Xtream, dodatek s kljucem debrid v
    poti) tako ni v pomnilniku strani (razsiritve, orodja za razvijalce, posnetek stanja). Predvajanje in osvezitev
    naslov dobita v Medijskem centru (sources())."""
    url = str(vir.get("url") or "")
    prikaz = vir["url_prikaz"] if isinstance(vir.get("url_prikaz"), str) else viri_sink.prikaz_naslova(url)
    izid = dict(vir, url_prikaz=prikaz)
    if url != prikaz:
        izid.pop("url", None)
    if izid.get("link_naslov") and not viri_sink.znan_javen(izid["link_naslov"], vir.get("javni") is True):
        izid.pop("link_naslov", None)
    if isinstance(izid.get("napaka"), str):
        izid["napaka"] = viri_sink.sporocilo_napake(izid["napaka"], url, vir.get("javni") is True, 300)   # Ê5, Ş5
    return izid


class _PrazenOdgovor(ValueError):
    """Ponudnik je na naslov vira z racunom odgovoril brez seznama (prazno telo, stran HTML - racun potekel ali
    zaklenjen; pregled 46, Ö5)."""



def _naslovi_skoka(gostitelj: str, vrata: int) -> list[str]:
    """Vsi naslovi imena (getaddrinfo enkrat), po vrsti in brez ponovitev."""
    izid: list[str] = []
    for *_x, naslov in socket.getaddrinfo(gostitelj, vrata, type=socket.SOCK_STREAM):
        if naslov[0] not in izid:
            izid.append(naslov[0])
    return izid


def _ni_javen(naslov: str) -> bool:
    """Naslov, ki ni javen (zasebni, zanka, povezavno-lokalni, CGNAT, rezervirani ...); ::ffff:a.b.c.d kot IPv4."""
    try:
        ip = ipaddress.ip_address(naslov.split("%", 1)[0])
    except ValueError:
        return True
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return not ip.is_global


def _domace_ime(gostitelj: str) -> bool:
    g = (gostitelj or "").lower()
    return g == "localhost" or g.endswith((".local", ".lan", ".home.arpa"))


def _pripni(req, gostitelj: str, vrata: int) -> list[str]:
    """Razresi ime skoka enkrat in si zapomni naslove (povezava gre samo nanje) ter ali je skok v domacem omrezju."""
    naslovi = _naslovi_skoka(gostitelj, vrata)
    req._safeer_pripeto = (gostitelj.lower(), vrata, naslovi)
    req._safeer_domace = _domace_ime(gostitelj) or (bool(naslovi) and all(_ni_javen(n) for n in naslovi))
    return naslovi


def _privzeta_vrata(deli) -> int:
    return deli.port or (443 if deli.scheme == "https" else 80)


class PreverjenSkok(urllib.request.HTTPRedirectHandler):
    """Preusmeritev ob prenosu vira (D1, pregled 5. 11. 2026): vsak skok posebej - samo http(s), nikoli s https na
    http in z javnega streznika nikoli v domace omrezje (192.168.x, localhost ...: tuj seznam ne sme z nasimi pravicami
    brati usmerjevalnika ali krajevnih storitev). Zacetni naslov je lahko http (seznami IPTV), ker ga je izbral
    uporabnik; preusmeritev izbere streznik.
    CodeRabbit 5. 11. 2026: ime z javnim IN zasebnim naslovom je prej preslo (veljalo je samo »vsi zasebni«), povezava pa
    je naslove razresila znova (DNS rebinding). Zdaj zavrne ime, ce je KATERIKOLI naslov ne-javen, in se poveze samo na
    naslove, preverjene tu (_PripetHttp/_PripetHttps)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        star, nov = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if nov.scheme not in ("http", "https") or not nov.hostname:
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev ni http(s)", headers, fp)
        if star.scheme == "https" and nov.scheme != "https":
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev s https na http", headers, fp)
        star_domace = getattr(req, "_safeer_domace", None)
        if star_domace is None:
            star_domace = media_servers.je_domace_omrezje(star.hostname or "")
        izid = super().redirect_request(req, fp, code, msg, headers, newurl)
        if izid is None:
            return None
        try:
            naslovi = _pripni(izid, nov.hostname, _privzeta_vrata(nov))
        except (OSError, UnicodeError) as e:
            raise urllib.error.URLError(e) from None
        if not star_domace and (_domace_ime(nov.hostname) or any(_ni_javen(n) for n in naslovi)):
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev v domace omrezje", headers, fp)
        return izid


def _odpiralec_naslovov(naslovi: list[str]):
    """Kot socket.create_connection, a vedno na enega od ze preverjenih naslovov (ime se ne razresi znova)."""
    def odpri(naslov, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        napaka: Optional[OSError] = None
        for n in naslovi:
            try:
                return socket.create_connection((n, naslov[1]), timeout, source_address)
            except OSError as e:
                napaka = e
        raise napaka or OSError("ni naslova")
    return odpri


def _pripeta_povezava(osnova, req):
    """Razred povezave za to zahtevo: ce gre naravnost na gostitelja zahteve (ne prek posrednika sistema), samo na
    naslove iz _pripni. Zacetni naslov (izbral ga je uporabnik) se razresi tu, preusmeritve v PreverjenSkok."""
    deli = urllib.parse.urlsplit(req.full_url)
    gostitelj, vrata = (deli.hostname or "").lower(), _privzeta_vrata(deli)
    pripeto = getattr(req, "_safeer_pripeto", None)
    if pripeto is None and gostitelj and req.host == deli.netloc:
        try:
            _pripni(req, gostitelj, vrata)
        except (OSError, UnicodeError) as e:
            raise urllib.error.URLError(e) from None
        pripeto = req._safeer_pripeto

    class Povezava(osnova):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            if pripeto and (str(self.host).lower(), self.port) == pripeto[:2]:
                self._create_connection = _odpiralec_naslovov(pripeto[2])
    return Povezava


class _PripetHttp(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_pripeta_povezava(http.client.HTTPConnection, req), req)


class _PripetHttps(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_pripeta_povezava(http.client.HTTPSConnection, req), req, context=self._context)

class MediaCenter:
    """Trajen katalog virov z atomskim zapisom in enotno logiko za vse platforme."""

    def __init__(self, config_dir: str, roots: Optional[Iterable[str | Path]] = None,
                 secret_encryptor=None, secret_decryptor=None, secret_forget=None):
        self.config_dir = Path(config_dir)
        self.store_path = self.config_dir / "media.json"
        self.roots = [Path(path) for path in roots] if roots is not None else self._default_roots()
        self._lock = threading.RLock()
        self._tokovi_odgovor = threading.local()   # .vsi: ali so ob zadnjem vprasanju po tokovih odgovorili vsi dodatki
        self._tmdb_cache: dict[str, tuple[float, dict]] = {}
        self._predpomnilnika_pociscena = time.time()
        self._dynamic_items: dict[str, dict] = {}
        #: koren dodatka -> ali je zaseben (manifest behaviorHints.adult); velja do konca tega zagona.
        self._zasebni_koreni: dict[str, bool] = {}
        #: Moji viri so se z usklajevanjem v Linku spremenili (core/viri_sink.py): klicatelj osvezi zaslon.
        self.ob_virih: Optional[Callable[[], None]] = None
        #: Preverba kanalov IPTV je spremenila, kateri kanali delujejo (core/kanali_iptv.py): klicatelj obvesti stran.
        self.ob_kanalih: Optional[Callable[[], None]] = None
        self._spoznavam_dodatke = False
        self._dodatki_vprasani: dict[str, float] = {}
        self._izvoz_virov_zapisan = False
        #: Zapomnjene meritve odziva gostiteljev (core/meritve_virov.py) - ista za razlicice toka in lastne vgrajene vire.
        self._meritve = meritve_virov.Meritve(self.config_dir / "meritve-virov.json")
        self._zakoniti_viri = zakoniti_viri.ZakonitiViri()
        #: Izvirni jezik naslovov z id-jem IMDb (Wikidata) za izbiro jezika vsebine; predpomnilnik je ob nastavitvah.
        self._izvirni_jeziki = izvirni_jezik.IzvirniJeziki(str(self.config_dir / "izvirni-jeziki.tsv"))
        self._secret_encryptor = secret_encryptor or _dpapi_protect
        self._secret_decryptor = secret_decryptor or _dpapi_unprotect
        #: Izbrise sifriran zapis iz zbirke skrivnosti (Linux: os_katalog.pozabi); DPAPI nima zbirke - nic.
        self._secret_forget = secret_forget or (lambda _vrednost: None)
        # Naloga 131: debrid storitve (TorBox, Real-Debrid, AllDebrid). Kljuci samo sifrirani (isti sifrirnik kot gesla
        # streznikov), v svoji datoteki - meritev po predvajanju ne sme ozastariti predpomnilnika kataloga.
        self.debrid = debrid.Debrid(self._beri_debrid, self._pisi_debrid, self._secret_encryptor, self._secret_decryptor,
                                    self._secret_forget)
        self._server_cache: dict[str, tuple[float, list[dict]]] = {}
        #: Zahteve virov, ki se tecejo (kljuc predpomnilnika -> nit): hitro tipkanje ne sprozi iste zahteve vecrat.
        self._v_teku: dict = {}
        # Trajni predpomnilnik kataloga in podatkov TMDB: ob odprtju se prikaze takoj,
        # sveze podatke dobimo v ozadju (uporabnik ne caka na prazen zaslon).
        self._predpomnilnik: Optional[dict] = None
        self._predpomnilnik_lock = threading.RLock()
        self._predpomnilnik_casovnik: Optional[threading.Timer] = None
        self._osvezujem: set[str] = set()
        # Kanali seznamov IPTV: prikazemo samo tiste, ki oddajajo (core/kanali_iptv.py; lastnik, 25. 10. 2026).
        self.kanali = kanali_iptv.PreverbaKanalov(self.config_dir / "kanali-preverba.json")
        self.kanali.ob_spremembi = self._kanali_spremenjeni
        self._zastareli_viri: set[str] = set()
        # Enkratna selitev po pregledu 46 (Ö3) - pred vsakim drugim zapisom media.json in viri_za_naprave.json.
        self._racuni_preseljeni = False
        self._preseli_racune()
        # Dodatki z osebnim zetonom (core/skrivni_dodatki.py): pravi naslov samo sifriran, povsod drugje nadomestek.
        skrivni_dodatki.nastavi_odklepalnik(self._odkleni_dodatek)
        self._preseli_skrivne_dodatke()

    # --- dodatki z osebnim zetonom ali kljucem v naslovu (Webtor, Torrentio z debrid kljucem) -------------------
    def _odkleni_dodatek(self, osnova: str) -> Optional[str]:
        """Pravi naslov dodatka za nadomestno osnovo (iz zbirke skrivnosti) ali None. Samo za omrezni klic."""
        with self._lock:
            zapis = next((s for s in self._load().get("osebni_strezniki", []) if isinstance(s, dict)
                          and s.get("url_enc") and skrivni_dodatki.nadomestna_osnova(str(s.get("url") or "")) == osnova),
                         None)
        if zapis is None:
            return None
        return self._secret_decryptor(str(zapis["url_enc"])) or None

    #: Najvecja datoteka, ki jo prehod prebere v celoti (vecja ostane v cakanju in se ponovi; meritev 25. 10.: mapa
    #: Medijskega centra na prenosniku ima 11 datotek, najvecja nekaj MB).
    PREHOD_NAJVEC_BAJTOV = 256 * 1024 * 1024
    #: Koreni dodatkov v drugih datotekah (katalog: »stremio:<koren>|«, izbrisi: »stremio|<naslov>«, »koren«): tudi
    #: odstranjen dodatek z zetonom tam dobi nadomestek (pregled Grok N3).
    _RX_KORENI = re.compile(rb'stremio:(https?:(?:/|\\/)[^|"\s]+)\||"stremio\|(https?:(?:/|\\/)[^"\s]+)"|"koren": ?"(https?:[^"\s]+)"')

    def _preseli_skrivne_dodatke(self) -> None:
        """Prehod (25. 10. 2026): dodatek, ki je bil v media.json shranjen s pravim naslovom (zeton v cistopisu), dobi
        sifriran naslov (url_enc) in nadomestek; nadomestek zamenja pravo predpono tudi v vseh drugih datotekah mape
        Medijskega centra (tudi podmape in koreni odstranjenih dodatkov). Ponovljivo (pregled Grok N1): nadomestne
        osnove, katerih druge datoteke se niso ociscene, ostanejo v media.json pod »skrivni_prehod«; ob naslovnem zagonu
        se prava predpona vzame iz zbirke skrivnosti in prehod se ponovi, dokler ne uspe povsod. Najprej druge datoteke,
        nato media.json. Ce sifriranje ne uspe (ni zbirke skrivnosti), zapis ostane, kot je (na novo mesto ne gre), dobi
        oznako »nezavarovan« (Moji viri to povedo), pravi naslov pa le v pomnilniku dobi nadomestek (tokovi, Grok N13)."""
        with self._lock:
            data = self._load()
            zamenjave: dict = {}
            sifrirani: list = []
            spremenjeno = skrivni = False
            cakajo = [str(o) for o in (data.get("skrivni_prehod") or []) if isinstance(o, str)]
            for s in data.get("osebni_strezniki", []):
                if not isinstance(s, dict) or s.get("ponudnik") != "stremio":
                    continue
                url = str(s.get("url") or "")
                predpona = skrivni_dodatki.skrivna_predpona_dodatka(url)
                if not predpona:
                    skrivni = skrivni or bool(s.get("url_enc"))
                    continue
                skrivni = True
                try:
                    enc = self._secret_encryptor(url)
                except Exception:  # noqa: BLE001 - brez zbirke skrivnosti: zapis ostane, uporabnik dobi opozorilo
                    enc = ""
                if not enc:
                    if not s.get("nezavarovan"):
                        s["nezavarovan"] = True
                        spremenjeno = True
                    skrivni_dodatki.odkleni(url)        # samo v pomnilniku: tokovi tega dodatka dobijo nadomestek
                    continue
                sifrirani.append(enc)
                nadomestni = skrivni_dodatki.odkleni(url)
                osnova = skrivni_dodatki.nadomestna_osnova(nadomestni) or ""
                zamenjave[predpona] = osnova
                if s.get("zaseben") is False:
                    # Grok N8: pred popravkom je sel ta naslov z lists.get napravam v Linku - Moji viri to povedo.
                    s["razkrit"] = True
                s.update(url=nadomestni, url_enc=enc, skriven=True)
                s.pop("nezavarovan", None)
                if osnova not in cakajo:
                    cakajo.append(osnova)
                spremenjeno = True
            # Nedokoncan prehod iz prejsnjega zagona: prava predpona iz zbirke skrivnosti (samo dokler ni koncan).
            # Odstranjen dodatek, ki ga odstranitev ni mogla koncati (zaklenjena zbirka), ima sifriran naslov v
            # »skrivni_prehod_enc« (pregled Grok 19, M1) - sicer bi prava predpona izginila za vedno.
            enc_prehoda = data.get("skrivni_prehod_enc") if isinstance(data.get("skrivni_prehod_enc"), dict) else {}
            enc_prehoda = {str(k): str(v) for k, v in enc_prehoda.items() if isinstance(v, str) and v}
            for osnova in list(cakajo):
                if osnova in zamenjave.values():
                    continue
                pravi = None
                try:
                    pravi = self._odkleni_dodatek(osnova)
                    if not pravi and osnova in enc_prehoda:
                        pravi = self._secret_decryptor(enc_prehoda[osnova]) or None
                except Exception:  # noqa: BLE001 - zaklenjena zbirka: prehod pocaka na naslednji zagon
                    pravi = None
                predpona = skrivni_dodatki.skrivna_predpona_dodatka(pravi or "")
                if predpona and skrivni_dodatki.nadomestek(predpona) == osnova:
                    zamenjave[predpona] = osnova
                    skrivni_dodatki.odkleni(pravi)
                elif osnova not in enc_prehoda and not any(
                        isinstance(x, dict) and skrivni_dodatki.nadomestna_osnova(str(x.get("url") or "")) == osnova
                        for x in data.get("osebni_strezniki", [])):
                    cakajo.remove(osnova)               # dodatka ni vec in sifriranega naslova ni - ni kaj iskati
            besedilo = json.dumps(data, ensure_ascii=False).encode("utf-8")
            koreni = self._skrivni_koreni(besedilo)
            if zamenjave or koreni or cakajo:
                koreni.update(zamenjave)
                ok = self._preseli_datoteke(koreni)
                if koreni:
                    data = json.loads(skrivni_dodatki.zamenjaj(besedilo.decode("utf-8"), koreni))
                    spremenjeno = True
                # Grok 19, M1: koncana je samo osnova, katere prava predpona je bila v tem teku znana in zamenjana
                # povsod; neznana (zaklenjena zbirka) caka naprej - prej je oznaka izginila in zeton zunaj vzorcev
                # _RX_KORENI je ostal v cistopisu za vedno.
                znane = set(zamenjave.values())
                novi = [o for o in cakajo if o not in znane] if ok else cakajo
                if novi != (data.get("skrivni_prehod") or []):
                    data["skrivni_prehod"] = novi
                    spremenjeno = True
                if not novi:
                    data.pop("skrivni_prehod", None)
            koncani_enc = [e for o, e in enc_prehoda.items() if o not in (data.get("skrivni_prehod") or [])]
            if koncani_enc:
                ostali = {o: e for o, e in enc_prehoda.items() if o in (data.get("skrivni_prehod") or [])}
                if ostali:
                    data["skrivni_prehod_enc"] = ostali
                else:
                    data.pop("skrivni_prehod_enc", None)
                spremenjeno = True
            if spremenjeno:
                try:
                    self._save(data)
                except OSError:
                    # Grok N11: sifriran naslov, ki ni zapisan nikamor, ne ostane v zbirki skrivnosti (sirota).
                    for enc in sifrirani:
                        self._pozabi_skrivnost(enc)
                    raise
                for enc in koncani_enc:                 # odstranjen dodatek: prehod koncan, naslov ni vec potreben
                    self._pozabi_skrivnost(enc)
        if skrivni:
            print("[SafeerMedia] dodatki z osebnim zetonom: prehod %d, nezavarovanih %d, cakajo %d" % (
                len(zamenjave), sum(1 for s in data.get("osebni_strezniki", []) if isinstance(s, dict) and s.get("nezavarovan")),
                len(data.get("skrivni_prehod") or [])), flush=True)
            # Izvoz za naprave (Safeer Control) je pred popravkom lahko vseboval pravi naslov: zapisemo ga znova.
            self._viri_zapisi_izvoz()

    def _odstranjen_skrivni(self, odstranjen: dict, data: dict) -> None:
        """Odstranjen dodatek z zetonom: ce prehod njegovih drugih datotek se ni bil koncan, ga koncamo zdaj (pozneje
        prave predpone ne bomo vec poznali), nato ga pozabimo v pomnilniku."""
        url = str(odstranjen.get("url") or "")
        osnova = skrivni_dodatki.nadomestna_osnova(url)
        cakajo = [o for o in (data.get("skrivni_prehod") or []) if isinstance(o, str)]
        if osnova and osnova in cakajo and odstranjen.get("url_enc"):
            koncano = False
            try:
                pravi = self._secret_decryptor(str(odstranjen["url_enc"]))
                predpona = skrivni_dodatki.skrivna_predpona_dodatka(pravi or "")
                if predpona and self._preseli_datoteke({predpona: osnova}):
                    data["skrivni_prehod"] = [o for o in cakajo if o != osnova]
                    self._save(data)
                    koncano = True
            except Exception:  # noqa: BLE001 - zaklenjena zbirka: prehod ga konca ob naslednjem zagonu
                print("[SafeerMedia] prehod ob odstranitvi ni uspel", flush=True)
            if not koncano:
                # Grok 19, M1: sifriran naslov ostane (os_katalog ga ne pozabi, dokler je tu), da naslednji zagon
                # najde pravo predpono tudi v oblikah zunaj vzorcev _RX_KORENI.
                enc = data.get("skrivni_prehod_enc") if isinstance(data.get("skrivni_prehod_enc"), dict) else {}
                enc[osnova] = str(odstranjen["url_enc"])
                data["skrivni_prehod_enc"] = enc
                try:
                    self._save(data)
                except OSError:
                    print("[SafeerMedia] prehod ob odstranitvi: zapis ni uspel", flush=True)
        skrivni_dodatki.pozabi(url)

    def skrivnosti_v_prehodu(self) -> set:
        """Sifrirani naslovi odstranjenih dodatkov, ki jih prehod se potrebuje (os_katalog jih ob odstranitvi ne pozabi)."""
        with self._lock:
            enc = self._load().get("skrivni_prehod_enc")
        return {str(v) for v in enc.values() if isinstance(v, str)} if isinstance(enc, dict) else set()

    def _pozabi_skrivnost(self, enc: str) -> None:
        try:
            self._secret_forget(enc)
        except Exception:  # noqa: BLE001 - zbirka skrivnosti nedosegljiva: vnos ostane (sifriran)
            print("[SafeerMedia] zbirka skrivnosti: pozabi ni uspel", flush=True)

    @classmethod
    def _skrivni_koreni(cls, besedilo: bytes) -> dict:
        """{prava predpona: nadomestna osnova} za korene dodatkov z zetonom v besedilu (tudi odstranjenih)."""
        izid: dict = {}
        for m in cls._RX_KORENI.finditer(besedilo):
            koren = next(g for g in m.groups() if g).decode("utf-8", "replace").replace("\\/", "/")
            predpona = skrivni_dodatki.skrivna_predpona_dodatka(koren)
            z = skrivni_dodatki.nadomestek(predpona) if predpona else None
            if predpona and z:
                izid[predpona] = z
        return izid

    def _datoteke_prehoda(self) -> list:
        """Vse navadne datoteke v mapi Medijskega centra in podmapah (brez media.json, ki ga pise prehod sam)."""
        izid = []
        for koren, mape, datoteke in os.walk(self.config_dir, followlinks=False):
            mape[:] = sorted(m for m in mape if not os.path.islink(os.path.join(koren, m)))
            for ime in sorted(datoteke):
                pot = Path(koren) / ime
                if pot != self.store_path and pot.is_file() and not pot.is_symlink() and not ime.endswith(".prehod"):
                    izid.append(pot)
        return izid

    def _preseli_datoteke(self, zamenjave: dict) -> bool:
        """Prave predpone -> nadomestki v vseh datotekah mape (bajti: tudi datoteke, ki niso UTF-8; tudi zapis »\\/«).
        Atomski zapis z istimi dovoljenji in fsync (Grok N12). Odkrije se tudi nova prava predpona (koren odstranjenega
        dodatka) in se doda v `zamenjave`. True = povsod uspelo; False = katera datoteka ostaja (ponovi se ob zagonu)."""
        ok = True
        for pot in self._datoteke_prehoda():
            try:
                velikost = pot.stat().st_size
                if velikost > self.PREHOD_NAJVEC_BAJTOV:
                    print("[SafeerMedia] prehod: datoteka prevelika, ostane za naslednji zagon", flush=True)
                    ok = False
                    continue
                bajti = pot.read_bytes()
                for p, z in self._skrivni_koreni(bajti).items():
                    zamenjave.setdefault(p, z)
                pari = [(p.encode("utf-8"), z.encode("utf-8")) for p, z in zamenjave.items() if p]
                pari += [(p.replace(b"/", b"\\/"), z.replace(b"/", b"\\/")) for p, z in pari]
                if not any(p in bajti for p, _z in pari):
                    continue
                if bajti[:16] == b"SQLite format 3\x00":
                    # Baze ne smemo popravljati po bajtih (dolzina se spremeni); izmerjeno 25. 10.: v mapi je ni.
                    print("[SafeerMedia] prehod: baza SQLite z zetonom ostane za naslednji zagon", flush=True)
                    ok = False
                    continue
                for p, z in sorted(pari, key=lambda pz: len(pz[0]), reverse=True):
                    bajti = bajti.replace(p, z)
                zacasna = pot.with_name(pot.name + ".%d.prehod" % threading.get_ident())
                try:
                    fd = os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, pot.stat().st_mode & 0o777)
                    with os.fdopen(fd, "wb") as f:
                        f.write(bajti)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(zacasna, pot)
                finally:
                    if zacasna.exists():
                        zacasna.unlink()
            except OSError:
                print("[SafeerMedia] prehod: datoteke ni bilo mogoce popraviti, ponovi se ob zagonu", flush=True)
                ok = False
        return ok

    # --- prijava osebnih streznikov ob predvajanju ------------------------------
    #: Strezniki, ki imajo prijavo v naslovu toka (core/media_servers.py, s_prijavo).
    _S_PRIJAVO = frozenset({"jellyfin", "emby", "navidrome", "plex", "kodi", "tvheadend", "funkwhale"})

    def _prijave_streznikov(self) -> list:
        """[(streznik, skrivnost)] osebnih streznikov s prijavo v naslovu. Skrivnost je samo v pomnilniku (kot vrstice
        _server_cache, ki jo ze nosijo), kljuc je sifriran zapis - nov zeton je nov kljuc."""
        with self._lock:
            strezniki = [s for s in self._load().get("osebni_strezniki", [])
                         if isinstance(s, dict) and s.get("ponudnik") in self._S_PRIJAVO and s.get("url")]
        if not hasattr(self, "_skrivnosti_strezn"):
            self._skrivnosti_strezn = {}
        izid = []
        for s in strezniki:
            enc = str(s.get("secret_enc") or "")
            if enc not in self._skrivnosti_strezn:
                try:
                    self._skrivnosti_strezn[enc] = self._secret_decryptor(enc) if enc else ""
                except Exception:  # noqa: BLE001 - zaklenjena zbirka skrivnosti: naslov brez prijave, poskusimo znova
                    izid.append((s, ""))
                    continue
            izid.append((s, self._skrivnosti_strezn[enc]))
        return izid

    def s_prijavo(self, url: str, streznik: str = "", prijave: Optional[list] = None) -> str:
        """Naslov s streznika, shranjen brez prijave (seznam, polica), s prijavo za predvajanje na tej napravi.
        [streznik]: id streznika, ki ga je skladba imela ob shranjevanju (ima prednost pred ujemanjem gostitelja)."""
        url = str(url or "")
        if not url.startswith(("http://", "https://")) or viri_sink.ima_prijavo(url):
            return url
        prijave = self._prijave_streznikov() if prijave is None else prijave
        for server, secret in sorted(prijave, key=lambda p: str(p[0].get("id") or "") != streznik):
            if media_servers.je_naslov_streznika(url, server):
                return media_servers.s_prijavo(url, server, secret)
        return url

    def _vnos_s_prijavo(self, item: Optional[dict], streznik: str = "", prijave: Optional[list] = None) -> Optional[dict]:
        """Vnos z naslovom toka in ovitka s prijavo (samo, ce kaze na uporabnikov streznik)."""
        if not isinstance(item, dict):
            return item
        streznik = streznik or str(item.get("streznik") or "") or media_servers.streznik_iz_id(item.get("id"))
        izid = item
        for polje in ("url", "slika"):
            prej = str(item.get(polje) or "")
            if prej.startswith(("http://", "https://")) and not viri_sink.ima_prijavo(prej):
                if prijave is None:
                    prijave = self._prijave_streznikov()
                    if not prijave:
                        return item
                novo = self.s_prijavo(prej, streznik, prijave)
                if novo != prej:
                    izid = dict(izid, **{polje: novo})
        return izid

    # --- trajni predpomnilnik -------------------------------------------------
    PREDPOMNILNIK_KATALOG = 80        # najvec shranjenih pogledov (vrsta/zvrst/stran/iskanje)
    PREDPOMNILNIK_TMDB = 400          # najvec shranjenih odgovorov TMDB (podrobnosti, ponudniki)
    SVEZE_SEKUND = 10 * 60            # mlajsega pogleda ne osvezujemo v ozadju

    #: Razlicica pravil kataloga: ob spremembi (11. 10. 2026: PeerTube in Internet Archive nista vec vgrajena, glasbeni
    #: dodatki gredo pod Glasbo) shranjen katalog ne velja vec - sicer bi stara vsebina ob zagonu se enkrat zasvetila.
    RAZLICICA_KATALOGA = 6      # 6: 25. 10. 2026 kanali IPTV samo v TV v zivo in samo delujoci
    #                             5: 15. 10. 2026 brez dvojnikov Jellyfin/Stremio (lastni strežnik prvi, kanali po imenu
    #                             in drzavi, epizode s strežnika v kartici serije); 4: programi RTV 365 po kanalih

    @property
    def pot_predpomnilnika(self) -> Path:
        return self.config_dir / "media-predpomnilnik.json"

    def _nalozi_predpomnilnik(self) -> dict:
        with self._predpomnilnik_lock:
            if self._predpomnilnik is None:
                data: Any = None
                try:
                    if self.pot_predpomnilnika.exists():
                        data = json.loads(self.pot_predpomnilnika.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = None
                if not isinstance(data, dict):
                    data = {}
                katalog = data.get("katalog") if isinstance(data.get("katalog"), dict) else {}
                if data.get("razlicica") != self.RAZLICICA_KATALOGA:
                    katalog = {}
                tmdb = data.get("tmdb") if isinstance(data.get("tmdb"), dict) else {}
                self._predpomnilnik = {"katalog": katalog, "tmdb": tmdb}
            return self._predpomnilnik

    def _shrani_predpomnilnik_zdaj(self) -> None:
        with self._predpomnilnik_lock:
            self._predpomnilnik_casovnik = None
            shramba = self._nalozi_predpomnilnik()
            for ime, meja in (("katalog", self.PREDPOMNILNIK_KATALOG), ("tmdb", self.PREDPOMNILNIK_TMDB)):
                zapisi = shramba[ime]
                if len(zapisi) > meja:
                    stari = sorted(zapisi, key=lambda k: float((zapisi[k] or {}).get("uporabljeno") or 0))
                    for kljuc in stari[:len(zapisi) - meja]:
                        zapisi.pop(kljuc, None)
            besedilo = json.dumps(dict(shramba, razlicica=self.RAZLICICA_KATALOGA), ensure_ascii=False, separators=(",", ":"))
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_besedilo_atomsko(str(self.pot_predpomnilnika), besedilo)
        except OSError:
            pass

    def _shrani_predpomnilnik(self) -> None:
        """Zapis z zamikom: vec sprememb v kratkem casu zdruzimo v en zapis na disk."""
        with self._predpomnilnik_lock:
            if self._predpomnilnik_casovnik is not None:
                return
            self._predpomnilnik_casovnik = threading.Timer(1.5, self._shrani_predpomnilnik_zdaj)
            self._predpomnilnik_casovnik.daemon = True
            self._predpomnilnik_casovnik.start()

    def ozastari_predpomnilnik(self, izbrisi: bool = False) -> None:
        """Po spremembi virov: pogledi ostanejo za takojsen prikaz, a se ob naslednjem odprtju osvezijo."""
        with self._predpomnilnik_lock:
            katalog = self._nalozi_predpomnilnik()["katalog"]
            if izbrisi:
                katalog.clear()
            else:
                for zapis in katalog.values():
                    if isinstance(zapis, dict):
                        zapis["cas"] = 0
        self._shrani_predpomnilnik()

    def kljuc_kataloga(self, query: str = "", kind: str = "vse", genre: str = "", page: int = 1,
                       razvrsti: str = "", izklopljeni: Iterable[str] = (), samo_lokalno: bool = False,
                       izklopljeni_jeziki: Iterable[str] = (), jezik: str = "", drzava_radia: str = "") -> str:
        # Prvi element je razlicica oblike pogleda: ob spremembi vrstnega reda stari pogledi ne veljajo.
        kljuc = ["v5", _text(query, 120).casefold(), kind or "vse", _text(genre, 20),
                 max(1, int(page or 1)), self.izbrana_drzava or "auto", razvrsti or "",
                 sorted({str(x) for x in (izklopljeni or []) if x}), bool(samo_lokalno),
                 sorted({str(x) for x in (izklopljeni_jeziki or []) if x})]
        if jezik in izvirni_jezik.KODE:
            # Izbran jezik vsebine je svoj pogled; brez izbire ostane kljuc tak kot prej (shranjeni pogledi veljajo).
            kljuc.append("jezik:" + jezik)
        if _drzava_radia(drzava_radia):
            kljuc.append("radio-drzava:" + _drzava_radia(drzava_radia))
        return json.dumps(kljuc, ensure_ascii=False)

    def _zapomni_katalog(self, kljuc: str, rezultat: dict, cas: Optional[float] = None) -> None:
        shranjeno = {k: v for k, v in rezultat.items() if k not in ("viri", "mape", "kljuc", "iz_predpomnilnika", "osvezujem")}
        zdaj = time.time()
        with self._predpomnilnik_lock:
            self._nalozi_predpomnilnik()["katalog"][kljuc] = {"cas": zdaj if cas is None else cas, "uporabljeno": zdaj,
                                                              "rezultat": shranjeno}
        self._shrani_predpomnilnik()

    def catalog_hitro(self, query: str = "", kind: str = "vse", genre: str = "", page: int = 1,
                      ob_osvezitvi=None, razvrsti: str = "", izklopljeni: Iterable[str] = (),
                      samo_lokalno: bool = False, izklopljeni_jeziki: Iterable[str] = (), jezik: str = "",
                      drzava_radia: str = "") -> dict:
        """Katalog najprej iz predpomnilnika (takoj), nato sveze v ozadju.

        ob_osvezitvi(kljuc, rezultat) se poklice samo, ce se je vsebina v ozadju res spremenila.
        Ce pogleda se ni v predpomnilniku, ga nalozimo normalno in shranimo za naslednjic.
        """
        izklopljeni = sorted({str(x) for x in (izklopljeni or []) if x})
        moznosti = {"razvrsti": razvrsti or "", "izklopljeni": izklopljeni, "samo_lokalno": bool(samo_lokalno),
                    "izklopljeni_jeziki": sorted({str(x) for x in (izklopljeni_jeziki or []) if x})}
        if jezik in izvirni_jezik.KODE:
            moznosti["jezik"] = jezik
        if _drzava_radia(drzava_radia):
            moznosti["drzava_radia"] = _drzava_radia(drzava_radia)
        kljuc = self.kljuc_kataloga(query, kind, genre, page, **moznosti)
        if samo_lokalno:
            # Krajevne datoteke so takoj na voljo: brez predpomnilnika (vedno sveze).
            return dict(self.catalog(query, kind, genre, page, **moznosti), kljuc=kljuc,
                        iz_predpomnilnika=False, osvezujem=False)
        with self._predpomnilnik_lock:
            zapis = self._nalozi_predpomnilnik()["katalog"].get(kljuc)
            if isinstance(zapis, dict):
                zapis["uporabljeno"] = time.time()
        if isinstance(zapis, dict) and isinstance(zapis.get("rezultat"), dict) and zapis["rezultat"].get("vnosi"):
            rezultat = dict(zapis["rezultat"])
            for item in rezultat.get("vnosi") or []:
                if isinstance(item, dict) and item.get("id"):
                    self._dynamic_items.setdefault(item["id"], item)
            starost = time.time() - float(zapis.get("cas") or 0)
            osvezi = starost >= self.SVEZE_SEKUND
            if osvezi:
                self._osvezi_v_ozadju(kljuc, query, kind, genre, page, ob_osvezitvi, moznosti)
            rezultat.update(viri=self.vidni_viri(), mape=[str(path) for path in self.roots],
                            kljuc=kljuc, iz_predpomnilnika=True, osvezujem=osvezi)
            # Pogled, shranjen pred to izdajo ali preden je bil dodatek spoznan kot zaseben, ga ne pokaze.
            return self._brez_zasebnih_rezultat(rezultat, kind)
        self._iskanje_nit.cakajoci = cakajoci = []
        try:
            rezultat = self.catalog(query, kind, genre, page, **moznosti)
        finally:
            self._iskanje_nit.cakajoci = None
        if cakajoci:
            # Pocasni viri se niso odgovorili: pokazemo, kar je (prvi zadetki takoj), ostalo stran dobi z dogodkom.
            # Delni pogled shranimo kot zastarel, da ga naslednje odprtje osvezi.
            if rezultat.get("vnosi"):
                self._zapomni_katalog(kljuc, rezultat, cas=0.0)
            self._dokoncaj_v_ozadju(kljuc, cakajoci, rezultat, query, kind, genre, page, ob_osvezitvi, moznosti)
            return dict(self._brez_zasebnih_rezultat(rezultat, kind), kljuc=kljuc, iz_predpomnilnika=False,
                        osvezujem=True)
        if rezultat.get("vnosi"):
            self._zapomni_katalog(kljuc, rezultat)
        return dict(self._brez_zasebnih_rezultat(rezultat, kind), kljuc=kljuc, iz_predpomnilnika=False, osvezujem=False)

    #: Najdlje toliko sekund cakamo v ozadju na pocasne vire iskanja (zahteve imajo svoj rok 10 s, dodatek z vec
    #: katalogi pa vec zahtev).
    DOKONCAJ_S = 45.0

    def _dokoncaj_v_ozadju(self, kljuc: str, cakajoci: list, delni: dict, query: str, kind: str, genre: str,
                           page: int, ob_osvezitvi, moznosti: dict) -> None:
        drzava = self.izbrana_drzava

        def delo() -> None:
            from concurrent.futures import wait
            wait(cakajoci, timeout=self.DOKONCAJ_S)
            try:
                self.izbrana_drzava = drzava
                # Koncani viri so zdaj v svojih predpomnilnikih; kratek rok le za vir, ki se vedno tece.
                self._iskanje_nit.rok = self.rok_vira or 2.5
                svez = self.catalog(query, kind, genre, page, **(moznosti or {}))
            except Exception:  # noqa: BLE001
                return
            if not svez.get("vnosi"):
                return
            self._zapomni_katalog(kljuc, svez)
            if ob_osvezitvi is not None and self._odtis_vnosov(svez) != self._odtis_vnosov(delni):
                ob_osvezitvi(kljuc, dict(self._brez_zasebnih_rezultat(svez, kind), kljuc=kljuc, iz_predpomnilnika=False,
                                         osvezujem=False))

        threading.Thread(target=delo, name="media-dokoncaj", daemon=True).start()

    @staticmethod
    def _odtis_vnosov(rezultat: Optional[dict]) -> str:
        vnosi = (rezultat or {}).get("vnosi") or []
        return hashlib.sha1(json.dumps(vnosi, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"), usedforsecurity=False).hexdigest()

    def _osvezi_v_ozadju(self, kljuc: str, query: str, kind: str, genre: str, page: int, ob_osvezitvi=None,
                         moznosti: Optional[dict] = None) -> None:
        with self._predpomnilnik_lock:
            if kljuc in self._osvezujem:
                return
            self._osvezujem.add(kljuc)
            drzava = self.izbrana_drzava

        def delo() -> None:
            try:
                self.izbrana_drzava = drzava
                self._iskanje_nit.rok = None        # v ozadju pocakamo na vse vire
                svez = self.catalog(query, kind, genre, page, **(moznosti or {}))
                with self._predpomnilnik_lock:
                    star = (self._nalozi_predpomnilnik()["katalog"].get(kljuc) or {}).get("rezultat")
                if not svez.get("vnosi"):
                    return  # brez omrezja ali napaka vira: raje ohranimo zadnji dober pogled
                spremenjeno = self._odtis_vnosov(svez) != self._odtis_vnosov(star)
                self._zapomni_katalog(kljuc, svez)
                if spremenjeno and ob_osvezitvi is not None:
                    ob_osvezitvi(kljuc, dict(self._brez_zasebnih_rezultat(svez, kind), kljuc=kljuc,
                                             iz_predpomnilnika=False, osvezujem=False))
            except Exception:
                pass
            finally:
                with self._predpomnilnik_lock:
                    self._osvezujem.discard(kljuc)

        threading.Thread(target=delo, name="media-osvezi", daemon=True).start()

    def prednalozi(self, vrste: Iterable[str] = ("vse", "film", "serija", "glasba", "radio", "tv-v-zivo")) -> None:
        """Ob zagonu v ozadju pripravi prve strani glavnih pogledov, da je ze prvi klik takojsen."""
        def delo() -> None:
            for vrsta in vrste:
                kljuc = self.kljuc_kataloga("", vrsta, "", 1)
                with self._predpomnilnik_lock:
                    zapis = self._nalozi_predpomnilnik()["katalog"].get(kljuc) or {}
                if time.time() - float(zapis.get("cas") or 0) < self.SVEZE_SEKUND:
                    continue
                try:
                    self._iskanje_nit.rok = None    # predgretje v ozadju: vsi viri
                    rezultat = self.catalog("", vrsta, "", 1)
                    if rezultat.get("vnosi"):
                        self._zapomni_katalog(kljuc, rezultat)
                except Exception:
                    continue
        threading.Thread(target=delo, name="media-prednalozi", daemon=True).start()

    def isci_v_predpomnilniku(self, query: str, meja: int = 8) -> list[dict]:
        """Poišči za sprotne predloge brez omrežja in brez osveževanja kataloga."""
        iskano = _text(query, 120).casefold().strip()
        if not iskano:
            return []
        kandidati: list[dict] = []
        with self._predpomnilnik_lock:
            for kljuc_pogleda, zapis in self._nalozi_predpomnilnik()["katalog"].items():
                if self._je_zasebni_pogled(kljuc_pogleda):
                    continue                      # shranjeni pogledi kategorije »Zasebno«
                rezultat = zapis.get("rezultat") if isinstance(zapis, dict) else None
                if isinstance(rezultat, dict):
                    kandidati.extend(x for x in (rezultat.get("vnosi") or []) if isinstance(x, dict))
        # Uporabnikovi uvoženi viri so že na disku in zato prav tako ne povzročijo omrežnega klica.
        with self._lock:
            data = self._load()
        # Isti izbor kot katalog: brez mrtvih, zaklenjenih in »Not 24/7« kanalov ter brez stare razclenitve.
        kandidati.extend(self._vnosi_virov(data, "vse", preveri=False))

        # Predlogi iskanja nikoli ne pokazejo zasebne vsebine (tudi iz shranjenih pogledov kategorije »Zasebno«).
        kandidati = self.brez_zasebnih(kandidati)
        zadetki, videni = [], set()
        for item in kandidati:
            haystack = " ".join(str(item.get(k) or "") for k in ("naslov", "izvajalec", "album", "opis", "vrsta")).casefold()
            if iskano not in haystack:
                continue
            if not lastni_vir(item) and self.znano_ni_na_voljo(item):
                continue                          # noben vir ga ne predvaja (kot brez_nerazpolozljivih)
            if self.kanal_skrit(item):
                continue                          # kanal IPTV, ki ne oddaja (tudi iz shranjenih pogledov)
            kljuc = str(item.get("id") or (item.get("naslov"), item.get("vrsta")))
            if kljuc in videni:
                continue
            videni.add(kljuc)
            zadetki.append({k: item.get(k) for k in ("id", "naslov", "izvajalec", "opis", "vrsta", "slika") if item.get(k) is not None})
            if len(zadetki) >= max(1, min(int(meja or 8), 20)):
                break
        return zadetki

    @staticmethod
    def _default_roots() -> list[Path]:
        home, out = Path.home(), []
        for name in ("Music", "Glasba", "Videos", "Video", "Movies", "Filmi", "Pictures", "Slike"):
            path = home / name
            if path.is_dir() and path not in out:
                out.append(path)
        return out

    def _load(self) -> dict:
        data = None
        try:
            if self.store_path.exists():
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not isinstance(data, dict):
            data = {"viri": []}
        if not isinstance(data.get("viri"), list):
            data["viri"] = []
        return data

    def _beri_debrid(self) -> dict:
        try:
            d = json.loads((self.config_dir / "debrid.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        return d if isinstance(d, dict) else {}

    def _pisi_debrid(self, d: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        shramba_json.zapisi_besedilo_atomsko(str(self.config_dir / "debrid.json"), json.dumps(d, ensure_ascii=False))

    def _razresi_debrid(self, item_id: str, item: dict, t: dict, rezerve: list) -> dict:
        """Naloga 131: torrent prek debrid storitve. Uspeh: povezava CDN (brez kljuca) z oznako ⚡ in imenom storitve, za
        njo neposredne povezave kot rezerva. Neuspeh: napaka_koda »debrid_<razlog>« - nikoli tiho na neposreden torrent."""
        izid = self.debrid.tok(str(t["hash"]), t.get("indeks"), str(t.get("ime") or ""), t.get("sledilniki") or ())
        if not izid.url:
            return dict(item, napaka_koda="debrid_" + (izid.napaka or debrid_pravila.NAPAKA_STREZNIK))
        tok = {"url": izid.url, "vir": "%s %s" % (debrid_pravila.OZNAKA_PREDPOMNJEN, debrid_pravila.ime(izid.ponudnik)),
               "kakovost": str(t.get("kakovost") or ""), "opis": str(t.get("opis") or "")}
        razlicice = [tok] + list(rezerve[:9])
        resolved = dict(item, url=izid.url, razlicice=razlicice, stevilo_razlicic=len(razlicice), debrid=izid.ponudnik)
        self._dynamic_items[item_id] = resolved
        return resolved

    #: Iskanje Usenet (zadnje: (kljuc, Future)) - en zaklep za razred, iskanje je eno naenkrat.
    _usenet_zaklep = threading.Lock()

    # --- filter vira Usenet (lastnik 10. 11. 2026: kot TV, izbira »⚡ Usenet« filtrira mrezo in omeji predvajanje)
    @property
    def usenet_filter(self) -> "usenet_filter.UsenetFilter":
        f = self.__dict__.get("_usenet_filter")
        if f is None:
            with self._usenet_zaklep:
                f = self.__dict__.get("_usenet_filter")
                if f is None:
                    f = self.__dict__["_usenet_filter"] = usenet_filter.UsenetFilter(
                        self.config_dir / usenet_filter.IME_DATOTEKE, self.debrid)
        return f

    @property
    def usenet_filter_mreze(self) -> "usenet_filter.FilterMreze":
        m = self.__dict__.get("_usenet_filter_mreze")
        if m is None:
            m = self.__dict__["_usenet_filter_mreze"] = usenet_filter.FilterMreze(
                self.usenet_filter, self._kljuc_razpolozljivosti, self._stremio_naslov_vnosa,
                lambda: tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)))
        return m

    def samo_usenet(self) -> bool:
        try:
            return bool(self.debrid.samo_usenet())
        except Exception:  # noqa: BLE001 - brez nastavitev debrida filtra ni
            return False

    def _razresi_samo_usenet(self, item_id: str, item: dict, tip: str, ident: str) -> dict:
        """Izbran »⚡ Usenet« (TV izbranSamoUsenet): predvaja SAMO Usenet - brez torrentov, povezav dodatkov in Webtorja.
        0 izdaj: zapis filtra pozabimo (kartica izgine) in stran pove »ni na voljo prek Useneta«; meja ali izpad
        indeksatorja zapisa ne pozabita (TV UsenetIskanjePravila.pozabiZapis)."""
        f = self.usenet_filter
        tokovi = None
        izid = debrid.IzidIskanja(None, False, "ni_indeksatorja")
        if self._usenet_mogoc(tip, ident):
            # Klik ima prednost pred preverbami filtra (TV Del A): preverbe pocakajo, klik dobi rezervirano mesto kvote.
            f.zacni_klik()
            f.prednost_klika()
            try:
                ms = f.rezerviraj_iskanje()
                if ms is None:
                    izid = debrid.IzidIskanja(None, True, "meja")
                else:
                    if ms > 0:
                        f.spi(ms / 1000.0)
                    tokovi, izid = self.debrid.usenet_iskanje_tokov(ident)
                    f.izid_klika(izid.meja, izid.izdaje is not None)
            finally:
                f.prednost_klika_konec()
        razlog = filter_vira_pravila.razlog_iskanja(None if tokovi is None else len(tokovi), izid.meja)
        if tokovi:
            from concurrent.futures import Future
            vrstni = dict(self._jezik_zvoka(item)) if hasattr(self, "_jezik_zvoka") else {}
            urejeni = tok_izbira.uredi(tokovi, lambda t: str(t.get("opis") or ""),
                                       tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)),
                                       naslov=lambda t: "", **vrstni)
            # Iste izdaje vzame korak »Usenet takoj« - indeksatorja ne vprasamo dvakrat za isti klik.
            gotovo: Future = Future()
            gotovo.set_result(urejeni)
            with self._usenet_zaklep:
                self._usenet_iskanje = ((item_id, ident), gotovo)
            resolved = self._razresi_usenet_takoj(item_id, item, ident, [])
            if resolved:
                return resolved
        _sled_usenet = {filter_vira_pravila.RazlogIskanja.NI_IZDAJ: "indeksator ni dal izdaj",
                        filter_vira_pravila.RazlogIskanja.MEJA: "indeksator omejuje hitrost (meja)",
                        filter_vira_pravila.RazlogIskanja.NI_ODGOVORA: "indeksator ni odgovoril",
                        filter_vira_pravila.RazlogIskanja.NI_INDEKSATORJA: "ni indeksatorja",
                        filter_vira_pravila.RazlogIskanja.OK: "ni predvajljivega toka"}
        _log_media.info("tokovi: samo Usenet - %s", _sled_usenet.get(razlog, "?"))
        if filter_vira_pravila.pozabi_zapis(razlog):
            k = self.usenet_filter_mreze._kljuc(item)
            if k:
                f.pozabi(k)
            return dict(item, napaka_koda="usenet_ni_izdaj")
        return dict(item, napaka_koda="usenet_ne_odgovarja")

    def _usenet_mogoc(self, tip: str, ident: str) -> bool:
        """Usenet prek TorBoxa (naloga 141) pride v postev: film ali epizoda z id-jem IMDb, vpisan indeksator in TorBox."""
        if tip not in ("movie", "series") or not usenet_pravila.iscemo(ident) or not self.debrid.usenet_na_voljo():
            return False
        # Serija brez epizode (tt…) bi iskala film z istim id-jem; film z epizodno obliko pa ni film.
        return (tip == "series") == (":" in ident)

    def _usenet_zadetki(self, item_id: str, item: dict, ident: str, rok: Optional[float] = None) -> list:
        """Izdaje Usenet po kakovosti za to napravo (najboljsa predvajljiva prva). Indeksator vprasamo enkrat za vse korake
        (pripravljen, nato s cakanjem); iskanje, ki zamudi [rok], tece naprej v ozadju in ga naslednji korak pocaka."""
        kljuc_iskanja = (item_id, ident)
        with self._usenet_zaklep:
            zadnje = getattr(self, "_usenet_iskanje", None)
            if zadnje is None or zadnje[0] != kljuc_iskanja or (zadnje[1].done() and zadnje[1].exception() is not None):
                vrstni = dict(self._jezik_zvoka(item)) if hasattr(self, "_jezik_zvoka") else {}
                visina = int(getattr(self, "visina_zaslona", 0) or 1080)

                def isci() -> list:
                    z = self.debrid.usenet_isci(ident)
                    return tok_izbira.uredi(z, lambda t: str(t.get("opis") or ""), tok_izbira.Zmoznosti(visina=visina),
                                            naslov=lambda t: "", **vrstni) if z else []

                zadnje = (kljuc_iskanja, debrid.v_ozadju(isci))
                self._usenet_iskanje = zadnje
        try:
            return list(zadnje[1].result(timeout=rok) or [])
        except Exception:  # noqa: BLE001 - rok ali napaka indeksatorja: brez Useneta v tem koraku
            return []

    def _usenet_razreseno(self, item_id: str, item: dict, t: dict, izid, rezerve: list) -> dict:
        # Naloga 114: lasten pogon nima imena storitve (debrid_pravila.ime pozna samo debride).
        ime = "NNTP" if izid.ponudnik == debrid.LASTNI_USENET else debrid_pravila.ime(izid.ponudnik)
        tok = {"url": izid.url, "vir": "Usenet · " + ime, "opis": str(t.get("opis") or "")}
        razlicice = [tok] + list(rezerve[:9])
        resolved = dict(item, url=izid.url, razlicice=razlicice, stevilo_razlicic=len(razlicice), debrid=izid.ponudnik,
                        usenet=True)
        self._dynamic_items[item_id] = resolved
        return resolved

    def _razresi_usenet_takoj(self, item_id: str, item: dict, ident: str, rezerve: list,
                              rok: float = usenet_pravila.TAKOJ_ROK_S) -> Optional[dict]:
        """Lastnik 25. 10. 2026 (07:25): Usenet, ki ga ima TorBox ze pripravljenega, gre prvi - najboljsa kakovost in
        hitrost, placan. Rok [rok] skupaj z iskanjem pri indeksatorju (preverba ⚡ tece hkrati), prve tri izdaje."""
        konec = time.monotonic() + rok
        zadetki = self._usenet_zadetki(item_id, item, ident, rok)
        if zadetki and self.debrid.lastni_usenet_na_voljo():
            # Naloga 114: z lastnim ponudnikom NNTP je vsaka izdaja »takoj« (pretakamo neposredno, brez prenosa pri
            # TorBoxu); po vrsti kakovosti, najvec dva poskusa do 15 GB kot pri TorBoxu. En film naenkrat (vezava).
            for i in usenet_pravila.za_samodejno([float(t.get("gb") or 0.0) for t in zadetki]):
                t = zadetki[i]
                izid = self.debrid.usenet_tok(str(t["url"]), str(t.get("naslov") or ""), lastni=True)
                if izid.url:
                    return self._usenet_razreseno(item_id, item, t, izid, rezerve)
        ostane = konec - time.monotonic()
        if not zadetki or ostane <= 0.2:
            return None
        izbira = self.debrid.usenet_takoj(zadetki, ostane)
        if izbira is None:
            return None
        return self._usenet_razreseno(item_id, item, zadetki[izbira[0]], izbira[1], rezerve)

    def _razresi_usenet(self, item_id: str, item: dict, tip: str, ident: str, rezerve: list,
                        samo_takoj: bool = False) -> Optional[dict]:
        """Usenet prek TorBoxa (kot Safeer OS za Android, naloga 141): uporabnikov indeksator najde izdaje, TorBox jih
        prenese in pretaka. Samodejno najboljsa do 15 GB, najvec dva poskusa; povezave ostanejo rezerva. None = ni Useneta
        ali ni uspelo - takrat gre izbira naprej (debrid torrent, povezave) brez okna »Izberi vir«."""
        if not self._usenet_mogoc(tip, ident):
            return None
        zadetki = self._usenet_zadetki(item_id, item, ident)
        # Lasten pogon je ze poskusil prvi korak (naloga 114): tu samo TorBox, sicer dvakrat isto izdajo prek NNTP.
        # Brez lastnega pogona klic ostane enak kot prej (obstojeci nadomestki usenet_tok nimajo argumenta lastni).
        samo_torbox = {"lastni": False} if self.debrid.lastni_usenet_na_voljo() else {}
        for i in usenet_pravila.za_samodejno([float(t.get("gb") or 0.0) for t in zadetki]):
            t = zadetki[i]
            izid = self.debrid.usenet_tok(str(t["url"]), str(t.get("naslov") or ""), samo_takoj=samo_takoj,
                                          rok_cakanja=debrid_pravila.CAKAJ_NOVEGA_S, **samo_torbox)
            if izid.url:
                return self._usenet_razreseno(item_id, item, t, izid, rezerve)
        return None

    def _save(self, data: dict) -> None:
        if self._racuni_preseljeni:
            data["racuni_preseljeni"] = self.PRESELITEV_RACUNOV      # zapis te razlicice: selitev ni vec potrebna
        self.config_dir.mkdir(parents=True, exist_ok=True)
        shramba_json.zapisi_atomsko(self.store_path, data, indent=2)
        # Viri so se spremenili: shranjeni pogledi se ob naslednjem odprtju osvezijo v ozadju.
        if self._predpomnilnik is not None:
            self.ozastari_predpomnilnik()

    # --- razpolozljivost: prikazemo samo, kar se da predvajati -----------------
    NI_NA_VOLJO_VELJA = 6 * 3600        # dodatki dobivajo nove vsebine: "ni na voljo" velja nekaj ur

    JE_NA_VOLJO_VELJA = 24 * 3600       # preverjeno "je na voljo" v tem zagonu ne sprasujemo znova

    @staticmethod
    def _stremio_naslov_vnosa(item: dict) -> Optional[tuple]:
        """(koren, tip, ident) filma ali serije iz dodatka Stremio (tudi med razlicicami zdruzene kartice)."""
        for u in [str(item.get("url") or "")] + [str(v.get("url") or "") for v in (item.get("razlicice") or []) if isinstance(v, dict)]:
            if u.startswith("stremio:"):
                koren, tip, ident = (u[len("stremio:"):].split("|") + ["", ""])[:3]
                if koren and tip in ("movie", "series") and ident:
                    return koren, tip, ident
        return None

    @classmethod
    def _kljuc_razpolozljivosti(cls, item: dict) -> str:
        """Film po TMDB/IMDb; serija iz dodatka po svojem id-ju. Posamezne epizode in drugih vrst ne skrivamo
        (ostale epizode so morda na voljo)."""
        vrsta = str(item.get("vrsta") or "")
        if vrsta == "serija":
            naslov = cls._stremio_naslov_vnosa(item)
            return "serija:" + naslov[2] if naslov and naslov[1] == "series" and ":" not in naslov[2] else ""
        if vrsta != "film":
            return ""
        ident = str(item.get("tmdb_id") or "") if int(item.get("tmdb_id") or 0) else str(item.get("imdb_id") or item.get("id") or "")
        return "film:" + ident if ident else ""

    def _ni_na_voljo_beri(self) -> dict:
        if getattr(self, "_ni_na_voljo", None) is None:
            try:
                data = json.loads((self.config_dir / "ni_na_voljo-2.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            self._ni_na_voljo = {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        return self._ni_na_voljo

    def oznaci_ni_na_voljo(self, item: dict) -> None:
        kljuc = self._kljuc_razpolozljivosti(item)
        if not kljuc:
            return
        with self._lock:
            stanje = self._ni_na_voljo_beri()
            zdaj = time.time()
            for k in [k for k, v in stanje.items() if zdaj - v > self.NI_NA_VOLJO_VELJA]:
                stanje.pop(k, None)
            stanje[kljuc] = zdaj
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                shramba_json.zapisi_atomsko(self.config_dir / "ni_na_voljo-2.json", stanje, indent=None)
            except OSError:
                pass

    def znano_ni_na_voljo(self, item: dict) -> bool:
        kljuc = self._kljuc_razpolozljivosti(item) if isinstance(item, dict) else ""
        if not kljuc:
            return False
        cas = self._ni_na_voljo_beri().get(kljuc)
        return cas is not None and time.time() - cas <= self.NI_NA_VOLJO_VELJA

    @staticmethod
    def _predvajljivi(tokovi: list) -> bool:
        if any(t.get("url") and not t.get("zunanje")
               and (str(t["url"]).startswith("https://") or media_servers.dovoljen_naslov(str(t["url"]))) for t in tokovi):
            return True
        # Torrent (infoHash) je predvajljiv na racunalniku, ki zna prenasati torrente - kot na Androidu.
        return any(t.get("torrent") and t.get("hash") for t in tokovi) and os_torrent_tok.podprto()

    #: Najvec toliko casa iscemo tok med torrenti (branje metapodatkov slabo podprtega torrenta traja).
    TORRENT_ROK_S = 60.0

    def _motor(self) -> dict:
        """Argumenta za enkratni prenos predvajalnega programa (napredek, preklic), ce ju je lupina nastavila; nov
        poskus predvajanja pocisti prejsnji preklic."""
        dodatno = {}
        napredek = getattr(self, "ob_prenosu_motorja", None)
        preklic = getattr(self, "preklic_motorja", None)
        if napredek is not None:
            dodatno["motor_napredek"] = napredek
        if preklic is not None:
            preklic.clear()
            dodatno["motor_preklic"] = preklic
        return dodatno

    @staticmethod
    def _jezik_zvoka(item: dict) -> dict:
        """Zeleni jezik zvoka za izbiro toka (lastnik, 10. 10. 2026): film v anglescini, slovenski film v slovenscini.
        Glasba in radio: brez (jezik zvoka tam ni izbira toka)."""
        if str(item.get("vrsta") or "") not in ("film", "serija", "video", "vse", ""):
            return {}
        izvirni = str(item.get("jezik") or "")[:2]
        return {"zelen_jezik": tok_izbira.zeleni_jezik(izvirni), "izvirni": izvirni}

    def _p2p_potrjeni(self) -> set:
        """Pari (naslov, hash): torrent, ki ga je uporabnik v tem zagonu za ta naslov izrecno poslal v roj (»Predvajaj
        neposredno«, kot Android potrjenP2p). Samo v pomnilniku - nov zagon vprasa znova."""
        return self.__dict__.setdefault("_p2p_potrjeni_pari", set())

    def _p2p_dovoljeni(self, naslov: str, torrenti: list) -> list:
        """Torrenti, ki gredo v roj brez nove potrditve: samo tisti, ki jih je uporabnik v tem zagonu ze potrdil za TA
        naslov. Prazno = uporabnik mora izbrati (napaka_koda p2p_potrditev). Pregled Grok 28 L1 (lastnik: IP v roj samo
        po izrecni potrditvi za ta torrent): zapis rabe motorja NI privolitev - vanj so prisli tudi torrenti, ki so sli v
        roj tiho pred izbiro, in potrjeni iz prejsnjih zagonov (drugo omrezje, brez VPN); ena potrjena zgoscena vrednost
        tudi ne odobri vseh torrentov naslova ali istega paketa pri drugem naslovu."""
        potrjeni = self._p2p_potrjeni()
        return [t for t in torrenti if (naslov, str(t.get("hash") or "").lower()) in potrjeni]

    def _ima_webtor(self) -> bool:
        """Uporabnik ima dodatek na webtor.io (tudi nadomestek ohrani gostitelja) - brez omrezja; za gumb »Poskusi znova
        cez minuto« (Webtor nov tok najprej prenese sam: pomocnik Windows 25. 10. - cez nekaj minut odgovori v 0,3-3,6 s)."""
        try:
            return any(webtor.gostitelj(str(x.get("url") or "")) == webtor.GOSTITELJ for x in self._stremio_strezniki())
        except Exception:  # noqa: BLE001
            return False

    def _razresi_torrent(self, item: dict, tokovi: list, ob_roju: Optional[Callable[[str], None]] = None) -> dict:
        """Naslov, ki ga ponujajo samo torrenti: najboljsi torrent za to napravo prenasa motor Safeer OS, predvajalnik
        dobi lokalni tok ze med prenosom (core/os_torrent_tok.py). Brez toka: kratka koda napake, naslova ne skrijemo."""
        urejeni = tok_izbira.uredi(tokovi, lambda t: str(t.get("opis") or "%s %s" % (t.get("vir", ""), t.get("kakovost", ""))),
                                   tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)),
                                   **self._jezik_zvoka(item))
        obvesti = getattr(self, "ob_pripravi_torrenta", None)
        if obvesti is not None:
            try:
                obvesti(item)
            except Exception:
                pass
        zacetek = time.monotonic()
        koda = "tok"
        # Enkratni prenos predvajalnega programa: stran kaze napredek in ga lahko preklice (core/os_katalog.py).
        motor = self._motor()
        for i, t in enumerate(urejeni[:3]):
            if i and time.monotonic() - zacetek > self.TORRENT_ROK_S:
                break
            if ob_roju is not None:
                ob_roju(str(t["hash"]).lower())     # ta torrent gre v roj z uporabnikovo izrecno potrditvijo
            try:
                tok = os_torrent_tok.pripravi(str(t["hash"]), t.get("indeks"), str(t.get("ime") or ""), t.get("sledilniki") or (),
                                              **motor)
            except os_torrent.NapakaTorrenta as napaka:
                # Brez programa ali po preklicu naslednji torrent ne pomaga (in bi program prenasal znova).
                if str(napaka) in ("ni_prostora", "malo_pomnilnika", "motor", "preklicano"):
                    koda = str(napaka)
                    break
                continue
            except Exception:
                continue
            resolved = dict(item, url=tok["url"], torrent=True, stevilo_razlicic=1,
                            razlicice=[{"url": tok["url"], "vir": t.get("vir") or "Torrent", "kakovost": t.get("kakovost") or ""}])
            if tok.get("pot"):
                resolved["pot"] = tok["pot"]
            if tok.get("podnapisi") and not resolved.get("podnapisi"):
                resolved["podnapisi"] = list(tok["podnapisi"])
            if tok.get("zacasen"):
                self._zabelezi_knjiznico(item, str(t["hash"]), tok.get("indeks"))
            return resolved
        return dict(item, napaka_koda=koda)

    # --- knjiznica kroga: polica »Na tvojih napravah« -----------------------------
    def _koren_zaseben(self, koren: str) -> Optional[bool]:
        """Ali se dodatek v manifestu sam oznaci kot zaseben. None = ne vemo (manifesta ni bilo mogoce prebrati)."""
        koren = media_servers._stremio_koren(str(koren or ""))
        if not koren:
            return None
        znano = self._zasebni_koreni.get(koren)
        if znano is not None:
            return znano
        try:
            zaseben = media_servers.stremio_je_zaseben(media_servers.stremio_manifest(koren))
        except Exception:
            return None
        self._zasebni_koreni[koren] = zaseben
        return zaseben

    def _zabelezi_knjiznico(self, item: dict, hash_: str, indeks: Any) -> None:
        """Film, ki ga je Safeer OS zaradi gledanja prenesel sam: zapomnimo si naslov in plakat za polico - ali, ce ga je
        ponudil zaseben dodatek (ali tega ne vemo), samo oznako, da je zaseben."""
        try:
            # Odloca dodatek, ki je torrent ponudil. Naslov iz kataloga samega dodatka (ne iz javnega kataloga TMDB)
            # je zaseben tudi, ce je zaseben ta dodatek. Drugi dodatki na kartici so le mozne razlicice.
            koreni = []
            dodatek = (getattr(self._tokovi_odgovor, "dodatki_torrentov", None) or {}).get(str(hash_).lower())
            if dodatek:
                koreni.append(dodatek)
            stremio = item.get("stremio") if isinstance(item.get("stremio"), dict) else {}
            if stremio.get("koren") and not item.get("tmdb_id"):
                koreni.append(str(stremio["koren"]))
            stanja = [self._koren_zaseben(k) for k in dict.fromkeys(koreni)] if dodatek else []
            zaseben = True if any(z is True for z in stanja) else (None if (not stanja or any(z is None for z in stanja)) else False)
            knjiznica_kroga.zabelezi(hash_, knjiznica_kroga.opis_vnosa(item, zaseben),
                                     indeks if isinstance(indeks, int) else None)
        except Exception:
            pass

    def knjiznica_vnos(self, v: dict) -> dict:
        """Vnos police, ki ga hrani motor Safeer OS na tem racunalniku: predvaja se naravnost iz torrenta, brez dodatka.
        Vnos obdrzi oznako izvirnega naslova (`ref`), da se film nadaljuje tam, kjer je uporabnik ostal."""
        kljuc = str(v.get("kljuc") or "").lower()
        datoteka = v.get("datoteka")
        item = {"id": str(v.get("ref") or "") or "knjiznica:" + kljuc, "naslov": str(v.get("naslov") or ""),
                "vrsta": "serija" if v.get("vrsta") == "serija" else "film", "slika": str(v.get("slika") or ""),
                "url": "knjiznica:%s|%s" % (kljuc, datoteka if isinstance(datoteka, int) else ""),
                "vir": "", "kakovost": "", "opis": "", "leto": 0, "izvajalec": ""}
        self._dynamic_items["knjiznica:" + kljuc] = item
        return item

    def _razresi_knjiznico(self, item: dict) -> dict:
        hash_, _, datoteka = str(item.get("url") or "")[len("knjiznica:"):].partition("|")
        try:
            tok = os_torrent_tok.pripravi(hash_, int(datoteka) if datoteka.isdigit() else None, **self._motor())
        except os_torrent.NapakaTorrenta as napaka:
            return dict(item, napaka_koda=str(napaka) if str(napaka) in ("ni_prostora", "malo_pomnilnika", "motor", "preklicano") else "tok")
        except Exception:
            return dict(item, napaka_koda="tok")
        resolved = dict(item, url=tok["url"], torrent=True, stevilo_razlicic=1,
                        razlicice=[{"url": tok["url"], "vir": "Torrent", "kakovost": ""}])
        if tok.get("pot"):
            resolved["pot"] = tok["pot"]
        if tok.get("podnapisi"):
            resolved["podnapisi"] = list(tok["podnapisi"])
        return resolved

    def _na_voljo(self, koren: str, tip: str, ident: str) -> Optional[bool]:
        """True = kateri od dodatkov ima tok, False = vsi so odgovorili in nobeden nima, None = ne vemo (izpad)."""
        if tip == "series" and not media_servers.stremio_je_epizoda(ident):
            try:
                poskusi = media_servers.stremio_poskusne_epizode_z_imdb(koren, ident)
            except Exception:
                return None
            if not poskusi:
                return None
            neznano = False
            for epizoda, dodatni in poskusi:
                if self._predvajljivi(self._stremio_tokovi_vseh(koren, tip, epizoda, dodatni)):
                    return True
                if not getattr(self._tokovi_odgovor, "vsi", False):
                    neznano = True
            return None if neznano else False
        if self._predvajljivi(self._stremio_tokovi_vseh(koren, tip, ident)):
            return True
        return False if getattr(self._tokovi_odgovor, "vsi", False) else None

    @staticmethod
    def _ima_drug_vir(item: dict) -> bool:
        """Kartica ima tudi vir, ki ni dodatek (splet, javna last, osebni streznik): take ne preverjamo in ne skrivamo."""
        naslovi = [str(item.get("url") or "")] + [str(v.get("url") or "") for v in (item.get("razlicice") or []) if isinstance(v, dict)]
        return any(u.startswith(("http://", "https://", "file:", "/", "\\\\")) or (len(u) > 2 and u[1:3] == ":\\") for u in naslovi)

    def preveri_razpolozljivost(self, vnosi: Any, ob_ni=None, najvec: int = 40) -> int:
        """V ozadju preveri filme in serije, ki jih ponujajo samo dodatki Stremio (kot Safeer OS za Android):
        cesar noben dodatek ne predvaja, si zapomnimo in sporocimo z ob_ni(seznam id-jev kartic). Vrne stevilo
        naslovov, ki jih je dala v preverjanje."""
        if not isinstance(vnosi, list):
            return 0
        with self._lock:
            znano_je = self.__dict__.setdefault("_je_na_voljo", {})
            v_teku = self.__dict__.setdefault("_preverjam", set())
        zdaj = time.time()
        kandidati = []
        for item in vnosi:
            if not isinstance(item, dict):
                continue
            kljuc = self._kljuc_razpolozljivosti(item)
            if not kljuc or kljuc in v_teku or self.znano_ni_na_voljo(item) or zdaj - znano_je.get(kljuc, 0) < self.JE_NA_VOLJO_VELJA:
                continue
            naslov = self._stremio_naslov_vnosa(item)
            if not naslov or self._ima_drug_vir(item):
                continue
            kandidati.append((kljuc, item, naslov))
            if len(kandidati) >= najvec:
                break
        if not kandidati:
            return 0
        for kljuc, _, _ in kandidati:
            v_teku.add(kljuc)

        def eden(kandidat):
            kljuc, item, (koren, tip, ident) = kandidat
            try:
                return kljuc, item, self._na_voljo(koren, tip, ident)
            except Exception:
                return kljuc, item, None

        def delo():
            from concurrent.futures import ThreadPoolExecutor
            ni: list[str] = []
            zadnje = time.time()
            try:
                with ThreadPoolExecutor(max_workers=3) as bazen:
                    for kljuc, item, izid in bazen.map(eden, kandidati):
                        v_teku.discard(kljuc)
                        if izid is True:
                            znano_je[kljuc] = time.time()
                        elif izid is False:
                            self.oznaci_ni_na_voljo(item)
                            ni.append(str(item.get("id") or ""))
                        if ni and ob_ni is not None and time.time() - zadnje > 1.5:
                            ob_ni(ni); ni = []; zadnje = time.time()
            finally:
                for kljuc, _, _ in kandidati:
                    v_teku.discard(kljuc)
            if ni and ob_ni is not None:
                ob_ni(ni)

        threading.Thread(target=delo, name="safeer-razpolozljivost", daemon=True).start()
        return len(kandidati)

    def brez_nerazpolozljivih(self, rezultat: Any) -> Any:
        """Katalog brez filmov in serij, za katere vemo, da jih noben vir ne predvaja, in brez kartic dodatkov
        Kodija iz starega predpomnilnika (Safeer jih ne more poganjati, zato jih ne ponuja)."""
        if isinstance(rezultat, dict) and isinstance(rezultat.get("vnosi"), list):
            vnosi = [v for v in rezultat["vnosi"] if not (isinstance(v, dict) and (
                (self.znano_ni_na_voljo(v) and not lastni_vir(v))      # na lastnem strežniku je vedno na voljo
                or self.kanal_skrit(v)                                  # kanal IPTV, ki ne oddaja (core/kanali_iptv.py)
                or str(v.get("url") or "").startswith("kodi-dodatek:")))]
            if len(vnosi) != len(rezultat["vnosi"]):
                novo = dict(rezultat, vnosi=vnosi)
                if isinstance(rezultat.get("skupaj"), int):  # stevec nad mrezo naj se ujema s prikazanim
                    novo["skupaj"] = max(len(vnosi), rezultat["skupaj"] - (len(rezultat["vnosi"]) - len(vnosi)))
                return novo
        return rezultat

    # --- seznami predvajanja ---------------------------------------------------
    # Uporabnikovi seznami (uvozeni z YouTuba ali Spotifyja): svoja datoteka, da sprememba seznama ne osvezuje
    # kataloga virov. Skladba ima id posnetka (YouTube) ali pa ga poiscemo ob predvajanju in si ga zapomnimo.
    NAJVEC_SEZNAMOV = 30

    @property
    def pot_seznamov(self) -> Path:
        return self.config_dir / "seznami.json"

    def _seznami_beri(self) -> list[dict]:
        try:
            data = json.loads(self.pot_seznamov.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        vsi = [x for x in data if isinstance(x, dict) and x.get("ime") and isinstance(x.get("skladbe"), list)] \
            if isinstance(data, list) else []
        if not getattr(self, "_seznami_ocisceni", False):
            # Enkratna selitev: starejse razlicice so v seznam zapisale naslove s prijavo streznika (api_key, u/t/s).
            self._seznami_ocisceni = True
            if any(isinstance(s, dict) and (viri_sink.ima_prijavo(s.get("url")) or viri_sink.ima_prijavo(s.get("slika")))
                   for x in vsi for s in x["skladbe"]):
                with self._lock:
                    try:
                        self._seznami_pisi(vsi)
                    except OSError:
                        pass
                vsi = [dict(x, skladbe=[viri_sink.cista_skladba(s) for s in x["skladbe"]]) for x in vsi]
        if not getattr(self, "_zavrnjeni_obnovljeni", False):
            self._zavrnjeni_obnovljeni = True
            vsi = self._obnovi_zavrnjene(vsi)
        return vsi

    def _obnovi_zavrnjene(self, vsi: list[dict]) -> list[dict]:
        """Enkratna selitev (18. 10. 2026): do 1.0.127 je napaka strojnega dekoderja (VA-API) veljala za »vgradnja ni
        dovoljena« in posnetek s seznama YouTube je bil trajno zamenjan z drugim zadetkom iskanja. Na seznamih YouTube
        (tocni posnetki, vir YouTube) vrnemo izvirni posnetek (prvi zavrnjeni) in pozabimo zavrnitve."""
        spremenjeni = False
        for x in vsi:
            if x.get("vir") != "YouTube":
                continue
            popravljen = False
            for s in x["skladbe"]:
                zavrnjeni = s.get("zavrnjeni") if isinstance(s, dict) else None
                if not zavrnjeni or not isinstance(zavrnjeni, list) or not isinstance(zavrnjeni[0], str):
                    continue
                izvirni = zavrnjeni[0]
                if YOUTUBE_ID_VZOREC.match(izvirni):
                    s["youtube"] = izvirni
                    s["slika"] = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % izvirni
                s.pop("zavrnjeni", None)
                popravljen = True
            if popravljen:
                x["cas"] = self._nov_cas(x["ime"], int(x.get("cas") or 0))
                spremenjeni = True
        if spremenjeni:
            with self._lock:
                try:
                    self._seznami_pisi(vsi)
                except OSError:
                    pass
        return vsi

    @staticmethod
    def _zdaj_ms() -> int:
        return int(time.time() * 1000)

    def _nov_cas(self, ime: str, prej: int = 0) -> int:
        """Cas krajevne spremembe seznama (seznami_sink.nov_cas): ne starejsi od prejsnjega stanja in znanega izbrisa."""
        return seznami_sink.nov_cas(self._zdaj_ms(), prej, self._izbrisani_beri().get(ime) or 0)

    # Izbrisani seznami (ime -> cas izbrisa, ms): da se seznam ne vrne z naprave, ki ga se ima (core/seznami_sink.py).
    def _izbrisani_beri(self) -> dict:
        try:
            data = json.loads((self.config_dir / "seznami_izbrisani.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float)) and v > 0} if isinstance(data, dict) else {}

    def _izbrisani_pisi(self, izbrisani: dict) -> None:
        zadnji = dict(sorted(izbrisani.items(), key=lambda kv: kv[1], reverse=True)[:100])
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.config_dir / "seznami_izbrisani.json", zadnji, indent=None)
        except OSError:
            pass

    def _zapomni_izbris(self, ime: str, cas: int = 0) -> None:
        """cas > 0: seznam je izbrisan (kasnejsi cas zmaga); cas == 0: seznam je spet ustvarjen, izbris pozabimo."""
        izbrisani = self._izbrisani_beri()
        if cas <= 0:
            if izbrisani.pop(ime, None) is None:
                return
        else:
            if int(izbrisani.get(ime) or 0) >= cas:
                return
            izbrisani[ime] = cas
        self._izbrisani_pisi(izbrisani)

    def seznami_izvoz(self, parametri: Optional[dict] = None, ozji: bool = False) -> dict:
        """Odgovor na `lists.get` druge naprave v Safeer Linku: kazalo seznamov ali ena stran skladb seznama. `ozji`:
        naprava v ozjem krogu - samo ta dobi vire in tokove z racunom ponudnika (viri_sink.za_ozji_krog)."""
        parametri = parametri if isinstance(parametri, dict) else {}
        ime = str(parametri.get("ime") or "")
        with self._lock:
            vsi = [x for x in self._seznami_beri() if not x.get("zaseben")]   # seznami racuna YouTube ostanejo tukaj
            if not ime:
                # Vir seznama z naslovom (geslom) samo ozjemu krogu (pregled 46, Ö2; enako core/link_seznami.py).
                return dict({"lists": [{"ime": x["ime"], "vir": viri_sink.vir_seznama_za(x.get("vir"), ozji),
                                        "cas": int(x.get("cas") or 0), "stevilo": len(x["skladbe"])} for x in vsi],
                             "deleted": self._izbrisani_beri(), "ozji": ozji is True}, **self.viri_izvoz(ozji))
            sz = next((x for x in vsi if x["ime"] == ime), None)
        if not sz:
            return {"ime": ime, "stevilo": 0, "skladbe": []}
        try:
            od = max(0, int(parametri.get("od") or 0))
        except (TypeError, ValueError):
            od = 0
        polja = ("naslov", "izvajalec", "youtube", "sekund", "slika", "url", "video", "android")
        # Prijava streznika ne gre na druge naprave (enako core/link_seznami.py, skladba_za_napravo).
        skladbe = [{k: c[k] for k in polja if k in c} for c in
                   (viri_sink.skladba_za(s, ozji) for s in sz["skladbe"][od:od + seznami_sink.STRAN] if isinstance(s, dict))]
        return {"ime": sz["ime"], "vir": viri_sink.vir_seznama_za(sz.get("vir"), ozji), "cas": int(sz.get("cas") or 0),
                "stevilo": len(sz["skladbe"]), "od": od, "skladbe": skladbe}

    def seznami_uskladi(self, vprasaj) -> bool:
        """Prevzame novejse sezname, izbrise in Moje vire ene naprave v Linku (vprasaj(parametri) -> data ukaza
        `lists.get` ali None). Vrne True, ce se je tukaj kaj spremenilo."""
        zajeto: dict = {}

        def vprasaj_in_zajemi(parametri):
            r = vprasaj(parametri)
            if not parametri and isinstance(r, dict):
                zajeto["kazalo"] = r        # kazalo nosi tudi vire (sources, sources_deleted): ne vprasamo dvakrat
            return r
        if not self._izvoz_virov_zapisan:
            self._izvoz_virov_zapisan = True
            self._viri_zapisi_izvoz()       # za Safeer Control (Linux), ki napravam odgovarja namesto Safeer OS
        spremenjeno = self._seznami_uskladi(vprasaj_in_zajemi)
        try:
            # Id posiljatelja (safeer_os._seznami_z_naprav ga pripne vprasaju): brez njega dokaza o ozjem krogu ni.
            if self.viri_uskladi(zajeto.get("kazalo"), str(getattr(vprasaj, "id_naprave", "") or "")):
                spremenjeno = True
        except Exception as e:  # noqa: BLE001 - viri ne smejo ustaviti usklajevanja seznamov
            print("[SafeerMedia] viri z naprave:", type(e).__name__, flush=True)
        return spremenjeno

    def _seznami_uskladi(self, vprasaj) -> bool:
        with self._lock:
            vsi, izbrisani = self._seznami_beri(), self._izbrisani_beri()
        # Zasebni seznami (racun YouTube) se usklajevanja ne udelezijo: izbris ali seznam z istim imenom z druge
        # naprave jih ne spremeni.
        zasebni = [x for x in vsi if x.get("zaseben")]
        imena = {x["ime"] for x in zasebni}
        moji = [x for x in vsi if not x.get("zaseben")]
        # Omrezje brez zaklepa (naprava lahko odgovarja pocasi); zapis nazaj le, ce se seznami vmes niso spremenili.
        novi, novi_izbrisani, spremenjeno = seznami_sink.prevzemi_od(vprasaj, moji, izbrisani, uvoz_seznama.NAJVEC)
        novi = [x for x in novi if x.get("ime") not in imena]
        if not spremenjeno and novi_izbrisani == izbrisani:
            return False
        with self._lock:
            if self._seznami_beri() != vsi:
                return False        # uporabnik je vmes sam spremenil seznam: uskladimo ob naslednji priloznosti
            if spremenjeno:
                self._seznami_pisi(novi + zasebni)
            if novi_izbrisani != izbrisani:
                self._izbrisani_pisi(novi_izbrisani)
        return spremenjeno

    def _seznami_pisi(self, seznami: list[dict]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Edina pot zapisa seznamov: prijava streznika (zeton, geslo) nikoli ne pride na disk ne na druge naprave.
        cisti = [dict(x, skladbe=[viri_sink.cista_skladba(s) for s in x["skladbe"]]) if isinstance(x.get("skladbe"), list) else x
                 for x in seznami[:self.NAJVEC_SEZNAMOV] if isinstance(x, dict)]
        shramba_json.zapisi_atomsko(self.pot_seznamov, cisti, indent=None)

    @staticmethod
    def _seznam_vnos(ime: str, vir: str, s: dict) -> dict:
        kljuc = "%s|%s" % (s.get("izvajalec") or "", s.get("naslov") or "")
        yt = str(s.get("youtube") or "")
        return {
            "id": "seznam:" + hashlib.sha1((ime + "\n" + kljuc).encode("utf-8"), usedforsecurity=False).hexdigest()[:20],
            "naslov": str(s.get("naslov") or ""), "izvajalec": str(s.get("izvajalec") or ""),
            "slika": str(s.get("slika") or ""), "vrsta": "glasba", "vir": vir or "Seznam", "vir_id": "seznam",
            # Posnetek z YouTuba ali (skladba, dodana iz kataloga) njen neposredni naslov.
            "url": ("https://www.youtube.com/watch?v=" + yt) if yt else str(s.get("url") or ""), "youtube": yt,
            "seznam": ime, "sekund": int(s.get("sekund") or 0),
            # Skladba osebnega streznika: naslov je shranjen brez prijave, doda jo s_prijavo (ob prikazu in predvajanju).
            "streznik": str(s.get("streznik") or ""),
        }

    def _seznam_vnos_s_prijavo(self, ime: str, vir: str, s: dict, prijave: Optional[list] = None) -> dict:
        vnos = self._seznam_vnos(ime, vir, s)
        if s.get("prijava") or s.get("streznik"):
            vnos = self._vnos_s_prijavo(vnos, vnos["streznik"], prijave)
        return vnos

    def seznami(self) -> list[dict]:
        """Seznami predvajanja za prikaz: ime, izvor, stevilo skladb in slika (ovitek prve skladbe)."""
        with self._lock:
            vsi = self._seznami_beri()
        prijave: Optional[list] = None
        izid = []
        for x in vsi:
            prva = next((s for s in x["skladbe"] if isinstance(s, dict) and s.get("slika")), None)
            slika = str((prva or {}).get("slika") or "")
            if prva and (prva.get("prijava") or prva.get("streznik")):
                prijave = self._prijave_streznikov() if prijave is None else prijave
                slika = self.s_prijavo(slika, str(prva.get("streznik") or ""), prijave)
            izid.append({"ime": x["ime"], "vir": x.get("vir") or "", "stevilo": len(x["skladbe"]), "slika": slika})
        return izid

    def seznam(self, ime: str) -> dict:
        """Skladbe seznama kot vnosi kataloga (kartice, vrsta predvajanja)."""
        with self._lock:
            sz = next((x for x in self._seznami_beri() if x["ime"] == ime), None)
            if not sz:
                return {"ime": ime, "vnosi": []}
            skladbe = [s for s in sz["skladbe"] if isinstance(s, dict)]
            prijave = self._prijave_streznikov() if any(s.get("prijava") or s.get("streznik") for s in skladbe) else []
            vnosi = [self._seznam_vnos_s_prijavo(sz["ime"], sz.get("vir") or "", s, prijave) for s in skladbe]
            for v in vnosi:
                self._dynamic_items[v["id"]] = v
            return {"ime": sz["ime"], "vir": sz.get("vir") or "", "vnosi": vnosi}

    def uvozi_seznam(self, vnos: str) -> dict:
        """Uvozi javni seznam z YouTuba ali Spotifyja; isto ime zamenja obstojecega (ponoven uvoz = osvezitev)."""
        uvoz, razlog = uvoz_seznama.uvozi_z_razlogom(vnos)
        zaseben = False
        if razlog == "zaseben" and self.yt_racun.prijavljen():
            # Zaseben seznam (Vseckani, Pozneje ...): prijavljen uporabnik ga prebere s svojim racunom.
            try:
                uvoz, razlog = self.yt_racun.seznam(uvoz_seznama.youtube_id(uvoz_seznama.povezava_iz(vnos) or vnos)), ""
            except youtube_racun.PoteklaPrijava:
                return {"napaka": "potekla"}
            except Exception as e:  # noqa: BLE001
                print("[SafeerMedia] zaseben seznam:", type(e).__name__, flush=True)
                uvoz = None
            zaseben = True
        if razlog or not uvoz:
            return {"napaka": razlog or "ni_uspel"}
        ime = str(uvoz.get("ime") or uvoz.get("vir") or "Seznam")[:60]
        with self._lock:
            vsi = self._seznami_beri()
            prej = next((int(x.get("cas") or 0) for x in vsi if x["ime"] == ime), 0)
            ostali = [x for x in vsi if x["ime"] != ime]
            self._seznami_pisi([dict({"ime": ime, "vir": uvoz.get("vir") or "", "cas": self._nov_cas(ime, prej), "skladbe": uvoz["skladbe"]},
                                     **({"zaseben": True} if zaseben else {}))] + ostali)
            self._zapomni_izbris(ime)
        return {"ime": ime, "stevilo": len(uvoz["skladbe"]), "vir": uvoz.get("vir") or ""}

    # ------------------------------------------------------------------ racun YouTube (prijava v Spletu)
    # Lastnik 17. 10. 2026: uporabnik, ki to zeli, se v Spletu prijavi v YouTube in predvaja vse svoje sezname
    # (core/youtube_racun.py). Seznami racuna ostanejo na napravi: shranjeni dobijo "zaseben" in ne gredo v Link.

    @property
    def yt_racun(self) -> "youtube_racun.Racun":
        racun = getattr(self, "_yt_racun", None)
        if racun is None:
            racun = self._yt_racun = youtube_racun.Racun()
        return racun

    def yt_stanje(self) -> dict:
        st = self.yt_racun.stanje()
        if st.get("prijavljen") and st.get("racuni"):
            self._yt_uskladi_v_ozadju(st["racuni"])
        return st

    #: Seznami racunov YouTube se samodejno prenesejo med sezname Medijskega centra in prek Safeer Link na vse
    #: uporabnikove naprave (lastnik 17. 10. 2026: prijava enkrat, poslusanje povsod). Najvec na toliko sekund.
    YT_USKLADI_S = 6 * 60 * 60

    def _yt_ime_shranjenega(self, ime: str, racun_ime: str, vec_racunov: bool) -> str:
        ime = str(ime or "YouTube")[:60]
        return ("%s · %s" % (ime, racun_ime))[:60] if vec_racunov and racun_ime else ime

    def _yt_uskladi_v_ozadju(self, racuni: list) -> None:
        zdaj = time.time()
        with self._lock:
            if getattr(self, "_yt_uskladujem", False) or zdaj - getattr(self, "_yt_uskladeno", 0) < self.YT_USKLADI_S:
                return
            self._yt_uskladujem = True

        def delo():
            try:
                vec = len(racuni) > 1
                posebna = {"LL": "Všečkani videoposnetki", "WL": "Oglej si pozneje", "LM": "YouTube Music – všečkano"}
                for r in racuni:
                    for x in r.get("seznami") or []:
                        try:
                            sz = self.yt_racun.seznam(x["id"], int(r.get("racun") or 0))
                        except youtube_racun.PoteklaPrijava:
                            return
                        except Exception:  # noqa: BLE001 - en seznam ne ustavi drugih
                            continue
                        if not sz or not sz.get("skladbe"):
                            continue
                        ime = posebna.get(x.get("posebni") or "", sz.get("ime") or x.get("ime") or "YouTube")
                        self._yt_zapisi(self._yt_ime_shranjenega(ime, r.get("ime") or "", vec), sz["skladbe"],
                                        kljuc="%s|%s" % (r.get("ime") or int(r.get("racun") or 0), x["id"]), osnova=ime)
                with self._lock:
                    self._yt_uskladeno = time.time()
            finally:
                with self._lock:
                    self._yt_uskladujem = False
        threading.Thread(target=delo, name="safeer-yt-uskladi", daemon=True).start()

    def _yt_zapisi(self, ime: str, skladbe: list, kljuc: str = "", osnova: str = "") -> None:
        """Seznam racuna med seznami Medijskega centra - NI zaseben: gre prek Linka na uporabnikove naprave.
        Seznama, ki ga je uporabnik izbrisal, samodejno usklajevanje ne vrne (izbris ima prednost).

        kljuc (racun|id seznama) ga drzi istega, tudi ko se ime spremeni (drug racun doda pripono » · racun«) - brez
        tega je vsak nov racun podvojil vse sezname (preizkus 17. 10. 2026). Ob tem izginejo starejse kopije istega
        seznama brez kljuca (isto ime ali ime z pripono in iste skladbe)."""
        posnetki = [s.get("youtube") for s in skladbe]
        osnova = osnova or ime
        def kopija(x: dict) -> bool:
            return (not x.get("yt_kljuc") and x.get("vir") == "YouTube"
                    and (x["ime"] == osnova or x["ime"] == ime or x["ime"].startswith(osnova + " · "))
                    and [s.get("youtube") for s in x.get("skladbe", [])] == posnetki)
        with self._lock:
            vsi = self._seznami_beri()
            obstaja = next((x for x in vsi if kljuc and x.get("yt_kljuc") == kljuc), None) \
                or next((x for x in vsi if x["ime"] == ime), None)
            if obstaja is None and int(self._izbrisani_beri().get(ime) or 0) > 0:
                return
            kopije = [x for x in vsi if x is not obstaja and kljuc and kopija(x)]
            if obstaja is not None and not kopije and obstaja["ime"] == ime and (obstaja.get("yt_kljuc") or "") == kljuc \
                    and [s.get("youtube") for s in obstaja.get("skladbe", [])] == posnetki:
                return                                   # brez spremembe: ne pisemo (in ne budimo Linka)
            prej = int((obstaja or {}).get("cas") or 0)
            ostali = [x for x in vsi if x is not obstaja and x["ime"] != ime and not any(x is k for k in kopije)]
            nov = {"ime": ime, "vir": "YouTube", "cas": self._nov_cas(ime, prej), "skladbe": skladbe}
            if kljuc:
                nov["yt_kljuc"] = kljuc
            self._seznami_pisi([nov] + ostali)
            # Odstranjene kopije ne smejo prek Linka priti nazaj z drugih naprav (izbris z casom, kot ob brisanju).
            for k in kopije:
                if k["ime"] != ime:
                    self._zapomni_izbris(k["ime"], self._nov_cas(k["ime"], int(k.get("cas") or 0)))

    def yt_seznam(self, ident: str, racun: int = 0) -> dict:
        """Seznam racuna za predvajanje (vnosi kot pri shranjenih seznamih) ali {"napaka": "potekla"|"ni_uspel"}."""
        try:
            sz = self.yt_racun.seznam(ident, racun)
        except youtube_racun.PoteklaPrijava:
            return {"napaka": "potekla"}
        except Exception as e:  # noqa: BLE001 - omrezje ali spremenjen odgovor: sporocilo, ne sesutje
            print("[SafeerMedia] seznam racuna YouTube:", type(e).__name__, flush=True)
            sz = None
        if not sz or not sz.get("skladbe"):
            return {"napaka": "ni_uspel"}
        ime = str(sz["ime"])[:60]
        kljuc = "%d:%s" % (int(racun), ident)
        with self._lock:
            self._yt_prebrani = dict(getattr(self, "_yt_prebrani", {}), **{kljuc: sz})
        vnosi = [self._seznam_vnos(ime, "YouTube", s) for s in sz["skladbe"]]
        for v in vnosi:
            self._dynamic_items[v["id"]] = v
        return {"ime": ime, "vir": "YouTube", "vnosi": vnosi, "yt": str(ident), "yt_racun": int(racun)}

    def yt_shrani(self, ident: str, racun: int = 0, ime: str = "") -> dict:
        """Prebrani seznam racuna shrani med sezname Medijskega centra (gre tudi na uporabnikove naprave v Linku)."""
        with self._lock:
            sz = getattr(self, "_yt_prebrani", {}).get("%d:%s" % (int(racun), ident))
        if not sz:
            return {"napaka": "ni_mogoce"}
        ime = str(ime or sz["ime"])[:60]
        with self._lock:
            self._zapomni_izbris(ime)
        self._yt_zapisi(ime, sz["skladbe"])
        return {"ok": True, "ime": ime, "stevilo": len(sz["skladbe"])}

    # ------------------------------------------------------------------ Twitch (core/twitch.py)
    # Lastnik 17. 10. 2026: Twitch v nasem predvajalniku, oglase izloci Scit (core/twitch_hls.py). Vnosi so dinamicni
    # (ne gredo na police ne v Link); kanali, ki jim prijavljen uporabnik sledi, se ne shranjujejo.

    @property
    def twitch(self) -> "twitch.Twitch":
        tw = getattr(self, "_twitch", None)
        if tw is None:
            tw = self._twitch = twitch.Twitch(nastavitve=str(self.config_dir / "twitch.json"))
            tw.visina_zaslona = int(getattr(self, "visina_zaslona", 0) or 1080)
        return tw

    def _twitch_zapomni(self, vnosi: list) -> list:
        for v in vnosi:
            self._dynamic_items[v["id"]] = v
        return vnosi

    def twitch_katalog(self, query: str = "", kategorija: str = "") -> dict:
        """Zavihek Twitch: iskanje kanalov ali priljubljeni prenosi (v izbrani kategoriji). Napaka omrezja -> prazno."""
        try:
            izid = self.twitch.isci(query) if str(query or "").strip() else self.twitch.priljubljeni(kategorija)
        except Exception as e:  # noqa: BLE001 - omrezje ali spremenjen GQL: prazen katalog, nic se ne sesuje
            print("[SafeerMedia] Twitch katalog:", type(e).__name__, flush=True)
            izid = {"vnosi": []}
        vnosi = self._twitch_zapomni(list(izid.get("vnosi") or []))
        return {"vnosi": vnosi, "skupaj": len(vnosi), "skupaj_strani": 1, "kljuc": "twitch|%s|%s" % (query, kategorija)}

    def twitch_kategorije(self) -> list[dict]:
        try:
            return self.twitch.kategorije()
        except Exception as e:  # noqa: BLE001
            print("[SafeerMedia] Twitch kategorije:", type(e).__name__, flush=True)
            return []

    def twitch_posnetki(self, login: str) -> dict:
        """Posnetki kanala kot seznam za mrezo kataloga ({"ime", "vnosi", "twitch": True}) ali {"napaka"}."""
        try:
            p = self.twitch.posnetki(login)
        except Exception as e:  # noqa: BLE001
            print("[SafeerMedia] Twitch posnetki:", type(e).__name__, flush=True)
            return {"napaka": "ni_uspel"}
        if not p.get("vnosi"):
            return {"napaka": "ni_posnetkov", "ime": p.get("ime") or ""}
        return {"ime": p["ime"], "vir": "Twitch", "vnosi": self._twitch_zapomni(p["vnosi"]), "twitch": True}

    def twitch_stanje(self) -> dict:
        st = self.twitch.stanje()
        self._twitch_zapomni(st.get("kanali") or [])
        return st

    def _razresi_twitch(self, item: dict) -> dict:
        try:
            r = self.twitch.predvajaj(item)
        except Exception as e:  # noqa: BLE001
            print("[SafeerMedia] Twitch predvajanje:", type(e).__name__, flush=True)
            r = None
        if not r or r.get("napaka_koda"):
            return dict(item, napaka_koda=(r or {}).get("napaka_koda") or "tok")
        return dict(item, url=r["url"], kakovost=r.get("kakovost") or "", razlicice=[], stevilo_razlicic=0)
    # ------------------------------------------------------------------ Spotify (skrit Safeer DRM)
    # Lastnik 17. 10. 2026: Spotify se predvaja v Medijskem centru prek Safeer DRM (core/spotify_racun.py). Seznami
    # racuna, ki jih uporabnik shrani, so "zaseben" (kot YouTube) in ostanejo na tej napravi.

    @property
    def spotify(self) -> "spotify_racun.Racun":
        racun = getattr(self, "_spotify", None)
        if racun is None:
            racun = self._spotify = spotify_racun.Racun(str(self.config_dir))
            # Sprememba skladbe ali predvajanja: Safeer OS jo takoj pokaze na namizju in v MPRIS (ob_spotify).
            racun.ob_spremembi = lambda: (getattr(self, "ob_spotify", None) or (lambda: None))()
        return racun

    def sp_vnos(self, ime: str, s: dict, kontekst: str) -> dict:
        """Skladba ali epizoda racuna Spotify kot vnos kataloga (kartica); predvaja jo skrit Safeer DRM."""
        uri = str(s.get("spotify") or "")
        return {"id": "spotify:" + hashlib.sha1((kontekst + "\n" + uri).encode("utf-8"), usedforsecurity=False).hexdigest()[:20],
                "naslov": str(s.get("naslov") or ""), "izvajalec": str(s.get("izvajalec") or ""),
                "slika": str(s.get("slika") or ""), "vrsta": "glasba", "vir": "Spotify", "vir_id": "spotify",
                "url": "", "spotify": uri, "spotify_kontekst": kontekst, "sekund": int(s.get("sekund") or 0), "seznam": ime}

    def sp_seznam(self, ident: str, ime: str = "") -> dict:
        sz = self.spotify.seznam(ident)
        if sz.get("napaka"):
            return sz
        if not sz.get("skladbe"):
            return {"napaka": "prazen"}
        ime = (ime or str(sz.get("ime") or "") or "Spotify")[:60]
        sz = dict(sz, ime=ime)
        with self._lock:
            self._sp_prebrani = dict(getattr(self, "_sp_prebrani", {}), **{str(ident): sz})
        vnosi = [self.sp_vnos(ime, s, str(sz.get("kontekst") or "")) for s in sz["skladbe"]]
        for v in vnosi:
            self._dynamic_items[v["id"]] = v
        return {"ime": ime, "vir": "Spotify", "vnosi": vnosi, "sp": str(ident), "kontekst": sz.get("kontekst") or ""}

    def sp_shrani(self, ident: str) -> dict:
        """Prebrani seznam racuna Spotify med sezname Medijskega centra (zaseben: samo na tej napravi). Skladbe nosijo
        naslov spotify:...; brez Safeer DRM jih Medijski center poisce na YouTubu (kot uvozen javni seznam)."""
        with self._lock:
            sz = getattr(self, "_sp_prebrani", {}).get(str(ident))
        if not sz:
            return {"napaka": "ni_mogoce"}
        ime = str(sz["ime"])[:60]
        with self._lock:
            vsi = self._seznami_beri()
            prej = next((int(x.get("cas") or 0) for x in vsi if x["ime"] == ime), 0)
            ostali = [x for x in vsi if x["ime"] != ime]
            self._seznami_pisi([{"ime": ime, "vir": "Spotify", "cas": self._nov_cas(ime, prej), "zaseben": True,
                                 "skladbe": sz["skladbe"][:uvoz_seznama.NAJVEC]}] + ostali)
            self._zapomni_izbris(ime)
        self.poisci_posnetke(ime)
        return {"ok": True, "ime": ime, "stevilo": len(sz["skladbe"])}

    def shrani_seznam(self, ime: str, skladbe: list) -> dict:
        """Samodejni seznam »Shrani kot seznam«: navaden seznam predvajanja z istimi skladbami (isto ime ga zamenja,
        kot ponoven uvoz). Skladbe imajo svoj naslov (datoteka ali tok), zato posnetkov ni treba iskati."""
        ime = str(ime or "").strip()[:60]
        skladbe = [s for s in (skladbe or []) if isinstance(s, dict) and s.get("naslov") and
                   str(s.get("url") or "").startswith(("http://", "https://", "file:"))][:uvoz_seznama.NAJVEC]
        if not ime or not skladbe:
            return {"napaka": "ni_mogoce"}
        with self._lock:
            vsi = self._seznami_beri()
            prej = next((int(x.get("cas") or 0) for x in vsi if x["ime"] == ime), 0)
            ostali = [x for x in vsi if x["ime"] != ime]
            self._seznami_pisi([{"ime": ime, "vir": "", "cas": self._nov_cas(ime, prej), "skladbe": skladbe}] + ostali)
            self._zapomni_izbris(ime)
        return {"ok": True, "ime": ime, "stevilo": len(skladbe)}

    def poisci_posnetke(self, ime: str, ob_koncu=None) -> None:
        """
        Uvozenim skladbam brez posnetka (Spotify) v ozadju poisce posnetke: seznam dobi slike posameznih skladb in
        predvajanje zacne brez iskanja. Uporabnik ne caka - seznam je ze odprt in predvajljiv.
        """
        def delo() -> None:
            with self._lock:
                sz = next((x for x in self._seznami_beri() if x["ime"] == ime), None)
            cakajo = [s for s in (sz or {}).get("skladbe", []) if isinstance(s, dict) and not s.get("youtube") and not s.get("url")]
            if not cakajo:
                return
            from concurrent.futures import ThreadPoolExecutor

            def ena(s: dict) -> tuple[str, str, str]:
                try:
                    return (str(s.get("naslov") or ""), str(s.get("izvajalec") or ""),
                            uvoz_seznama.najdi(str(s.get("naslov") or ""), str(s.get("izvajalec") or ""), int(s.get("sekund") or 0)))
                except Exception:
                    return (str(s.get("naslov") or ""), str(s.get("izvajalec") or ""), "")

            with ThreadPoolExecutor(max_workers=3) as bazen:
                najdeni = {(n, i): yt for n, i, yt in bazen.map(ena, cakajo) if yt}
            if not najdeni:
                return
            with self._lock:
                vsi = self._seznami_beri()
                for x in vsi:
                    if x["ime"] != ime:
                        continue
                    for y in x["skladbe"]:
                        yt = isinstance(y, dict) and not y.get("youtube") and najdeni.get((y.get("naslov"), y.get("izvajalec")))
                        if yt:
                            y["youtube"] = yt
                            y["slika"] = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % yt
                    x["cas"] = self._nov_cas(ime, int(x.get("cas") or 0))      # najdeni posnetki so sprememba: druge naprave jih dobijo z usklajevanjem
                self._seznami_pisi(vsi)
            if ob_koncu:
                try:
                    ob_koncu(ime)
                except Exception:
                    pass

        threading.Thread(target=delo, daemon=True, name="safeer-seznam-posnetki").start()

    def dodaj_na_seznam(self, ime: str, item_id: str) -> dict:
        """Skladbo (s seznama ali iz kataloga) doda na konec seznama [ime]; seznam ustvari, ce ga se ni."""
        ime = str(ime or "").strip()[:60]
        if not ime:
            return {"napaka": "ime"}
        zapis: Optional[dict] = None
        if str(item_id).startswith("seznam:"):
            with self._lock:
                for sz in self._seznami_beri():
                    for s in sz["skladbe"]:
                        if isinstance(s, dict) and self._seznam_vnos(sz["ime"], sz.get("vir") or "", s)["id"] == item_id:
                            zapis = {k: s[k] for k in ("naslov", "izvajalec", "youtube", "slika", "sekund", "url",
                                                       "streznik", "prijava") if k in s}
        else:
            vnos = self._dynamic_items.get(item_id)
            url = str((vnos or {}).get("url") or "")
            if vnos and str(vnos.get("vrsta") or "") in ("glasba", "podcast", "podkast") and url.startswith(("http://", "https://", "file:")):
                zapis = {"naslov": str(vnos.get("naslov") or ""), "izvajalec": str(vnos.get("izvajalec") or ""),
                         "youtube": "", "slika": str(vnos.get("slika") or ""), "sekund": 0, "url": url}
                streznik = media_servers.streznik_iz_id(item_id)
                if streznik:        # prijavo (zeton) odstrani _seznami_pisi; ob predvajanju jo doda ta streznik
                    zapis["streznik"] = streznik
        if not zapis or not zapis.get("naslov"):
            return {"napaka": "ni_mogoce"}
        with self._lock:
            vsi = self._seznami_beri()
            cilj = next((x for x in vsi if x["ime"] == ime), None)
            nov = cilj is None
            if nov:
                cilj = {"ime": ime, "vir": "", "skladbe": []}
                vsi.insert(0, cilj)
            if any(isinstance(y, dict) and y.get("naslov") == zapis["naslov"] and y.get("izvajalec") == zapis.get("izvajalec")
                   for y in cilj["skladbe"]):
                return {"ze": True, "ime": ime}
            cilj["skladbe"] = (cilj["skladbe"] + [zapis])[-uvoz_seznama.NAJVEC:]
            cilj["cas"] = self._nov_cas(ime, int(cilj.get("cas") or 0))
            self._seznami_pisi(vsi)
            if nov:
                self._zapomni_izbris(ime)
        return {"ok": True, "ime": ime}

    def odstrani_s_seznama(self, ime: str, item_id: str) -> bool:
        """Odstrani skladbo s seznama; prazen seznam izgine."""
        with self._lock:
            vsi = self._seznami_beri()
            spremenjeno = False
            for sz in vsi:
                if sz["ime"] != ime:
                    continue
                ostale = [s for s in sz["skladbe"]
                          if not (isinstance(s, dict) and self._seznam_vnos(sz["ime"], sz.get("vir") or "", s)["id"] == item_id)]
                spremenjeno = len(ostale) != len(sz["skladbe"])
                sz["skladbe"] = ostale
                if spremenjeno:
                    sz["cas"] = self._nov_cas(ime, int(sz.get("cas") or 0))
            if spremenjeno:
                self._seznami_pisi([x for x in vsi if x["skladbe"]])
                for x in vsi:
                    if not x["skladbe"]:        # prazen seznam izgine: to je izbris, ki ga dobijo tudi druge naprave
                        self._zapomni_izbris(x["ime"], int(x.get("cas") or 0) or self._zdaj_ms())
            return spremenjeno

    def odstrani_seznam(self, ime: str) -> bool:
        with self._lock:
            vsi = self._seznami_beri()
            ostali = [x for x in vsi if x["ime"] != ime]
            if len(ostali) == len(vsi):
                return False
            prej = max(int(x.get("cas") or 0) for x in vsi if x["ime"] == ime)
            self._seznami_pisi(ostali)
            self._zapomni_izbris(ime, self._nov_cas(ime, prej))
            return True

    def seznam_posnetek(self, item_id: str, zamenjaj: bool = False) -> Optional[dict]:
        """
        Skladba seznama s posnetkom: uvozeni skladbi brez posnetka (Spotify) ga poiscemo in si ga zapomnimo.
        [zamenjaj]: trenutnega posnetka ni mogoce predvajati (lastnik ne dovoli vgradnje) - poiscemo drugega.
        """
        with self._lock:
            vsi = self._seznami_beri()
            zadetek = None
            for sz in vsi:
                for s in sz["skladbe"]:
                    if isinstance(s, dict) and self._seznam_vnos(sz["ime"], sz.get("vir") or "", s)["id"] == item_id:
                        zadetek = (sz, s)
                        break
                if zadetek:
                    break
        if not zadetek:
            # Neshranjen seznam racuna YouTube (yt_seznam): posnetek je znan, vnos je v _dynamic_items.
            vnos = self._dynamic_items.get(item_id)
            return vnos if vnos and vnos.get("youtube") and not zamenjaj else None
        sz, s = zadetek
        stari = str(s.get("youtube") or "")
        if (stari and not zamenjaj) or (s.get("url") and not stari):
            # Posnetek je znan (ali pa ima skladba svoj neposredni naslov): nic ne iscemo. Skladba s streznika dobi
            # prijavo sele zdaj (shranjena je brez nje).
            return self._seznam_vnos_s_prijavo(sz["ime"], sz.get("vir") or "", s)
        if zamenjaj and stari and sz.get("vir") == "YouTube":
            # Seznam YouTube ima tocno izbrane posnetke uporabnika: nikoli jih ne zamenjamo z zadetkom iskanja
            # (lastnik, 18. 10. 2026). Ce se posnetek ne predvaja, stran gre na naslednjo skladbo.
            return None
        zavrnjeni = tuple(x for x in (list(s.get("zavrnjeni") or []) + ([stari] if stari else [])) if x)
        if zamenjaj and len(zavrnjeni) > 3:
            return None
        novi = uvoz_seznama.najdi(str(s.get("naslov") or ""), str(s.get("izvajalec") or ""), int(s.get("sekund") or 0), zavrnjeni)
        if not novi:
            return None
        with self._lock:
            vsi = self._seznami_beri()
            for x in vsi:
                if x["ime"] != sz["ime"]:
                    continue
                for y in x["skladbe"]:
                    if isinstance(y, dict) and y.get("naslov") == s.get("naslov") and y.get("izvajalec") == s.get("izvajalec"):
                        y["youtube"] = novi
                        y["slika"] = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % novi
                        if zavrnjeni:
                            y["zavrnjeni"] = list(zavrnjeni)
                        s = y
                        x["cas"] = self._nov_cas(x["ime"], int(x.get("cas") or 0))
            self._seznami_pisi(vsi)
        vnos = self._seznam_vnos(sz["ime"], sz.get("vir") or "", s)
        self._dynamic_items[vnos["id"]] = vnos
        return vnos

    def sources(self) -> list[dict]:
        with self._lock:
            data = self._load()
            regular = []
            for source in data.get("viri", []):
                if not isinstance(source, dict):
                    continue
                vir = {k: value for k, value in source.items() if k != "vnosi"}
                # Na zaslonu cel naslov samo pozitivno znanega javnega vira, drugo samo gostitelj (pregled 46, Ö1).
                vir["url_prikaz"] = viri_sink.prikaz_naslova(source.get("url"), source.get("javni") is True)
                if self._racun_vira(source):
                    ostane = self._zavrnjen_do(source) - time.time()
                    if ostane > 0:
                        vir["premor_s"] = int(ostane) + 1       # vrstica pove, cez koliko casa je nov poskus mogoc (Ą5)
                if (source.get("ozji_krog") and not source.get("caka_uporabnika") and "premor_s" not in vir
                        and (source.get("prvo_uporaba")
                             or time.time() - float(source.get("posodobljeno") or 0) >= self.OZJI_KROG_PREDPOMNILNIK_S)):
                    vir["odpri"] = True                         # gumb »Odpri«: povezava samo za ta vir (Ą4)
                kanali = self._statistika_kanalov(source)
                if kanali is not None:
                    # Lastnik, 25. 10. 2026: mrtvih kanalov ni niti v stevcu Virov. Steje, kar je vidno: delujoci in
                    # neznani (J3: viden z oznako »preverjam« oziroma kanal seznama z racunom, ki ga ne preverjamo).
                    vir["kanali"] = kanali
                    vir["stevilo"] = kanali["izbranih"] - kanali["mrtvih"] - kanali["zaklenjenih"] + sum(
                        1 for x in source.get("vnosi") or [] if isinstance(x, dict) and not x.get("iptv"))
                regular.append(vir)
            # Dodatek z osebnim zetonom samo z nadomestkom (core/skrivni_dodatki.py, _vir_za_prikaz); sifrirano geslo
            # in uporabnik streznika nista v podatkih strani (pregled 46, Ö8).
            personal = [{k: value for k, value in self._vir_za_prikaz(source).items() if k not in ("secret_enc", "uporabnik")}
                        for source in data.get("osebni_strezniki", []) if isinstance(source, dict)]
            return regular + personal

    def vidni_viri(self) -> list[dict]:
        """Viri za prikaz v medijskem centru: brez tistih, iz katerih ni nic predvajljivega (in brez zasebnih dodatkov,
        dokler kategorija »Zasebno« ni vklopljena)."""
        return [vir_za_stran(vir) for vir in self.sources()
                if (vir.get("vrsta") == "streznik" or int(vir.get("stevilo") or 0) > 0
                    or (vir.get("tip") == "predvajalni_vir" and not vir.get("napaka")))
                and (self.zasebno or not self.zaseben_streznik(vir))]

    def add_server(self, provider: str, name: str, url: str, username: str, secret: str,
                   prevzet: Optional[dict] = None) -> dict:
        """`prevzet`: vir je prisel z druge naprave v Linku ({"tip", "naslov", "cas"}, core/viri_sink.py)."""
        provider = _text(provider, 20).lower()
        url = _text(url, 1024)
        if url.startswith("stremio://"):
            url = "https://" + url[len("stremio://"):]
        if provider == "stremio":
            # En zapis za isti dodatek: koren + /manifest.json, ne glede na to, ali je uporabnik prilepil koren,
            # manifest, stran /configure ali povezavo »Install« (stremio://).
            url = media_servers.stremio_naslov_dodatka(url) or url
        parsed = urllib.parse.urlsplit(url)
        username = _text(username, 160)
        secret = str(secret or "")
        if provider not in media_servers.PONUDNIKI:
            return {"ok": False, "napaka": "Nepodprta vrsta strežnika."}
        if len(secret) > 4096:
            return {"ok": False, "napaka": "Geslo ali žeton je predolg."}
        if provider in ("jellyfin", "emby", "navidrome") and (not username or not secret):
            return {"ok": False, "napaka": "Ta strežnik zahteva uporabniško ime in geslo."}
        varen = parsed.scheme == "https" or (parsed.scheme == "http" and media_servers.je_domace_omrezje(parsed.hostname or ""))
        if not varen or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return {"ok": False, "napaka": "Vnesi naslov strežnika brez prijavnih podatkov ali parametrov "
                                          "(HTTP je dovoljen samo v domačem omrežju, drugače HTTPS)."}
        base = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc,
                                        parsed.path if provider in ("dlna", "stremio") else parsed.path.rstrip("/"), "", ""))
        raw_secret = secret
        try:
            auth = media_servers.authenticate(provider, base, username, raw_secret)
            encrypted = self._secret_encryptor(auth.get("token") or raw_secret)
        except Exception:
            return {"ok": False, "napaka": "Prijava ni uspela; preveri HTTPS naslov in uporabniške podatke."}
        if provider == "stremio":
            try:
                razlog = media_servers.stremio_preveri(base)
            except Exception:
                razlog = "Dodatka ni bilo mogoče prebrati; preveri naslov manifest.json."
            if razlog:
                return {"ok": False, "napaka": razlog, "sporocilo": razlog}
        if provider == "stremio" and not _text(name, 80):
            # Brez imena: ime iz manifesta (»Torrentio«, ne gostitelj), kot v Stremiu in na Androidu.
            try:
                name = str(media_servers.stremio_manifest(base).get("name") or "")
            except Exception:
                name = ""
        # Dodatek z osebnim zetonom ali kljucem v naslovu (Webtor, Torrentio z debrid kljucem): pravi naslov samo
        # sifriran, v media.json in povsod drugje nadomestek; drugim napravam ne gre (core/skrivni_dodatki.py).
        skriven = provider == "stremio" and skrivni_dodatki.skrivna_predpona_dodatka(base) is not None
        shranjen, url_enc = base, ""
        if skriven and not base.startswith("https://"):
            # Pregled Grok U5/N6: zeton samo po HTTPS - »domace omrezje« po http je drugje (kavarna) tuj racunalnik.
            napaka = "Dodatek z osebnim žetonom ali ključem deluje samo prek HTTPS (žeton bi sicer šel po omrežju nešifriran)."
            return {"ok": False, "napaka": napaka, "sporocilo": napaka}
        koreni = {media_servers._stremio_koren(base), media_servers._stremio_koren(skrivni_dodatki.v_nadomestek(base))}

        def podvojen(viri: list) -> bool:
            return any(isinstance(item, dict) and (item.get("id") == source_id or (
                provider == "stremio" and item.get("ponudnik") == "stremio"
                and media_servers._stremio_koren(str(item.get("url") or "")) in koreni)) for item in viri)
        source_id = "streznik-" + hashlib.sha256((provider + skrivni_dodatki.v_nadomestek(base) + username).encode()).hexdigest()[:16]
        with self._lock:
            if podvojen(self._load().get("osebni_strezniki", [])):
                # Pred sifriranjem (Grok N11): ponovno dodajanje ne pusti sirote v zbirki skrivnosti.
                napaka = "Ta dodatek je že dodan." if provider == "stremio" else "Ta strežnik je že dodan."
                return {"ok": False, "napaka": napaka, "sporocilo": napaka, "podvojen": True}
        if skriven:
            try:
                url_enc = self._secret_encryptor(base)
            except Exception:  # noqa: BLE001 - brez zbirke skrivnosti zetona ne shranimo v cistopisu
                url_enc = ""
            if not url_enc:
                napaka = ("Dodatka z osebnim žetonom ni mogoče varno shraniti, ker zbirka gesel sistema ni na voljo. "
                          "Odkleni jo ali jo nastavi in poskusi znova.")
                return {"ok": False, "napaka": napaka, "sporocilo": napaka}
            shranjen = skrivni_dodatki.odkleni(base)
        source = {"id": source_id, "vrsta": "streznik", "ponudnik": provider,
                  "ime": _text(name, 80) or urllib.parse.urlsplit(base).hostname,
                  "url": shranjen, "uporabnik": username, "user_id": auth.get("user_id", ""),
                  "secret_enc": encrypted}
        if skriven:
            source.update(url_enc=url_enc, skriven=True)
        if provider == "stremio":
            # Zaseben dodatek ostane na tem racunalniku (ne gre drugim napravam v Linku); ce ne vemo, velja kot zaseben.
            zaseben = self._koren_zaseben(shranjen)
            if zaseben is not None:
                source["zaseben"] = bool(zaseben)
        with self._lock:
            data = self._load()
            sources = data.setdefault("osebni_strezniki", [])
            if podvojen(sources):
                if url_enc:
                    self._pozabi_skrivnost(url_enc)
                napaka = "Ta dodatek je že dodan." if provider == "stremio" else "Ta strežnik je že dodan."
                return {"ok": False, "napaka": napaka, "sporocilo": napaka, "podvojen": True}
            if provider == "stremio" and not skriven:
                self._vir_dodan(source, viri_sink.STREMIO, base, prevzet)
            sources.append(source)
            try:
                self._save(data)
            except OSError:
                if url_enc:
                    self._pozabi_skrivnost(url_enc)
                raise
        if provider == "stremio" and not skriven:
            self._vir_potrjen(viri_sink.STREMIO, base)
        return {"ok": True, "vir": self._vir_za_prikaz(source)}

    @staticmethod
    def _vir_za_prikaz(source: dict) -> dict:
        """Vir za stran: brez skrivnosti (geslo, uporabnik, sifriran naslov); dodatek z zetonom ima »prikaz« brez njega."""
        vir = {k: v for k, v in source.items() if k not in ("secret_enc", "uporabnik", "url_enc")}
        if source.get("ponudnik") == "stremio":
            prikaz = skrivni_dodatki.za_prikaz(str(source.get("url") or ""))
            if prikaz != str(source.get("url") or ""):
                vir["prikaz"] = prikaz
                # Na stran tudi pri nezavarovanem zapisu samo nadomestek (Grok N13; prehod ga odklene v pomnilniku).
                vir["url"] = skrivni_dodatki.v_nadomestek(str(source.get("url") or ""))
                if vir["url"].startswith("http://"):
                    vir["samo_https"] = True        # Grok N6: zeton po http ne gre - dodatek ne deluje, stran pove zakaj
        return vir

    def jellyfin_dostop(self, server_id: str) -> tuple:
        """(naslov, zeton) dodanega strežnika Jellyfin za upravljanje vticnikov (core/jellyfin_vticniki.py). Zeton je
        v sistemski zbirki skrivnosti; tu ga samo preberemo za en klic in ga nikamor ne shranimo."""
        with self._lock:
            server = next((x for x in self._load().get("osebni_strezniki", []) if isinstance(x, dict)
                           and x.get("id") == server_id and x.get("ponudnik") == "jellyfin" and x.get("url")), None)
        if server is None:
            raise ValueError("Tega strežnika Jellyfin ni med viri.")
        return str(server["url"]), self._secret_decryptor(str(server.get("secret_enc") or ""))

    def streznik_spremenjen(self, server_id: str) -> None:
        """Vsebina strežnika se je spremenila (vticnik, ponovni zagon): knjiznico preberemo znova, katalog se osvezi."""
        self._server_cache = {k: v for k, v in self._server_cache.items() if not k.startswith(str(server_id) + ":")}
        self.ozastari_predpomnilnik()

    def _stremio_strezniki(self) -> list[dict]:
        """Uporabnikovi Stremio dodatki (osebni strezniki s ponudnikom stremio); zasebni le, ce je »Zasebno« vklopljeno."""
        with self._lock:
            vsi = [x for x in self._load().get("osebni_strezniki", []) if isinstance(x, dict) and x.get("ponudnik") == "stremio" and x.get("url")]
        return vsi if self.zasebno else [x for x in vsi if not self.zaseben_streznik(x)]

    def _stremio_tokovi_vseh(self, koren: str, tip: str, ident: str, dodatni: str = "") -> list[dict]:
        """
        Tokovi za vsebino iz VSEH uporabnikovih dodatkov, ne le iz tistega, ki jo je pokazal: katalog (npr. Cinemeta)
        pozna naslove, tokove ima pogosto drug dodatek - kot v Stremiu in kot v Safeer OS za Android.
        """
        if tip == "series" and not media_servers.stremio_je_epizoda(ident):
            # Serija brez izbrane epizode: prvo epizodo doloci dodatek, ki serijo pozna; z njenim id-jem vprasamo vse.
            # Naloga 131: poleg id-ja dodatka vprasamo se id po IMDb (tt...:S:E) - dodatki s torrenti poznajo samo tega.
            # Dodatek kartice epizod ne da: prvo epizodo po IMDb poiscemo pri drugem uporabnikovem dodatku z metapodatki.
            serija = ident
            try:
                prvi, dodatni = media_servers.stremio_prva_epizoda_z_imdb(koren, ident)
            except Exception:
                prvi = ""
            if not prvi:
                drugi = [media_servers._stremio_koren(str(x.get("url") or "")) for x in self._stremio_strezniki()]
                prvi = media_servers.stremio_prva_epizoda_drugje([k for k in drugi if k and k != koren],
                                                                 media_servers.stremio_imdb_iz_meta({}, serija))
            ident = prvi or ident
        koreni = [koren] if self.zasebno or koren not in self.zasebni_koreni() else []
        for streznik in self._stremio_strezniki():
            k = media_servers._stremio_koren(str(streznik.get("url") or ""))
            if k and k not in koreni:
                koreni.append(k)

        # Ali so odgovorili vsi dodatki: "tega nimam" (404) je odgovor, izpad (omrezje, 5xx, prijava) ni. Brez tega
        # bi hip nedosegljiv dodatek film skril za ure (glej resolve).
        izpadi: list[str] = []
        # Zdravje dodatkov (lastnik 5. 11. 2026, viri tokov): dodatek s kljucem v kazni preskocimo (zaklep racuna),
        # na dodatek brez kljuca v kazni ne cakamo. Preskoceni steje kot izpad - naslov zato ne postane »ni na voljo«.
        zdravje = self._zdravje_dodatkov()
        for k in [k for k in koreni if zdravje.preskoci(k, media_servers.stremio_dodatek_s_kljucem(k))]:
            koreni.remove(k)
            izpadi.append(k)
        zadrzani = {k for k in koreni if zdravje.zadrzan(k)}

        def vprasaj_en(k: str, ident: str = ident) -> Optional[list[dict]]:
            """Tokovi dodatka; None = neuspeh (napaka, cas, prazen odgovor, prijava) za zdravje dodatka."""
            try:
                return media_servers.stremio_tokovi(k, tip, ident)
            except urllib.error.HTTPError as napaka:
                if not (400 <= napaka.code < 500 and napaka.code not in (401, 403, 407, 408, 425, 429)):
                    izpadi.append(k)
                    return None
                return []
            except Exception:
                izpadi.append(k)
                return None

        def vprasaj(k: str) -> list[dict]:
            # Naloga 131: isti dodatek se z id-jem po IMDb (npr. Torrentio za serijo iz kataloga z lastnimi id-ji).
            izidi_k = [vprasaj_en(k)] + ([vprasaj_en(k, dodatni)] if dodatni else [])
            # Ena vsebina je en poskus: dodatek je zdrav, ce je odgovoril vsaj na eno vprasanje.
            if any(i is not None for i in izidi_k):
                zdravje.uspeh(k)
            else:
                zdravje.neuspeh(k)
            return [t for i in izidi_k if i for t in i]

        # Kateri dodatek je ponudil torrent (za zasebnost na polici »Na tvojih napravah«). Naslov dodatka ostane tu:
        # v njem je lahko uporabnikov zeton, zato ga tokovom, ki gredo na stran, ne pripisemo.
        dodatki_torrentov: dict[str, str] = {}
        self._tokovi_odgovor.dodatki_torrentov = dodatki_torrentov

        def zapomni(k: str, izid: list) -> None:
            for t in izid:
                if t.get("torrent") and t.get("hash"):
                    dodatki_torrentov.setdefault(str(t["hash"]).lower(), k)

        if not koreni:
            self._tokovi_odgovor.vsi = False      # ni odgovor »tega ni« - ne skrije kartice za ure
            return []
        if len(koreni) == 1:
            ime = next((str(x.get("ime") or "")[:60] for x in self._stremio_strezniki()
                        if media_servers._stremio_koren(str(x.get("url") or "")) == koreni[0]), "")
            tokovi = self._oznaci_webtor(koreni[0], vprasaj(koreni[0]))
            if ime:
                tokovi = [dict(t, dodatek=ime) for t in tokovi]
            zapomni(koreni[0], tokovi)
            self._tokovi_odgovor.vsi = not izpadi
            return tok_izbira.zdruzi_dvojnike(tokovi)
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        tokovi: list[dict] = []
        videni: set[str] = set()
        # Vsi dodatki hkrati. Ko ima kateri ze neposreden tok in je minil TOKOVI_ROK_S, ne cakamo na pocasne (meritev
        # 15. 10. 2026: neodziven dodatek je Predvajaj zadrzal 10 s, ceprav je tok ze bil); ti stejejo kot izpad, zato
        # naslov ne postane »ni na voljo«.
        bazen = ThreadPoolExecutor(max_workers=min(10, len(koreni)))
        niti = {bazen.submit(vprasaj, k): k for k in koreni[:10]}
        zacetek = time.monotonic()
        izidi: dict[str, list] = {}
        try:
            cakajo = set(niti)
            # Dodatek v kazni (zdravje) ne zadrzi rezultatov: ko so tokovi ze tu, cakamo samo se na zdrave dodatke,
            # odgovor dodatka v kazni vzamemo, ce je ze prisel. Brez vsakega toka cakamo tudi nanj (do roka).
            while cakajo and (any(niti[n] not in zadrzani for n in cakajo) or not any(izidi.values())):
                pretecen = time.monotonic() - zacetek
                ima_tok = any(t.get("url") and not t.get("zunanje") for v in izidi.values() for t in v)
                rok = (self.TOKOVI_ROK_S if ima_tok else self.TOKOVI_NAJDLJE_S) - pretecen
                if rok <= 0:
                    break
                koncane, cakajo = wait(cakajo, timeout=rok, return_when=FIRST_COMPLETED)
                for nit in koncane:
                    izidi[niti[nit]] = nit.result() if nit.exception() is None else []
            for nit in cakajo:
                if nit.done() and nit.exception() is None:
                    izidi[niti[nit]] = nit.result()
                else:
                    izpadi.append(niti[nit])
        finally:
            bazen.shutdown(wait=False)
        # Ime dodatka, kot ga je poimenoval uporabnik (seznam razlicic v podrobnostih) - naslova dodatka ne.
        imena = {media_servers._stremio_koren(str(x.get("url") or "")): str(x.get("ime") or "")[:60]
                 for x in self._stremio_strezniki()}
        for k in koreni[:10]:               # vrstni red dodatkov ostane (prvi je dodatek kartice)
            izid = [dict(t, dodatek=imena.get(k) or "") if imena.get(k) else t
                    for t in self._oznaci_webtor(k, izidi.get(k) or [])]
            zapomni(k, izid)
            for t in izid:
                # Torrente z istim hashem zdruzi zdruzi_dvojnike (sledilniki, sejalci), ne zavrze drugega.
                kljuc = str(t.get("url") or "")
                if t.get("torrent") and not kljuc:
                    tokovi.append(t)
                elif kljuc not in videni:
                    videni.add(kljuc)
                    tokovi.append(t)
        self._tokovi_odgovor.vsi = not izpadi
        return tok_izbira.zdruzi_dvojnike(tokovi)

    def _zdravje_dodatkov(self) -> "media_servers.ZdravjeDodatkov":
        """Zdravje dodatkov Stremio v pomnilniku tega procesa (ob ponovnem zagonu vsi spet zdravi)."""
        return self.__dict__.setdefault("_zdravje_dodatkov_stanje", media_servers.ZdravjeDodatkov())

    # --- Webtor rezerva (lastnik 25. 10. 2026; core/webtor.py) ------------------------------------------------------
    def _je_webtor_koren(self, koren: str) -> bool:
        """Dodatek je uporabnikov osebni dodatek Webtor: https://webtor.io (natanko) IN id manifesta Webtorja."""
        if webtor.gostitelj(koren) != webtor.GOSTITELJ or not str(koren).lower().startswith("https://"):
            return False
        znani = self.__dict__.setdefault("_webtor_koreni", {})
        if koren not in znani:
            try:
                znani[koren] = webtor.je_webtor_dodatek(str(media_servers.stremio_manifest(koren).get("id") or ""), koren)
            except Exception:  # noqa: BLE001 - manifesta ni: ta zagon ga vprasamo znova ob naslednjem iskanju toka
                return False
        return znani[koren]

    def _oznaci_webtor(self, koren: str, tokovi: list) -> list:
        """Tokovi dodatka Webtor (`.../resolve/<JWT>`) dobijo vrsto (`[⚡WT]`, `[WT]`, `[⚡TB]`, `[P2P]`) in izdajo iz JWT
        (hash, datoteka) - v izbiri gredo posebej, ne med neposredne povezave."""
        if not tokovi or not self._je_webtor_koren(koren):
            return tokovi
        izid = []
        for t in tokovi:
            # Prepoznava po PRAVEM naslovu (samo v pomnilniku): zivi tek 25. 10. 2026 - dodatek je kratka povezava
            # `/s/<koda>`, tokovi `/token/<uuid>/stremio/resolve/<JWT>`; skrij_tok skrije cel naslov (JWT je neprozoren
            # odsek), zato nadomestek nima »/resolve/« in tok je sel med neposredne povezave (brez preverbe vsebine).
            try:
                pravi = skrivni_dodatki.dejanski(str(t.get("url") or ""))
            except ValueError:
                pravi = ""
            if pravi and webtor.je_resolve_naslov(pravi):
                # Izdaja in datoteka iz JWT (idx; brez JWT IDX_NEZNAN) - Android webtor-popravek, skupni primeri v3.
                t = dict(t, webtor=webtor.razcleni(str(t.get("vir") or ""))[0],
                         webtor_kljuc=webtor.kljuc_webtor(t.get("hash"), pravi))
            izid.append(t)
        return izid

    def _webtor_sonda(self, url: str, rok_ms: int, pricakovano_gb: float = 0.0) -> webtor.Sonda:
        return webtor.sonda(url, rok_ms, pricakovano_gb=pricakovano_gb)

    def _skrivni_sonda(self, url: str, rok_ms: int, glave: Optional[dict] = None) -> webtor.Sonda:
        return webtor.sonda(url, rok_ms, preveri_vsebino=False, glave=glave)

    def _razresi_skrivne_tokove(self, tokovi: list, stanje: dict) -> list:
        """Tokovi dodatka z osebnim kljucem imajo nadomestek (core/skrivni_dodatki.skrij_tok; Torrentio z debrid kljucem:
        `/resolve/realdebrid/<kljuc>/...`). V predvajalnik (in v Link: »kaj se predvaja«) ne sme ne nadomestek ne pravi
        naslov s kljucem (pregled Grok N2, N5): prvi tak tok na vrhu razresimo s sondo (https, javni naslovi, najvec 5
        preusmeritev) in predvajalnik dobi KONCNI naslov brez kljuca; ce ga nosi tudi koncni (brez preusmeritve), toka ne
        predvajamo. Drugi tokovi z nadomestkom izpadejo iz razlicic. Najvec 2 sondi in 15 s (kot Webtor)."""
        izid: list = []
        for t in tokovi:
            u = str(t.get("url") or "")
            if not skrivni_dodatki.je_nadomestek(u):
                izid.append(t)
                continue
            if izid:
                continue                        # razlicica: sonde zanjo ne delamo, nadomestek ne gre v predvajalnik
            zdaj = int(time.monotonic() * 1000)
            rok = webtor.rok_sonde(stanje["zacetek"], zdaj, stanje["poskusov"])
            if rok <= 0:
                continue
            try:
                pravi = skrivni_dodatki.dejanski(u)
            except ValueError:
                continue
            if stanje["zacetek"] is None:
                stanje["zacetek"] = zdaj
            stanje["poskusov"] += 1
            try:
                s = self._skrivni_sonda(pravi, rok, t.get("glave"))     # Grok 19 M3: glave toka tudi sondi
            except Exception as e:  # noqa: BLE001 - nepricakovana napaka sonde: naslednji tok
                print("[SafeerMedia] sonda toka s kljucem:", type(e).__name__, flush=True)
                continue
            print("[SafeerMedia] sonda toka s kljucem:", webtor.opis_za_dnevnik(s), flush=True)
            if s.izid == webtor.PREDVAJAJ and s.koncni and not skrivni_dodatki.nosi_skrivnost(s.koncni, pravi):
                nov = dict(t, url=s.koncni, preverjen=True)
                if webtor.gostitelj(s.koncni) != webtor.gostitelj(pravi):
                    nov.pop("glave", None)          # Grok 19 M3: glave dodatka ne gredo gostitelju po preusmeritvi
                izid.append(nov)
        return izid

    def _razresi_webtor(self, item_id: str, item: dict, tokovi: list, indeksi: list, stanje: dict) -> Optional[dict]:
        """Prvi tok Webtor (po `indeksi`), ki v roku da prvi bajt: predvajalnik dobi KONCNI naslov, ki ga je sonda
        preverila (https, javni naslov, najvec 5 preusmeritev) - nikoli /resolve/ z zetonom. Vse sonde ene izbire skupaj
        najvec 15 s in najvec 2 (webtor.rok_sonde). None = nic (naslednji korak)."""
        for i in indeksi:
            if i in stanje["poskuseni"]:
                continue
            stanje["poskuseni"].add(i)
            t = tokovi[i]
            try:
                pravi = skrivni_dodatki.dejanski(str(t.get("url") or ""))
            except ValueError:
                continue                        # dodatek ni odklenjen (zbirka skrivnosti zaklenjena)
            if not webtor.je_resolve_naslov(pravi):
                continue
            zdaj = int(time.monotonic() * 1000)
            rok = webtor.rok_sonde(stanje["zacetek"], zdaj, stanje["poskusov"])
            if rok <= 0:
                return None
            if stanje["zacetek"] is None:
                stanje["zacetek"] = zdaj
            stanje["poskusov"] += 1
            try:
                s = self._webtor_sonda(pravi, rok, webtor.pricakovana_velikost_gb(str(t.get("opis") or "")))
            except Exception as e:  # noqa: BLE001 - nepricakovana napaka sonde: naslednji tok (Grok N9)
                print("[SafeerMedia] webtor sonda:", type(e).__name__, flush=True)
                continue
            if not webtor.steje_kot_poskus(s.izid, int(time.monotonic() * 1000) - zdaj):
                stanje["poskusov"] -= 1         # hitro zavrnjena vsebina (.srt namesto filma) ni poskus (skupno v4)
            print("[SafeerMedia] webtor sonda:", webtor.opis_za_dnevnik(s), flush=True)
            if s.izid != webtor.PREDVAJAJ or not s.koncni or skrivni_dodatki.nosi_skrivnost(s.koncni, pravi):
                continue                        # ni video posode ali zeton v naslovu: nikoli v predvajalnik
            ime = webtor.razcleni(str(t.get("vir") or ""))[1]
            tok = {"url": s.koncni, "vir": ("%s %s" % (webtor.IME, ime)).strip()[:60],
                   "kakovost": str(t.get("kakovost") or ""), "opis": str(t.get("opis") or "")}
            resolved = dict(item, url=s.koncni, razlicice=[tok], stevilo_razlicic=1, webtor=True, preverjen=True)
            self._dynamic_items[item_id] = resolved
            return resolved
        return None

    #: Tokovi: ko kateri dodatek ze da tok, na ostale cakamo se najvec do toliko sekund od zacetka.
    #: Meritev 15. 10. 2026 (10 dodatkov, 4 filmi x 3): vsi dodatki odgovorijo v 2,9-5,4 s, izjeme 7,7 in 10,1 s
    #: (dodatek, ki ne odgovori). Pri 3 s je odpadla vecina razlicic (34 -> 1), pri 5 s ostanejo, izjeme pa odpadejo.
    TOKOVI_ROK_S = 5.0
    #: Brez nobenega toka cakamo do toliko sekund (zahteva dodatka ima svoj rok 10 s).
    TOKOVI_NAJDLJE_S = 12.0

    def _stremio_vnosi(self, imdb: str, tmdb_id: int, kind: str, title: str, season: int = 0, episode: int = 0) -> list[dict]:
        """Vnosi za film/epizodo iz TMDB kataloga, ki jih zna predvajati kateri od uporabnikovih Stremio dodatkov.

        Tok se poisce sele ob predvajanju (resolve): url je stremio:<koren>|<tip>|<imdb>[:S:E]. Brez IMDb ID
        dodatek vsebine ne pozna."""
        if not imdb:
            return []
        items = []
        for server in self._stremio_strezniki():
            koren = media_servers._stremio_koren(str(server["url"]))
            if kind == "serija":
                tip, ident = "series", "%s:%d:%d" % (imdb, season, episode)
            else:
                tip, ident = "movie", imdb
            items.append({"id": "stremio:%s:%s:%s" % (server.get("id"), tip, ident), "naslov": title, "vrsta": kind,
                          "url": "stremio:%s|%s|%s" % (koren, tip, ident), "vir": str(server.get("ime") or "Stremio"),
                          "imdb_id": imdb, "tmdb_id": int(tmdb_id or 0), "sezona": season, "epizoda": episode,
                          "kakovost": "", "slika": "", "opis": "", "leto": 0, "izvajalec": "", "stremio": {"koren": koren, "tip": tip, "id": ident}})
        return items

    def _osebni_naslovi(self, vrsta: str, imdb: str, tmdb_id: int, sezona: int = 0, epizoda: int = 0) -> list[dict]:
        """Isti film ali epizoda na uporabnikovem strežniku (iz ze prebranih knjiznic, brez omrezja): ob izbiri iz
        kataloga TMDB ali dodatka ima lastni tok prednost (merge_duplicates)."""
        if not imdb and not tmdb_id:
            return []
        izid, videni = [], set()
        for _cas, vrstice in list(self._server_cache.values()):
            for r in vrstice:
                if not isinstance(r, dict) or r.get("vrsta") != vrsta or not media_servers.streznik_iz_id(r.get("id")):
                    continue
                if not ((imdb and _imdb_id(r.get("imdb_id")) == imdb) or (tmdb_id and _tmdb_id(r.get("tmdb_id")) == tmdb_id)):
                    continue
                if vrsta == "serija" and (int(r.get("sezona") or 0) != sezona or int(r.get("epizoda") or 0) != epizoda):
                    continue
                if r.get("url") and r["url"] not in videni:
                    videni.add(r["url"])
                    izid.append(dict(r))
        return izid

    def _kodi_streznik(self, server_id: str = "") -> Optional[tuple]:
        """(streznik, geslo) povezanega Kodija - dolocenega ali prvega."""
        with self._lock:
            servers = [x for x in self._load().get("osebni_strezniki", []) if x.get("ponudnik") == "kodi"]
        izbran = next((x for x in servers if x.get("id") == server_id), servers[0] if servers else None)
        if not izbran:
            return None
        try:
            return izbran, self._secret_decryptor(str(izbran.get("secret_enc") or ""))
        except Exception:
            return izbran, ""

    #: Drzava, ki jo je uporabnik izbral pri "Kje gledati" (ali "auto" = zaznana).
    izbrana_drzava = "auto"

    def _drzava_uporabnika(self) -> str:
        try:
            return str(self.watch_country_settings(self.izbrana_drzava or "auto", "sl").get("drzava", "") or "")
        except Exception:
            return ""

    def tv_drzave(self) -> list[dict]:
        with self._lock:
            data = self._load()
            moji = any(x.get("ponudnik") in ("tvheadend", "dlna", "kodi")
                       for x in data.get("osebni_strezniki", []))
        drzava = self._drzava_uporabnika()
        izid = zakoniti_viri.tv_drzave(drzava, moji)
        # Drzave delujocih kanalov iz seznamov IPTV (izbira v Virih) kot gumbi: drzava uporabnika, nato tiste z najvec
        # kanali (najvec TV_DRZAV_GUMBOV, vsaj TV_DRZAVA_KANALOV kanalov - eng.m3u ima kanale iz ~100 drzav, vrsta gumbov
        # bi zakrila mrezo). »Moji kanali« ostanejo zadnji.
        znane = {d["id"] for d in izid}
        stevilo: dict[str, int] = {}
        for x in self._vnosi_virov(data, "tv-v-zivo", preveri=False):
            d = str(x.get("drzava") or "").upper()
            if d not in znane and re.fullmatch(r"[A-Z]{2}", d):
                stevilo[d] = stevilo.get(d, 0) + 1
        dodatne = sorted((d for d, n in stevilo.items() if n >= self.TV_DRZAVA_KANALOV or d == drzava.upper()),
                         key=lambda d: (d != drzava.upper(), -stevilo[d], d))[:self.TV_DRZAV_GUMBOV]
        if dodatne:
            konec = [d for d in izid if d["id"] == "moji"]
            izid = [d for d in izid if d["id"] != "moji"] + [{"id": d, "ime": zakoniti_viri.DRZAVE.get(d, d)} for d in dodatne] + konec
        return izid

    # --- kanali seznamov IPTV (core/kanali_iptv.py) -------------------------------------------------------------
    TV_DRZAV_GUMBOV = 24
    TV_DRZAVA_KANALOV = 3

    def _kanali_spremenjeni(self, viri: bool = False) -> None:
        """Preverba v ozadju je nasla nov delujoc kanal ali kanal ne deluje vec: pogledi se ob naslednjem odprtju osvezijo,
        stran dobi dogodek (mediaKanaliPreverjeni - stevci v Virih brez ponovnega nalaganja mreze, po kateri uporabnik
        morda ravno drsi). `viri`: vir je bil prebran znova - stran osvezi vire in katalog (mediaViriUsklajeni)."""
        self.ozastari_predpomnilnik()
        povratni = self.ob_virih if viri else self.ob_kanalih
        if povratni is not None:
            try:
                povratni()
            except Exception:  # noqa: BLE001, S110 - obvestilo strani ne sme ustaviti preverbe
                pass

    def _drzava_tv(self) -> str:
        """Drzava uporabnika za kanale: izbrana v Medijskem centru ali iz regije sistema (brez omrezja)."""
        izbrana = str(getattr(self, "izbrana_drzava", "") or "auto").upper()
        if re.fullmatch(r"[A-Z]{2}", izbrana):
            return izbrana
        try:
            return watch_providers.detect_country("sl")
        except Exception:  # noqa: BLE001
            return ""

    @property
    def pot_tv_izbire(self) -> Path:
        return self.config_dir / "tv-izbira.json"

    def tv_izbira(self) -> dict:
        """Drzave in jeziki kanalov javnih seznamov (iptv-org). Privzeto drzava uporabnika in drzave z anglescino."""
        try:
            d = json.loads(self.pot_tv_izbire.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = None
        if not isinstance(d, dict):
            return kanali_iptv.privzeta_izbira(self._drzava_tv())
        return {"drzave": [x for x in d.get("drzave") or [] if isinstance(x, str) and re.fullmatch(r"[A-Z]{2}", x)][:300],
                "jeziki": [x for x in d.get("jeziki") or [] if isinstance(x, str) and re.fullmatch(r"[a-z]{2}", x)][:200]}

    def nastavi_tv_izbiro(self, drzave: Iterable[str], jeziki: Iterable[str]) -> dict:
        izbira = {"drzave": sorted({str(x).upper() for x in drzave or [] if re.fullmatch(r"[A-Za-z]{2}", str(x))})[:300],
                  "jeziki": sorted({str(x).lower() for x in jeziki or [] if re.fullmatch(r"[A-Za-z]{2}", str(x))})[:200]}
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.pot_tv_izbire, izbira, indent=None)
        except OSError:
            pass
        self.ozastari_predpomnilnik()
        return izbira

    def tv_izbira_na_voljo(self) -> dict:
        """Drzave in jeziki kanalov javnih seznamov (za izbiro v Virih) s stevilom kanalov."""
        with self._lock:
            data = self._load()
        drzave: dict[str, int] = {}
        jeziki: dict[str, int] = {}
        for source in data.get("viri", []):
            if not isinstance(source, dict) or not kanali_iptv.je_javni_seznam(source.get("url")):
                continue
            for item in source.get("vnosi") or []:
                if isinstance(item, dict) and item.get("iptv"):
                    if item.get("drzava"):
                        drzave[item["drzava"]] = drzave.get(item["drzava"], 0) + 1
                    if item.get("jezik"):
                        jeziki[item["jezik"]] = jeziki.get(item["jezik"], 0) + 1
        return {"drzave": [{"id": k, "n": v} for k, v in sorted(drzave.items(), key=lambda p: -p[1])],
                "jeziki": [{"id": k, "n": v} for k, v in sorted(jeziki.items(), key=lambda p: -p[1])],
                "uporabnik": self._drzava_tv(), "izbrano": self.tv_izbira()}

    @staticmethod
    def _zastarela_razclenitev(source: dict) -> bool:
        """Seznam M3U, razclenjen pred kanali_iptv.RAZCLENITEV (napacni naslovi in vrste): ne kazemo ga, dokler ga v
        ozadju ne preberemo znova."""
        if source.get("razclenitev") == kanali_iptv.RAZCLENITEV:
            return False
        pot = urllib.parse.urlsplit(str(source.get("url") or "")).path.lower()
        if pot.endswith((".m3u", ".m3u8")) or "type=m3u" in str(source.get("url") or "").lower():
            return True
        return any(isinstance(x, dict) and urllib.parse.urlsplit(str(x.get("url") or "")).path.lower().endswith((".m3u8", ".ts"))
                   for x in (source.get("vnosi") or [])[:50])

    #: Vir, ki ga ni bilo mogoce prebrati znova (brez povezave, VPN), poskusimo spet ob odprtju kataloga po tem casu -
    #: prej je ostal skrit do ponovnega zagona (pregled 30, J9).
    ZASTARELI_ZNOVA_S = 600.0
    #: Ponudnik je seznam zavrnil (401/402/403/429: racun potekel ali zaklenjen, prevec zahtev): samodejno ga prenesemo
    #: znova sele po teh premorih, zapisanih v viru (velja tudi po ponovnem zagonu). Prej vsakih 10 min - vsaka zahteva
    #: na racun, ki je ze v tezavah, steje (pregled 39, I5). Rocna osvezitev (gumb v Virih) velja takoj.
    ZAVRNJEN_PREMORI_S = (600.0, 3600.0, 6 * 3600.0, 24 * 3600.0)
    ZAVRNJENE_KODE = frozenset({401, 402, 403, 429})
    #: Vir z racunom, pri katerem tolikokrat zapored ni bilo povezave (koda 0), dobi isti rastoci premor (Ê1).
    NI_POVEZAVE_ZAPORED = 3
    #: Vir iz ozjega kroga (lastnik, 26. 10. 2026: »v ozadju se ne osvezuje«): po prvi uporabi velja prebran seznam 24 h.
    #: To je MEJA, ne sprozilec (pregled 68, Ą1): osvezitev sprozi samo uporabnik - odprtje TEGA vira (odpri_vir; ne
    #: katalog, Ą4), ko je seznam starejsi od 24 h, ali »Osvezi«; refresh_stale vira ne kazeta nikoli. Vsaka osvezitev, tudi
    #: uporabnikova, je najvec ena na minuto. Meje veljajo na napravo: usklajevanja med napravami ni, zato dnevne
    #: osvezitve v ozadju na vsaki napravi ne bi smeli imeti (N naprav = N prijav na dan z razlicnih naslovov IP).
    OZJI_KROG_PREDPOMNILNIK_S = 24 * 3600.0
    OZJI_KROG_OSVEZITEV_S = 60.0

    def _zavrnjen_do(self, source: dict) -> float:
        """Do kdaj (unix) vira, ki ga je ponudnik zavrnil, samodejno ne prenasamo znova (0: ni zavrnjen)."""
        zavrnjen = source.get("zavrnjen")
        if not isinstance(zavrnjen, dict):
            return 0.0
        try:
            n, ob = int(zavrnjen.get("n") or 1), float(zavrnjen.get("ob") or 0)
        except (TypeError, ValueError):
            return 0.0
        return ob + self.ZAVRNJEN_PREMORI_S[min(max(n, 1), len(self.ZAVRNJEN_PREMORI_S)) - 1]

    def odpri_vir(self, source_id: str) -> dict:
        """Uporabnik je odprl TA vir (vrstica v Virih; pregled 68, Ą4). Vir iz ozjega kroga, ki se se ni prebral ali je
        prebran pred vec kot 24 h, dobi eno povezavo v ozadju (premor, 1/min in »ena naenkrat« veljajo); drug vir ali vir
        v predpomnilniku ne naredi nic. Vrne {"ok": True, "zacet": bool}."""
        with self._lock:
            source = next((s.copy() for s in self._load().get("viri", []) if s.get("id") == source_id), None)
        if source is None:
            return {"ok": False, "napaka": "ni_vira", "zacet": False}
        if not source.get("ozji_krog") or source.get("caka_uporabnika"):
            return {"ok": True, "zacet": False}
        stara = time.time() - float(source.get("posodobljeno") or 0) >= self.OZJI_KROG_PREDPOMNILNIK_S
        if not (source.get("prvo_uporaba") or stara):
            return {"ok": True, "zacet": False}
        return {"ok": True, "zacet": bool(self._prvo_uporaba_v_ozadju([source]))}

    @staticmethod
    def _kategorije_vira(source: dict) -> set:
        """Kategorije Medijskega centra (vrste kataloga), kamor spada vir iz ozjega kroga: prebran vir po vrstah vnosov,
        se neprebran po vrsti, ki jo je navedla druga naprava (link_tip; vrsti ne zaupamo za nic drugega kot za to, v
        kateri kategoriji uporabnik vir pricakuje): podkast - Glasba, tok - TV v zivo in Radio, drugo (seznam IPTV,
        neznana oblika) - TV v zivo."""
        izid = set()
        for x in source.get("vnosi") or []:
            if not isinstance(x, dict):
                continue
            vrsta = "tv-v-zivo" if x.get("iptv") else str(x.get("vrsta") or "")
            izid.add("glasba" if vrsta in ("podcast", "podkast") else vrsta)
        izid.discard("")
        if izid:
            return izid
        tip = str(source.get("link_tip") or "")
        if tip == "podkast":
            return {"glasba"}
        if tip in ("tok", "tok-hls"):
            return {"tv-v-zivo", "radio"}
        return {"tv-v-zivo"}

    def odpri_kategorijo(self, vrsta: str) -> dict:
        """Uporabnik je odprl KATEGORIJO Medijskega centra (klik na zavihek, npr. TV v zivo; pregled 68, Ą4). Vsak vir iz
        ozjega kroga, ki pripada tej kategoriji in ga je treba prebrati (prvic ali po 24 h), dobi eno povezavo v ozadju;
        viri drugih kategorij ne. Klic samo iz uporabnikovega klika - ne iz obnove zaslona ob zagonu, predgrevanja
        ali samodejnega osvezevanja kataloga. Premor, 1/min in ena naenkrat veljajo (_prvo_uporaba_v_ozadju)."""
        vrsta = str(vrsta or "")
        if not vrsta or vrsta == "vse":
            return {"ok": True, "zacetih": 0}
        pred = time.time() - self.OZJI_KROG_PREDPOMNILNIK_S
        with self._lock:
            viri = [s.copy() for s in self._load().get("viri", []) if isinstance(s, dict)
                    and s.get("ozji_krog") and not s.get("caka_uporabnika")
                    and (s.get("prvo_uporaba") or float(s.get("posodobljeno") or 0) <= pred)]
        viri = [s for s in viri if vrsta in self._kategorije_vira(s)]
        return {"ok": True, "zacetih": len(self._prvo_uporaba_v_ozadju(viri)) if viri else 0}

    def _prvo_uporaba_v_ozadju(self, viri: list) -> list:
        """Povezava vira iz ozjega kroga ob uporabnikovem odprtju tega vira (odpri_vir; lastnik, 26. 10. 2026): prva, nato
        sele ko je prebrani seznam starejsi od 24 h (pregled 68, Ą1: nikoli iz ozadja). Ena zahteva na vir; ne med
        premorom po napaki (_zavrnjen_do), ne ce ze tece ena in ne pogosteje kot na minuto. Uspeh odstrani oznako
        prvo_uporaba, napaka jo pusti (premor se daljsa v refresh_source)."""
        with self._lock:
            poskusi = self.__dict__.setdefault("_prvo_poskusi", {})
            v_teku = self.__dict__.setdefault("_prvo_v_teku", set())
            zdaj = time.monotonic()
            novi = []
            for source in viri:
                ident = str(source.get("id") or "")
                if (not ident or ident in v_teku or time.time() < self._zavrnjen_do(source)
                        or zdaj - poskusi.get(ident, -self.OZJI_KROG_OSVEZITEV_S) < self.OZJI_KROG_OSVEZITEV_S):
                    continue
                novi.append(ident)
                poskusi[ident] = zdaj
            v_teku.update(novi)
        if not novi:
            return []

        def delo() -> None:
            for ident in novi:
                try:
                    self.refresh_source(ident)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    with self._lock:
                        v_teku.discard(ident)
            self._kanali_spremenjeni(viri=True)

        threading.Thread(target=delo, name="media-prva-uporaba", daemon=True).start()
        return novi

    def _osvezi_zastarele_v_ozadju(self, idji: list) -> None:
        with self._lock:
            neuspeli = self.__dict__.setdefault("_zastareli_neuspeh", {})
            zdaj = time.monotonic()
            novi = [i for i in idji if i not in self._zastareli_viri
                    and zdaj - neuspeli.get(i, -self.ZASTARELI_ZNOVA_S) >= self.ZASTARELI_ZNOVA_S]
            self._zastareli_viri.update(novi)
        if not novi:
            return

        def delo() -> None:
            for ident in novi:
                try:
                    odgovor = self.refresh_source(ident)
                    uspeh = bool(odgovor.get("ok")) and not odgovor.get("predpomnjeno") and not odgovor.get("ze_tece")
                except Exception:  # noqa: BLE001
                    uspeh = False
                if not uspeh:
                    # Tudi napaka brez izjeme (refresh_source jo zapise v vir): znova ob odprtju kataloga po
                    # ZASTARELI_ZNOVA_S, zavrnitev ponudnika sele po ZAVRNJEN_PREMORI_S (_vnosi_virov; pregled 39, I5).
                    with self._lock:
                        self._zastareli_viri.discard(ident)
                        neuspeli[ident] = time.monotonic()
            self._kanali_spremenjeni(viri=True)

        threading.Thread(target=delo, name="media-razclenitev", daemon=True).start()

    def _vnosi_virov(self, data: dict, kind: str = "vse", preveri: bool = True) -> list[dict]:
        """Vnosi uporabnikovih spletnih virov za katalog; seznam s staro razclenitvijo se prebere znova. Kanali seznamov
        IPTV: iz javnih seznamov samo izbranih drzav in jezikov; kanal, za katerega vemo, da ne oddaja, ni viden.

        Pregled 30, J3 (lastnik, 26. 10. 2026: nevarnost zaklepa racuna je prioriteta): v ozadju preverjamo samo javne
        brezplacne sezname (kanali_iptv.preverba_dovoljena) - neznan kanal je do izida viden z oznako »preverjam«, v
        vrsto gre v vrstnem redu prikaza (najprej, kar je na zaslonu). Seznamov z racunom (Xtream, uporabnik:geslo@)
        ne preverjamo: kanal je viden, o njem odloci pravo predvajanje. Prej je bil neznan kanal skrit, dokler preverba
        - pri ponudniku ure - ni koncala, in vsak kanal ponudnika se je odprl vsakih 6 h."""
        izid: list[dict] = []
        za_preverbo: list[tuple] = []
        zastareli: list[str] = []
        izbira: Optional[dict] = None
        for source in data.get("viri", []):
            if isinstance(source, dict) and source.get("prvo_uporaba"):
                # Vir iz ozjega kroga (lastnik, 26. 10. 2026): viden, a prazen do prve uporabe. Povezavo sprozi samo
                # uporabnikovo odprtje njegove KATEGORIJE (odpri_kategorijo) ali TEGA vira (odpri_vir; pregled 68, Ą4),
                # nikoli klic kataloga: ta pride tudi ob obnovi zaslona, predgrevanju in osvezevanju ter bi prijavil vse.
                continue
            if not isinstance(source, dict) or source.get("caka_uporabnika"):
                continue                    # prejet vir z racunom ima prazen seznam do uporabnikove osvezitve (Ñ2)
            if self._zastarela_razclenitev(source):
                if time.time() >= self._zavrnjen_do(source):
                    zastareli.append(str(source.get("id") or ""))
                continue
            javni = kanali_iptv.je_javni_seznam(source.get("url"))
            # Samo znan javni vir ali seznam, ki ga je uporabnik oznacil kot javnega (pregled 39, I1).
            seznam_preverljiv = kanali_iptv.javni_brezplacni(str(source.get("url") or ""), source.get("javni") is True)
            serije: dict[str, dict] = {}
            for item in source.get("vnosi") or []:
                if not isinstance(item, dict) or not (kind in ("", "vse") or item.get("vrsta") == kind):
                    continue
                if item.get("iptv"):
                    if javni:
                        izbira = izbira if izbira is not None else self.tv_izbira()
                        if not kanali_iptv.v_izbiri(item, izbira):
                            continue
                    url = str(item.get("url") or "")
                    preverljiv = seznam_preverljiv and not kanali_iptv.s_poverilnicami(url)   # preverba_dovoljena
                    potrebuje = self.kanali.potrebuje_preverbo(url)
                    if preveri and preverljiv and potrebuje:
                        za_preverbo.append((_text(item.get("naslov"), 200).casefold(), url, item.get("glave") or {}))
                    izid_kanala = self.kanali.izid(url)
                    if izid_kanala in (kanali_iptv.MRTEV, kanali_iptv.ZAKLENJEN) and (preverljiv or not potrebuje):
                        continue                    # vemo, da ne oddaja (izid seznama brez preverbe velja do izteka)
                    if izid_kanala != kanali_iptv.DELUJE and preverljiv:
                        item = dict(item, preverjam=True)
                elif item.get("iz_seznama") and item.get("vrsta") == "serija" and int(item.get("epizoda") or 0):
                    # Epizode s seznama so ena kartica serije s sezonami in epizodami (ne kartica na epizodo).
                    self._dodaj_epizodo(serije, item)
                    continue
                izid.append(item)
            izid.extend(serije.values())
        if zastareli and preveri:
            self._osvezi_zastarele_v_ozadju([z for z in zastareli if z])
        if za_preverbo:
            # Prva stran mreze TV v zivo je abecedna (_merge_variants): v tem redu tudi preverba.
            za_preverbo.sort(key=lambda x: x[0])
            self.kanali.preveri_v_ozadju((url, glave, False) for _ime, url, glave in za_preverbo)
        return izid

    NAJVEC_EPIZOD_SERIJE = 2000

    @staticmethod
    def _dodaj_epizodo(serije: dict, item: dict) -> None:
        naslov = re.sub(r"\s*[-–—:|]?\s*(?:[Ss]\d{1,2}\s*[Ee]\d{1,3}|\d{1,2}x\d{2,3})\b.*$", "", _text(item.get("naslov"), 200)).strip() \
            or _text(item.get("naslov"), 200)
        kljuc_serije = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", naslov).encode("ascii", "ignore").decode().lower()).strip()
        kartica = serije.get(kljuc_serije)
        if kartica is None:
            kartica = dict(item, naslov=naslov, sezona=0, epizoda=0, epizode_seznama=[])
            kartica["id"] = "seznam-serija:" + hashlib.sha256(
                (str(item.get("vir_id") or "") + "|" + kljuc_serije).encode()).hexdigest()[:20]
            serije[kljuc_serije] = kartica
        if len(kartica["epizode_seznama"]) < MediaCenter.NAJVEC_EPIZOD_SERIJE:
            kartica["epizode_seznama"].append({k: item.get(k) for k in ("naslov", "url", "sezona", "epizoda", "glave", "referer",
                                                                         "slika", "kakovost", "locljivost")})

    def season_seznama(self, item_id: str, sezona: int) -> dict:
        """Epizode sezone serije s seznama (brez TMDB) za podrobnosti."""
        kartica = self._dynamic_items.get(str(item_id or "")) or {}
        epizode = sorted((e for e in kartica.get("epizode_seznama") or [] if int(e.get("sezona") or 0) == int(sezona)),
                         key=lambda e: int(e.get("epizoda") or 0))
        return {"sezona": int(sezona), "epizode": [{"stevilka": int(e.get("epizoda") or 0), "sezona": int(sezona),
                                                    "naslov": _text(e.get("naslov"), 200), "opis": "", "trajanje": 0,
                                                    "ocena": 0, "datum": "", "slika": ""} for e in epizode]}

    def epizoda_seznama(self, item_id: str, sezona: int, epizoda: int) -> Optional[dict]:
        """Predvajalni vnos epizode serije s seznama."""
        kartica = self._dynamic_items.get(str(item_id or "")) or {}
        e = next((e for e in kartica.get("epizode_seznama") or []
                  if int(e.get("sezona") or 0) == int(sezona) and int(e.get("epizoda") or 0) == int(epizoda)), None)
        if not e:
            return None
        vnos = _item(e.get("naslov") or kartica.get("naslov"), e.get("url"), base=str(e.get("url") or ""),
                     source_id=str(kartica.get("vir_id") or ""), source_name=str(kartica.get("vir") or ""),
                     kind="serija", season=int(sezona), episode=int(epizoda), headers=e.get("glave"),
                     referer=e.get("referer") or "", image=e.get("slika") or kartica.get("slika") or "")
        if not vnos:
            return None
        vnos["id"] = hashlib.sha256(("seznam-epizoda|" + str(e.get("url"))).encode()).hexdigest()[:20]
        self._dynamic_items[vnos["id"]] = vnos
        return vnos

    def kanal_skrit(self, item: Any) -> bool:
        """Kartica kanala IPTV, za katere vse kanale seznama vemo, da ne oddajajo (in nima vira, ki ni seznam IPTV).
        Neznan kanal ni skrit (pregled 30, J3); izid kanala z racunom (ki ga ne preverjamo) velja do izteka."""
        if not isinstance(item, dict) or item.get("vrsta") != "tv-v-zivo":
            return False
        razlicice = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)] or [item]
        if not all(r.get("iptv") for r in razlicice):
            return False

        def ne_oddaja(url: str) -> bool:
            if self.kanali.izid(url) not in (kanali_iptv.MRTEV, kanali_iptv.ZAKLENJEN):
                return False
            return not (kanali_iptv.s_poverilnicami(url) and self.kanali.potrebuje_preverbo(url))
        return all(ne_oddaja(str(r.get("url") or "")) for r in razlicice)

    def skrij_kanal(self, item: Any, url: str = "") -> bool:
        """Kanal ob kliku ni zaigral z nobeno razlicico: vsi njegovi kanali seznama so mrtvi (takoj skriti, do ponovne
        preverbe). Vrne True, ce je bil kanal s seznama IPTV."""
        if not isinstance(item, dict) or item.get("vrsta") != "tv-v-zivo":
            return False
        razlicice = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)] or [item]
        urlji = [str(r.get("url") or "") for r in razlicice if r.get("iptv") and r.get("url")]
        if not urlji:
            return False
        for u in urlji:
            self.kanali.oznaci_mrtev(u)
        self.ozastari_predpomnilnik()
        return True

    def _statistika_kanalov(self, source: dict) -> Optional[dict]:
        kanali = [x for x in source.get("vnosi") or [] if isinstance(x, dict) and x.get("iptv")]
        if not kanali:
            return None
        javni = kanali_iptv.je_javni_seznam(source.get("url"))
        izbira = self.tv_izbira() if javni else None
        vidni = [x for x in kanali if izbira is None or kanali_iptv.v_izbiri(x, izbira)]
        stevci = self.kanali.povzetek(str(x.get("url") or "") for x in vidni)
        # Seznam z racunom ne gre v preverbo (J3): stran pove, da kanale preveri sele predvajanje. Seznam, ki ni znan
        # javni vir in v naslovu nima racuna, sme uporabnik oznaciti kot javnega (pregled 39, I1).
        url = str(source.get("url") or "")
        oznacen = source.get("javni") is True
        preverba = kanali_iptv.javni_brezplacni(url, oznacen)
        return {"skupaj": len(kanali), "izbranih": len(vidni), "deluje": stevci[kanali_iptv.DELUJE],
                "zaklenjenih": stevci[kanali_iptv.ZAKLENJEN], "mrtvih": stevci[kanali_iptv.MRTEV],
                "preverjam": stevci["neznano"] if preverba else 0, "preverba": preverba,
                "ne_24_7": int(source.get("ne_24_7") or 0), "javni": javni,
                "oznacljiv": kanali_iptv.oznacljiv_javni(url), "oznacen_javni": oznacen}

    def nastavi_javni_seznam(self, source_id: str, javni: bool) -> dict:
        """Uporabnik je v Virih seznam oznacil kot javni brezplacni (brez racuna pri ponudniku) ali oznako umaknil.
        V ozadju se preverja SAMO tak seznam in znani javni viri (pregled 39, I1); seznama z racunom v naslovu ni mogoce
        oznaciti. Ob umiku oznake gredo njegovi kanali takoj iz vrste preverbe."""
        javni = javni is True
        with self._lock:
            data = self._load()
            source = next((x for x in data.get("viri", []) if isinstance(x, dict) and x.get("id") == str(source_id or "")),
                          None)
            if source is None:
                return {"ok": False, "napaka": "ni_vira"}
            if javni and not kanali_iptv.oznacljiv_javni(str(source.get("url") or "")):
                return {"ok": False, "napaka": "racun"}
            if javni:
                source["javni"] = True
            else:
                source.pop("javni", None)
            self._save(data)
            kopija = dict(source)
        if javni:
            self._vnosi_virov({"viri": [kopija]}, "tv-v-zivo")       # neznani kanali gredo v vrsto preverbe
        else:
            self.kanali.odstrani_iz_vrste(str(x.get("url") or "") for x in kopija.get("vnosi") or []
                                          if isinstance(x, dict) and x.get("iptv"))
        self.ozastari_predpomnilnik()
        return {"ok": True, "javni": javni}

    def ima_kodi(self) -> bool:
        return self._kodi_streznik() is not None

    def predvajaj_na_kodi(self, item_id: str) -> dict:
        kodi = self._kodi_streznik()
        if not kodi:
            return {"ok": False, "napaka": "V Medijskem centru ni povezanega Kodija."}
        item = self.resolve(item_id)
        url = str((item or {}).get("url") or "")
        if not url or (item or {}).get("stran") or (item or {}).get("napaka"):
            return {"ok": False, "napaka": "Te vsebine ni mogoče poslati na Kodi."}
        try:
            media_servers.kodi_predvajaj(kodi[0]["url"], kodi[0].get("uporabnik", ""), kodi[1], url)
        except Exception:
            return {"ok": False, "napaka": "Kodi se ni odzval."}
        return {"ok": True, "kodi": kodi[0].get("ime", "Kodi")}

    #: Osebni strezniki in dodatki: svez odgovor velja 5 min; do STREZNIK_STARO_S vrnemo zadnji odgovor takoj in ga
    #: osvezimo v ozadju (kot DNS »serve stale«), da Medijski center ne caka na pocasen dodatek.
    STREZNIK_SVEZE_S = 300
    STREZNIK_STARO_S = 6 * 60 * 60
    #: Neodziven dodatek (testni PC 17. 10. 2026: manifest Iracemaflix vsakic 10 s do roka) si zapomnimo za toliko
    #: sekund z zadnjim znanim (ali praznim) odgovorom; nato ga osvezujemo samo se v ozadju.
    STREZNIK_NAPAKA_S = 120
    #: Brez roka iskanja (rok_vira) na streznike cakamo najvec toliko sekund; kar ne odgovori, se nalaga naprej v ozadju
    #: in pride v predpomnilnik za naslednje iskanje.
    STREZNIKI_ROK_S = 4.0

    #: Odgovori TMDB in iskanja po strezniki, starejsi od tega, v pomnilniku niso vec uporabni (disk velja 24 h, sveze
    #: 2 h oz. 5 min); brez ciscenja sta v dolgotrajnem procesu rasla z vsakim iskanjem in vsako stranjo kataloga.
    PREDPOMNILNIK_POMNILNIK_S = 24 * 60 * 60

    def _pocisti_predpomnilnika(self) -> None:
        """Na 10 min odstrani zapise, starejse od PREDPOMNILNIK_POMNILNIK_S. Knjiznice streznikov (kljuc »id:«) ostanejo:
        iz njih _osebni_naslovi najde lastne tokove brez omrezja."""
        zdaj = time.time()
        if zdaj - self._predpomnilnika_pociscena < 600:
            return
        self._predpomnilnika_pociscena = zdaj
        meja = zdaj - self.PREDPOMNILNIK_POMNILNIK_S
        for kljuc, (cas, _v) in list(self._tmdb_cache.items()):
            if cas < meja:
                self._tmdb_cache.pop(kljuc, None)
        for kljuc, (cas, _v) in list(self._server_cache.items()):
            if cas < meja and not kljuc.endswith(":"):
                self._server_cache.pop(kljuc, None)

    #: Iskanje in katalog cakata na vsak vir najvec toliko sekund (None = do konca, npr. osvezitev v ozadju in orodja;
    #: osebni strezniki pa najvec STREZNIKI_ROK_S). Pocasni vir se konca v ozadju; njegove zadetke stran dobi z dogodkom
    #: (catalog_hitro -> ob_osvezitvi). Meritev 15. 10. 2026 (testni racunalnik, 10 dodatkov): viri zaporedno 20-40 s,
    #: en dodatek sam 11-20 s.
    rok_vira: Optional[float] = None
    #: Na nit: rok cakanja na vire in seznam nedokoncanih zahtev zadnjega kataloga (glej rok_vira).
    _iskanje_nit = threading.local()
    _v_teku_lock = threading.Lock()

    def _rok_zdaj(self) -> Optional[float]:
        rok = getattr(self._iskanje_nit, "rok", "privzeto")
        return self.rok_vira if rok == "privzeto" else rok

    def _rok_osebnih(self) -> Optional[float]:
        """Rok za osebne vire: rok niti ali rok_vira, sicer STREZNIKI_ROK_S. Le osvezitev v ozadju (rok niti None) pocaka
        vse - ne zadrzi nikogar, pogled pa je popoln."""
        rok = getattr(self._iskanje_nit, "rok", "privzeto")
        if rok != "privzeto":
            return rok
        return self.rok_vira if self.rok_vira is not None else self.STREZNIKI_ROK_S

    def _vzporedno(self, delo, *args):
        """Delo v skupnem bazenu virov (ena nit na vir); iste zahteve, ki se tecejo, se ne ponovijo."""
        return _bazen_virov().submit(delo, *args)

    def _cakaj(self, niti: list, rok: Optional[float]) -> list:
        """Pocaka na niti najvec `rok` s; nedokoncane zabelezi (catalog_hitro jih dokonca v ozadju)."""
        from concurrent.futures import wait
        if not niti:
            return []
        _koncane, nekoncane = wait(niti, timeout=rok)
        if nekoncane:
            cakajoci = getattr(self._iskanje_nit, "cakajoci", None)
            if isinstance(cakajoci, list):
                cakajoci.extend(nekoncane)
        return list(nekoncane)

    def _nalozi_streznik(self, provider: str, server: dict, server_query: str, key: str) -> list[dict]:
        secret = self._secret_decryptor(str(server.get("secret_enc") or ""))
        rows = media_servers.catalog(provider, str(server.get("url") or ""), server, secret, server_query)
        self._server_cache[key] = (time.time(), rows)
        self._pocisti_predpomnilnika()
        return rows

    def _nalozi_enkrat(self, provider: str, server: dict, server_query: str, key: str, cakaj: bool = True) -> list[dict]:
        """En prenos naenkrat na kljuc (hitro tipkanje, osvezitev v ozadju): ce isti ze tece, pocakamo njegov odgovor
        (`cakaj`) ali odnehamo. Napaka velja kot odgovor za STREZNIK_NAPAKA_S (zadnji znani ali prazen): naslednja
        iskanja ne cakajo znova do roka. Prenos se zabelezi sele, ko res tece - kdor caka, ne caka na nit v vrsti."""
        from concurrent.futures import Future
        if not isinstance(getattr(self, "_v_teku", None), dict):
            self._v_teku = {}
        with self._v_teku_lock:
            tece = self._v_teku.get(key)
            lastna = tece is None
            if lastna:
                tece = self._v_teku[key] = Future()
        if not lastna:
            return tece.result() if cakaj else []
        rows: list = []
        try:
            try:
                rows = self._nalozi_streznik(provider, server, server_query, key)
            except Exception:  # noqa: BLE001
                cached = self._server_cache.get(key)
                rows = cached[1] if cached else []
                self._server_cache[key] = (time.time() - self.STREZNIK_SVEZE_S + self.STREZNIK_NAPAKA_S, rows)
        finally:
            with self._v_teku_lock:
                self._v_teku.pop(key, None)
            tece.set_result(rows)
        return rows

    def _osvezi_streznik_v_ozadju(self, provider: str, server: dict, server_query: str, key: str) -> None:
        self._vzporedno(self._nalozi_enkrat, provider, server, server_query, key, False)

    def _vrstice_streznika(self, server: dict, query: str, zasebni: bool) -> list[dict]:
        """Vrstice enega osebnega vira (nit v skupnem bazenu): zasebnost (lahko prebere manifest) in prenos v niti
        streznika, da mrtev dodatek ne zadrzi drugih."""
        if self.zaseben_streznik(server) != zasebni:
            return []
        provider = str(server.get("ponudnik") or "")
        server_id = str(server.get("id") or "")
        server_query = query if provider in ("navidrome", "funkwhale") else ""
        key = server_id + ":" + server_query.casefold()
        cached = self._server_cache.get(key)
        now = time.time()
        if cached and now - cached[0] < self.STREZNIK_SVEZE_S:
            rows = cached[1]
        elif cached and now - cached[0] < self.STREZNIK_STARO_S:
            rows = cached[1]
            self._osvezi_streznik_v_ozadju(provider, server, server_query, key)
        else:
            rows = self._nalozi_enkrat(provider, server, server_query, key)
        if query and provider not in ("navidrome", "funkwhale"):
            rows = [item for item in rows if media_servers.ujema_iskanje(item, query)]
        return rows

    def _znane_vrstice(self, server: dict, query: str, zasebni: bool) -> list[dict]:
        """Vir, ki do roka ni odgovoril: zadnji znani zadetki (brez omrezja), sveze pridejo z dogodkom."""
        if self._zaseben_brez_omrezja(server) != zasebni:
            return []
        provider = str(server.get("ponudnik") or "")
        server_query = query if provider in ("navidrome", "funkwhale") else ""
        sid = str(server.get("id") or "")
        znano = self._server_cache.get(sid + ":" + server_query.casefold()) or self._server_cache.get(sid + ":")
        vrstice = list(znano[1]) if znano else []
        if query:
            vrstice = [item for item in vrstice if media_servers.ujema_iskanje(item, query)]
        return vrstice

    def _personal_items(self, query: str, zasebni: bool = False) -> list[dict]:
        """Vnosi osebnih virov, vsi hkrati (prej zaporedno - iskanje je cakalo na vsoto vseh), najvec _rok_osebnih() s;
        vrstni red streznikov ostane. Zasebni dodatki so posebej: `zasebni=True` vrne samo njihove (kategorija
        »Zasebno«)."""
        with self._lock:
            servers = [s for s in self._load().get("osebni_strezniki", []) if isinstance(s, dict)]
        zasebni = bool(zasebni)
        niti = [self._vzporedno(self._vrstice_streznika, server, query, zasebni) for server in servers]
        javni = [s for s in servers if not self._zaseben_brez_omrezja(s)]
        cinemeta = self._vzporedno(self._cinemeta_items, javni, [], query) if javni and not zasebni else None
        self._cakaj(niti + ([cinemeta] if cinemeta else []), self._rok_osebnih())
        result = []
        for server, nit in zip(servers, niti):
            if nit.done() and nit.exception() is None:
                result.extend(nit.result())
            else:
                result.extend(self._znane_vrstice(server, query, zasebni))
        if cinemeta is not None and cinemeta.done() and cinemeta.exception() is None and not self._ima_katalog_tt(result):
            result.extend(cinemeta.result())
        return result

    @staticmethod
    def _ima_katalog_tt(vrstice: list) -> bool:
        """Katalog dodatka ze daje filme/serije z id-ji IMDb: Cinemete ne dodajamo."""
        return any(isinstance(x, dict) and x.get("stremio") and str(x.get("imdb_id") or "").startswith("tt")
                   and x.get("vrsta") in ("film", "serija") for x in vrstice)

    def _cinemeta_items(self, servers: list, vrstice: list, query: str) -> list[dict]:
        """Katalog filmov in serij (Cinemeta - samo podatki o naslovih, tokove dajo uporabnikovi dodatki), kadar ima
        uporabnik dodatek, ki predvaja filme ali serije po id-jih IMDb, njegovi katalogi pa takih naslovov ne dajo -
        kot Safeer OS na Androidu (Stremio.zKatalogom). Uporabnik doda dodatek in pozabi nanj: filmi in serije se
        pokazejo, kar noben dodatek ne predvaja, skrije preverba razpolozljivosti."""
        # Samo katalogi dodatkov: naslovi z id-ji IMDb z osebnega strežnika (Jellyfin) Cinemete ne nadomestijo.
        if self._ima_katalog_tt(vrstice):
            return []
        stremio = [s for s in servers if isinstance(s, dict) and s.get("ponudnik") == "stremio" and s.get("url")
                   and media_servers._stremio_koren(str(s.get("url"))) != media_servers._stremio_koren(media_servers.CINEMETA)]
        if not stremio:
            return []
        zdaj = time.time()
        if not hasattr(self, "_tt_dodatki"):
            self._tt_dodatki = {}
        imdb = False
        for s in stremio:
            koren = media_servers._stremio_koren(str(s.get("url")))
            znano = self._tt_dodatki.get(koren)
            if not znano or zdaj - znano[0] > 3600:
                try:
                    znano = (zdaj, media_servers.stremio_toki_imdb(media_servers.stremio_manifest(koren)))
                except Exception:
                    znano = (zdaj, False)
                self._tt_dodatki[koren] = znano
            if znano[1]:
                imdb = True
                break
        if not imdb:
            return []
        streznik = {"id": "cinemeta", "ime": "Cinemeta", "ponudnik": "stremio", "url": media_servers.CINEMETA}
        kljuc = "cinemeta:" + query.casefold()
        cached = self._server_cache.get(kljuc)
        if cached and zdaj - cached[0] < 300:
            return cached[1]
        try:
            vrstice_c = media_servers.catalog("stremio", media_servers.CINEMETA, streznik, "", query)
        except Exception:
            return cached[1] if cached else []
        vrstice_c = [x for x in vrstice_c if x.get("vrsta") in ("film", "serija")]
        self._server_cache[kljuc] = (zdaj, vrstice_c)
        self._pocisti_predpomnilnika()
        return vrstice_c

    def add_source(self, url: str, name: str = "", prevzet: Optional[dict] = None, ozji_krog: bool = False) -> dict:
        """`prevzet`: vir je prisel z druge naprave v Linku ({"tip", "naslov", "cas"}, core/viri_sink.py). `ozji_krog`:
        ta naprava nas ima v ozjem krogu (odgovor `lists.get`: "ozji" true); brez dokaza (privzeto) je prejet vir z
        racunom ali neznane oblike fail-closed."""
        canonical = canonical_url(url)
        with self._lock:
            data = self._load()
            for source in data.get("viri", []):
                if source.get("url") == canonical:
                    return {"ok": False, "napaka": "podvojen",
                            "vir": {k: v for k, v in source.items() if k != "vnosi"}}
            source = {
                "id": hashlib.sha256(canonical.encode()).hexdigest()[:16],
                "url": canonical,
                "ime": _text(name, 80) or urllib.parse.urlsplit(canonical).hostname or "Vir",
                "posodobljeno": 0,
                "napaka": "",
                "stevilo": 0,
                "vnosi": [],
            }
            if _je_predvajalni_vir(canonical):
                source["tip"] = "predvajalni_vir"
            self._vir_dodan(source, viri_sink.URL, canonical, prevzet)
            neprenesen = bool(prevzet) and self._caka_uporabnika(canonical)
            prvo = neprenesen and ozji_krog is True
            caka = neprenesen and not prvo
            if prvo:
                # Lastnik, 26. 10. 2026 (vse naprave pripadajo uporabniku): vir iz ozjega kroga je viden takoj, a se ne
                # prenese ob prejemu in ne v ozadju - prva povezava (ena) je ob odprtju seznama na tej napravi, nato velja
                # 24-urni predpomnilnik in najvec ena osvezitev na minuto (refresh_source). Nikoli ne dvakrat naenkrat.
                source["prvo_uporaba"] = int(time.time())
                source["ozji_krog"] = True
                source["razclenitev"] = kanali_iptv.RAZCLENITEV
            elif caka:
                # Pregled 51, Ñ2: vir z racunom, prejet z druge naprave, se ne prenese ob prejemu (vsaka naprava v krogu
                # bi ob prvem usklajevanju poslala ponudniku zahtevo z geslom). Prenese ga naprava, kjer je bil dodan; ta
                # ga prenese, ko uporabnik osvezi vir (refresh_source); samodejna pota ga preskocijo. Pregled 57, Ş1:
                # velja za vsak prejet vir, ki ni pozitivno znan javen, ne le za prepoznano obliko racuna.
                source["caka_uporabnika"] = int(time.time())
                source["razclenitev"] = kanali_iptv.RAZCLENITEV       # ni »zastarel«: katalog ga ne bere v ozadju
            data.setdefault("viri", []).append(source)
            self._save(data)
        if neprenesen:
            self._potrdi_prejeti_vir(canonical, prevzet)
            return {"ok": True, "napaka": "", "caka": caka, "prvo_uporaba": prvo,
                    "vir": {k: v for k, v in source.items() if k != "vnosi"}}
        # Odziv vira začnemo meriti takoj ob dodajanju, da je meritev navadno
        # že na voljo, ko uporabnik prvič izbere film ali epizodo.
        threading.Thread(target=self._izmeri_ping, args=(canonical,), daemon=True).start()
        # Vdelava strani HTML samo ob prvem dodajanju, ko je uporabnik prisoten (pregled 63, Ŷ1); prejet vir je ne dobi.
        rezultat = self.refresh_source(source["id"], dovoli_vdelavo=not prevzet)
        vir = rezultat.get("vir") or {}
        # Vir predvajalnika (TMDB katalog + vdelani predvajalnik) nima lastnih vnosov, a je predvajljiv.
        if rezultat.get("ok") and (int(vir.get("stevilo") or 0) > 0 or source.get("tip") == "predvajalni_vir"
                                   or vir.get("tip") in ("predvajalni_vir", "uradni_vdelani_predvajalnik")):
            self._potrdi_prejeti_vir(canonical, prevzet)
            return rezultat
        # Vira, iz katerega ne moremo nicesar predvajati, ne pustimo v medijskem centru - in povemo zakaj.
        with self._lock:
            data = self._load()
            data["viri"] = [item for item in data.get("viri", []) if item.get("id") != source["id"]]
            self._save(data)
        razlog = _text(rezultat.get("napaka"), 180)
        sporocilo = ("Safeer v tem viru ni našel ničesar, kar bi lahko predvajal, zato ga nismo dodali."
                     + (" (" + razlog + ")" if razlog and razlog != "ni_vira" else ""))
        return {"ok": False, "napaka": razlog or "nepredvajljiv", "nepredvajljiv": True, "sporocilo": sporocilo}

    @staticmethod
    def _caka_uporabnika(naslov: str) -> bool:
        """Vir, prejet z druge naprave, ki ga ob prejemu ne prenesemo (pregled 51, Ñ2): vsak, ki ni POZITIVNO znan javen
        (viri_sink.za_ozji_krog, enako kot pri izvozu in prikazu). Pregled 57, Ş1: prej je odlocala hevristika oblike
        naslova ali vrsta, ki jo je navedla druga naprava (»seznam«), zato se je kratka povezava, zeton v poti ali
        .../x.m3u vrste »url« ob prejemu takoj prenesla na vsaki napravi v ozjem krogu (lastnikov racun, zaklep pri
        ponudniku). Vrsti ne zaupamo (doloci jo druga naprava), obliki naslova tudi ne: ob dvomu vir caka, dokler
        uporabnik na tej napravi izrecno ne pritisne »Osvezi« (refresh_source)."""
        return viri_sink.za_ozji_krog(naslov)

    def remove_source(self, source_id: str, cas: int = 0, kljuc: str = "") -> bool:
        """`cas`, `kljuc`: izbris je prisel z druge naprave v Linku (njen cas in njen kljuc vira, core/viri_sink.py)."""
        with self._lock:
            data = self._load()
            servers_before = len(data.get("osebni_strezniki", []))
            odstranjen = next((s for s in data.get("osebni_strezniki", []) if s.get("id") == source_id), None)
            data["osebni_strezniki"] = [server for server in data.get("osebni_strezniki", [])
                                        if server.get("id") != source_id]
            if len(data["osebni_strezniki"]) != servers_before:
                self._server_cache = {key: value for key, value in self._server_cache.items()
                                      if not key.startswith(source_id + ":")}
                self._save(data)
                self.ozastari_predpomnilnik(izbrisi=True)  # odstranjen vir ne sme vec kazati svojih vnosov
                if isinstance(odstranjen, dict) and odstranjen.get("ponudnik") == "stremio":
                    if odstranjen.get("url_enc") or not viri_sink.javen_naslov(viri_sink.STREMIO, str(odstranjen.get("url") or "")):
                        self._odstranjen_skrivni(odstranjen, data)       # ni v Linku: izbrisa ne posljemo
                    else:
                        self._vir_izbrisan(odstranjen, cas, kljuc)
                return True
            before = len(data.get("viri", []))
            odstranjen = next((s for s in data.get("viri", []) if s.get("id") == source_id), None)
            data["viri"] = [source for source in data.get("viri", []) if source.get("id") != source_id]
            if len(data["viri"]) == before:
                return False
            self._save(data)
            self.ozastari_predpomnilnik(izbrisi=True)
            if isinstance(odstranjen, dict):
                self._vir_izbrisan(odstranjen, cas, kljuc)
            return True

    # --- Moji viri so enaki na vseh napravah v Safeer Linku (core/viri_sink.py) ---------------------------------
    def _viri_stanje(self) -> dict:
        """{"izbrisani": {"tip|naslov": cas}, "zavrnjeni": {istovetnost: [cas poskusa, koliko velja]}}."""
        try:
            data = json.loads((self.config_dir / "viri_sink.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        izbrisani = data.get("izbrisani") if isinstance(data.get("izbrisani"), dict) else {}
        zavrnjeni = data.get("zavrnjeni") if isinstance(data.get("zavrnjeni"), dict) else {}
        return {"izbrisani": {str(k): int(v) for k, v in izbrisani.items() if isinstance(v, (int, float)) and v > 0},
                "zavrnjeni": {str(k): [int(v[0]), int(v[1])] for k, v in zavrnjeni.items()
                              if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)}}

    def _viri_stanje_pisi(self, stanje: dict) -> None:
        zavrnjeni = dict(sorted(stanje.get("zavrnjeni", {}).items(), key=lambda kv: kv[1][0], reverse=True)[:400])
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.config_dir / "viri_sink.json", {"izbrisani": viri_sink.obrezi_izbrisane(stanje.get("izbrisani", {})),
                                           "zavrnjeni": zavrnjeni}, indent=None)
        except OSError:
            pass

    @staticmethod
    def _vir_kljuc(source: dict) -> tuple:
        """(vrsta, naslov) vira za druge naprave: kar je prislo z naprave, obdrzi njen zapis; dodatek je naslov
        manifesta (kot na Androidu); naslov, dodan na racunalniku, ima vrsto "url"."""
        if source.get("ponudnik") == "stremio":
            return viri_sink.STREMIO, str(source.get("link_naslov") or "") or viri_sink.stremio_naslov(str(source.get("url") or ""))
        return str(source.get("link_tip") or viri_sink.URL), str(source.get("link_naslov") or source.get("url") or "")

    def _vir_dodan(self, source: dict, tip: str, naslov: str, prevzet: Optional[dict]) -> None:
        """Ob dodajanju (klic pod zaklepom): cas dodajanja za usklajevanje in - pri viru z naprave - njen zapis."""
        stanje = self._viri_stanje()
        if prevzet:
            source["dodan"] = int(prevzet.get("cas") or 0) or 1
            if tip != viri_sink.STREMIO:
                source["link_tip"] = str(prevzet.get("tip") or viri_sink.URL)
            source["link_naslov"] = str(prevzet.get("naslov") or naslov)
        else:
            source["dodan"] = viri_sink.nov_cas(self._zdaj_ms(), 0, viri_sink.cas_izbrisa(stanje["izbrisani"], tip, naslov) or 0)

    def _vir_potrjen(self, tip: str, naslov: str) -> None:
        """Vir je res dodan (predvajljiv): znan izbris in zavrnitev istega vira pozabimo, izvoz za naprave osvezimo."""
        with self._lock:
            stanje = self._viri_stanje()
            self._vir_potrjen_pod_zaklepom(stanje, tip, naslov)
        self._viri_zapisi_izvoz()

    def _vir_potrjen_pod_zaklepom(self, stanje: dict, tip: str, naslov: str) -> None:
        i = viri_sink.istovetnost(tip, naslov)
        ostali = {k: v for k, v in stanje["izbrisani"].items() if viri_sink.istovetnost_kljuca(k) != i}
        if len(ostali) != len(stanje["izbrisani"]) or i in stanje["zavrnjeni"]:
            stanje["izbrisani"] = ostali
            stanje["zavrnjeni"].pop(i, None)
            self._viri_stanje_pisi(stanje)

    def _vir_izbrisan(self, source: dict, cas: int = 0, kljuc: str = "") -> None:
        """Izbris si zapomnimo s casom: druge naprave v Linku vir izbrisejo tudi pri sebi in ga ne vrnejo sem."""
        tip, naslov = self._vir_kljuc(source)
        if not naslov:
            return
        stanje = self._viri_stanje()
        stanje["izbrisani"][kljuc or viri_sink.kljuc(tip, naslov)] = \
            int(cas) if cas else viri_sink.nov_cas(self._zdaj_ms(), int(source.get("dodan") or 0), 0)
        self._viri_stanje_pisi(stanje)
        self._viri_zapisi_izvoz()

    def _stremio_zaseben_znano(self, server: dict) -> Optional[bool]:
        """Ali je dodatek zaseben - brez omrezja: iz zapisa streznika ali iz tega zagona. None = se ne vemo."""
        # Ime dodatka za odrasle (»JAV Nexus«) velja tudi, ce je zapis iz casa pred to presojo shranil »ni zaseben«.
        if media_servers.je_besedilo_za_odrasle(server.get("ime")):
            return True
        if isinstance(server.get("zaseben"), bool):
            return server["zaseben"]
        return self._zasebni_koreni.get(media_servers._stremio_koren(str(server.get("url") or "")))

    # --- kategorija »Zasebno« (lastnik, 17. 10. 2026) ------------------------------------------------------------
    # Vsebina zasebnih dodatkov (manifest behaviorHints.adult) se pokaze samo, ce jo uporabnik vklopi, in samo v svoji
    # kategoriji - nikoli v drugih kategorijah, iskanju, predlogih ali na policah. Privzeto izklopljeno. Kar ne vemo,
    # ali je zaseben (manifesta ni bilo mogoce prebrati), velja kot zaseben.
    ZASEBNO = "zasebno"
    #: Ali je uporabnik vklopil kategorijo »Zasebno« (core/os_katalog.py jo nastavi iz nastavitev Medijskega centra).
    zasebno = False
    #: Dodatek, katerega manifesta ni bilo mogoce prebrati, vprasamo znova sele cez toliko sekund (mrtev dodatek ne
    #: sme ob vsakem iskanju toka cakati na omrezje).
    ZASEBEN_NEZNANO_S = 300

    def zaseben_streznik(self, server: dict) -> bool:
        """Ali je osebni vir zaseben dodatek. Prvic lahko prebere manifest (klic iz delovne niti)."""
        if not isinstance(server, dict) or server.get("ponudnik") != "stremio":
            return False
        znano = self._stremio_zaseben_znano(server)
        if znano is None:
            koren = media_servers._stremio_koren(str(server.get("url") or ""))
            neznano = self.__dict__.setdefault("_zaseben_neznano", {})
            if time.monotonic() - neznano.get(koren, -1e9) > self.ZASEBEN_NEZNANO_S:
                znano = self._koren_zaseben(koren)
                if znano is None:
                    neznano[koren] = time.monotonic()
        return znano is not False

    def _zaseben_brez_omrezja(self, server: dict) -> bool:
        """Kot zaseben_streznik, brez omrezja: kar se ne vemo, velja kot zaseben."""
        if not isinstance(server, dict) or server.get("ponudnik") != "stremio":
            return False
        return self._stremio_zaseben_znano(server) is not False

    def zasebni_koreni(self) -> set:
        """Koreni zasebnih dodatkov med uporabnikovimi viri (in tistih, ki so se v tem zagonu pokazali kot zasebni)."""
        with self._lock:
            strezniki = [x for x in self._load().get("osebni_strezniki", []) if isinstance(x, dict)]
        koreni = {media_servers._stremio_koren(str(s.get("url") or "")) for s in strezniki if self.zaseben_streznik(s)}
        koreni.update(k for k, z in list(self._zasebni_koreni.items()) if z)
        koreni.discard("")
        return koreni

    @staticmethod
    def _zaseben_naslov(url: str, koreni: set) -> bool:
        if not url.startswith("stremio:"):
            return False
        return url[len("stremio:"):].split("|", 1)[0] in koreni

    def je_zaseben_vnos(self, item: Any, koreni: Optional[set] = None) -> bool:
        """Kartico je ponudil zaseben dodatek (njen tok ali katera od razlicic je iz njega)."""
        if not isinstance(item, dict):
            return False
        koreni = self.zasebni_koreni() if koreni is None else koreni
        if not koreni:
            return False
        stremio = item.get("stremio") if isinstance(item.get("stremio"), dict) else {}
        if media_servers._stremio_koren(str(stremio.get("koren") or "")) in koreni:
            return True
        naslovi = [str(item.get("url") or "")] + [str(r.get("url") or "") for r in (item.get("razlicice") or [])
                                                  if isinstance(r, dict)]
        return any(self._zaseben_naslov(u, koreni) for u in naslovi)

    def brez_zasebnih(self, vnosi: Any, koreni: Optional[set] = None) -> Any:
        """Seznam kartic brez vsebine zasebnih dodatkov: zasebne razlicice izpadejo, kartica brez drugih tudi."""
        if not isinstance(vnosi, list):
            return vnosi
        koreni = self.zasebni_koreni() if koreni is None else koreni
        if not koreni:
            return vnosi
        izhod = []
        for item in vnosi:
            if not isinstance(item, dict) or not self.je_zaseben_vnos(item, koreni):
                izhod.append(item)
                continue
            ostale = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)
                      and not self._zaseben_naslov(str(r.get("url") or ""), koreni)]
            if not ostale:
                continue                          # samo iz zasebnega dodatka
            glavna = ostale[0]
            novo = dict(item, razlicice=ostale, stevilo_razlicic=len(ostale),
                        url=glavna.get("url") or item.get("url"), vir=glavna.get("vir") or item.get("vir"),
                        vir_id=glavna.get("vir_id") or item.get("vir_id"),
                        viri=list(dict.fromkeys(r.get("vir", "") for r in ostale if r.get("vir"))))
            stremio = item.get("stremio") if isinstance(item.get("stremio"), dict) else {}
            if media_servers._stremio_koren(str(stremio.get("koren") or "")) in koreni:
                # Javni naslov (npr. TMDB), katerega glavna razlicica je bila iz zasebnega dodatka: dodatek ostane javni.
                novo.pop("stremio", None)
                u = str(novo.get("url") or "")
                if u.startswith("stremio:"):
                    koren, tip, ident = (u[len("stremio:"):].split("|") + ["", ""])[:3]
                    novo["stremio"] = {"koren": koren, "tip": tip, "id": ident}
            izhod.append(novo)
        return izhod

    def _brez_zasebnih_rezultat(self, rezultat: Any, kind: str) -> Any:
        """Odgovor kataloga za kategorijo: v »Zasebno« samo, ce je vklopljena; drugje nikoli zasebne vsebine."""
        if not isinstance(rezultat, dict):
            return rezultat
        if kind == self.ZASEBNO:
            return rezultat if self.zasebno else dict(rezultat, vnosi=[], skupaj=0, skupaj_strani=1)
        vnosi = self.brez_zasebnih(rezultat.get("vnosi"))
        if vnosi is rezultat.get("vnosi"):
            return rezultat
        novo = dict(rezultat, vnosi=vnosi)
        if isinstance(rezultat.get("skupaj"), int):
            novo["skupaj"] = max(len(vnosi), rezultat["skupaj"] - (len(rezultat["vnosi"]) - len(vnosi)))
        return novo

    def pozabi_zasebno_v_predpomnilniku(self) -> None:
        """Kategorija »Zasebno« izklopljena: njeni shranjeni pogledi izginejo tudi z diska."""
        with self._predpomnilnik_lock:
            katalog = self._nalozi_predpomnilnik()["katalog"]
            for kljuc in list(katalog):
                if self._je_zasebni_pogled(kljuc):
                    katalog.pop(kljuc, None)
        self._shrani_predpomnilnik()

    @classmethod
    def _je_zasebni_pogled(cls, kljuc: str) -> bool:
        """Kljuc shranjenega pogleda (kljuc_kataloga) je kategorija »Zasebno«."""
        try:
            return json.loads(kljuc)[2] == cls.ZASEBNO
        except (ValueError, TypeError, IndexError, KeyError):
            return False

    @staticmethod
    def _vir_za_naprave(source: dict) -> bool:
        """Naslov, dodan na racunalniku, gre napravam, ce je tu predvajljiv in ni predloga predvajalnika (te pozna
        samo racunalnik)."""
        url = str(source.get("url") or "")
        if source.get("tip") == "predvajalni_vir" or "{" in url or source.get("napaka"):
            return False
        return int(source.get("stevilo") or 0) > 0

    def viri_izvoz(self, ozji: bool = False) -> dict:
        """Moji viri za druge naprave v Linku (del odgovora `lists.get {}`): brez omrezja. Vir z racunom ponudnika in
        njegov izbris samo napravi v ozjem krogu (`ozji`; viri_sink.za_ozji_krog - z Androida, VISOKO, 26. 10. 2026)."""
        return viri_sink.viri_za(self._viri_izvoz_razdeljen(), ozji)

    def _viri_izvoz_razdeljen(self) -> dict:
        """Viri za naprave, razdeljeni na vire brez racuna in z racunom (viri_sink.razdeli_izvoz). Zasebnega dodatka in
        dodatka, za katerega se ne vemo, ali je zaseben, ni (tega spoznamo v ozadju)."""
        with self._lock:
            data = self._load()
            stanje = self._viri_stanje()
        viri, neznani = [], []
        for s in data.get("osebni_strezniki", []):
            if not isinstance(s, dict) or s.get("ponudnik") != "stremio" or not s.get("url"):
                continue
            zaseben = self._stremio_zaseben_znano(s)
            if zaseben is None:
                neznani.append(str(s.get("id") or ""))
            if zaseben is not False:
                continue
            tip, naslov = self._vir_kljuc(s)
            if s.get("link_naslov") and viri_sink.za_ozji_krog(naslov):
                continue                # prejet z druge naprave: ne naprej v NAS ozji krog (pregled 51, Ê4)
            viri.append({"tip": tip, "ime": str(s.get("ime") or "")[:200], "naslov": naslov, "cas": int(s.get("dodan") or 0)})
        for v in data.get("viri", []):
            if not isinstance(v, dict) or not v.get("url") or not (v.get("link_tip") or self._vir_za_naprave(v)):
                continue
            tip, naslov = self._vir_kljuc(v)
            if v.get("link_naslov") and viri_sink.za_ozji_krog(naslov, v.get("javni") is True):
                continue                # Ê4: ozji krog je na vsaki napravi poseben; vir z geslom ne sme tranzitivno naprej
            viri.append(dict({"tip": tip, "ime": str(v.get("ime") or "")[:200], "naslov": naslov, "cas": int(v.get("dodan") or 0)},
                             # oznaka uporabnika »javni« (viri_sink.znan_javen); napravam ne gre (cist_vir)
                             **({"javni": True} if v.get("javni") is True else {})))
        if neznani:
            self._spoznaj_dodatke(neznani)
        return viri_sink.razdeli_izvoz([v for v in viri if viri_sink.cist_vir(v)], dict(stanje["izbrisani"]),
                                       self._usenet_za_krog())

    def _usenet_za_krog(self) -> Optional[dict]:
        """Naloga 114: lasten ponudnik Usenet (brez gesla) za ozji krog; razdeli_izvoz ga da samo v del »ozji«."""
        l = getattr(self.debrid, "lastni_usenet", None)
        try:
            return l.za_krog() if l is not None else None
        except Exception:  # noqa: BLE001 - zapis virov za naprave ne sme pasti zaradi ponudnika
            return None

    #: Enkratna selitev virov z racunom (pregled 46, Ö3); zapis "racuni_preseljeni" v media.json.
    PRESELITEV_RACUNOV = 1

    def _preseli_racune(self) -> None:
        """Enkrat po posodobitvi (pregled 46, Ö3). Starejse razlicice so vir z racunom (seznam Xtream z geslom) dale
        vsem napravam z dovoljenjem Predvajalnik; izbris ga zunaj ozjega kroga ne doseze.
        1) Vir, prejet z druge naprave (link_naslov), ki ni pozitivno znan javen, gre s te naprave - BREZ zapisa izbrisa
           (izbris bi se razsiril nazaj in vir izbrisal lastniku). Naprava v ozjem krogu ga ob naslednjem usklajevanju
           dobi znova (odgovor z "ozji": true; viri_sink.prevzem_dovoljen).
        2) Opozorilo za menjavo gesla (pregled 51, Ê2; lastnik: opozorilo je neskodljivo, zato ob dvomu da). Dobi ga
           vsak lastni vir z racunom (viri_sink.verjetno_geslo), razen ce je DOKAZANO, da nikoli ni sel zunaj ozjega
           kroga: zapisa za naprave (viri_za_naprave.json, edini vir za Control, core/link_seznami.py) sploh ni bilo ali
           vira nikoli nismo uspesno prebrali. Ne zavisi od javnega dela starega zapisa (razlicica 0f3f368 je vir pisala
           v »ozji«, zapis se prepisuje ob spremembah), ne od trenutnih naprav v Linku (gost je lahko ze odstranjen) in ne
           od tega, da vir se obstaja: za izbrisane vire z geslom (viri_sink.json) je eno splosno opozorilo.

        Robustnost (pregled 51, Ê7): pokvarjen zapis ali nepricakovana vrsta polja selitve ne sme ustaviti Medijskega
        centra; oznaka "racuni_preseljeni" se zapise sele, ko je selitev stekla (ali ko je ni cesa seliti)."""
        if self._racuni_preseljeni:
            return
        try:
            self._preseli_racune_delo()
        except Exception as exc:  # noqa: BLE001 - selitev ne sme ustaviti Medijskega centra
            print("[SafeerMedia] selitev racunov ni uspela (%s), poskusimo ob naslednjem zagonu" % type(exc).__name__,
                  flush=True)

    @staticmethod
    def _celo(vrednost: object) -> int:
        """Vrednost zapisa kot celo stevilo; kar to ni, je 0."""
        try:
            return int(vrednost or 0)
        except (TypeError, ValueError):
            return 0

    def _preseli_racune_delo(self) -> None:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._racuni_preseljeni = True      # nova namestitev: nic za preseliti, prvi _save zapise oznako
            return
        except ValueError:
            self._racuni_preseljeni = True      # pokvarjen zapis nima kopij, ki bi jih odstranili; _save ga zamenja
            return
        except OSError:
            return                              # zapis je, a ga zdaj ne moremo prebrati: poskusimo ob naslednjem zagonu
        if not isinstance(data, dict) or self._celo(data.get("racuni_preseljeni")) >= self.PRESELITEV_RACUNOV:
            self._racuni_preseljeni = True
            return
        try:
            (self.config_dir / "viri_za_naprave.json").read_text(encoding="utf-8")
            zapis_je = True
        except FileNotFoundError:
            zapis_je = False            # Control ni imel kaj ponuditi: nobena naprava ni dobila gesla
        except (OSError, ValueError):
            zapis_je = True             # zapis je, a ga ne moremo prebrati: ne dokazuje nic
        zdaj = self._zdaj_ms()

        def prejet(s: object) -> bool:
            return isinstance(s, dict) and bool(s.get("link_naslov")) and viri_sink.za_ozji_krog(str(s["link_naslov"]))
        with self._lock:
            data = self._load()
            if self._celo(data.get("racuni_preseljeni")) >= self.PRESELITEV_RACUNOV:
                self._racuni_preseljeni = True
                return
            strezniki = data.get("osebni_strezniki") if isinstance(data.get("osebni_strezniki"), list) else []
            odstranjeni = [str(s.get("id") or "") for s in strezniki if prejet(s)]
            data["osebni_strezniki"] = [s for s in strezniki if not prejet(s)]
            pred = len(data["viri"])
            data["viri"] = [v for v in data["viri"] if not prejet(v)]
            for v in data["viri"]:
                if (zapis_je and isinstance(v, dict) and not v.get("link_naslov") and not v.get("deljeno_potrjeno")
                        and not self._nikoli_prebran(v)
                        and viri_sink.verjetno_geslo(v.get("url"), any(isinstance(x, dict) and x.get("iptv")
                                                                      for x in (v["vnosi"] if isinstance(v.get("vnosi"), list) else [])),
                                                     v.get("javni") is True)):
                    v["deljeno_zunaj"] = zdaj
            if (zapis_je and not data.get("deljeno_izbrisani_potrjeno")
                    and any(viri_sink.verjetno_racun_seznama(k.partition("|")[2], siroko=True)
                            for k in self._viri_stanje()["izbrisani"])):
                data["deljeno_izbrisani"] = zdaj
            self._racuni_preseljeni = True              # oznako zapise _save: selitev je stekla
            self._save(data)
            self._server_cache = {k: c for k, c in self._server_cache.items()
                                  if not any(k.startswith(i + ":") for i in odstranjeni if i)}
        if odstranjeni or len(data["viri"]) != pred:
            print("[SafeerMedia] selitev: prejeti viri z racunom odstranjeni: %d" % (len(odstranjeni) + pred - len(data["viri"])),
                  flush=True)
        if zapis_je:
            self._viri_zapisi_izvoz()   # stari zapis (vir z geslom v javnem delu) takoj zamenjamo - Control bere tega

    @staticmethod
    def _nikoli_prebran(vir: dict) -> bool:
        """Vira nikoli nismo uspesno prebrali (posodobljeno in stevilo 0, brez vnosov): ponujen ni bil nikoli
        (`_vir_za_naprave` zahteva stevilo > 0)."""
        return (not vir.get("vnosi") and not MediaCenter._celo(vir.get("posodobljeno"))
                and not MediaCenter._celo(vir.get("stevilo")))

    def opozorila_virov(self) -> dict:
        """Splosna opozorila Virov, ki niso vezana na en vir: `izbrisani` - geslo vira, ki ga je lastnik ze izbrisal, je
        bilo morda deljeno zunaj ozjega kroga (pregled 51, Ê2)."""
        with self._lock:
            return {"izbrisani": bool(self._load().get("deljeno_izbrisani"))}

    def potrdi_opozorilo_deljeno(self, source_id: str) -> dict:
        """Lastnik je prebral opozorilo, da je bilo geslo vira deljeno zunaj ozjega kroga (pregled 46, Ö3): ne pokazemo
        ga vec. `*`: splosno opozorilo za izbrisane vire (pregled 51, Ê2)."""
        with self._lock:
            data = self._load()
            if source_id == "*":
                if data.pop("deljeno_izbrisani", None) is not None:
                    data["deljeno_izbrisani_potrjeno"] = self._zdaj_ms()
                    self._save(data)
                return {"ok": True}
            source = next((x for x in data.get("viri", []) if isinstance(x, dict) and x.get("id") == str(source_id or "")),
                          None)
            if source is None:
                return {"ok": False, "napaka": "ni_vira"}
            if source.pop("deljeno_zunaj", None) is not None:
                source["deljeno_potrjeno"] = self._zdaj_ms()
                self._save(data)
        return {"ok": True}

    def _viri_zapisi_izvoz(self) -> None:
        """Na Linuxu drugim napravam odgovarja Safeer Control (tudi ko Safeer OS ni odprt, core/link_seznami.py): vire
        zanj zapisemo v datoteko ob seznamih. Zapis je ze prefiltriran - zasebnih dodatkov v njem ni."""
        try:
            izvoz = self._viri_izvoz_razdeljen()        # Control vire z racunom da samo ozjemu krogu (link_seznami)
            self.config_dir.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.config_dir / "viri_za_naprave.json", izvoz, indent=None)
        except Exception:  # noqa: BLE001 - izvoz za naprave ne sme ustaviti Medijskega centra
            pass

    def _spoznaj_dodatke(self, idji: list) -> None:
        """Dodatke, dodane pred usklajevanjem, v ozadju vprasa po manifestu (ali so zasebni) in to zapise k strezniku;
        vsakega najvec enkrat na 10 minut."""
        zdaj = time.monotonic()
        idji = [i for i in idji if i and zdaj - self._dodatki_vprasani.get(i, -1e9) > 600]
        if not idji or self._spoznavam_dodatke:
            return
        self._spoznavam_dodatke = True
        for i in idji:
            self._dodatki_vprasani[i] = zdaj

        def delo() -> None:
            try:
                spoznani = {}
                with self._lock:
                    strezniki = [dict(s) for s in self._load().get("osebni_strezniki", []) if s.get("id") in idji]
                for s in strezniki:
                    zaseben = self._koren_zaseben(str(s.get("url") or ""))
                    if zaseben is not None:
                        spoznani[s["id"]] = bool(zaseben)
                if spoznani:
                    with self._lock:
                        data = self._load()
                        for s in data.get("osebni_strezniki", []):
                            if s.get("id") in spoznani:
                                s["zaseben"] = spoznani[s["id"]]
                        self._save(data)
            finally:
                self._spoznavam_dodatke = False
            if spoznani:
                self._viri_zapisi_izvoz()
        threading.Thread(target=delo, name="safeer-viri-dodatki", daemon=True).start()

    def _viri_moji(self, data: dict) -> list:
        """[(istovetnost, cas dodajanja, id vira)] - vir z naprave ima dve istovetnosti (njen naslov in nas)."""
        izid = []
        for s in data.get("osebni_strezniki", []):
            if isinstance(s, dict) and s.get("ponudnik") == "stremio" and s.get("url"):
                izid.append((viri_sink.istovetnost(viri_sink.STREMIO, str(s["url"])), int(s.get("dodan") or 0), str(s.get("id") or "")))
        for v in data.get("viri", []):
            if isinstance(v, dict) and v.get("url"):
                for naslov in dict.fromkeys((str(v["url"]), str(v.get("link_naslov") or v["url"]))):
                    izid.append((viri_sink.istovetnost(viri_sink.URL, naslov), int(v.get("dodan") or 0), str(v.get("id") or "")))
        return izid

    #: Najvec toliko novih virov poskusimo prevzeti ob enem usklajevanju (vsak prevzem je omrezno preverjanje).
    NAJVEC_PREVZEMOV = 6

    @staticmethod
    def _posiljatelj_v_ozjem_krogu(posiljatelj: str) -> bool:
        """Ali je posiljatelj v ozjem krogu TE naprave (core/link_dostop.v_ozjem_krogu: izrecna privolitev uporabnika na
        tem racunalniku). Napaka ali prazen id: ne (pregled 68, Ą3)."""
        if not posiljatelj:
            return False
        try:
            from . import link_dostop
            return bool(link_dostop.v_ozjem_krogu(posiljatelj))
        except Exception:  # noqa: BLE001
            return False

    def _usenet_iz_kroga(self, zapis: object, v_krogu: bool) -> bool:
        l = getattr(self.debrid, "lastni_usenet", None)
        if zapis is None or l is None:
            return False
        try:
            return bool(l.prejmi_iz_kroga(zapis, v_krogu))
        except Exception:  # noqa: BLE001
            return False

    def viri_uskladi(self, kazalo: object, posiljatelj: str = "") -> bool:
        """Moji viri z ene naprave v Linku (kazalo odgovora `lists.get {}`): izbrisi, nato novi viri. Racunalnik
        prevzame samo, kar zna predvajati; zasebnega dodatka nikoli. Klic iz delovne niti (omrezje). Vrne True, ce
        se je tukaj kaj spremenilo."""
        if not isinstance(kazalo, dict):
            return False
        tuji_izbrisi = viri_sink.cisti_izbrisi(kazalo.get("sources_deleted"))
        # Ali nas ima naprava v ozjem krogu (true/false); None: starejsa razlicica (pregled 46, Ö3).
        ozji_odgovor = kazalo.get("ozji") if isinstance(kazalo.get("ozji"), bool) else None
        # Pregled 68, Ą3 (AGENTS.md: nic iz dohodnega sporocila ne sme podeliti dostopa): »ozji« v odgovoru je izjava
        # posiljatelja, da ima NAS v svojem krogu. Dokaz je sele to, da je posiljatelj v ozjem krogu TE naprave (izrecna
        # privolitev tukaj, core/link_dostop); sicer velja kot naprava zunaj kroga: vira z racunom ne prevzamemo.
        if ozji_odgovor is True and not self._posiljatelj_v_ozjem_krogu(posiljatelj):
            ozji_odgovor = False
        surovi = kazalo.get("sources") if isinstance(kazalo.get("sources"), list) else []
        tuji = [c for c in (viri_sink.cist_vir(o) for o in surovi[:viri_sink.NAJVEC_VIROV]) if c]
        # Naloga 114: ponudnik Usenet (brez gesla) samo od naprave v ozjem krogu v obe smeri; lokalnega ne prepise.
        spremenjeno = self._usenet_iz_kroga(kazalo.get(viri_sink.USENET_PONUDNIK), ozji_odgovor is True)
        if not tuji_izbrisi and not tuji:
            return spremenjeno
        # 1) Izbrisi: vir, izbrisan na drugi napravi, izgine tudi tukaj, ce ga tu nismo dodali pozneje.
        za_izbris = []
        with self._lock:
            moji = self._viri_moji(self._load())
            stanje = self._viri_stanje()
            zapisi = False
            for k, cas in tuji_izbrisi.items():
                i = viri_sink.istovetnost_kljuca(k)
                moj = next((m for m in moji if m[0] == i), None)
                if moj is None:
                    if int(stanje["izbrisani"].get(k) or 0) < cas:
                        stanje["izbrisani"][k] = cas
                        zapisi = True
                elif viri_sink.izbris_vira_velja(moj[1], cas):
                    za_izbris.append((moj[2], cas, k))
            if zapisi:
                self._viri_stanje_pisi(stanje)
        for source_id, cas, k in za_izbris:
            if self.remove_source(source_id, cas=cas, kljuc=k):
                spremenjeno = True
        # 2) Novi viri.
        poskusov = 0
        for v in tuji:
            if v["tip"] not in viri_sink.PREVZEMLJIVE or poskusov >= self.NAJVEC_PREVZEMOV:
                continue
            if not viri_sink.prevzem_dovoljen(v["naslov"], ozji_odgovor):
                continue                # vir z racunom samo od naprave, ki nas ima v ozjem krogu (pregled 46, Ö3)
            i = viri_sink.istovetnost(v["tip"], v["naslov"])
            zdaj = self._zdaj_ms()
            with self._lock:
                stanje = self._viri_stanje()
                if any(m[0] == i for m in self._viri_moji(self._load())):
                    continue
                if not viri_sink.vir_prevzamemo(False, viri_sink.cas_izbrisa(stanje["izbrisani"], v["tip"], v["naslov"]), v["cas"]):
                    continue
                zavrnjen = stanje["zavrnjeni"].get(i)
                if zavrnjen and zdaj - zavrnjen[0] < zavrnjen[1]:
                    continue
            poskusov += 1
            # "ozji": odgovor naprave pove, da nas ima v ozjem krogu; cist_vir tega polja nikoli ne postavi, zato ga ne more ponarediti vir.
            ok, velja = self._prevzemi_vir(dict(v, ozji=ozji_odgovor is True))
            if ok:
                spremenjeno = True
            elif velja:
                with self._lock:
                    stanje = self._viri_stanje()
                    stanje["zavrnjeni"][i] = [zdaj, velja]
                    self._viri_stanje_pisi(stanje)
        if spremenjeno:
            self._viri_zapisi_izvoz()
            if self.ob_virih is not None:
                try:
                    self.ob_virih()
                except Exception:  # noqa: BLE001
                    pass
        return spremenjeno

    def _prevzemi_vir(self, v: dict) -> tuple:
        """Doda vir z druge naprave, ce ga ta racunalnik zna predvajati. Vrne (dodan, koliko ms ne poskusamo znova)."""
        try:
            if v["tip"] == viri_sink.STREMIO:
                try:
                    manifest = media_servers.stremio_manifest(v["naslov"])
                except Exception:
                    return False, viri_sink.NEDOSEGLJIV_VELJA_MS
                # Zasebnega dodatka ne prevzamemo - tudi ce ga ponudi naprava s starejso razlicico.
                if media_servers.stremio_je_zaseben(manifest):
                    return False, viri_sink.ZAVRNJEN_VELJA_MS
                self._zasebni_koreni[media_servers._stremio_koren(v["naslov"])] = False
                r = self.add_server("stremio", _text(manifest.get("name"), 80) or v["ime"], v["naslov"], "", "", prevzet=v)
            else:
                r = self.add_source(v["naslov"], v["ime"], prevzet=v, ozji_krog=v.get("ozji") is True)
        except Exception:  # noqa: BLE001 - neveljaven naslov, omrezje ...
            return False, viri_sink.ZAVRNJEN_VELJA_MS
        if isinstance(r, dict) and r.get("ok"):
            print("[SafeerMedia] vir z naprave: %s" % v["tip"], flush=True)
            return True, 0
        return False, viri_sink.ZAVRNJEN_VELJA_MS

    def _download(self, url: str) -> tuple[bytes, str, str]:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, application/rss+xml, application/xml, audio/x-mpegurl, text/html;q=0.9, */*;q=0.5",
            "Accept-Language": "sl,en-US;q=0.9,en;q=0.8",
        })
        with urllib.request.build_opener(PreverjenSkok(), _PripetHttp(), _PripetHttps()).open(request, timeout=15) as response:  # nosec B310
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_DOWNLOAD:
                raise ValueError("Vir je prevelik.")
            payload = response.read(MAX_DOWNLOAD + 1)
            if len(payload) > MAX_DOWNLOAD:
                raise ValueError("Vir je prevelik.")
            final_url = canonical_url(response.geturl())
            return payload, response.headers.get_content_type(), final_url

    def _potrdi_prejeti_vir(self, canonical: str, prevzet: object) -> None:
        """Prejet vir v Linku potrdi samo kot URL in samo za naslov, ki je bil na tej napravi dejansko dodan (pregled
        Grok 98, K4, iz Windows). _vir_potrjen pozabi izbris in zavrnitev - tip in naslov iz dohodnega sporocila bi
        sicer izbrala, katero izbrisano ali zavrnjeno stvar ta naprava pozabi (o vsebinah te naprave odloca samo ta)."""
        self._vir_potrjen(viri_sink.URL, canonical)
        if not isinstance(prevzet, dict):
            return
        naslov = prevzet.get("naslov")
        if not isinstance(naslov, str) or not naslov or naslov == canonical:
            return
        if str(prevzet.get("tip") or viri_sink.URL) != viri_sink.URL:
            return
        try:
            enak = canonical_url(naslov) == canonical
        except Exception:  # noqa: BLE001 - neveljaven naslov ni ta vir
            enak = False
        if enak:
            self._vir_potrjen(viri_sink.URL, naslov)

    @staticmethod
    def _racun_vira(source: dict) -> bool:
        """Ali vir velja za vir z racunom pri ponudniku: premor ob vsakem odgovoru brez seznama, ena zahteva, nikoli
        rezervna pot. Velja za VSAK vir, ki ni pozitivno znan javen (viri_sink.za_ozji_krog), ne glede na obliko naslova
        (pregled 57, Ş2; enako Android, pregled 52, I5). Pregled 51, Ê1 je odlocal zaznan_racun in zastavico iptv v vnosih:
        kratka povezava ali zeton v poti sta pred prvim uspesnim branjem veljala za »ni racun« in 404, 5xx ali prazen 200
        sta pomenila dve zahtevi z geslom brez premora. Izjema so znane platforme, ki jih beremo samo prek uradnih vdelav
        in nimajo racuna pri ponudniku IPTV (_platforma_brez_racuna)."""
        url = source.get("url")
        return viri_sink.za_ozji_krog(url, source.get("javni") is True) and not _platforma_brez_racuna(url)

    @staticmethod
    def _vdelava_strani(source: dict, content_type: str, payload: bytes, final_url: str) -> bool:
        """Stran HTML brez predvajljive vsebine dobi vnos »Vdelana vsebina« (lastnik: uporabnik lahko vdela katero koli
        stran; pregled 57, Ş2), ce je uporabnik vir SAM dodal na tej napravi (ni prejet z druge: brez link_naslov in
        link_tip) in naslov (tudi po preusmeritvi) NIMA znakov poverilnice (user:pass@, username=, password=, token=,
        /live/<u>/<g>/, get.php ...: viri_sink.verjetno_racun_seznama). Prazno telo ali drugo vrsto vsebine to ni.
        Klice jo samo prvo dodajanje (add_source), nikoli osvezitev (pregled 63, Ŷ1: odgovor HTML poteklega racuna bi
        sicer pobrisal premor in zamenjal ze prebrane kanale IPTV). Oznake »javni« ne upoštevamo: poverilnica v naslovu
        izklopi vdelavo tudi za oznacen vir."""
        if source.get("link_naslov") or source.get("link_tip"):
            return False
        if str(content_type or "").split(";")[0].strip().casefold() != "text/html" or not (payload or b"").strip():
            return False
        return not (viri_sink.verjetno_racun_seznama(source.get("url")) or viri_sink.verjetno_racun_seznama(final_url))

    def refresh_source(self, source_id: str, dovoli_vdelavo: bool = False) -> dict:
        """Osvezi vir. Najvec ena osvezitev istega vira naenkrat (pregled 68, Ą5): sociasen »Osvezi« in prva uporaba ali
        osvezitev v ozadju bi sicer poslala ponudniku dve prijavi z geslom - drugi klic vrne {"ze_tece": True} brez zahteve."""
        if source_id.startswith("streznik-"):
            return self._refresh_source_ena(source_id, dovoli_vdelavo)
        with self._lock:
            tece = self.__dict__.setdefault("_osvezuje_vire", set())
            source = next((s for s in self._load().get("viri", []) if isinstance(s, dict) and s.get("id") == source_id),
                          None)
            # Pregled Grok 98, K2 (iz Windows): zaklep tudi po RACUNU, ne le po id vira - isti racun je lahko v vec virih
            # (type=m3u in m3u_plus, player_api.php, druga vrata); nikoli dve hkratni prijavi istega racuna.
            racun = _kljuc_racuna(source.get("url")) if source is not None and self._racun_vira(source) else None
            racuni = self.__dict__.setdefault("_osvezuje_racune", [])
            if source_id in tece or (racun is not None and any(
                    g == racun[0] and (u is None or racun[1] is None or u == racun[1]) for g, u in racuni)):
                return {"ok": False, "napaka": "", "ze_tece": True}
            tece.add(source_id)
            if racun is not None:
                racuni.append(racun)
        try:
            return self._refresh_source_ena(source_id, dovoli_vdelavo)
        finally:
            with self._lock:
                tece.discard(source_id)
                if racun is not None:
                    racuni.remove(racun)

    def _refresh_source_ena(self, source_id: str, dovoli_vdelavo: bool = False) -> dict:
        if source_id.startswith("streznik-"):
            with self._lock:
                self._server_cache = {key: value for key, value in self._server_cache.items()
                                      if not key.startswith(source_id + ":")}
            return {"ok": any(item.get("id") == source_id for item in self.sources())}
        with self._lock:
            source = next((item.copy() for item in self._load().get("viri", [])
                           if item.get("id") == source_id), None)
        if source is None:
            return {"ok": False, "napaka": "ni_vira"}
        if self._racun_vira(source):
            # Pregled 68, Ą5 (lastnikova prednost: nikoli zaklep racuna): premor po zavrnitvi velja tudi za uporabnikov
            # »Osvezi«. Prej je rocna osvezitev premor obsla (10 klikov = 10 prijav na racun, ki ga je ponudnik ze zavrnil).
            ostane = self._zavrnjen_do(source) - time.time()
            if ostane > 0:
                return {"ok": False, "napaka": "premor", "premor_s": int(ostane) + 1,
                        "vir": {k: v for k, v in source.items() if k != "vnosi"}}
        if source.get("ozji_krog"):
            # Vir iz ozjega kroga: najvec ena zahteva na minuto, ne glede na to, kdo jo sprozi (uporabnik, katalog, ozadje).
            try:
                zadnja = float(source.get("zadnja_zahteva") or 0)
            except (TypeError, ValueError):
                zadnja = 0.0
            if 0 <= time.time() - zadnja < self.OZJI_KROG_OSVEZITEV_S:
                napaka = str(source.get("napaka") or "")
                return {"ok": not napaka and not source.get("prvo_uporaba"), "napaka": napaka, "predpomnjeno": True,
                        "vir": {k: v for k, v in source.items() if k != "vnosi"}}
            source["zadnja_zahteva"] = int(time.time())
        try:
            music_embed, embed_error = _official_music_embed(source["url"], source["id"], source["ime"])
            if embed_error:
                raise ValueError(embed_error)
            if music_embed is not None:
                items = music_embed
                source["tip"] = "uradni_vdelani_predvajalnik"
            elif source.get("tip") == "predvajalni_vir" or _je_predvajalni_vir(source["url"]):
                source["tip"] = "predvajalni_vir"
                if _je_predloga_predvajalnika(source["url"]):
                    items = _katalog_iz_predloge(source["url"], source["id"], source["ime"])
                else:
                    items = _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
                if not items:
                    raise ValueError("Predloga potrebuje {tmdbId} ali {imdbId} in pot /movie/ ali /tv/.")
            elif _je_neposredni_medijski_tok(source["url"]):
                # Neposrednega MP3/MP4/HLS toka ne prenašaj v pomnilnik kot
                # spletni katalog; shrani ga kot en predvajalni vnos.
                items = _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
                if not items:
                    raise ValueError("Neposrednega medijskega toka ni mogoče dodati.")
                source["tip"] = "neposredni_medijski_tok"
            elif source.get("tip") == "vdelana_stran":
                # Stran, vdelana ob dodajanju: ne spreminja se, ponovni prenos ni potreben (brez zahteve na naslov).
                items = _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
                if not items:
                    raise ValueError("Strani ni mogoče vdelati.")
            else:
                payload, content_type, final_url = self._download(source["url"])
                stevci: dict = {}
                items = parse_payload(payload, content_type, final_url, source["id"], source["ime"], stevci=stevci)
                source["ne_24_7"] = int(stevci.get("ne_24_7") or 0)
                if not items:
                    vdelava = (dovoli_vdelavo and self._racun_vira(source)
                               and self._vdelava_strani(source, content_type, payload, final_url))
                    if self._racun_vira(source) and not vdelava:
                        # Odgovor brez seznama na naslov z geslom: brez se ene zahteve z geslom (vdelani predvajalnik)
                        # in samodejno vse redkeje (pregled 46, Ö5). Osvezitev nikoli ne vdela strani (pregled 63, Ŷ1).
                        raise _PrazenOdgovor("Ponudnik ni vrnil seznama.")
                    if vdelava:
                        source["tip"] = "vdelana_stran"
                    items = _resolve_embed_or_direct_source(final_url, source["id"], source["ime"])
            source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": "",
                           "razclenitev": kanali_iptv.RAZCLENITEV})
            ok, error = True, ""
        except Exception as exc:
            host = (urllib.parse.urlsplit(source["url"]).hostname or "").casefold()
            restricted = host == "bandcamp.com" or host.endswith(".bandcamp.com")
            koda = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
            # Vir z racunom (pregled 46, Ö5): vsak odgovor ponudnika brez seznama (404, 5xx, lastne kode, prazen 200) je
            # zavrnitev z vse daljsim premorom; brez povezave (koda 0) ostane ponovitev po 10 min. Nikoli druge zahteve
            # na naslov z geslom.
            racun = self._racun_vira(source)
            ni_povezave = 0
            if racun and koda == 0 and not isinstance(exc, _PrazenOdgovor):
                # Prekinjena povezava, TLS, rok: nekateri paneli zaklenjen racun ali IP odrezejo ze na ravni povezave,
                # zato tretjic zapored tudi to vse redkeje (pregled 51, Ê1); rocna osvezitev velja takoj.
                try:
                    ni_povezave = int(source.get("ni_povezave") or 0) + 1
                except (TypeError, ValueError):
                    ni_povezave = 1
                source["ni_povezave"] = ni_povezave
            if (koda in self.ZAVRNJENE_KODE or (racun and (koda > 0 or isinstance(exc, _PrazenOdgovor)))
                    or ni_povezave >= self.NI_POVEZAVE_ZAPORED):
                # Ponudnik je seznam zavrnil: brez se ene zahteve na isti naslov (vdelani predvajalnik) in samodejno
                # znova sele po vse daljsem premoru (ZAVRNJEN_PREMORI_S; pregled 39, I5).
                prej = source.get("zavrnjen") if isinstance(source.get("zavrnjen"), dict) else {}
                try:
                    n = int(prej.get("n") or 0)
                except (TypeError, ValueError):
                    n = 0
                source["zavrnjen"] = {"koda": koda, "ob": int(time.time()), "n": min(n + 1, len(self.ZAVRNJEN_PREMORI_S))}
            items = [] if restricted or racun or koda in self.ZAVRNJENE_KODE else \
                _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
            if items:
                source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": "",
                               "razclenitev": kanali_iptv.RAZCLENITEV})
                ok, error = True, ""
            else:
                # Pregled 57, Ş5: najprej zakrij, sele nato skrajsaj (rez pred zakrivanjem je odrezal zakljucno navednico).
                error = (viri_sink.sporocilo_napake(exc, source.get("url"), source.get("javni") is True)
                         or "Vira ni bilo mogoče prebrati.")
                source["napaka"] = error
                ok = False
        with self._lock:
            data = self._load()
            saved = next((item for item in data.get("viri", []) if item.get("id") == source_id), None)
            if saved is None:
                return {"ok": False, "napaka": "ni_vira"}
            if ok:
                # Ponudnik seznam spet da; uporabnik je vir osvezil: ne caka vec (Ñ2). Samo ob uspehu (pregled 57, Ş6):
                # po neuspeli osvezitvi (racun zaklenjen, brez povezave) bi sicer refresh_stale vir sam ponavljal in
                # naprava, ki racuna se nikoli ni prebrala, bi postala samodejni odjemalec racuna v tezavah.
                for oznaka in ("zavrnjen", "ni_povezave", "caka_uporabnika", "prvo_uporaba"):
                    source.pop(oznaka, None)
                    saved.pop(oznaka, None)
            saved.update(source)
            self._save(data)
        if ok and any(isinstance(x, dict) and x.get("iptv") for x in items):
            # Zaklenjene kanale vira preverimo znova (morda je uporabnik pravkar placal naroznino), vse neznane takoj,
            # da TV v zivo ob prvem ogledu ne caka (samo izbrane drzave in jeziki javnih seznamov).
            self.kanali.pozabi(str(x.get("url") or "") for x in items if isinstance(x, dict) and x.get("iptv"))
            self._vnosi_virov({"viri": [source]}, "tv-v-zivo")
        public = {k: value for k, value in source.items() if k != "vnosi"}
        return {"ok": ok, "napaka": error, "vir": public}

    def refresh_all(self) -> dict:
        # Cakajoci vir (Ñ2, Ş1) osvezi samo uporabnikov pritisk na NJEGOVO vrstico: skupna osvezitev bi na enkrat
        # poslala zahteve z gesli vsem virom, ki jih uporabnik se ni potrdil.
        ids = [source.get("id", "") for source in self.sources()
               if not source.get("caka_uporabnika") and not source.get("prvo_uporaba")]    # prvo_uporaba: ob odprtju seznama
        results = [self.refresh_source(source_id) for source_id in ids]
        return {"ok": all(item.get("ok") for item in results), "rezultati": results}

    def refresh_stale(self, max_age: int = 6 * 60 * 60) -> dict:
        """V ozadju osveži le vire, katerih uspešni podatki so že zastareli."""
        zdaj = int(time.time())
        cutoff = zdaj - max(60, int(max_age))
        ids = [source.get("id", "") for source in self.sources()
               if not source.get("caka_uporabnika")             # prejet vir z racunom: sele ob uporabnikovi osvezitvi (Ñ2)
               and not source.get("ozji_krog")                  # vir iz ozjega kroga: nikoli v ozadju (pregled 68, Ą1)
               # Pregled Grok 98, K1 (iz Windows; lastnik: nevarnost zaklepa racuna je prioriteta): vira z racunom (IPTV)
               # samodejna pot nikoli ne odpre - prijava z geslom med predvajanjem bi bila druga hkratna povezava.
               and not self._racun_vira(source)
               and zdaj >= self._zavrnjen_do(source)            # premor po napaki velja tudi za samodejno pot
               and (int(source.get("posodobljeno") or 0) < cutoff
                    or (_je_predvajalni_vir(str(source.get("url") or ""))
                        and source.get("tip") != "predvajalni_vir"))]
        results = [self.refresh_source(source_id) for source_id in ids]
        return {"ok": all(item.get("ok") for item in results), "osvezenih": len(results),
                "rezultati": results}

    def _local_items(self) -> list[dict]:
        items = []
        def tag_value(tags, *keys):
            for key in keys:
                value = tags.get(key) if tags else None
                if value is None:
                    continue
                value = getattr(value, "text", value)
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else ""
                if value:
                    return str(value)
            return ""
        custom = [Path(value) for value in self._load().get("lokalne_mape", []) if isinstance(value, str)]
        for root in dict.fromkeys(self.roots + custom):
            if not root.is_dir():
                continue
            for base, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if not name.startswith(".")][:80]
                for filename in files:
                    path = Path(base) / filename
                    if path.suffix.lower() == ".iso" or filename.upper() == "VIDEO_TS.IFO":
                        # DVD brez zaščite (slika ISO z VIDEO_TS ali mapa diska) je film; predvaja LibVLC.
                        dvd = _dvd_item(path)
                        if dvd:
                            items.append(dvd)
                        if len(items) >= MAX_FILES:
                            return items
                        continue
                    if path.suffix.lower() not in MEDIA_EXT:
                        continue
                    try:
                        modified = int(path.stat().st_mtime)
                    except OSError:
                        continue
                    ext = path.suffix.lower()
                    kind = "glasba" if ext in AUDIO else "slika" if ext in IMAGES else "film"
                    title, artist, album, year, image = path.stem, "", "", 0, ""
                    if ext in AUDIO:
                        try:
                            import base64
                            from mutagen import File as MutagenFile
                            audio = MutagenFile(str(path), easy=True) or {}
                            artist = tag_value(audio, "artist", "albumartist", "TPE1", "TPE2", "ARTIST")
                            album = tag_value(audio, "album", "TALB", "ALBUM")
                            title = tag_value(audio, "title", "TIT2", "TITLE") or path.stem
                            date_tag = tag_value(audio, "date", "year", "TDRC", "TYER", "DATE")
                            match = re.match(r"\d{4}", date_tag)
                            year = int(match.group()) if match else 0
                            raw = MutagenFile(str(path))
                            pictures = getattr(raw, "pictures", None)
                            cover = pictures[0].data if pictures else None
                            cover_type = pictures[0].mime if pictures else "image/jpeg"
                            if not cover and getattr(raw, "tags", None):
                                apic = next((value for value in raw.tags.values()
                                             if value.__class__.__name__ == "APIC"), None)
                                if apic:
                                    cover, cover_type = apic.data, apic.mime
                                if not cover:
                                    picture_data = raw.tags.get("metadata_block_picture")
                                    if picture_data:
                                        from mutagen.flac import Picture
                                        picture = Picture(base64.b64decode(picture_data[0]))
                                        cover, cover_type = picture.data, picture.mime
                            if cover:
                                if len(cover) <= 1500 * 1024:
                                    image = "data:%s;base64,%s" % (cover_type or "image/jpeg", base64.b64encode(cover).decode("ascii"))
                        except Exception:
                            pass
                    found = _item(title, path.as_uri(), base=path.as_uri(), source_id="lokalno",
                                  source_name="Ta računalnik", kind=kind, artist=artist,
                                  image=image, year=year, description=str(path))
                    if found:
                        found.update({"pot": str(path), "cas": modified, "mime": mimetypes.guess_type(str(path))[0] or "",
                                      "album": album, "skupina": album or artist})
                        items.append(found)
                    if len(items) >= MAX_FILES:
                        return items
        return items

    def add_local_root(self, value: str) -> dict:
        raw = _text(value, 1024)
        if raw.lower().startswith(("nfs://", "nfs:")):
            nfs_client = False
            if os.name == "nt":
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        r"SYSTEM\CurrentControlSet\Services\NfsClnt"):
                        nfs_client = True
                except OSError:
                    pass
            note = ("NFS odjemalec je nameščen; najprej priklopite izvoz s sistemskim mount ukazom, nato dodajte črko pogona."
                    if nfs_client else "Windows NFS odjemalec ni zaznan; priklop NFS ni na voljo. Uporabite UNC pot ali namestite NFS odjemalec.")
            return {"ok": False, "napaka": note}
        path = Path(raw).expanduser()
        is_unc = raw.startswith("\\\\")
        if not raw or not (path.is_dir() or (is_unc and os.name == "nt")):
            return {"ok": False, "napaka": "Mapa ne obstaja ali ni dosegljiva."}
        with self._lock:
            data = self._load()
            roots = data.setdefault("lokalne_mape", [])
            normalized = str(path)
            if normalized in roots:
                return {"ok": False, "napaka": "Mapa je že dodana."}
            roots.append(normalized)
            self._save(data)
        return {"ok": True, "pot": normalized}

    def zvrsti_filtrirajo(self, kind: str, izklopljeni: Iterable[str] = ()) -> bool:
        """Ali izbira zvrsti pri tej vrsti res spremeni katalog (lastnik, 14. 10. 2026: gumb zvrsti, ki nicesar ne
        filtrira, zmede). Glasba in radio imata svoje zvrsti, TV v zivo drzave; filmi in serije samo prek TMDB, torej
        ce je dodan vsaj en ponudnik za vgradno predvajanje in ga uporabnik ni zacasno izklopil (enako kot catalog)."""
        if kind in ("glasba", "radio", "tv-v-zivo"):
            return True
        if kind not in ("film", "serija"):
            return False
        with self._lock:
            data = self._load()
        embed_ids = {str(provider.get("id") or host) for provider, _parsed, host in self._embed_viri(data)}
        izklopljeni = {str(x) for x in (izklopljeni or []) if x}
        return bool(embed_ids) and not embed_ids <= izklopljeni

    def _ima_embed_vir(self, data: Optional[dict] = None) -> bool:
        configured = data if isinstance(data, dict) else self._load()
        return bool(self._embed_viri(configured))

    @staticmethod
    def _embed_viri(data: dict) -> list[tuple[dict, urllib.parse.SplitResult, str]]:
        """Vrne samo varne HTTPS ponudnike, ki jih je uporabnik sam dodal."""
        result = []
        for source in data.get("viri", []):
            if not isinstance(source, dict):
                continue
            parsed = urllib.parse.urlsplit(str(source.get("url") or ""))
            host = (parsed.hostname or "").casefold()
            if parsed.scheme == "https" and any(host == domain or host.endswith("." + domain)
                                                 for domain in _EMBED_DOMAINS):
                result.append((source, parsed, host))
        return result

    def _tmdb(self, endpoint: str, params: Optional[dict] = None) -> dict:
        query = dict(params or {})
        query.update({"api_key": TMDB_API_KEY, "language": "sl-SI", "include_adult": "false"})
        url = TMDB_API + endpoint + "?" + urllib.parse.urlencode(query)
        cached = self._tmdb_cache.get(url)
        if cached and time.time() - cached[0] < 2 * 60 * 60:
            return cached[1]
        # Kljuc na disku je odtis naslova (brez API kljuca v datoteki).
        disk_kljuc = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()
        with self._predpomnilnik_lock:
            na_disku = self._nalozi_predpomnilnik()["tmdb"].get(disk_kljuc)
        if (not cached and isinstance(na_disku, dict) and isinstance(na_disku.get("podatki"), dict)
                and time.time() - float(na_disku.get("cas") or 0) < 24 * 60 * 60):
            self._tmdb_cache[url] = (float(na_disku["cas"]), na_disku["podatki"])
            if time.time() - float(na_disku["cas"]) < 2 * 60 * 60:
                return na_disku["podatki"]
        request = urllib.request.Request(url, headers={"User-Agent": "SafeerOS/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read(MAX_DOWNLOAD)
            data = json.loads(payload.decode("utf-8"))
        except (OSError, ValueError):
            # Brez omrezja: raje starejsi podatki kot prazen zaslon.
            if isinstance(na_disku, dict) and isinstance(na_disku.get("podatki"), dict):
                return na_disku["podatki"]
            if cached:
                return cached[1]
            raise
        if not isinstance(data, dict):
            return {}
        zdaj = time.time()
        self._tmdb_cache[url] = (zdaj, data)
        self._pocisti_predpomnilnika()
        with self._predpomnilnik_lock:
            self._nalozi_predpomnilnik()["tmdb"][disk_kljuc] = {"cas": zdaj, "uporabljeno": zdaj, "podatki": data}
        self._shrani_predpomnilnik()
        return data

    def watch_regions(self, language: str = "sl") -> dict:
        """List TMDB regions, cached for seven days; soft-fail on network errors."""
        locale = {"sl": "sl-SI", "en": "en-GB", "de": "de-DE", "es": "es-ES",
                  "fr": "fr-FR", "it": "it-IT"}.get(str(language).split("-")[0], "en-GB")
        key = "watch-regions:" + locale
        cached = self._tmdb_cache.get(key)
        if cached and time.time() - cached[0] < 7 * 24 * 60 * 60:
            return cached[1]
        query = urllib.parse.urlencode({"api_key": TMDB_API_KEY, "language": locale})
        request = urllib.request.Request(TMDB_API + "/watch/providers/regions?" + query,
                                         headers={"User-Agent": "SafeerOS/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read(MAX_DOWNLOAD).decode("utf-8"))
            rows = data.get("results", []) if isinstance(data, dict) else []
            regions = [{"code": str(row.get("iso_3166_1") or "").upper(),
                        "native_name": str(row.get("native_name") or ""),
                        "english_name": str(row.get("english_name") or "")}
                       for row in rows if isinstance(row, dict) and re.fullmatch(
                           r"[A-Z]{2}", str(row.get("iso_3166_1") or "").upper())]
            result = {"regions": regions}
            self._tmdb_cache[key] = (time.time(), result)
            return result
        except Exception:
            return cached[1] if cached else {"regions": []}

    def _watch_providers(self, media_type: str, tmdb_id: int, country: str, title: str = "") -> dict:
        key = f"watch-providers:{media_type}:{int(tmdb_id)}:{country}"
        cached = self._tmdb_cache.get(key)
        if cached and time.time() - cached[0] < 12 * 60 * 60:
            return cached[1]
        try:
            raw = self._tmdb(f"/{media_type}/{int(tmdb_id)}/watch/providers")
            region = raw.get("results", {}).get(country, {}) if isinstance(raw, dict) else {}
            groups = []
            for group_id, keys, group_title in (
                ("naročnina", ("flatrate",), "Naročnina"),
                ("brezplačno", ("free", "ads"), "Brezplačno"),
                ("izposoja", ("rent",), "Izposoja"),
                ("nakup", ("buy",), "Nakup"),
            ):
                entries = []
                seen = set()
                for key_name in keys:
                    for provider in region.get(key_name, []) if isinstance(region, dict) else []:
                        if not isinstance(provider, dict):
                            continue
                        name = str(provider.get("provider_name") or "").strip()
                        if not name or name.casefold() in seen:
                            continue
                        seen.add(name.casefold())
                        base = WATCH_PROVIDER_SEARCH.get(name.casefold())
                        encoded_title = urllib.parse.quote(title) if base else ""
                        url = base + encoded_title if base else str(region.get("link") or "")
                        logo_path = str(provider.get("logo_path") or "")
                        entries.append({"ime": name,
                                        "logo": TMDB_IMAGE + "/w92" + logo_path if logo_path.startswith("/") else "",
                                        "povezava": url})
                if entries:
                    groups.append({"id": group_id, "naziv": group_title, "ponudniki": entries})
            result = {"drzava": country, "skupine": groups, "link": str(region.get("link") or "")}
            self._tmdb_cache[key] = (time.time(), result)
            return result
        except Exception:
            return cached[1] if cached else {"drzava": country, "skupine": [], "link": ""}

    def watch_country_settings(self, selected: str = "auto", language: str = "sl") -> dict:
        detected = watch_providers.detect_country(language)
        regions = self.watch_regions(language).get("regions", [])
        names = {row["code"]: row.get("native_name") or row.get("english_name") or row["code"]
                 for row in regions}
        selected = str(selected or "auto").upper()
        country = detected if selected == "AUTO" else selected
        if not re.fullmatch(r"[A-Z]{2}", country):
            country, selected = detected, "AUTO"
        return {"izbrana": "auto" if selected == "AUTO" else country, "drzava": country,
                "ime_drzave": names.get(country, country), "zaznana": detected,
                "ime_zaznane": names.get(detected, detected), "regions": regions}

    @staticmethod
    def _tmdb_tip(value: str) -> str:
        return "serija" if value == "tv" else "film"

    def _tmdb_vnos(self, raw: dict, source: dict) -> Optional[dict]:
        tmdb_id = _tmdb_id(raw.get("id"))
        media_type = str(raw.get("media_type") or source.get("media_type") or ("tv" if raw.get("first_air_date") else "movie"))
        if not tmdb_id or media_type not in ("movie", "tv"):
            return None
        kind = self._tmdb_tip(media_type)
        title = _text(raw.get("title") or raw.get("name"), 200)
        if not title:
            return None
        # Prikazujemo samo resnično izdane vsebine s plakatom.
        if not raw.get("poster_path"):
            return None
        date = str(raw.get("release_date") or raw.get("first_air_date") or "")
        if not date:
            return None
        try:
            if _date.fromisoformat(date) > _date.today():
                return None
        except ValueError:
            return None
        year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else 0
        if year < 1920:
            return None
        rating = round(float(raw.get("vote_average") or 0), 1)
        vote_count = int(raw.get("vote_count") or 0)
        if rating <= 0 or vote_count < 10:
            return None
        imdb_id = TMDB_TO_IMDB.get(str(tmdb_id), "")
        poster = f"{TMDB_IMAGE}/w500{raw['poster_path']}"
        overview = raw.get("overview") or ""
        backdrop = f"{TMDB_IMAGE}/original{raw['backdrop_path']}" if raw.get("backdrop_path") else ""
        genres = raw.get("genre_ids") or []

        providers = self._embed_viri(self._load())
        items = []
        for provider, parsed, host in providers:
            url = _embed_url_for_provider(
                host, parsed.scheme, imdb_id, str(tmdb_id), kind,
                1 if kind == "serija" else 0,
                1 if kind == "serija" else 0,
            )
            item = _item(title, url, base=url,
                         source_id=str(provider.get("id") or host),
                         source_name=str(provider.get("ime") or host), kind=kind, year=year,
                         image=poster, description=overview, tmdb_id=tmdb_id, imdb_id=imdb_id,
                         season=0, episode=0, quality="Samodejno")
            if item:
                items.append(item)
        if not items:
            return None
        prepared = merge_duplicates(items)[0]

        prepared.update({
            "datum": date,
            "ocena": rating,
            "zanri": genres,
            "ozadje": backdrop,
            "jezik": zakoniti_viri.jezik_koda(raw.get("original_language")),
            "media_type": media_type,
        })
        self._dynamic_items[prepared["id"]] = prepared
        return prepared

    # Razvrscanje po letu izida ali abecedi; TMDB zna razvrstiti celoten katalog (ne samo stran).
    RAZVRSTITVE = ("", "novo", "staro", "az", "za")

    @staticmethod
    def _tmdb_razvrstitev(razvrsti: str, media_type: str, jezik: str = "") -> dict:
        datum = "first_air_date" if media_type == "tv" else "primary_release_date"
        ime = "name" if media_type == "tv" else "title"
        # Prag glasov: brez njega bi na vrhu stali neznani ali se neizdani naslovi. Pri izbranem jeziku (razen
        # anglescine) je naslovov malo: z visokim pragom bi npr. slovenski filmi izpadli skoraj vsi.
        def prag(n: int) -> int:
            return 10 if jezik and jezik != "en" else n
        return {
            "novo": {"sort_by": datum + ".desc", datum + ".lte": _date.today().isoformat(), "vote_count.gte": prag(50)},
            "staro": {"sort_by": datum + ".asc", "vote_count.gte": prag(200)},
            "az": {"sort_by": ime + ".asc", "vote_count.gte": prag(300)},
            "za": {"sort_by": ime + ".desc", "vote_count.gte": prag(300)},
        }.get(razvrsti, {})

    def _tmdb_po_jeziku(self, kind: str, genre: str, page: int, razvrsti: str, jezik: str) -> tuple[list[dict], int]:
        """Katalog TMDB v izbranem izvirnem jeziku. TMDB po jeziku izbira samo v /discover (film ali serija posebej);
        pri »vse« vprasamo oboje in kartice izmenjujemo. Kode, pod katerimi TMDB vodi isti jezik (srbohrvascina,
        kantonscina, bokmal), gredo zraven."""
        media_type = "tv" if kind == "serija" else "movie" if kind == "film" else "all"
        vrste = ["movie", "tv"] if media_type == "all" and not genre else ["tv" if media_type == "tv" else "movie"]
        osnova: dict[str, Any] = {"page": max(1, min(int(page or 1), 500)),
                                  "with_original_language": "|".join(izvirni_jezik.kode_vira(jezik))}
        if genre:
            osnova["with_genres"] = genre
        skupine, strani = [], 1
        for vrsta in vrste:
            params = dict(osnova)
            # Brez izbrane razvrstitve po priljubljenosti; prag glasov je isti, kot ga zahteva kartica (_tmdb_vnos).
            params.update(self._tmdb_razvrstitev(razvrsti, vrsta, jezik) or {"sort_by": "popularity.desc", "vote_count.gte": 10})
            try:
                resp = self._tmdb(f"/discover/{vrsta}", params)
            except Exception:
                continue
            strani = max(strani, min(int(resp.get("total_pages") or 1), 500))
            skupina = []
            for row in resp.get("results", []):
                if not isinstance(row, dict):
                    continue
                item = self._tmdb_vnos(dict(row, media_type=vrsta), {})
                if item and (kind in ("", "vse") or item["vrsta"] == kind):
                    skupina.append(item)
            skupine.append(skupina)
        najdeno: list[dict] = []
        for i in range(max((len(s) for s in skupine), default=0)):
            najdeno.extend(s[i] for s in skupine if i < len(s))
        return najdeno, strani

    def _tmdb_catalog(self, data: dict, query: str, kind: str, genre: str, page: int,
                      razvrsti: str = "", jezik: str = "") -> tuple[list[dict], int]:
        if jezik and not query:
            return self._tmdb_po_jeziku(kind, genre, page, razvrsti, jezik)
        source = {}
        media_type = "tv" if kind == "serija" else "movie" if kind == "film" else "all"
        current_page = max(1, min(int(page or 1), 500))
        params: dict[str, Any] = {"page": current_page}
        if query:
            endpoint = "/search/multi"
            params["query"] = query
        elif razvrsti and media_type != "all":
            endpoint = f"/discover/{media_type}"
            params.update(self._tmdb_razvrstitev(razvrsti, media_type))
            if genre:
                params["with_genres"] = genre
        elif genre:
            endpoint = f"/discover/{'tv' if media_type == 'tv' else 'movie'}"
            params.update({"with_genres": genre, "sort_by": "popularity.desc"})
        elif media_type == "all":
            endpoint = "/trending/all/week"
        else:
            endpoint = f"/{media_type}/popular"
        tmdb_total_pages = 500
        try:
            resp = self._tmdb(endpoint, params)
            raw = resp.get("results", [])
            tmdb_total_pages = min(int(resp.get("total_pages") or 500), 500)
        except Exception:
            return [], 1
        found = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            if media_type != "all" and str(row.get("media_type") or media_type) != media_type:
                row = dict(row, media_type=media_type)
            item = self._tmdb_vnos(row, source)
            if item and (kind in ("", "vse") or item["vrsta"] == kind):
                found.append(item)
        return found, tmdb_total_pages

    @staticmethod
    def _razvrsti_vnose(items: list[dict], razvrsti: str) -> list[dict]:
        if razvrsti in ("az", "za"):
            return sorted(items, key=lambda x: unicodedata.normalize("NFKD", str(x.get("naslov") or "")).casefold(),
                          reverse=razvrsti == "za")
        if razvrsti in ("novo", "staro"):
            def leto(x: dict) -> int:
                try:
                    vrednost = int(x.get("leto") or 0)
                except (TypeError, ValueError):
                    vrednost = 0
                if vrednost:
                    return vrednost
                datum = str(x.get("datum") or "")[:4]
                return int(datum) if datum.isdigit() else 0
            z_letom = [x for x in items if leto(x)]
            brez = [x for x in items if not leto(x)]  # brez letnice vedno na konec
            return sorted(z_letom, key=leto, reverse=razvrsti == "novo") + brez
        return items

    @staticmethod
    def _filtriraj_vire(items: list[dict], izklopljeni: set[str]) -> list[dict]:
        """Zacasno izklopljeni viri: iz kartice odstranimo njihove razlicice, prazne kartice skrijemo."""
        if not izklopljeni:
            return items
        out = []
        for item in items:
            razlicice = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)]
            if not razlicice:
                if str(item.get("vir_id") or "") not in izklopljeni:
                    out.append(item)
                continue
            ostale = [r for r in razlicice if str(r.get("vir_id") or "") not in izklopljeni]
            if not ostale:
                continue
            if len(ostale) == len(razlicice):
                out.append(item)
                continue
            glavna = ostale[0]
            out.append(dict(item, razlicice=ostale, stevilo_razlicic=len(ostale),
                            url=glavna.get("url") or item.get("url"), vir=glavna.get("vir") or item.get("vir"),
                            vir_id=glavna.get("vir_id") or item.get("vir_id"),
                            viri=list(dict.fromkeys(r.get("vir", "") for r in ostale if r.get("vir")))))
        return out

    @staticmethod
    def _filtriraj_jezike(items: list[dict], izklopljeni_jeziki: set[str]) -> list[dict]:
        """Zacasno izklopljeni jeziki; vnosi brez znanega jezika ostanejo (jih ne skrivamo po nakljucju)."""
        if not izklopljeni_jeziki:
            return items
        return [x for x in items if str(x.get("jezik") or "") not in izklopljeni_jeziki]

    def _samo_jezik(self, items: list[dict], jezik: str) -> list[dict]:
        return self._po_jeziku(items, jezik)[0]

    def _po_jeziku(self, items: list[dict], jezik: str) -> tuple:
        """Izbran jezik vsebine (poleg zvrsti): ostane, kar je v tem jeziku. Jezik pove vir (TMDB, PeerTube, Jamendo,
        javna last, radio); za naslove z id-jem IMDb brez jezika vprasamo Wikidato (core/izvirni_jezik.py). Vnos,
        katerega jezika ne poznamo, se med izbiro ne kaze - izbira »slovenscina« ne sme kazati filmov, za katere ne
        vemo, v katerem jeziku so. Naslovov iz zasebnih dodatkov ne sprasujemo: kar pride iz njih, ostane tu.
        Klic iz delovne niti (omrezje)."""
        vprasaj: list[str] = []
        for x in items:
            if x.get("jezik") or not izvirni_jezik.veljaven_imdb(x.get("imdb_id")):
                continue
            dodatek = x.get("stremio") if isinstance(x.get("stremio"), dict) else None
            if dodatek and self._koren_zaseben(str(dodatek.get("koren") or "")) is not False:
                continue
            vprasaj.append(x["imdb_id"])
        try:
            znani = self._izvirni_jeziki.jeziki(vprasaj) if vprasaj else {}
        except Exception:
            znani = {}
        vprasani = set(vprasaj)
        izid, neznani = [], []
        for x in items:
            lastni = str(x.get("jezik") or "")
            if lastni:
                if izvirni_jezik.ustreza(lastni, jezik):
                    izid.append(x)
            elif x.get("imdb_id") in vprasani and jezik in znani.get(x["imdb_id"], ()):
                izid.append(dict(x, jezik=jezik))
            elif not (x.get("imdb_id") in vprasani and znani.get(x["imdb_id"])):
                # Jezika ne pove ne vir ne Wikidata (npr. dodatek brez id-jev IMDb): ne trdimo, da je v izbranem
                # jeziku, a ga tudi ne skrijemo - pride za vsebino v izbranem jeziku, pod »Jezik ni znan«.
                neznani.append(dict(x, jezik_neznan=True))
        return izid, neznani

    def catalog(self, query: str = "", kind: str = "vse", genre: str = "", page: int = 1,
                razvrsti: str = "", izklopljeni: Iterable[str] = (), samo_lokalno: bool = False,
                izklopljeni_jeziki: Iterable[str] = (), jezik: str = "", drzava_radia: str = "") -> dict:
        """`jezik` (koda iz izvirni_jezik.KODE): izbran jezik vsebine - katalog pokaze samo vsebino v njem.
        `drzava_radia` (npr. "SI"): radijske postaje samo iz te drzave."""
        jezik = jezik if jezik in izvirni_jezik.KODE else ""
        drzava_radia = _drzava_radia(drzava_radia)
        izklopljeni_jeziki = {str(x) for x in (izklopljeni_jeziki or []) if x}
        razvrsti = razvrsti if razvrsti in self.RAZVRSTITVE else ""
        izklopljeni = {str(x) for x in (izklopljeni or []) if x}
        if samo_lokalno:
            # Samo ta naprava: brez omrezja in brez cakanja na spletne kataloge.
            page_num = max(1, int(page or 1))
            local = [item for item in self._local_items() if (kind in ("", "vse") or item.get("vrsta") == kind)]
            needle = _text(query, 120).casefold()
            if needle:
                local = [item for item in local if needle in " ".join(
                    str(item.get(k) or "") for k in ("naslov", "izvajalec", "album", "opis")).casefold()]
            merged = self._razvrsti_vnose(merge_duplicates(local), razvrsti)
            for shown in merged:
                if shown.get("id"):
                    self._dynamic_items.setdefault(shown["id"], shown)
            return {"vnosi": merged, "viri": self.vidni_viri(), "skupaj": len(merged), "stran": 1,
                    "skupaj_strani": 1, "mape": [str(path) for path in self.roots]}
        if kind == self.ZASEBNO:
            return self._catalog_zasebno(query, page, razvrsti, izklopljeni)
        with self._lock:
            data = self._load()
        page_num = max(1, int(page or 1))
        local = [item for item in self._local_items() if (kind in ("", "vse") or item.get("vrsta") == kind)] if page_num == 1 else []
        remote = [_series_catalog_card(item) for item in self._vnosi_virov(data, kind)] if page_num == 1 else []
        glasbena = kind in ("glasba", "radio") and _text(genre, 20) in zakoniti_viri.GLASBENE_ZVRSTI
        embed_ids = {str(provider.get("id") or host) for provider, _parsed, host in self._embed_viri(data)}
        tmdb_izklopljen = bool(embed_ids) and embed_ids <= izklopljeni
        # Javni katalogi imajo svoj 30-minutni cache in se napake posameznega API-ja
        # ne smejo prenesti v glavni katalog.
        configured_hosts = [str(source.get("url") or "") for source in data.get("viri", [])
                            if isinstance(source, dict) and source.get("url")]
        vrsta_virov = "" if kind in ("", "vse") else kind
        # TMDB, javni viri in osebni (dodatki Stremio, Cinemeta, strezniki) hkrati, vsak najvec rok_vira s: pocasen vir
        # ne zadrzi prvih zadetkov (meritev 15. 10. 2026: iskanje 20-40 s, ker so osebni viri sli eden za drugim).
        rok = self._rok_zdaj()
        zacetek_virov = time.monotonic()
        nit_tmdb = None if (glasbena or tmdb_izklopljen or not self._ima_embed_vir(data)) else self._vzporedno(
            self._tmdb_catalog, data, _text(query, 120), kind, _text(genre, 20), page_num, razvrsti, jezik)
        nit_javni = (self._vzporedno(lambda: self._zakoniti_viri.get(
                         _text(query, 120), configured_hosts, _text(genre, 20), jezik, vrsta=vrsta_virov,
                         drzava_radia=drzava_radia)) if glasbena
                     else self._vzporedno(lambda: self._zakoniti_viri.get(
                         _text(query, 120), configured_hosts, "", jezik,
                         filmska_zvrst=_text(genre, 20) if kind in ("film", "vse") else "",
                         vrsta=vrsta_virov, drzava_radia=drzava_radia)))
        try:
            _osebni_vnosi = self._personal_items(_text(query, 120))   # sam caka najvec rok_vira s
        except Exception:  # noqa: BLE001 - en vir ne sme podreti kataloga
            _osebni_vnosi = []
        # En skupen rok za vse vire (osebni so ga ze porabili del): prvi zadetki najkasneje po rok_vira s.
        self._cakaj([n for n in (nit_tmdb, nit_javni) if n is not None],
                    None if rok is None else max(0.0, rok - (time.monotonic() - zacetek_virov)))

        def izid(nit, privzeto):
            if nit is None or not nit.done() or nit.exception() is not None:
                return privzeto
            return nit.result()
        dynamic, tmdb_pages = izid(nit_tmdb, ([], 1))
        lawful = list(izid(nit_javni, []) or [])
        if glasbena:
            # Pri zvrsti pokazemo samo zadetke te zvrsti, ne tudi krajevnih datotek in osebnih virov.
            local, remote = [], []
        if drzava_radia and kind == "radio":
            # Izbrana drzava radia: samo postaje, za katere vemo, da so iz nje (osebni viri drzave ne povejo).
            local, remote = [], []
            _osebni_vnosi = [x for x in _osebni_vnosi if isinstance(x, dict) and str(x.get("drzava") or "").upper() == drzava_radia]
        if kind == "tv-v-zivo":
            lawful = lawful + zakoniti_viri.tv_v_zivo(self._drzava_uporabnika())
            izbrana = _text(genre, 20)
            if izbrana == "moji":
                lawful, dynamic, remote = [], [], []
            elif izbrana:
                # TV v zivo po drzavah (kot zanri pri filmih); osebni kanali so pod "Moji kanali". Delujoci kanali
                # seznamov IPTV iz izbrane drzave ostanejo.
                lawful = [item for item in lawful if str(item.get("drzava") or "").upper() == izbrana.upper()]
                remote = [item for item in remote if item.get("iptv") and str(item.get("drzava") or "").upper() == izbrana.upper()]
                dynamic, local = [], []
        if kind not in ("", "vse"):
            lawful = [item for item in lawful if item.get("vrsta") == kind]
        personal = _osebni_vnosi
        if kind == "tv-v-zivo" and _text(genre, 20) not in ("", "moji"):
            personal = []
        if glasbena:
            # Tudi na osebnih streznikih (Kodi, Funkwhale, DLNA ...) po zvrsti, ce jo vnos navaja.
            ime_z, oznaka_j, oznaka_r = zakoniti_viri.GLASBENE_ZVRSTI[_text(genre, 20)]
            iskane = {x.casefold() for x in (ime_z, oznaka_j, oznaka_r, _text(genre, 20)) if x}
            personal = [item for item in personal if any(z in str(item.get("zanri") or "").casefold() for z in iskane)]
        if kind not in ("", "vse"):
            personal = [item for item in personal if item.get("vrsta") == kind]
        # Vsak vnos mora imeti oznako vira, sicer ga uporabnik ne more zacasno izklopiti
        # (zakoniti viri - PeerTube, Jamendo, radio, TV - so jo prej imeli le kot besedilo "vir").
        def z_oznako(vnosi: list) -> list:
            out = []
            for vnos in vnosi:
                if isinstance(vnos, dict) and not vnos.get("vir_id") and vnos.get("vir"):
                    vnos = dict(vnos, vir_id="vir:" + re.sub(r"\s+", " ", str(vnos["vir"])).strip().casefold()[:80])
                out.append(vnos)
            return out
        dynamic, lawful, personal, remote = z_oznako(dynamic), z_oznako(lawful), z_oznako(personal), z_oznako(remote)
        # Privzeto (Priporoceno): najprej najboljsi viri, v vsakem najbolj priljubljena vsebina.
        # Viri ze vracajo vsebino po priljubljenosti (TMDB popular/trending, javna last po prenosih,
        # PeerTube po ogledih, Jamendo po poslusanjih, radio po klikih) - ta vrstni red ohranimo.
        lawful = sorted(lawful, key=lambda x: 0 if x.get("vir_id") == "archive-javna-last" else 1)
        prednostni = dynamic + lawful + remote + personal + local
        mesto: dict[str, int] = {}
        for indeks, vnos in enumerate(prednostni):
            if isinstance(vnos, dict) and vnos.get("url"):
                mesto.setdefault(str(vnos["url"]), indeks)
        merged = self._filtriraj_vire(zdruzi_epizode_v_serije(merge_duplicates(local + remote + dynamic + lawful + personal)),
                                      izklopljeni)
        if not razvrsti:
            def prednost(vnos: dict) -> int:
                urlji = [str(vnos.get("url") or "")] + [str(r.get("url") or "") for r in (vnos.get("razlicice") or [])
                                                        if isinstance(r, dict)]
                return min((mesto[u] for u in urlji if u in mesto), default=len(prednostni))
            merged = sorted(merged, key=prednost)
        # Prenos, ki ga izdajatelj ponuja samo na svoji strani (RTV SLO): zdruzevanje polja ne ohrani.
        strani = {str(item.get("url")): item["stran"] for item in lawful if isinstance(item, dict) and item.get("stran")}
        if strani:
            merged = [dict(item, stran=strani[str(item.get("url"))]) if str(item.get("url")) in strani else item
                      for item in merged]
        needle = _text(query, 120).casefold()
        if needle:
            def zadetek(item: dict) -> bool:
                hay = " ".join(str(item.get(key) or "") for key in
                               ("naslov", "izvajalec", "album", "opis", "imdb_id", "tmdb_id")).casefold()
                if needle in hay:
                    return True
                # Vse iskane besede, brez naglasov ("sport tv" najde "Šport TV 1").
                if media_servers.ujema_iskanje(item, query):
                    return True
                return any(difflib.SequenceMatcher(None, needle, token).ratio() >= 0.72
                           for token in re.findall(r"[\wÀ-ž]{3,}", hay))
            merged = [item for item in merged if zadetek(item)]
            if not razvrsti:
                # Iskanje: najprej zadetki, ki se z iskanim ujemajo v naslovu, med njimi uporabnikovi viri in dodatki
                # (prej so bili na koncu, za desetinami ohlapnih zadetkov s spleta). Vrstni red znotraj skupin ostane.
                moji = {str(x.get("url")) for x in (personal + local) if isinstance(x, dict)}
                # Tocno ujemanje naslova je prvo (»breaking bad« -> serija Breaking Bad, ne dokumentarec o njej;
                # testni PC 17. 10. 2026 je bila serija sele cetrta), nato naslovi, ki se z iskanim zacnejo.
                merged = sorted(merged, key=lambda it: (
                    _ujemanje_naslova(str(it.get("naslov") or ""), query),
                    0 if media_servers.ujema_iskanje({"naslov": it.get("naslov")}, query) else 1,
                    0 if str(it.get("url")) in moji else 1))
        merged = self._filtriraj_jezike(merged, izklopljeni_jeziki)
        if jezik:
            # Lastnik, 11. 10. 2026: izbira jezika (npr. anglescina) je pokazala 0 filmov, ker dodatek jezika ne pove.
            # Najprej vsebina v izbranem jeziku, nato tista z neznanim jezikom - nic ne izgine brez razloga.
            v_jeziku, neznan = self._po_jeziku(merged, jezik)
            merged = self._razvrsti_vnose(v_jeziku, razvrsti) + self._razvrsti_vnose(neznan, razvrsti)
        else:
            merged = self._razvrsti_vnose(merged, razvrsti)
        # Zasebna vsebina je samo v svoji kategoriji (npr. razlicica filma TMDB iz zasebnega dodatka izpade).
        merged = self.brez_zasebnih(merged)
        tmdb_strani = (self._ima_embed_vir(data) and not tmdb_izklopljen and tmdb_pages > 1
                       and kind in ("", "vse", "film", "serija"))
        total_pages = tmdb_pages if tmdb_strani else max(1, math.ceil(len(merged) / NA_STRAN))
        # Zapomni si vse prikazane vnose (tudi zadetke iskanja in zdruzene kartice),
        # da jih resolve() najde, ko uporabnik klikne - sicer se klik na zadetek
        # iskanja tiho ne zgodi, ker katalog brez iskanja tega vnosa nima.
        for shown in merged:
            if isinstance(shown, dict) and shown.get("id") and shown["id"] not in self._dynamic_items:
                self._dynamic_items[shown["id"]] = shown
        if len(self._dynamic_items) > 5000:
            for old_key in list(self._dynamic_items)[:len(self._dynamic_items) - 4000]:
                self._dynamic_items.pop(old_key, None)
        # Lokalni seznami: vrnemo samo izbrano stran. Prej je sel ves katalog (npr. 501 kartica,
        # 43 000 px visoka mreza) in vsak izris strani je v QtWebEngine (programsko risanje) puscal
        # pomnilnik - po eni uri 21 GB in neodziven Safeer OS (28. 9. 2026).
        stran_vnosi = merged
        if not tmdb_strani:
            trenutna = min(max(1, int(page_num or 1)), total_pages)
            stran_vnosi = merged[(trenutna - 1) * NA_STRAN:trenutna * NA_STRAN]
        return {
            "vnosi": stran_vnosi,
            "viri": self.vidni_viri(),
            "skupaj": len(merged),
            "stran": page_num,
            "skupaj_strani": total_pages,
            "mape": [str(path) for path in self.roots]
        }

    def _catalog_zasebno(self, query: str, page: int, razvrsti: str, izklopljeni: set) -> dict:
        """Kategorija »Zasebno«: samo vsebina zasebnih dodatkov in samo, ce jo je uporabnik vklopil."""
        merged = []
        if self.zasebno:
            vnosi = self._personal_items(_text(query, 120), zasebni=True)
            merged = self._razvrsti_vnose(self._filtriraj_vire(
                zdruzi_epizode_v_serije(merge_duplicates(vnosi)), izklopljeni), razvrsti)
        for shown in merged:
            if shown.get("id"):
                self._dynamic_items.setdefault(shown["id"], shown)
        total_pages = max(1, math.ceil(len(merged) / NA_STRAN))
        trenutna = min(max(1, int(page or 1)), total_pages)
        return {"vnosi": merged[(trenutna - 1) * NA_STRAN:trenutna * NA_STRAN], "viri": self.vidni_viri(),
                "skupaj": len(merged), "stran": trenutna, "skupaj_strani": total_pages,
                "mape": [str(path) for path in self.roots]}

    def details(self, item_id: str, country: str = "auto", language: str = "sl") -> dict:
        # Odprte podrobnosti niso predvajanje: torrenta zaradi njih ne zacnemo prenasati.
        item = self.resolve(item_id, pripravi_torrent=False)
        if item and not item.get("tmdb_id") and item.get("epizode_seznama"):
            # Serija s seznama M3U: sezone so tiste, ki jih seznam ima (nikoli prazna stran »Sezone niso na voljo«).
            stevilo: dict[int, int] = {}
            for e in item["epizode_seznama"]:
                stevilo[int(e.get("sezona") or 0)] = stevilo.get(int(e.get("sezona") or 0), 0) + 1
            return dict(item, sezone=[{"stevilka": s, "ime": "", "epizod": n} for s, n in sorted(stevilo.items()) if s > 0],
                        media_type="tv", iz_seznama=True)
        if not item or not item.get("tmdb_id"):
            return item or {}
        media_type = "tv" if item.get("vrsta") == "serija" else "movie"
        try:
            raw = self._tmdb(f"/{media_type}/{item['tmdb_id']}", {"append_to_response": "external_ids"})
        except Exception:
            raw = {}
        seasons = [{"stevilka": s.get("season_number"), "ime": s.get("name") or f"Sezona {s.get('season_number')}",
                    "epizod": s.get("episode_count") or 0}
                   for s in raw.get("seasons", []) if int(s.get("season_number") or 0) > 0]
        country_settings = self.watch_country_settings(country, language)
        providers = self._watch_providers(media_type, int(item["tmdb_id"]),
                                          country_settings["drzava"], str(item.get("naslov") or ""))
        providers.update({"ime_drzave": country_settings["ime_drzave"],
                          "vir": "JustWatch prek TMDB"})
        # Id-ji za lastne vgrajene vire ({imdb}, {tvdb} - core/os_vgrajeni_viri.py): TMDB jih da v external_ids.
        zunanji = raw.get("external_ids") if isinstance(raw.get("external_ids"), dict) else {}
        imdb = item.get("imdb_id") or _imdb_id(zunanji.get("imdb_id"))
        tvdb = item.get("tvdb_id") or _tmdb_id(zunanji.get("tvdb_id"))
        leto = item.get("leto") or str(raw.get("release_date") or raw.get("first_air_date") or "")[:4]
        return dict(item, imdb_id=imdb or "", tvdb_id=tvdb or 0, leto=leto,
                    opis=raw.get("overview") or item.get("opis", ""),
                    ocena=round(float(raw.get("vote_average") or item.get("ocena") or 0), 1),
                    sezone=seasons, media_type=media_type, kje_gledati=providers)

    def season(self, tmdb_id: int, season_number: int) -> dict:
        try:
            raw = self._tmdb(f"/tv/{int(tmdb_id)}/season/{int(season_number)}")
        except Exception:
            return {"epizode": []}
        episodes = []
        for ep in raw.get("episodes", []):
            if not isinstance(ep, dict):
                continue
            episodes.append({
                "stevilka": int(ep.get("episode_number") or 0), "sezona": int(season_number),
                "naslov": ep.get("name") or f"Epizoda {ep.get('episode_number')}",
                "opis": ep.get("overview") or "", "trajanje": ep.get("runtime") or 0,
                "ocena": round(float(ep.get("vote_average") or 0), 1),
                "datum": ep.get("air_date") or "",
                "slika": f"{TMDB_IMAGE}/w500{ep['still_path']}" if ep.get("still_path") else "",
            })
        return {"tmdb_id": int(tmdb_id), "sezona": int(season_number), "epizode": episodes}

    def episode_item(self, tmdb_id: int, season: int, episode: int, title: str = "") -> Optional[dict]:
        tmdb = str(int(tmdb_id))
        imdb = TMDB_TO_IMDB.get(tmdb, "")
        s, ep = max(1, int(season or 1)), max(1, int(episode or 1))
        ep_title = title or f"S{s:02d}E{ep:02d}"
        items = []
        for provider, parsed, host in self._embed_viri(self._load()):
            url = _embed_url_for_provider(host, parsed.scheme, imdb, tmdb, "serija", s, ep)
            it = _item(ep_title, url, base=url,
                       source_id=str(provider.get("id") or host),
                       source_name=str(provider.get("ime") or host),
                       kind="serija", season=s, episode=ep,
                       imdb_id=imdb, tmdb_id=int(tmdb_id), quality="1080p HD")
            if it:
                items.append(it)
        items += self._stremio_vnosi(imdb, int(tmdb_id), "serija", ep_title, s, ep)
        items += self._osebni_naslovi("serija", imdb, int(tmdb_id), s, ep)
        if not items:
            return None
        merged = merge_duplicates(items)
        if merged:
            res = merged[0]
            self._dynamic_items[res["id"]] = res
            return res
        return None

    def movie_item(self, tmdb_id: int, title: str = "") -> Optional[dict]:
        tmdb = str(int(tmdb_id))
        imdb = TMDB_TO_IMDB.get(tmdb, "")
        items = []
        for provider, parsed, host in self._embed_viri(self._load()):
            url = _embed_url_for_provider(host, parsed.scheme, imdb, tmdb, "film", 0, 0)
            it = _item(title or "Film", url, base=url,
                       source_id=str(provider.get("id") or host),
                       source_name=str(provider.get("ime") or host),
                       kind="film", imdb_id=imdb, tmdb_id=int(tmdb_id), quality="1080p HD")
            if it:
                items.append(it)
        items += self._stremio_vnosi(imdb, int(tmdb_id), "film", title or "Film")
        items += self._osebni_naslovi("film", imdb, int(tmdb_id))
        if not items:
            return None
        merged = merge_duplicates(items)
        if merged:
            res = merged[0]
            self._dynamic_items[res["id"]] = res
            return res
        return None

    def export_json(self) -> dict:
        """Izvozi celotno konfiguracijo in shranjene vire za prenos ali varnostno kopijo."""
        with self._lock:
            data = self._load()
            return {
                "razlicica": 1,
                "aplikacija": "Safeer Media",
                "cas": int(time.time()),
                "viri": data.get("viri", []),
            }

    def import_json(self, raw_data: Any, default_name: str = "") -> dict:
        """Uvozi JSON kodo ali izvoženo JSON datoteko.

        Podpira:
        1. Celoten izvoz Safeer Media (slovar z 'viri').
        2. Seznam medijskih vnosov ali katalog z 'items'/'vnosi'.
        3. Prilagojen vir s tokovi.
        """
        if isinstance(raw_data, str):
            besedilo = raw_data.strip()
            if not besedilo:
                return {"ok": False, "napaka": "Prazen vnos JSON"}
            try:
                data = json.loads(besedilo)
            except Exception as exc:
                return {"ok": False, "napaka": f"Neveljaven JSON: {exc}"}
        elif isinstance(raw_data, (dict, list)):
            data = raw_data
        else:
            return {"ok": False, "napaka": "Neveljaven format podatkov"}

        with self._lock:
            shramba = self._load()
            obstojeci_viri = shramba.get("viri", [])

            # Primer 1: Izvožena konfiguracija virov z 'viri'
            if isinstance(data, dict) and isinstance(data.get("viri"), list):
                uvozeni_viri = data.get("viri", [])
                st_dodanih = 0
                st_posodobljenih = 0
                for v in uvozeni_viri:
                    if not isinstance(v, dict):
                        continue
                    url = v.get("url") or f"custom://{v.get('id', int(time.time()))}"
                    ime = _text(v.get("ime") or v.get("name") or "Uvoženi vir", 80)
                    vnosi = v.get("vnosi") if isinstance(v.get("vnosi"), list) else []

                    najden = next((x for x in obstojeci_viri if x.get("url") == url or (x.get("id") and x.get("id") == v.get("id"))), None)
                    if najden:
                        najden["ime"] = ime
                        if vnosi:
                            najden["vnosi"] = vnosi
                            najden["stevilo"] = len(vnosi)
                        najden["posodobljeno"] = int(time.time())
                        st_posodobljenih += 1
                    else:
                        vir_id = v.get("id") or hashlib.sha256(url.encode()).hexdigest()[:16]
                        nov_vir = {
                            "id": vir_id,
                            "url": url,
                            "ime": ime,
                            "posodobljeno": int(time.time()),
                            "napaka": "",
                            "stevilo": len(vnosi),
                            "vnosi": vnosi,
                        }
                        obstojeci_viri.append(nov_vir)
                        st_dodanih += 1
                shramba["viri"] = obstojeci_viri
                self._save(shramba)
                return {"ok": True, "st_dodanih": st_dodanih, "st_posodobljenih": st_posodobljenih, "vrsta": "viri"}

            # Primer 2: Seznam elementov ali posamezen katalog
            vir_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
            source_id = f"custom-{vir_hash}"
            custom_name = _text(default_name or (data.get("name") if isinstance(data, dict) else "") or (data.get("ime") if isinstance(data, dict) else "") or "Uvoženi JSON katalog", 80)

            items = _items_from_json(data, base="", source_id=source_id, source_name=custom_name)
            if not items:
                return {"ok": False, "napaka": "V JSON podatkih ni vsebin, ki bi jih Safeer lahko predvajal (torrentov, arhivov in namestitvenih datotek ne predvaja)."}

            najden = next((x for x in obstojeci_viri if x.get("id") == source_id), None)
            if najden:
                najden["ime"] = custom_name
                najden["vnosi"] = items
                najden["stevilo"] = len(items)
                najden["posodobljeno"] = int(time.time())
            else:
                obstojeci_viri.append({
                    "id": source_id,
                    "url": f"custom://{source_id}",
                    "ime": custom_name,
                    "posodobljeno": int(time.time()),
                    "napaka": "",
                    "stevilo": len(items),
                    "vnosi": items,
                })
            shramba["viri"] = obstojeci_viri
            self._save(shramba)
            return {"ok": True, "st_vnosov": len(items), "vir": custom_name, "vrsta": "katalog"}

    #: Ali pred predvajanjem preverimo, da streznik prvega toka res odgovori. Vklopi aplikacija (os_katalog); preizkusi
    #: in orodja brez omrezja ostanejo brez zahtev.
    preveri_tokove = False

    #: Izid sonde toka velja toliko sekund: drugi klic Predvajaj (ali podrobnosti, nato Predvajaj) istega naslova ne
    #: sprasuje znova - streznik toka dobi eno zahtevo manj.
    SONDA_VELJA = 60.0

    def _sonda(self, tok: dict) -> bool:
        url = str(tok.get("url") or "")
        if skrivni_dodatki.je_nadomestek(url):
            return True         # tok s kljucem preveri sonda pred predvajanjem (_razresi_skrivne_tokove), ne tu
        if not hasattr(self, "_sonde"):
            self._sonde: dict[str, tuple[float, bool]] = {}
        zdaj = time.time()
        znano = self._sonde.get(url)
        if znano and zdaj - znano[0] < self.SONDA_VELJA:
            return znano[1]
        ok = media_servers.tok_stanje(url, tok.get("glave"))[0]
        if len(self._sonde) > 500:
            self._sonde.clear()
        self._sonde[url] = (zdaj, ok)
        return ok

    def _zivi_naprej(self, tokovi: list) -> list:
        """Prvi tok mora res odgovoriti: prve tri vprasamo hkrati (zahteva prvih bajtov z glavami toka,
        core/media_servers.tok_stanje) in na prvo mesto damo najboljsega, ki odgovori - mrtva povezava (izbrisana,
        zavrnjena, potekla brez roka v naslovu) tako ne pride do predvajalnika. Ce ne odgovori nobeden, vrstni red ostane
        (predvajalnik tiho poskusi razlicice in napako pove sele, ko ne dela nobena)."""
        if not self.preveri_tokove or len(tokovi) < 2:
            return tokovi
        from concurrent.futures import ThreadPoolExecutor
        kandidati = tokovi[:3]
        bazen = ThreadPoolExecutor(max_workers=len(kandidati))
        try:
            niti = [bazen.submit(self._sonda, t) for t in kandidati]
            for i, nit in enumerate(niti):
                try:
                    ok = bool(nit.result(timeout=5))
                except Exception:  # noqa: BLE001
                    ok = False
                if ok:
                    return tokovi if i == 0 else [kandidati[i]] + [t for j, t in enumerate(tokovi) if j != i]
        finally:
            bazen.shutdown(wait=False)
        return tokovi

    # --- razlicice naslova (podrobnosti filma ali epizode: uporabnik lahko izbere drug vir) -----------------------------
    @staticmethod
    def _podpis_razlicice(r: dict) -> str:
        """Stalna oznaka razlicice: dodatek ali vir, kakovost in gostitelj - ne naslov (podpisani naslovi potecejo)."""
        gost = urllib.parse.urlsplit(str(r.get("url") or "")).hostname or ""
        deli = [str(r.get("dodatek") or r.get("vir") or ""), str(r.get("opis") or r.get("kakovost") or "")[:80],
                hashlib.sha1(gost.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]]
        return hashlib.sha1("|".join(deli).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    @staticmethod
    def _kljuc_naslova(item: dict) -> str:
        """Naslov za zapomnjeno izbiro: film po TMDB/IMDb, epizoda po id-ju dodatka (tt..:sezona:epizoda)."""
        for u in [str(item.get("url") or "")] + [str(v.get("url") or "") for v in (item.get("razlicice") or []) if isinstance(v, dict)]:
            if u.startswith("stremio:"):
                _koren, tip, ident = (u[len("stremio:"):].split("|") + ["", ""])[:3]
                if tip and ident:
                    return "stremio:%s:%s" % (tip, ident)
        if int(item.get("tmdb_id") or 0):
            return "tmdb:%s:%s:%s:%s" % (item.get("vrsta") or "", item.get("tmdb_id"), item.get("sezona") or 0, item.get("epizoda") or 0)
        if str(item.get("imdb_id") or "").startswith("tt"):
            return "imdb:" + str(item["imdb_id"])
        return "id:" + str(item.get("id") or "") if item.get("id") else ""

    def _izbire_razlicic(self) -> dict:
        if getattr(self, "_izbire", None) is None:
            try:
                data = json.loads((self.config_dir / "izbrane-razlicice.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            self._izbire = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        return self._izbire

    def izberi_razlicico(self, item_id: str, podpis: str) -> bool:
        """Rocna izbira razlicice za ta naslov (zapomni se); privzeta (samodejna) izbiro pobrise."""
        item = self._dynamic_items.get(item_id)
        if not isinstance(item, dict):
            return False
        kljuc = self._kljuc_naslova(item)
        if not kljuc:
            return False
        razlicice = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)]
        if podpis and not any(self._podpis_razlicice(r) == podpis for r in razlicice):
            return False
        with self._lock:
            izbire = self._izbire_razlicic()
            samodejna = razlicice and self._podpis_razlicice(razlicice[0]) == podpis and not item.get("izbrana_razlicica")
            if not podpis or samodejna:
                izbire.pop(kljuc, None)
            else:
                izbire[kljuc] = podpis
            while len(izbire) > 500:
                izbire.pop(next(iter(izbire)))
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                shramba_json.zapisi_atomsko(self.config_dir / "izbrane-razlicice.json", izbire, indent=None)
            except OSError:
                pass
        # Naslednji Predvajaj uporabi izbiro (razresen vnos ostane, uredi ga uporabi_izbiro).
        self._dynamic_items[item_id] = dict(item, izbrana_razlicica="")
        return True

    def uporabi_izbiro(self, item: Optional[dict]) -> Optional[dict]:
        """Zapomnjena rocna izbira gre na prvo mesto (ce je razlicica se med ponujenimi); sicer ostane samodejna."""
        if not isinstance(item, dict):
            return item
        razlicice = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)]
        podpis = self._izbire_razlicic().get(self._kljuc_naslova(item)) if razlicice else None
        if not podpis:
            return item
        izbrana = next((r for r in razlicice if self._podpis_razlicice(r) == podpis), None)
        if izbrana is None or not str(izbrana.get("url") or "").startswith(("http://", "https://")):
            return item
        out = dict(item, razlicice=[izbrana] + [r for r in razlicice if r is not izbrana], url=izbrana["url"],
                   izbrana_razlicica=podpis)
        if izbrana.get("glave"):
            out["glave"] = dict(izbrana["glave"])
        elif "glave" in out and izbrana.get("tok"):
            out.pop("glave", None)
        return out

    def _ping_ms(self, url: str) -> Optional[float]:
        """Zadnji izmerjeni odziv gostitelja (ms) ali None - zbirka meritev core/meritve_virov.py (ista kot za lastne
        vgrajene vire)."""
        try:
            return self._meritve.ms(str(url))
        except Exception:  # noqa: BLE001
            return None

    def _dodaj_toke_dodatkov(self, item_id: str, izvirni: Optional[dict], item: dict) -> dict:
        """Kartica z lastnim strežnikom se predvaja takoj (resolve ne caka na dodatke), zato toki dodatkov iste vsebine
        pridejo sele za seznam v podrobnostih: za lastnimi, kot rezerva ob Predvajaj (tiha zamenjava)."""
        if not item.get("lastni") or item.get("toki_dodatkov") or not isinstance(izvirni, dict):
            return item
        stremio_url = next((str(v.get("url")) for v in (izvirni.get("razlicice") or [])
                            if isinstance(v, dict) and str(v.get("url") or "").startswith("stremio:")), "")
        if not stremio_url:
            return item
        koren, tip, ident = (stremio_url[len("stremio:"):].split("|") + ["", ""])[:3]
        try:
            tokovi = self._stremio_tokovi_vseh(koren, tip, ident)
        except Exception:  # noqa: BLE001
            tokovi = []
        neposredni = [dict(t, tok=True) for t in tokovi if t.get("url") and not t.get("zunanje")
                      and (t["url"].startswith("https://") or media_servers.dovoljen_naslov(t["url"]))]
        neposredni = tok_izbira.uredi(neposredni, lambda t: str(t.get("opis") or "%s %s" % (t.get("vir", ""), t.get("kakovost", ""))),
                                      tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)),
                                      naslov=lambda t: str(t.get("url") or ""), **self._jezik_zvoka(item))
        obstojeci = {str(r.get("url")) for r in (item.get("razlicice") or []) if isinstance(r, dict)}
        dodani = [t for t in neposredni[:10] if t["url"] not in obstojeci]
        out = dict(item, razlicice=list(item.get("razlicice") or []) + dodani, toki_dodatkov=True)
        out["stevilo_razlicic"] = len(out["razlicice"])
        self._dynamic_items[item_id] = out
        return out

    def razlicice_naslova(self, item_id: str) -> dict:
        """Razlicice za seznam v podrobnostih: ime vira (dodatek ali streznik, ki ga je dodal uporabnik), kakovost,
        izmerjen odziv gostitelja. Mrtvih (sonda pred predvajanjem jih je zavrnila) ni. Prva je privzeta (samodejna)."""
        izvirni = self._dynamic_items.get(item_id)
        item = self.resolve(item_id, pripravi_torrent=False)
        if not isinstance(item, dict) or item.get("napaka_koda") or item.get("napaka"):
            return {"id": item_id, "razlicice": []}
        item = self._dodaj_toke_dodatkov(item_id, izvirni, item)
        samodejno = [r for r in (item.get("razlicice") or []) if isinstance(r, dict)
                     and str(r.get("url") or "").startswith(("http://", "https://"))]
        if self.preveri_tokove:
            # Lastni strežnik je vedno privzet (lastnik): tudi njega vprasamo, ali odgovori - nedosegljiv ni na seznamu,
            # privzeta (in Predvajaj) je naslednja razlicica.
            from concurrent.futures import wait
            lastni = [r for r in samodejno if r.get("lastni")][:3]
            if lastni:
                wait([_bazen_virov().submit(self._sonda, r) for r in lastni], timeout=4.5)
        sonde = getattr(self, "_sonde", {})

        def ziva(r: dict) -> bool:
            sonda = sonde.get(str(r.get("url")))
            if sonda is not None:
                return sonda[1]             # sonda tik pred tem (z glavami toka) ima prednost
            try:
                return not self._meritve.nedosegljiv(str(r.get("url")))
            except Exception:  # noqa: BLE001
                return True
        zive = [r for r in samodejno if ziva(r)]
        if zive and samodejno and zive[0] is not samodejno[0]:
            # Prva (samodejna) razlicica ne odgovori: Predvajaj zacne z naslednjo zivo, ostale ostanejo za tiho zamenjavo.
            mrtve = [r for r in samodejno if r not in zive]
            prva = zive[0]
            popravljen = dict(item, url=prva["url"], razlicice=zive + mrtve)
            if prva.get("glave"):
                popravljen["glave"] = dict(prva["glave"])
            else:
                popravljen.pop("glave", None)
            self._dynamic_items[item_id] = popravljen
        gostitelji = {urllib.parse.urlsplit(str(r["url"])).hostname: r["url"] for r in zive}
        neznani = [u for u in gostitelji.values() if self._ping_ms(u) is None or self._meritve.zastarelo(u)]
        if neznani:
            from concurrent.futures import wait
            wait([_bazen_virov().submit(self._izmeri_ping, u) for u in neznani[:8]], timeout=1.0)
        izbira = self._izbire_razlicic().get(self._kljuc_naslova(item), "")
        pingi = [self._ping_ms(r["url"]) for r in zive]
        # »Najhitrejsi« ima smisel samo med vec streznikov: oznaci prvo razlicico najhitrejsega gostitelja.
        po_gostiteljih = {urllib.parse.urlsplit(str(r["url"])).hostname: p for r, p in zip(zive, pingi) if p is not None}
        najhitrejsi_i = -1
        if len(po_gostiteljih) > 1:
            najhitrejsi_i = min((i for i, p in enumerate(pingi) if p is not None), key=lambda i: (pingi[i], i))
        izhod = []
        for i, (r, ping) in enumerate(zip(zive, pingi)):
            podpis = self._podpis_razlicice(r)
            kakovost = str(r.get("kakovost") or "") or (_quality_label(int(r.get("locljivost") or 0)) if r.get("locljivost") else "")
            izhod.append({"podpis": podpis, "vir": str(r.get("dodatek") or r.get("vir") or "")[:60],
                          "opis": str(r.get("opis") or "").split("\n")[0][:80], "kakovost": kakovost[:20],
                          "ping": None if ping is None else round(ping), "privzeta": i == 0,
                          "najhitrejsi": i == najhitrejsi_i,
                          "izbrana": bool(izbira) and podpis == izbira, "lastni": bool(r.get("lastni"))})
        return {"id": item_id, "razlicice": izhod, "izbira": bool(izbira) and any(x["izbrana"] for x in izhod)}

    def tokovi_postaje(self, item_id: str) -> list[dict]:
        """Programi radijske postaje (Rock Radio: Best Ballads, Hard & Heavy ...) kot vnosi, ki jih resolve() pozna."""
        item = self._dynamic_items.get(item_id) or next((x for x in self.catalog()["vnosi"] if x.get("id") == item_id), None)
        if not item or item.get("vrsta") != "radio":
            return []
        izhod = []
        for tok in self._zakoniti_viri.tokovi_postaje(item):
            vnos = {"id": "tok:" + hashlib.sha1(tok["url"].encode("utf-8"), usedforsecurity=False).hexdigest()[:16], "naslov": tok["naslov"],
                    "vrsta": "radio", "url": tok["url"], "mime": tok.get("mime") or "", "bitrate": tok.get("bitrate") or 0,
                    "slika": item.get("slika") or "", "vir": item.get("vir") or "", "vir_id": item.get("vir_id") or "",
                    "postaja_id": item_id}
            self._dynamic_items[vnos["id"]] = vnos
            izhod.append({"id": vnos["id"], "naslov": vnos["naslov"], "bitrate": vnos["bitrate"]})
        return izhod

    def resolve(self, item_id: str, pripravi_torrent: bool = True, p2p: bool = False) -> Optional[dict]:
        """Vnos, pripravljen za predvajanje. `pripravi_torrent=False` (podrobnosti naslova): naslova, ki ga ponujajo
        samo torrenti, ne zacnemo prenasati - to se zgodi sele, ko uporabnik pritisne Predvajaj. `p2p=True`: uporabnik
        je izrecno izbral »Predvajaj neposredno« (njegov naslov IP bo viden v roju) - glej _p2p_dovoljeni."""
        if str(item_id or "").startswith("seznam:"):
            return self.seznam_posnetek(str(item_id))
        if str(item_id or "").startswith(("twitch:", "twitch-posnetek:")):
            # Twitch: vnos iz zadnjega seznama ali (po ponovnem zagonu) iz samega id-ja - brez iskanja po katalogu.
            ident = str(item_id).split(":", 1)[1]
            item = self._dynamic_items.get(item_id) or (
                {"id": item_id, "vrsta": "twitch", "login": ident, "naslov": ident} if item_id.startswith("twitch:")
                else {"id": item_id, "vrsta": "twitch-posnetek", "naslov": "Twitch"})
            return self._razresi_twitch(item)
        if str(item_id or "").startswith("spotify:"):
            return self._dynamic_items.get(item_id)      # skladba racuna Spotify (sp_seznam)
        item = self._dynamic_items.get(item_id) or next((item for item in self.catalog()["vnosi"] if item.get("id") == item_id), None)
        if not item:
            return None
        # Vnos s police ali samodejnega seznama nosi naslov streznika brez prijave (shranjen je bil tako): prijava zdaj.
        item = self._vnos_s_prijavo(item)
        if str(item.get("url") or "").startswith("knjiznica:"):
            return self._razresi_knjiznico(item) if pripravi_torrent else dict(item, torrent=True)
        if item.get("lastni") and str(item.get("url") or "").startswith(("http://", "https://")):
            # Kartica s tokom z uporabnikovega strežnika (merge_duplicates): predvaja se takoj, brez cakanja na dodatke
            # Stremio. Razlicice ostanejo tiste, ki jih predvajalnik zna odpreti (http), lastne najprej.
            razlicice = [v for v in (item.get("razlicice") or []) if isinstance(v, dict)
                         and str(v.get("url") or "").startswith(("http://", "https://"))]
            item = dict(item, razlicice=razlicice, stevilo_razlicic=len(razlicice))
        # Posebni naslovi (Stremio dodatek) so lahko tudi med razlicicami zdruzene kartice.
        posebni = [str(item.get("url") or "")] + [str(v.get("url") or "") for v in (item.get("razlicice") or []) if isinstance(v, dict)]
        if any(u.startswith("kodi-dodatek:") for u in posebni):
            # Kartica iz starega predpomnilnika: dodatkov Kodija ne ponujamo vec (Safeer jih ne more poganjati).
            return dict(item, napaka_koda="ni_toka")
        stremio_url = next((u for u in posebni if u.startswith("stremio:")), "")
        if stremio_url:
            koren, tip, ident = (stremio_url[len("stremio:"):].split("|") + ["", ""])[:3]
            if pripravi_torrent and tip in ("movie", "series") and self.samo_usenet():
                # Lastnik 10. 11. 2026 (kot TV): z izbranim »⚡ Usenet« klik predvaja samo prek Useneta.
                return self._razresi_samo_usenet(item_id, item, tip, ident)
            tokovi = self._stremio_tokovi_vseh(koren, tip, ident)
            # Webtor rezerva (core/webtor.py): tokovi dodatka Webtor niso neposredne povezave - gredo v svoj korak.
            webtor_tokovi = [t for t in tokovi if t.get("webtor")]
            tokovi = [t for t in tokovi if not t.get("webtor")]
            if p2p:
                webtor_tokovi = []      # uporabnik je izrecno izbral roj (Webtor ni dal toka): ne caka znova 15 s
            # tok=True: neposreden tok dodatka (tudi brez koncnice) - predvajalnik ga sme tiho poskusiti kot razlicico.
            neposredni = [dict(t, tok=True) for t in tokovi if t.get("url") and not t.get("zunanje")
                          and (t["url"].startswith("https://") or media_servers.dovoljen_naslov(t["url"]))]
            # Najboljsi tok za to napravo na prvo mesto (film se zacne takoj, brez izbiranja); ostali ostanejo kot razlicice.
            # Steje tudi rok veljavnosti povezave: potekla (dodatek jo ponudi iz predpomnilnika) je zadnja, mrtva ne pride
            # na prvo mesto (_zivi_naprej) - uporabnik ne caka na vir, ki ne dela.
            neposredni = tok_izbira.uredi(neposredni, lambda t: str(t.get("opis") or "%s %s" % (t.get("vir", ""), t.get("kakovost", ""))),
                                          tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)),
                                          naslov=lambda t: str(t.get("url") or ""), **self._jezik_zvoka(item))
            neposredni = self._zivi_naprej(neposredni)
            drugi_http = [v for v in (item.get("razlicice") or []) if isinstance(v, dict)
                          and str(v.get("url") or "").startswith(("http://", "https://"))]
            # Naloga 131: z vpisanim kljucem debrid gre najboljsi PRIPRAVLJEN torrent pred neposrednimi povezavami
            # (zasebno, hitro, obicajno boljsa kakovost) - kot Safeer OS za Android (naloga 130), brez »Izberi vir«.
            torrenti = [t for t in tokovi if t.get("torrent") and t.get("hash")]
            aktivna = self.debrid.aktivna() if torrenti else None
            hashi: list = []
            if aktivna:
                jezik = self._jezik_zvoka(item) if hasattr(self, "_jezik_zvoka") else {}
                torrenti = tok_izbira.uredi(torrenti, lambda t: str(t.get("opis") or "%s %s" % (t.get("vir", ""), t.get("kakovost", ""))),
                                            tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)),
                                            naslov=lambda t: "", **jezik)
                hashi = [str(t["hash"]) for t in torrenti]
            # Vrstni red virov (lastnik 25. 10. 2026 07:25, skupno pravilo usenet_pravila.vrstni_red_virov): z vpisanim
            # indeksatorjem gre Usenet, ki ga ima TorBox pripravljenega, prvi (placan, najboljsa kakovost in hitrost);
            # preverba ⚡ tece hkrati z njim. Nato ⚡ torrent, povezave, Usenet s cakanjem, debrid s cakanjem.
            usenet = bool(pripravi_torrent) and self._usenet_mogoc(tip, ident)
            pred_f = debrid.v_ozadju(self.debrid.predpomnjeni, hashi) if usenet and aktivna and hashi else None
            # Webtor (lastnik 25. 10. 2026): kar nas debrid nima pripravljenega, zacne teci prek Webtorja (pred cakanjem
            # na debrid). Ista izdaja kot nasi torrenti najprej; `[⚡TB]` skrijemo, ce je nas debrid TorBox (podvaja ga).
            wt = [(tuple(t["webtor_kljuc"]) if t.get("webtor_kljuc") else None, t["webtor"]) for t in webtor_tokovi]
            nasi = [webtor.kljuc(t.get("hash"), t.get("indeks")) for t in torrenti]
            # Kaj bo /resolve predvajal (glavni video, najvecji, negotovo, ni video): ime toka ali nas tok z istim hashem.
            nasi_po_hashu = {str(t.get("hash") or "").lower(): t for t in tokovi if t.get("torrent") and t.get("hash")}
            datoteke = []
            for t, (k, _v) in zip(webtor_tokovi, wt):
                nas = nasi_po_hashu.get(k[0]) if k else None
                datoteke.append(webtor.datoteka(k[1] if k else webtor.IDX_NEZNAN, str(t.get("datoteka") or ""),
                                                (nas.get("indeks") if isinstance(nas.get("indeks"), int) else -1) if nas else None,
                                                str((nas or {}).get("ime") or "")))
            imamo_torbox = aktivna == debrid_pravila.TORBOX
            wt_stanje: dict = {"zacetek": None, "poskusov": 0, "poskuseni": set()}
            sk_stanje: dict = {"zacetek": None, "poskusov": 0}
            for korak in usenet_pravila.vrstni_red_virov(usenet, webtor=bool(webtor_tokovi)):
                if korak == usenet_pravila.KORAK_USENET_TAKOJ:
                    resolved = self._razresi_usenet_takoj(item_id, item, ident, neposredni)
                    if resolved:
                        return resolved
                elif korak == usenet_pravila.KORAK_PREDPOMNJEN and aktivna and pripravi_torrent:
                    try:
                        pred = pred_f.result(timeout=10) if pred_f is not None else self.debrid.predpomnjeni(hashi)
                    except Exception:  # noqa: BLE001 - brez preverbe ⚡ gre izbira naprej
                        pred = set()
                    k = debrid_pravila.samodejni_torrent(aktivna, hashi, pred)
                    if k >= 0:
                        resolved = self._razresi_debrid(item_id, item, torrenti[k], neposredni)
                        if resolved.get("url") and not resolved.get("napaka_koda"):
                            return resolved
                elif korak == usenet_pravila.KORAK_NEPOSREDNI:
                    if neposredni and pripravi_torrent:
                        neposredni = self._razresi_skrivne_tokove(neposredni, sk_stanje)
                    if neposredni:
                        if drugi_http and str(item.get("url") or "").startswith(("http://", "https://")):
                            # Kartica ima tudi druge (vdelane) vire: tokove dodatka dodamo kot dodatne razlicice.
                            razlicice = drugi_http + [t for t in neposredni[:10] if t["url"] not in {v.get("url") for v in drugi_http}]
                            resolved = dict(item, razlicice=razlicice, stevilo_razlicic=len(razlicice))
                        else:
                            resolved = dict(item, url=neposredni[0]["url"], razlicice=neposredni[:10], stevilo_razlicic=len(neposredni[:10]))
                        if neposredni[0].get("podnapisi") and not resolved.get("podnapisi"):
                            resolved["podnapisi"] = list(neposredni[0]["podnapisi"])
                        if neposredni[0].get("glave") and not resolved.get("glave"):
                            resolved["glave"] = dict(neposredni[0]["glave"])
                        if neposredni[0].get("preverjen") and resolved.get("url") == neposredni[0]["url"]:
                            resolved["preverjen"] = True        # koncni naslov sonde: predvajalnik brez preusmeritev
                        self._dynamic_items[item_id] = resolved
                        return resolved
                    if webtor_tokovi and pripravi_torrent:
                        # Takoj predvajljivo pri Webtorju (`[⚡WT]`, `[⚡TB]` brez nasega TorBoxa) - kot ziva povezava.
                        red = webtor.vrstni_red(nasi, wt, imamo_torbox, samo_takoj=True, datoteke=datoteke)
                        resolved = self._razresi_webtor(item_id, item, webtor_tokovi, red, wt_stanje)
                        if resolved:
                            return resolved
                    if drugi_http:
                        return dict(item, razlicice=drugi_http, stevilo_razlicic=len(drugi_http))
                elif korak == usenet_pravila.KORAK_USENET_CAKAJ:
                    # Pripravljen je bil preverjen v prvem koraku: tu TorBox izdajo prenese (prenos Usenet je hiter -
                    # izmerjeno na TV 2,2 GB v 36 s), najvec dva poskusa do 15 GB.
                    resolved = self._razresi_usenet(item_id, item, tip, ident, [], samo_takoj=False)
                    if resolved:
                        return resolved
                elif korak == usenet_pravila.KORAK_WEBTOR and webtor_tokovi:
                    if not pripravi_torrent:
                        return dict(item, torrent=True)
                    red = webtor.vrstni_red(nasi, wt, imamo_torbox, datoteke=datoteke)
                    resolved = self._razresi_webtor(item_id, item, webtor_tokovi, red, wt_stanje)
                    if resolved:
                        return resolved
                elif korak == usenet_pravila.KORAK_DEBRID_CAKAJ and torrenti and aktivna:
                    # Naloga 131: ni povezave in ni pripravljenega torrenta - prek debrida (s cakanjem samo, ce ga
                    # uporabnik dovoli). Ob napaki NIKOLI tiho na neposreden torrent (razkril bi IP racunalnika).
                    return self._razresi_debrid(item_id, item, torrenti[0], []) if pripravi_torrent else dict(item, torrent=True)
            if torrenti and os_torrent_tok.podprto():
                if not pripravi_torrent:
                    return dict(item, torrent=True)
                # P2P s tega racunalnika (naslov IP v roju) nikoli tiho (lastnik 25. 10. 2026, enako kot Android
                # opozoriPredRojem): pomocnik na Windows je izmeril, da je izbira po neuspehu Webtorja brez besede sla v
                # roj. Brez nove potrditve samo torrent, ki ga je uporabnik v tem zagonu za ta naslov ze potrdil; sicer
                # izbira na strani. Potrjen je samo torrent, ki je res sel v roj (ne vsi torrenti naslova).
                if p2p:
                    potrjeni = self._p2p_potrjeni()
                    return self._razresi_torrent(item, torrenti, ob_roju=lambda h: potrjeni.add((str(item_id), h)))
                dovoljeni = self._p2p_dovoljeni(str(item_id), torrenti)
                if dovoljeni:
                    return self._razresi_torrent(item, dovoljeni)
                return dict(item, napaka_koda="p2p_potrditev",
                            p2p={"webtor": bool(webtor_tokovi) or self._ima_webtor(), "debrid": bool(aktivna)})
            # Brez predvajljivega toka ni strani in ni seznama povezav: kratko obvestilo, vsebina izgine s seznama.
            # Za ure si to zapomnimo le, ce so odgovorili vsi dodatki (izpad dodatka ni "ni na voljo").
            if getattr(self._tokovi_odgovor, "vsi", False) and not webtor_tokovi:
                # Webtor je tok imel, a ni odgovoril v roku: to ni »ni na voljo« (naslednjic morda je).
                if tip == "series" and not media_servers.stremio_je_epizoda(ident):
                    # Serija: ena epizoda brez toka se ni "serije ni" - presodimo po vec epizodah (v ozadju).
                    self.preveri_razpolozljivost([item])
                else:
                    self.oznaci_ni_na_voljo(item)
            return dict(item, napaka_koda="ni_toka")
        if item.get("tunein_id"):
            try:
                resolved = self._zakoniti_viri.resolve_tunein(item)
            except Exception:
                resolved = None
            if not resolved:
                return dict(item, napaka="TuneIn za to postajo trenutno ne ponuja toka.")
            resolved = dict(resolved, id=item_id, razlicice=[{"url": resolved["url"], "vir": "TuneIn",
                                                             "kakovost": ""}], stevilo_razlicic=1)
            self._dynamic_items[item_id] = resolved
            return resolved
        if item.get("archive_id"):
            try:
                resolved = self._zakoniti_viri.resolve_archive(item)
            except Exception:
                resolved = None
            if not resolved:
                return dict(item, napaka="Internet Archive za ta film trenutno ne ponuja datoteke MP4.")
            resolved = dict(resolved, id=item_id, razlicice=[{"url": resolved["url"], "vir": resolved.get("vir", ""),
                                                             "kakovost": resolved.get("kakovost", "")}], stevilo_razlicic=1)
            self._dynamic_items[item_id] = resolved
            return resolved
        if item.get("peertube_uuid"):
            configured = [str(source.get("url") or "") for source in self.sources()]
            # Najprej glavna razlicica, nato ostale (zdruzena kartica ima vec
            # streznikov z istim videom) - prvi, ki odgovori, zmaga.
            kandidati = [item]
            for variant in item.get("razlicice") or []:
                match = re.search(r"https://([^/]+)/(?:videos/watch|w)/([0-9a-fA-F-]{8,})", str((variant or {}).get("url") or ""))
                if match and match.group(2) != item.get("peertube_uuid"):
                    kandidati.append(dict(item, streznik=match.group(1), peertube_uuid=match.group(2),
                                          url=variant.get("url"), vir=variant.get("vir") or item.get("vir")))
            for kandidat in kandidati:
                resolved = self._zakoniti_viri.resolve_video(kandidat, configured)
                if resolved:
                    # Predvajalnik bere razlicice, zato jih nadomesti s predvajalnim
                    # tokom - prvotne razlicice kazejo na spletne strani videov
                    # (/videos/watch/...), ki jih VLC ne more predvajati.
                    predvajalna = {"url": resolved["url"], "vir": resolved.get("vir") or kandidat.get("vir", ""),
                                   "kakovost": resolved.get("kakovost") or ("HLS" if str(resolved.get("mime", "")).endswith("mpegurl") else "")}
                    resolved = dict(resolved, id=item_id, razlicice=[predvajalna], stevilo_razlicic=1)
                    self._dynamic_items[item_id] = resolved
                    return resolved
            return None
        return self._izberi_najhitrejsi(self._dodaj_predvajalne_razlicice(item))

    def _dodaj_predvajalne_razlicice(self, item: dict) -> dict:
        """Sestavi razlicice samo iz virov, ki jih je dodal uporabnik.

        Katalog ostane brez podvojenih kartic. Pri predvajanju pa isti TMDb/IMDb
        naslov dobi po eno razlicico za vsak uporabnikov embed vir, zato lahko
        vmesnik ob nedosegljivem viru varno nadaljuje z naslednjim.
        """
        if item.get("vrsta") not in ("film", "serija"):
            return item
        existing = list(item.get("razlicice") or [])
        if len(existing) >= 2:
            return item
        tmdb_id = str(int(item.get("tmdb_id") or 0)) if item.get("tmdb_id") else ""
        imdb_id = str(item.get("imdb_id") or "")
        if not tmdb_id and not imdb_id:
            return item
        season, episode = int(item.get("sezona") or 0), int(item.get("epizoda") or 0)
        with self._lock:
            sources = list(self._load().get("viri", []))
        embed_sources = [
            (source, str(source.get("url") or ""), parsed, host)
            for source, parsed, host in self._embed_viri({"viri": sources})
        ]
        allowed_hosts = {host for _, _, _, host in embed_sources}
        current_variants = []
        for variant in existing:
            host = (urllib.parse.urlsplit(str(variant.get("url") or "")).hostname or "").casefold()
            is_embed = any(host == domain or host.endswith("." + domain) for domain in _EMBED_DOMAINS)
            if not is_embed or any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
                current_variants.append(variant)
        existing = current_variants

        # Uporabnikov vrstni red je stabilen, razen kadar so že znani pingi.
        # Katalogski URL ne sme dodati neizbranega ponudnika.
        item_host = (urllib.parse.urlsplit(str(item.get("url") or "")).hostname or "").casefold()
        item_is_embed = any(item_host == domain or item_host.endswith("." + domain)
                            for domain in _EMBED_DOMAINS)
        if (not existing and item.get("url")
                and (not item_is_embed or any(item_host == host or item_host.endswith("." + host)
                                              for host in allowed_hosts))):
            existing.insert(0, {k: item.get(k) for k in (
                "url", "vir", "vir_id", "kakovost", "locljivost", "glave", "referer"
            ) if item.get(k) not in (None, "")})

        for source, source_url, parsed, host in embed_sources:
            if item.get("vrsta") == "serija" and (season < 1 or episode < 1):
                continue
            if _PREDLOGA_TOKEN.search(source_url):
                play_url = _izpolni_predlogo(source_url, imdb_id, tmdb_id, season, episode)
            else:
                play_url = _embed_url_for_provider(host, parsed.scheme or "https", imdb_id, tmdb_id,
                                                   str(item.get("vrsta")), season, episode)
            if play_url:
                existing.append({
                    "url": play_url,
                    "vir": str(source.get("ime") or host),
                    "vir_id": str(source.get("id") or ""),
                    "kakovost": "1080p",
                    "locljivost": 1080,
                })

        variants, seen = [], set()
        for variant in existing:
            url = str(variant.get("url") or "")
            canonical = canonical_url(url) if url.startswith(("http://", "https://")) else url
            if not url or canonical in seen:
                continue
            seen.add(canonical)
            variants.append(dict(variant, url=url))
        out = dict(item)
        if variants:
            out["razlicice"] = variants
            out["stevilo_razlicic"] = len(variants)
        return out

    def _izmeri_ping(self, url: str) -> None:
        """V ozadju izmeri odziv gostitelja (core/meritve_virov.py: 3 vzorci, mediana, zapomnjeno); predvajanje ne caka."""
        try:
            self._meritve.izmeri(str(url))
        except (OSError, ValueError):
            return

    def _izberi_najhitrejsi(self, item: dict) -> dict:
        variants = item.get("razlicice") or []
        if len(variants) < 2:
            return item
        # Skupno pravilo (meritve_virov.razvrsti): lastni strežnik, nato dosegljivi po zapomnjenem odzivu, neizmerjeni,
        # nedosegljivi; znotraj enakih kakovost. Neizmerjene in zastarele izmerimo v ozadju za naslednjic.
        urejene = meritve_virov.razvrsti([dict(v) for v in variants], self._meritve)
        # Razlicica, ki na sondo pred kratkim ni odgovorila (tudi lastni strežnik), gre na konec: ostane le kot rezerva.
        sonde, zdaj = getattr(self, "_sonde", {}), time.time()

        def mrtva(v: dict) -> bool:
            z = sonde.get(str(v.get("url") or ""))
            return bool(z) and not z[1] and zdaj - z[0] < self.SONDA_VELJA
        urejene = [v for v in urejene if not mrtva(v)] + [v for v in urejene if mrtva(v)]
        zastarele = [str(v.get("url") or "") for v in variants if self._meritve.zastarelo(str(v.get("url") or ""))]
        if zastarele:
            self._meritve.izmeri_v_ozadju(zastarele)
        best = urejene[0]
        ping = self._meritve.ms(str(best.get("url") or ""))
        out = dict(item)
        out["razlicice"] = urejene
        out["url"] = best.get("url", out.get("url"))
        out["izbran_ping_ms"] = ping
        out["izbran_vir"] = best.get("vir", out.get("vir", ""))
        return out


_bazen = None
_bazen_lock = threading.Lock()


def _bazen_virov():
    """Skupen bazen niti za vire kataloga (dodatki, strezniki, javni viri, TMDB). Nit, ki caka na pocasen vir, ne
    zadrzi iskanja; omejitev 16 hkratnih zahtev varuje omrezje in streznike."""
    global _bazen
    with _bazen_lock:
        if _bazen is None:
            from concurrent.futures import ThreadPoolExecutor
            _bazen = ThreadPoolExecutor(max_workers=16, thread_name_prefix="media-vir")
        return _bazen


_default_center: Optional[MediaCenter] = None


def _default() -> MediaCenter:
    global _default_center
    if _default_center is None:
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        _default_center = MediaCenter(os.path.join(config, "safeer-os"))
    return _default_center


def katalog() -> dict:
    """Združljivost z obstoječim Linux mostom."""
    return _default().catalog()


def odpri(pot: str) -> bool:
    """Odpri lokalno datoteko v sistemskem predvajalniku (Linux združljivost)."""
    path = Path(str(pot)).expanduser()
    if not path.is_file() or path.suffix.lower() not in MEDIA_EXT:
        return False
    try:
        from core import varuh_procesov, zasebni_webkit      # sistemski predvajalnik brez nasih zasebnih poti v okolju
        for ukaz in (["gio", "open", str(path)], ["xdg-open", str(path)]):
            if shutil.which(ukaz[0]) is None:
                continue
            try:
                pid = varuh_procesov.zazeni_program(ukaz, zasebni_webkit.okolje_za_zunanje())
                if pid:
                    return True
            except Exception:
                pass
        if zasebni_webkit.odpri_privzeto(str(path)):      # v procesu (Gio), xdg-open je rezerva
            return True
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=zasebni_webkit.okolje_za_zunanje())
        return True
    except OSError:
        return False


def _playerctl(*args: str) -> str:
    try:
        # Svojega predvajalnika (core/os_mpris.py) tu ne beremo: to je pogled na DRUGE predvajalnike v sistemu.
        result = subprocess.run(["playerctl", "--ignore-player=safeer", *args], capture_output=True, text=True,
                                timeout=1.5, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def stanje() -> dict:
    status = _playerctl("status")
    if not status:
        return {"na_voljo": False}
    row = _playerctl("metadata", "--format",
                     "{{title}}\t{{artist}}\t{{position}}\t{{mpris:length}}\t{{xesam:url}}").split("\t")
    row += [""] * (5 - len(row))

    def _number(value: str) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    length = _number(row[3])
    return {"na_voljo": True, "predvaja": status.lower() == "playing",
            "naslov": row[0][:200], "izvajalec": row[1][:200],
            "polozaj": _number(row[2]), "trajanje": length / 1_000_000 if length else 0,
            "url": row[4][:2048] if row[4].startswith(("http://", "https://")) else ""}


def ukaz(ime: str) -> bool:
    command = {"predvajaj_pavza": "play-pause", "naprej": "next",
               "nazaj": "previous", "ustavi": "stop"}.get(str(ime))
    if not command:
        return False
    try:
        return subprocess.run(["playerctl", "--ignore-player=safeer", command], timeout=1.5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
