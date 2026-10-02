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
import json
import math
import mimetypes
import os
import re
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date as _date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional

from . import zakoniti_viri
from . import media_servers
from . import tok_izbira
from . import watch_providers

AUDIO = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma"}
VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpeg", ".mpg", ".ts", ".m3u8"}
IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MEDIA_EXT = AUDIO | VIDEO | IMAGES
MAX_FILES = 500
MAX_SOURCE_ITEMS = 1500
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
    if any(x in hint for x in ("series", "episode", "season", "show", "tv", "serija", "epizoda", "/tv/", "/series/")):
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
    if "youtube.com" in netloc or netloc == "youtu.be":
        video_id = ""
        if netloc == "youtu.be":
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
        if "music.youtube.com" in netloc:
            item = _item("YouTube Music · brskanje", url, base=url,
                         source_id=source_id, source_name=source_name or "YouTube Music",
                         kind="glasba", description="Izberi glasbo v vgrajeni aplikaciji Safeer Media.")
            return [item] if item else []
    # Splošen neposredni tok ali vdelana stran
    kind = _kind("", url, source_name)
    title = source_name if source_name and source_name != parsed.netloc else (parsed.netloc or "Vdelana vsebina")
    it = _item(title, url, base=url, source_id=source_id, source_name=source_name, kind=kind)
    return [it] if it else []


def _parse_m3u(text: str, base: str, source_id: str, source_name: str) -> list[dict]:
    # HLS manifest je en prilagodljiv tok, ne katalog segmentov. LibVLC sam izbere
    # najboljšo različico glede na povezavo in zmogljivost naprave.
    if "#EXT-X-TARGETDURATION" in text or "#EXT-X-STREAM-INF" in text:
        found = _item(source_name, base, base=base, source_id=source_id,
                      source_name=source_name, kind=_kind("", base, source_name), quality="adaptive")
        return [found] if found else []
    out, pending = [], {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            attrs, _, title = line.partition(",")
            pending = {"title": title.strip() or source_name}
            for key, value in re.findall(r'([\w-]+)="([^"]*)"', attrs):
                pending[key.lower()] = value
        elif line and not line.startswith("#"):
            title = pending.get("title") or Path(urllib.parse.urlsplit(line).path).stem or source_name
            found = _item(title, line, base=base, source_id=source_id, source_name=source_name,
                          kind=pending.get("group-title", ""), image=pending.get("tvg-logo", ""),
                          quality=pending.get("quality", ""))
            if found:
                out.append(found)
            pending = {}
        if len(out) >= MAX_SOURCE_ITEMS:
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
                  source_id: str = "vir", source_name: str = "Vir") -> list[dict]:
    """Razbere medijske vnose iz enega prenesenega odgovora brez izvajanja tuje kode."""
    text = payload.decode("utf-8", "replace")
    content = (content_type or "").lower()
    stripped = text.lstrip()
    if "scpls" in content or "playlist" in content and stripped.lower().startswith("[playlist]") or source_url.lower().endswith(".pls"):
        return _parse_pls(text, source_url, source_id, source_name)
    if "mpegurl" in content or source_url.lower().endswith((".m3u", ".m3u8")) or stripped.startswith("#EXTM3U"):
        return _parse_m3u(text, source_url, source_id, source_name)
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


def _identity(item: dict, include_year: bool = True) -> str:
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
        for token in filter(None, (
            f"{scope}|imdb:{imdb}" if imdb else "",
            f"{scope}|tmdb:{tmdb}" if tmdb else "",
        )):
            if token in id_owner:
                union(index, id_owner[token])
            else:
                id_owner[token] = index
        title_groups.setdefault(_identity(item, include_year=False), []).append(index)

    # Naslov je rezervna identiteta za vire brez ID-ja. Različnih predelav z
    # različnimi znanimi letnicami ne združimo; neznan letnik povežemo samo,
    # kadar obstaja natanko en možen znani letnik.
    for indices in title_groups.values():
        by_year: dict[int, list[int]] = {}
        for index in indices:
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
        variants.sort(key=_score, reverse=True)
        best = dict(variants[0])
        metadata = max(variants, key=_metadata_score)
        if _metadata_score(metadata) > _metadata_score(best):
            best["naslov"] = metadata.get("naslov") or best.get("naslov")
        for field in ("imdb_id", "tmdb_id", "leto", "slika", "opis", "izvajalec"):
            if not best.get(field):
                best[field] = next((item.get(field) for item in variants if item.get(field)), best.get(field))

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
        best["razlicice"] = [{k: value for k, value in item.items()
                              if k in ("url", "vir", "vir_id", "kakovost", "locljivost", "bitrate",
                                       "glave", "referer", "imdb_id", "tmdb_id")}
                             for item in variants]
        best["stevilo_razlicic"] = len(variants)
        best["viri"] = list(dict.fromkeys(item.get("vir", "") for item in variants if item.get("vir")))
        result.append(best)
    return sorted(result, key=lambda item: (item.get("vrsta", ""), item.get("naslov", "").casefold()))


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


class MediaCenter:
    """Trajen katalog virov z atomskim zapisom in enotno logiko za vse platforme."""

    def __init__(self, config_dir: str, roots: Optional[Iterable[str | Path]] = None,
                 secret_encryptor=None, secret_decryptor=None):
        self.config_dir = Path(config_dir)
        self.store_path = self.config_dir / "media.json"
        self.roots = [Path(path) for path in roots] if roots is not None else self._default_roots()
        self._lock = threading.RLock()
        self._tmdb_cache: dict[str, tuple[float, dict]] = {}
        self._dynamic_items: dict[str, dict] = {}
        self._ping_cache: dict[str, tuple[float, float]] = {}
        self._ping_lock = threading.Lock()
        self._zakoniti_viri = zakoniti_viri.ZakonitiViri()
        self._secret_encryptor = secret_encryptor or _dpapi_protect
        self._secret_decryptor = secret_decryptor or _dpapi_unprotect
        self._server_cache: dict[str, tuple[float, list[dict]]] = {}
        # Trajni predpomnilnik kataloga in podatkov TMDB: ob odprtju se prikaze takoj,
        # sveze podatke dobimo v ozadju (uporabnik ne caka na prazen zaslon).
        self._predpomnilnik: Optional[dict] = None
        self._predpomnilnik_lock = threading.RLock()
        self._predpomnilnik_casovnik: Optional[threading.Timer] = None
        self._osvezujem: set[str] = set()

    # --- trajni predpomnilnik -------------------------------------------------
    PREDPOMNILNIK_KATALOG = 80        # najvec shranjenih pogledov (vrsta/zvrst/stran/iskanje)
    PREDPOMNILNIK_TMDB = 400          # najvec shranjenih odgovorov TMDB (podrobnosti, ponudniki)
    SVEZE_SEKUND = 10 * 60            # mlajsega pogleda ne osvezujemo v ozadju

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
            besedilo = json.dumps(shramba, ensure_ascii=False, separators=(",", ":"))
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            zacasna = self.pot_predpomnilnika.with_suffix(".tmp")
            zacasna.write_text(besedilo, encoding="utf-8")
            os.replace(zacasna, self.pot_predpomnilnika)
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
                       izklopljeni_jeziki: Iterable[str] = ()) -> str:
        # Prvi element je razlicica oblike pogleda: ob spremembi vrstnega reda stari pogledi ne veljajo.
        return json.dumps(["v5", _text(query, 120).casefold(), kind or "vse", _text(genre, 20),
                           max(1, int(page or 1)), self.izbrana_drzava or "auto", razvrsti or "",
                           sorted({str(x) for x in (izklopljeni or []) if x}), bool(samo_lokalno),
                           sorted({str(x) for x in (izklopljeni_jeziki or []) if x})], ensure_ascii=False)

    def _zapomni_katalog(self, kljuc: str, rezultat: dict) -> None:
        shranjeno = {k: v for k, v in rezultat.items() if k not in ("viri", "mape", "kljuc", "iz_predpomnilnika", "osvezujem")}
        zdaj = time.time()
        with self._predpomnilnik_lock:
            self._nalozi_predpomnilnik()["katalog"][kljuc] = {"cas": zdaj, "uporabljeno": zdaj, "rezultat": shranjeno}
        self._shrani_predpomnilnik()

    def catalog_hitro(self, query: str = "", kind: str = "vse", genre: str = "", page: int = 1,
                      ob_osvezitvi=None, razvrsti: str = "", izklopljeni: Iterable[str] = (),
                      samo_lokalno: bool = False, izklopljeni_jeziki: Iterable[str] = ()) -> dict:
        """Katalog najprej iz predpomnilnika (takoj), nato sveze v ozadju.

        ob_osvezitvi(kljuc, rezultat) se poklice samo, ce se je vsebina v ozadju res spremenila.
        Ce pogleda se ni v predpomnilniku, ga nalozimo normalno in shranimo za naslednjic.
        """
        izklopljeni = sorted({str(x) for x in (izklopljeni or []) if x})
        moznosti = {"razvrsti": razvrsti or "", "izklopljeni": izklopljeni, "samo_lokalno": bool(samo_lokalno),
                    "izklopljeni_jeziki": sorted({str(x) for x in (izklopljeni_jeziki or []) if x})}
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
            return rezultat
        rezultat = self.catalog(query, kind, genre, page, **moznosti)
        if rezultat.get("vnosi"):
            self._zapomni_katalog(kljuc, rezultat)
        return dict(rezultat, kljuc=kljuc, iz_predpomnilnika=False, osvezujem=False)

    @staticmethod
    def _odtis_vnosov(rezultat: Optional[dict]) -> str:
        vnosi = (rezultat or {}).get("vnosi") or []
        return hashlib.sha1(json.dumps(vnosi, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

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
                svez = self.catalog(query, kind, genre, page, **(moznosti or {}))
                with self._predpomnilnik_lock:
                    star = (self._nalozi_predpomnilnik()["katalog"].get(kljuc) or {}).get("rezultat")
                if not svez.get("vnosi"):
                    return  # brez omrezja ali napaka vira: raje ohranimo zadnji dober pogled
                spremenjeno = self._odtis_vnosov(svez) != self._odtis_vnosov(star)
                self._zapomni_katalog(kljuc, svez)
                if spremenjeno and ob_osvezitvi is not None:
                    ob_osvezitvi(kljuc, dict(svez, kljuc=kljuc, iz_predpomnilnika=False, osvezujem=False))
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
            for zapis in self._nalozi_predpomnilnik()["katalog"].values():
                rezultat = zapis.get("rezultat") if isinstance(zapis, dict) else None
                if isinstance(rezultat, dict):
                    kandidati.extend(x for x in (rezultat.get("vnosi") or []) if isinstance(x, dict))
        # Uporabnikovi uvoženi viri so že na disku in zato prav tako ne povzročijo omrežnega klica.
        with self._lock:
            for vir in self._load().get("viri", []):
                kandidati.extend(x for x in (vir.get("vnosi") or []) if isinstance(x, dict))

        zadetki, videni = [], set()
        for item in kandidati:
            haystack = " ".join(str(item.get(k) or "") for k in ("naslov", "izvajalec", "album", "opis", "vrsta")).casefold()
            if iskano not in haystack:
                continue
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

    def _save(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.store_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.store_path)
        # Viri so se spremenili: shranjeni pogledi se ob naslednjem odprtju osvezijo v ozadju.
        if self._predpomnilnik is not None:
            self.ozastari_predpomnilnik()

    def sources(self) -> list[dict]:
        with self._lock:
            data = self._load()
            regular = [{k: value for k, value in source.items() if k != "vnosi"}
                       for source in data.get("viri", []) if isinstance(source, dict)]
            personal = [{k: value for k, value in source.items() if k not in ("secret_enc", "uporabnik")}
                        for source in data.get("osebni_strezniki", []) if isinstance(source, dict)]
            return regular + personal

    def vidni_viri(self) -> list[dict]:
        """Viri za prikaz v medijskem centru: brez tistih, iz katerih ni nic predvajljivega."""
        return [vir for vir in self.sources()
                if vir.get("vrsta") == "streznik" or int(vir.get("stevilo") or 0) > 0
                or (vir.get("tip") == "predvajalni_vir" and not vir.get("napaka"))]

    def add_server(self, provider: str, name: str, url: str, username: str, secret: str) -> dict:
        provider = _text(provider, 20).lower()
        url = _text(url, 1024)
        if url.startswith("stremio://"):
            url = "https://" + url[len("stremio://"):]
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
        source_id = "streznik-" + hashlib.sha256((provider + base + username).encode()).hexdigest()[:16]
        source = {"id": source_id, "vrsta": "streznik", "ponudnik": provider,
                  "ime": _text(name, 80) or urllib.parse.urlsplit(base).hostname,
                  "url": base, "uporabnik": username, "user_id": auth.get("user_id", ""),
                  "secret_enc": encrypted}
        with self._lock:
            data = self._load()
            sources = data.setdefault("osebni_strezniki", [])
            if any(item.get("id") == source_id for item in sources):
                return {"ok": False, "napaka": "Ta strežnik je že dodan."}
            sources.append(source)
            self._save(data)
        return {"ok": True, "vir": {k: v for k, v in source.items() if k not in ("secret_enc", "uporabnik")}}

    def _stremio_strezniki(self) -> list[dict]:
        """Uporabnikovi Stremio dodatki (osebni strezniki s ponudnikom stremio)."""
        with self._lock:
            return [x for x in self._load().get("osebni_strezniki", []) if isinstance(x, dict) and x.get("ponudnik") == "stremio" and x.get("url")]

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
            moji = any(x.get("ponudnik") in ("tvheadend", "dlna", "kodi")
                       for x in self._load().get("osebni_strezniki", []))
        return zakoniti_viri.tv_drzave(self._drzava_uporabnika(), moji)

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

    def _personal_items(self, query: str) -> list[dict]:
        with self._lock:
            servers = list(self._load().get("osebni_strezniki", []))
        result = []
        now = time.time()
        for server in servers:
            provider = str(server.get("ponudnik") or "")
            server_id = str(server.get("id") or "")
            server_query = query if provider in ("navidrome", "funkwhale") else ""
            key = server_id + ":" + server_query.casefold()
            cached = self._server_cache.get(key)
            if cached and now - cached[0] < 300:
                rows = cached[1]
                if query and provider not in ("navidrome", "funkwhale"):
                    needle = query.casefold()
                    rows = [item for item in rows if needle in " ".join((item.get("naslov", ""), item.get("izvajalec", ""),
                                                                            item.get("album", ""), item.get("opis", ""))).casefold()]
                result.extend(rows); continue
            try:
                secret = self._secret_decryptor(str(server.get("secret_enc") or ""))
                rows = media_servers.catalog(provider, str(server.get("url") or ""), server, secret, server_query)
                self._server_cache[key] = (now, rows)
            except Exception:
                rows = cached[1] if cached else []
            if query and provider not in ("navidrome", "funkwhale"):
                needle = query.casefold()
                rows = [item for item in rows if needle in " ".join((item.get("naslov", ""), item.get("izvajalec", ""),
                                                                        item.get("album", ""), item.get("opis", ""))).casefold()]
            result.extend(rows)
        return result

    def add_source(self, url: str, name: str = "") -> dict:
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
            data.setdefault("viri", []).append(source)
            self._save(data)
        # Odziv vira začnemo meriti takoj ob dodajanju, da je meritev navadno
        # že na voljo, ko uporabnik prvič izbere film ali epizodo.
        threading.Thread(target=self._izmeri_ping, args=(canonical,), daemon=True).start()
        rezultat = self.refresh_source(source["id"])
        vir = rezultat.get("vir") or {}
        # Vir predvajalnika (TMDB katalog + vdelani predvajalnik) nima lastnih vnosov, a je predvajljiv.
        if rezultat.get("ok") and (int(vir.get("stevilo") or 0) > 0 or source.get("tip") == "predvajalni_vir"
                                   or vir.get("tip") in ("predvajalni_vir", "uradni_vdelani_predvajalnik")):
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

    def remove_source(self, source_id: str) -> bool:
        with self._lock:
            data = self._load()
            servers_before = len(data.get("osebni_strezniki", []))
            data["osebni_strezniki"] = [server for server in data.get("osebni_strezniki", [])
                                        if server.get("id") != source_id]
            if len(data["osebni_strezniki"]) != servers_before:
                self._server_cache = {key: value for key, value in self._server_cache.items()
                                      if not key.startswith(source_id + ":")}
                self._save(data)
                self.ozastari_predpomnilnik(izbrisi=True)  # odstranjen vir ne sme vec kazati svojih vnosov
                return True
            before = len(data.get("viri", []))
            data["viri"] = [source for source in data.get("viri", []) if source.get("id") != source_id]
            if len(data["viri"]) == before:
                return False
            self._save(data)
            self.ozastari_predpomnilnik(izbrisi=True)
            return True

    def _download(self, url: str) -> tuple[bytes, str, str]:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, application/rss+xml, application/xml, audio/x-mpegurl, text/html;q=0.9, */*;q=0.5",
            "Accept-Language": "sl,en-US;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_DOWNLOAD:
                raise ValueError("Vir je prevelik.")
            payload = response.read(MAX_DOWNLOAD + 1)
            if len(payload) > MAX_DOWNLOAD:
                raise ValueError("Vir je prevelik.")
            final_url = canonical_url(response.geturl())
            return payload, response.headers.get_content_type(), final_url

    def refresh_source(self, source_id: str) -> dict:
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
            else:
                payload, content_type, final_url = self._download(source["url"])
                items = parse_payload(payload, content_type, final_url, source["id"], source["ime"])
                if not items:
                    items = _resolve_embed_or_direct_source(final_url, source["id"], source["ime"])
            source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": ""})
            ok, error = True, ""
        except Exception as exc:
            host = (urllib.parse.urlsplit(source["url"]).hostname or "").casefold()
            restricted = host == "bandcamp.com" or host.endswith(".bandcamp.com")
            items = [] if restricted else _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
            if items:
                source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": ""})
                ok, error = True, ""
            else:
                error = _text(exc, 180) or "Vira ni bilo mogoče prebrati."
                source["napaka"] = error
                ok = False
        with self._lock:
            data = self._load()
            saved = next((item for item in data.get("viri", []) if item.get("id") == source_id), None)
            if saved is None:
                return {"ok": False, "napaka": "ni_vira"}
            saved.update(source)
            self._save(data)
        public = {k: value for k, value in source.items() if k != "vnosi"}
        return {"ok": ok, "napaka": error, "vir": public}

    def refresh_all(self) -> dict:
        ids = [source.get("id", "") for source in self.sources()]
        results = [self.refresh_source(source_id) for source_id in ids]
        return {"ok": all(item.get("ok") for item in results), "rezultati": results}

    def refresh_stale(self, max_age: int = 6 * 60 * 60) -> dict:
        """V ozadju osveži le vire, katerih uspešni podatki so že zastareli."""
        cutoff = int(time.time()) - max(60, int(max_age))
        ids = [source.get("id", "") for source in self.sources()
               if int(source.get("posodobljeno") or 0) < cutoff
               or (_je_predvajalni_vir(str(source.get("url") or ""))
                   and source.get("tip") != "predvajalni_vir")]
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
        disk_kljuc = hashlib.sha1(url.encode("utf-8")).hexdigest()
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
    def _tmdb_razvrstitev(razvrsti: str, media_type: str) -> dict:
        datum = "first_air_date" if media_type == "tv" else "primary_release_date"
        ime = "name" if media_type == "tv" else "title"
        # Prag glasov: brez njega bi na vrhu stali neznani ali se neizdani naslovi.
        return {
            "novo": {"sort_by": datum + ".desc", datum + ".lte": _date.today().isoformat(), "vote_count.gte": 50},
            "staro": {"sort_by": datum + ".asc", "vote_count.gte": 200},
            "az": {"sort_by": ime + ".asc", "vote_count.gte": 300},
            "za": {"sort_by": ime + ".desc", "vote_count.gte": 300},
        }.get(razvrsti, {})

    def _tmdb_catalog(self, data: dict, query: str, kind: str, genre: str, page: int,
                      razvrsti: str = "") -> tuple[list[dict], int]:
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

    def catalog(self, query: str = "", kind: str = "vse", genre: str = "", page: int = 1,
                razvrsti: str = "", izklopljeni: Iterable[str] = (), samo_lokalno: bool = False,
                izklopljeni_jeziki: Iterable[str] = ()) -> dict:
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
        with self._lock:
            data = self._load()
        page_num = max(1, int(page or 1))
        local = [item for item in self._local_items() if (kind in ("", "vse") or item.get("vrsta") == kind)] if page_num == 1 else []
        remote = [_series_catalog_card(item) for source in data.get("viri", []) for item in source.get("vnosi", [])
                  if isinstance(item, dict) and (kind in ("", "vse") or item.get("vrsta") == kind)] if page_num == 1 else []
        glasbena = kind in ("glasba", "radio") and _text(genre, 20) in zakoniti_viri.GLASBENE_ZVRSTI
        embed_ids = {str(provider.get("id") or host) for provider, _parsed, host in self._embed_viri(data)}
        tmdb_izklopljen = bool(embed_ids) and embed_ids <= izklopljeni
        dynamic, tmdb_pages = ([], 1) if (glasbena or tmdb_izklopljen) else (
            self._tmdb_catalog(data, _text(query, 120), kind, _text(genre, 20), page_num, razvrsti)
            if self._ima_embed_vir(data) else ([], 1))
        # Javni katalogi imajo svoj 30-minutni cache in se napake posameznega API-ja
        # ne smejo prenesti v glavni katalog.
        configured_hosts = [str(source.get("url") or "") for source in data.get("viri", [])
                            if isinstance(source, dict) and source.get("url")]
        lawful = (self._zakoniti_viri.get(_text(query, 120), configured_hosts, _text(genre, 20)) if glasbena
                  else self._zakoniti_viri.get(_text(query, 120), configured_hosts))
        if glasbena:
            # Pri zvrsti pokazemo samo zadetke te zvrsti, ne tudi krajevnih datotek in osebnih virov.
            local, remote = [], []
        if kind == "tv-v-zivo":
            lawful = lawful + zakoniti_viri.tv_v_zivo(self._drzava_uporabnika())
            izbrana = _text(genre, 20)
            if izbrana == "moji":
                lawful, dynamic, remote = [], [], []
            elif izbrana:
                # TV v zivo po drzavah (kot zanri pri filmih); osebni kanali so pod "Moji kanali".
                lawful = [item for item in lawful if str(item.get("drzava") or "").upper() == izbrana.upper()]
                dynamic, remote, local = [], [], []
        if kind not in ("", "vse"):
            lawful = [item for item in lawful if item.get("vrsta") == kind]
        personal = self._personal_items(_text(query, 120))
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
        merged = self._filtriraj_vire(merge_duplicates(local + remote + dynamic + lawful + personal), izklopljeni)
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
                return any(difflib.SequenceMatcher(None, needle, token).ratio() >= 0.72
                           for token in re.findall(r"[\wÀ-ž]{3,}", hay))
            merged = [item for item in merged if zadetek(item)]
        merged = self._filtriraj_jezike(merged, izklopljeni_jeziki)
        merged = self._razvrsti_vnose(merged, razvrsti)
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

    def details(self, item_id: str, country: str = "auto", language: str = "sl") -> dict:
        item = self.resolve(item_id)
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
        return dict(item, opis=raw.get("overview") or item.get("opis", ""),
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

    def resolve(self, item_id: str) -> Optional[dict]:
        item = self._dynamic_items.get(item_id) or next((item for item in self.catalog()["vnosi"] if item.get("id") == item_id), None)
        if not item:
            return None
        # Posebni naslovi (Kodi dodatek, Stremio dodatek) so lahko tudi med razlicicami zdruzene kartice.
        posebni = [str(item.get("url") or "")] + [str(v.get("url") or "") for v in (item.get("razlicice") or []) if isinstance(v, dict)]
        kodi_url = next((u for u in posebni if u.startswith("kodi-dodatek:")), "")
        if kodi_url:
            server_id, _, dodatek = kodi_url[len("kodi-dodatek:"):].partition("|")
            kodi = self._kodi_streznik(server_id)
            if not kodi:
                return dict(item, napaka="Kodi ni več povezan.")
            try:
                media_servers.kodi_odpri_dodatek(kodi[0]["url"], kodi[0].get("uporabnik", ""), kodi[1],
                                                 dodatek, item.get("vrsta") == "glasba")
            except Exception:
                return dict(item, napaka="Kodi dodatka ni bilo mogoče odpreti.")
            return dict(item, sporocilo="%s se odpira na napravi s Kodijem (%s)." % (item.get("naslov"), kodi[0].get("ime")))
        stremio_url = next((u for u in posebni if u.startswith("stremio:")), "")
        if stremio_url:
            koren, tip, ident = (stremio_url[len("stremio:"):].split("|") + ["", ""])[:3]
            try:
                tokovi = media_servers.stremio_tokovi(koren, tip, ident)
            except Exception:
                tokovi = []
            neposredni = [t for t in tokovi if t.get("url") and not t.get("zunanje")
                          and (t["url"].startswith("https://") or media_servers.dovoljen_naslov(t["url"]))]
            # Najboljsi tok za to napravo na prvo mesto (film se zacne takoj, brez izbiranja); ostali ostanejo kot razlicice.
            neposredni = tok_izbira.uredi(neposredni, lambda t: str(t.get("opis") or "%s %s" % (t.get("vir", ""), t.get("kakovost", ""))),
                                          tok_izbira.Zmoznosti(visina=int(getattr(self, "visina_zaslona", 0) or 1080)))
            drugi_http = [v for v in (item.get("razlicice") or []) if isinstance(v, dict)
                          and str(v.get("url") or "").startswith(("http://", "https://"))]
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
                self._dynamic_items[item_id] = resolved
                return resolved
            if drugi_http:
                return dict(item, razlicice=drugi_http, stevilo_razlicic=len(drugi_http))
            zunanji = [t for t in tokovi if t.get("zunanje")]
            if zunanji:
                return dict(item, url=zunanji[0]["url"], stran=zunanji[0]["url"])
            if any(t.get("torrent") for t in tokovi):
                return dict(item, napaka="Ta dodatek ponuja samo torrent povezave; Safeer predvaja neposredne tokove.")
            return dict(item, napaka="Dodatek za to vsebino ni vrnil predvajalne povezave.")
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
        """V ozadju izmeri TCP odziv gostitelja; predvajanje na to ne čaka."""
        try:
            parsed = urllib.parse.urlsplit(str(url))
            host = parsed.hostname
            if not host or parsed.scheme not in ("http", "https"):
                return
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            zacetek = time.perf_counter()
            with socket.create_connection((host, port), timeout=0.8):
                pass
            meritev = round((time.perf_counter() - zacetek) * 1000, 1)
            with self._ping_lock:
                self._ping_cache[f"{host}:{port}"] = (time.time(), meritev)
        except (OSError, ValueError):
            return

    def _izberi_najhitrejsi(self, item: dict) -> dict:
        variants = item.get("razlicice") or []
        if len(variants) < 2:
            return item
        zdaj = time.time()
        scored = []
        for variant in variants:
            url = str(variant.get("url") or "")
            parsed = urllib.parse.urlsplit(url)
            key = f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}" if parsed.hostname else ""
            with self._ping_lock:
                cached = self._ping_cache.get(key)
            ping = cached[1] if cached and zdaj - cached[0] < 300 else 9999.0
            quality = int(variant.get("locljivost") or 0)
            # Ne čakamo na meritve: kakovost je začetni kriterij, svež ping pa
            # ima prednost, ko je že na voljo.
            scored.append((0 if ping < 9999 else 1, ping, -quality, variant))
            if ping >= 9999 and url:
                threading.Thread(target=self._izmeri_ping, args=(url,), daemon=True).start()
        scored.sort(key=lambda row: row[:3])
        best = scored[0][3]
        out = dict(item)
        out["razlicice"] = [row[3] for row in scored]
        out["url"] = best.get("url", out.get("url"))
        out["izbran_ping_ms"] = None if scored[0][1] >= 9999 else scored[0][1]
        out["izbran_vir"] = best.get("vir", out.get("vir", ""))
        return out


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
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def _playerctl(*args: str) -> str:
    try:
        result = subprocess.run(["playerctl", *args], capture_output=True, text=True,
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
        return subprocess.run(["playerctl", command], timeout=1.5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
