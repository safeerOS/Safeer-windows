"""Enotni lokalni katalog in predvajalno jedro za Safeer Media.

Vir je lahko javni JSON API, RSS/Atom, M3U ali spletna stran/spletna aplikacija,
ki objavi medije v HTML, OpenGraph, JSON-LD ali vdelanem JSON-u. Viri in njihov
zadnji uspešni katalog ostanejo lokalno shranjeni. Elementi iz vseh virov se
normalizirajo, podvojeni naslovi združijo, za predvajanje pa se izbere najboljša
razpoložljiva različica.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Optional

AUDIO = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma"}
VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpeg", ".mpg", ".ts", ".m3u8"}
MEDIA_EXT = AUDIO | VIDEO
MAX_FILES = 500
MAX_SOURCE_ITEMS = 1500
MAX_DOWNLOAD = 6 * 1024 * 1024
TRACKING_QUERY = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


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


def _absolute(base: str, value: Any) -> str:
    raw = _text(value, 4096)
    if not raw:
        return ""
    url = urllib.parse.urljoin(base, raw)
    return url if urllib.parse.urlsplit(url).scheme in ("http", "https", "file") else ""


def _kind(value: Any, url: str = "", title: str = "", season: int = 0, episode: int = 0) -> str:
    if season > 0 or episode > 0:
        return "serija"
    hint = f"{value or ''} {url} {title}".lower()
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if ext in AUDIO or any(x in hint for x in ("audio", "music", "song", "track", "album", "glasba", "/music/")):
        return "glasba"
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


KNOWN_IMDB = {
    "tt1375666": {
        "title": "Inception (Izvor)",
        "kind": "film",
        "year": 2010,
        "image": "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_SX300.jpg",
        "description": "Tat, ki krade skrivnosti skozi tehnologijo deljenja sanj, dobi obratno nalogo: vsaditev ideje.",
    },
    "tt0816692": {
        "title": "Interstellar (Medzvezdno)",
        "kind": "film",
        "year": 2014,
        "image": "https://m.media-amazon.com/images/M/MV5BZjdkOTU3MDktN2IxOS00OGEyLWFmMjktY2FiMmZkNWIyODZiXkEyXkFqcGdeQXVyMTMxODk2OTU@._V1_SX300.jpg",
        "description": "Skupina raziskovalcev potuje skozi črvino v vesolju v poskusu zagotovitve preživetja človeštva.",
    },
    "tt0468569": {
        "title": "The Dark Knight (Vitez teme)",
        "kind": "film",
        "year": 2008,
        "image": "https://m.media-amazon.com/images/M/MV5BMTMxNTMwODM0NF5BMl5BanBnXkFtZTcwODAyMTk2Mw@@._V1_SX300.jpg",
        "description": "Batman se spopade s psihopatskim Jokerjem, ki v Gotham prinaša kaos.",
    },
    "tt0111161": {
        "title": "Kaznilnica odrešitve (The Shawshank Redemption)",
        "kind": "film",
        "year": 1994,
        "image": "https://m.media-amazon.com/images/M/MV5BNDE3ODcxNzMtY2YzZC00NmNlLWJiNDMtZDViZWM2MzIxZDYwXkEyXkFqcGdeQXVyNjAwNDUxODI@._V1_SX300.jpg",
        "description": "Zgodba o upanju in prijateljstvu med zapornikoma v zaporu Shawshank.",
    },
    "tt0110912": {
        "title": "Šund (Pulp Fiction)",
        "kind": "film",
        "year": 1994,
        "image": "https://m.media-amazon.com/images/M/MV5BNGNhMDIzZTUtNTBlZi00MTRlLWFjM2ItYzViMjE3YzI5MjljXkEyXkFqcGdeQXVyNzkwMjQ5NzEt._V1_SX300.jpg",
        "description": "Prepletene zgodbe dveh plačanih morilcev, boksarja in mafijskega šefa.",
    },
    "tt0133093": {
        "title": "Matrica (The Matrix)",
        "kind": "film",
        "year": 1999,
        "image": "https://m.media-amazon.com/images/M/MV5BNzQzOTk3OTAtNDQ0Zi00ZTVkLWI0MTEtMDllZjNkYzNjNTc4L2ltYWdlXkEyXkFqcGdeQXVyNjU0OTQ0OTY@._V1_SX300.jpg",
        "description": "Programer odkrije resnico o svoji navidezni resničnosti in vojni proti strojem.",
    },
    "tt0172495": {
        "title": "Gladiator",
        "kind": "film",
        "year": 2000,
        "image": "https://m.media-amazon.com/images/M/MV5BMDliMmNhNDEtODUyOS00MjNlLTgxODEtN2U3NzIxMGVkZTA1L2ltYWdlXkEyXkFqcGdeQXVyNjU0OTQ0OTY@._V1_SX300.jpg",
        "description": "Nekdanji rimski general se maščuje pokvarjenemu cesarju, ki je umoril njegovo družino.",
    },
    "tt15239678": {
        "title": "Dune: Part Two (Dune: Peščeni planet 2)",
        "kind": "film",
        "year": 2024,
        "image": "https://m.media-amazon.com/images/M/MV5BN2QyZGUgkUtYTY5MS00ZTM0LWI0NDktZjBkNjVjYzJkZTI4XkEyXkFqcGdeQXVyMTkxNjUyNQ@@._V1_SX300.jpg",
        "description": "Paul Atreides se združi s Chani in Fremeni na poti maščevanja.",
    },
    "tt15398776": {
        "title": "Oppenheimer",
        "kind": "film",
        "year": 2023,
        "image": "https://m.media-amazon.com/images/M/MV5BMDBmYTZjNjMtNjc5Yi00Nzc5LODExOWUtODEzNTYRmMjVhNDhkXkEyXkFqcGdeQXVyNzAwMjU2MTY@._V1_SX300.jpg",
        "description": "Zgodba o očetu atomske bombe J. Robertu Oppenheimerju in projektu Manhattan.",
    },
    "tt1630029": {
        "title": "Avatar: Pot vode (The Way of Water)",
        "kind": "film",
        "year": 2022,
        "image": "https://m.media-amazon.com/images/M/MV5BYjhiNjBlODctY2ZiOC00YjVlLWFlNzAtNTVhNzM1YjI1NzMxXkEyXkFqcGdeQXVyMjkwOTAyMDU@._V1_SX300.jpg",
        "description": "Jake Sully in Neytiri ščitita svojo družino na oceanih Pandore.",
    },
    "tt0944947": {
        "title": "Igra prestolov (Game of Thrones)",
        "kind": "serija",
        "year": 2011,
        "image": "https://m.media-amazon.com/images/M/MV5BN2EyZjM3NzUtNWUzMi00MTgxLWI0NTctMzY4M2VlOTdjZWRiXkEyXkFqcGdeQXVyNDUzOTQ5MjY@._V1_SX300.jpg",
        "description": "Plemiške družine se borijo za nadzor nad Deželami Westerosa.",
        "episodes": [
            (1, 1, "Zima prihaja (Winter Is Coming)"),
            (1, 2, "Kraljeva cesta (The Kingsroad)"),
            (1, 3, "Lord Snow"),
            (1, 4, "Pohabljenci, pankrti in zlomljene reči"),
            (1, 5, "Volk in lev (The Wolf and the Lion)"),
        ],
    },
    "tt0903747": {
        "title": "Kriva pota (Breaking Bad)",
        "kind": "serija",
        "year": 2008,
        "image": "https://m.media-amazon.com/images/M/MV5BYmQ4YWMxYjUtNjZmYi00MDQ1LWFjMjAtNjA5cfFhMmZmN2I3XkEyXkFqcGdeQXVyMTMzNDExODE5._V1_SX300.jpg",
        "description": "Učitelj kemije z rakom začne kuhati metamfetamin s svojim nekdanjim dijakom.",
        "episodes": [
            (1, 1, "Pilot"),
            (1, 2, "Mačka v žaklju (Cat's in the Bag...)"),
            (1, 3, "...in vreča v reki (...And the Bag's in the River)"),
            (1, 4, "Mož z rakom (Cancer Man)"),
            (1, 5, "Siva snov (Gray Matter)"),
        ],
    },
    "tt4574334": {
        "title": "Stranger Things (Nenavadne stvari)",
        "kind": "serija",
        "year": 2016,
        "image": "https://m.media-amazon.com/images/M/MV5BMDZkYmVhNjMtNWU4MC00MDQxLWE3YTgtZDAzOWZkYzg3NTBhXkEyXkFqcGdeQXVyMTkxNjUyNQ@@._V1_SX300.jpg",
        "description": "Ko deček izgine v majhnem mestu, prijatelji in mati odkrijejo skrivne poskuse in deklico z nadnaravnimi močmi.",
        "episodes": [
            (1, 1, "Izginotje Willa Byersa"),
            (1, 2, "Čudakinja na ulici Maple"),
            (1, 3, "Božične lučke"),
        ],
    },
    "tt3581920": {
        "title": "The Last of Us",
        "kind": "serija",
        "year": 2023,
        "image": "https://m.media-amazon.com/images/M/MV5BZGUzYTI3M2EtZmM0Yy00NGUyLWI4ODEtN2Q3ZGJlYzhhZjU3XkEyXkFqcGdeQXVyNTM0NTU5Mg@@._V1_SX300.jpg",
        "description": "Joel in Ellie potujeta skozi post-apokaliptične Združene države.",
        "episodes": [
            (1, 1, "Ko si izgubljen v temi"),
            (1, 2, "Okuženi"),
            (1, 3, "Dolg, dolg čas"),
        ],
    },
    "tt8462636": {
        "title": "Černobil (Chernobyl)",
        "kind": "serija",
        "year": 2019,
        "image": "https://m.media-amazon.com/images/M/MV5BNTBlOWUxZTctNTY2ZS00NjJkLTgwZjEtZWM1M2IxM2U0MDMzXkEyXkFqcGdeQXVyMTkxNjUyNQ@@._V1_SX300.jpg",
        "description": "Kronika jedrske nesreče v Černobilu leta 1986 in neprimerljivega poguma reševalcev.",
        "episodes": [
            (1, 1, "1:23:45"),
            (1, 2, "Prosim, ostanite mirni"),
            (1, 3, "Odpri se, zemlja"),
        ],
    },
}

ID_PAIRS = [
    ("tt0944947", "1399"), ("tt0903747", "1396"), ("tt4574334", "66732"),
    ("tt3581920", "100088"), ("tt8462636", "87108"), ("tt1375666", "27205"),
    ("tt0816692", "157336"), ("tt0468569", "155"), ("tt0111161", "278"),
    ("tt0110912", "680"), ("tt0133093", "603"), ("tt0172495", "98"),
    ("tt15239678", "693134"), ("tt15398776", "872585"), ("tt1630029", "76600")
]
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
    if not media_url or not clean_title:
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
            if any(x in src.lower() for x in ("embed", "player", "vidsrc", "vidlink", "youtube", "vimeo", "dailymotion", "stream")) or Path(urllib.parse.urlsplit(src).path).suffix.lower() in MEDIA_EXT:
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
                any(x in href.lower() for x in ("vidsrc", "vidlink", "superembed", "embed.su", "watch", "stream", "video", "movie", "tv", "series", "epizoda", "sezona"))
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
    """Sestavi embed URL za danega ponudnika glede na tip vsebine."""
    s, e = max(1, season), max(1, episode)
    is_tv = (media_type == "serija")

    if "vidlink" in netloc:
        if is_tv:
            return f"https://vidlink.pro/tv/{tmdb_id}/{s}/{e}?primaryColor=00e5ff&autoplay=true&sub=0&subtitles=false"
        return f"https://vidlink.pro/movie/{tmdb_id}?primaryColor=00e5ff&autoplay=true&sub=0&subtitles=false"

    if "vidsrc.me" in netloc:
        if is_tv:
            return f"https://vidsrc.me/embed/tv?tmdb={tmdb_id}&season={s}&episode={e}&sub=0"
        return f"https://vidsrc.me/embed/movie?tmdb={tmdb_id}&sub=0"

    if "vidsrc.in" in netloc:
        if is_tv:
            return f"https://vidsrc.in/embed/tv/{tmdb_id}/{s}/{e}?sub=0"
        return f"https://vidsrc.in/embed/movie/{tmdb_id}?sub=0"

    if "vidsrc.pm" in netloc:
        if is_tv:
            return f"https://vidsrc.pm/embed/tv/{tmdb_id}/{s}/{e}?sub=0"
        return f"https://vidsrc.pm/embed/movie/{tmdb_id}?sub=0"

    if "autoembed" in netloc:
        if is_tv:
            return f"https://player.autoembed.cc/embed/tv/{tmdb_id}/{s}/{e}"
        return f"https://player.autoembed.cc/embed/movie/{tmdb_id}"

    if "multiembed" in netloc:
        if is_tv:
            return f"https://multiembed.mov/?video_id={tmdb_id}&tmdb=1&s={s}&e={e}&sub=0"
        return f"https://multiembed.mov/?video_id={tmdb_id}&tmdb=1&sub=0"

    if "2embed" in netloc:
        if is_tv:
            return f"https://www.2embed.cc/embedtv/{tmdb_id}&s={s}&e={e}&sub=0"
        return f"https://www.2embed.cc/embed/{tmdb_id}"

    if "111movies" in netloc:
        if is_tv:
            return f"https://111movies.com/tv/{tmdb_id}/{s}/{e}"
        return f"https://111movies.com/movie/{tmdb_id}"

    # Privzeto: vidsrc.cc format
    if is_tv:
        return f"{scheme}://{netloc}/v2/embed/tv/{imdb_id}/{s}/{e}"
    return f"{scheme}://{netloc}/v2/embed/movie/{imdb_id}"


# Vse prepoznane embed domene (razširjeno)
_EMBED_DOMAINS = ("vidsrc", "vidlink", "embed.su", "superembed", "multiembed",
                  "2embed", "autoembed", "111movies")


def _resolve_embed_or_direct_source(url: str, source_id: str, source_name: str) -> list[dict]:
    """Prepozna embed ponudnike, specifične epizode/filme ali splošne vdelane toke."""
    parsed = urllib.parse.urlsplit(url)
    netloc = parsed.netloc.lower()
    path = parsed.path
    is_embed_domain = any(dom in netloc for dom in _EMBED_DOMAINS)

    # 1. Specifična povezava do TV serije ali epizode (/tv/ ali /series/ ali SxxExx)
    match_tv = re.search(r"/(?:tv|series|embed/tv)/([^/]+)/(\d+)/(\d+)", url)
    if match_tv:
        imdb_id = match_tv.group(1).lower()
        season = int(match_tv.group(2))
        episode = int(match_tv.group(3))
        info = KNOWN_IMDB.get(imdb_id, {})
        title_base = info.get("title", source_name or "Serija")
        ep_name = ""
        for s, e, n in info.get("episodes", []):
            if s == season and e == episode:
                ep_name = f" - {n}"
                break
        clean_title = f"{title_base} S{season:02d}E{episode:02d}{ep_name}"
        item = _item(clean_title, url, base=url, source_id=source_id, source_name=source_name or "VidSrc",
                     kind="serija", year=info.get("year", 0), image=info.get("image", ""),
                     season=season, episode=episode, description=info.get("description", ""))
        return [item] if item else []

    # 1b. Povezava do celotne TV serije brez sezone/epizode (npr. /embed/tv/1399 ali /tv/tt0944947)
    match_tv_show = re.search(r"/(?:tv|series|embed/tv)/([^/?#]+)/?$", url)
    if match_tv_show:
        imdb_id = match_tv_show.group(1).lower()
        info = KNOWN_IMDB.get(imdb_id, {})
        title_base = info.get("title", source_name or "Serija")
        embed_host = parsed.netloc or "vidsrc.cc"
        scheme = parsed.scheme or "https"
        effective_name = source_name if source_name and source_name != embed_host else "VidSrc"
        episodes = info.get("episodes", [])
        if episodes:
            items = []
            for s, e, ep_name in episodes:
                # Za TMDB ponudnike poišči TMDB ID iz aliasov
                tmdb_id = imdb_id  # privzeto (če je že TMDB)
                for tmdb_k, imdb_v in [(k, v) for k, v in KNOWN_IMDB.items() if not k.startswith("tt") and v.get("title") == info.get("title")]:
                    tmdb_id = tmdb_k
                    break
                tv_url = _embed_url_for_provider(embed_host, scheme, imdb_id, tmdb_id, "serija", s, e)
                full_title = f"{title_base} S{s:02d}E{e:02d} - {ep_name}"
                it = _item(full_title, tv_url, base=tv_url, source_id=source_id,
                           source_name=effective_name, kind="serija",
                           year=info.get("year", 0), image=info.get("image", ""),
                           season=s, episode=e, description=info.get("description", ""))
                if it:
                    items.append(it)
            return items
        else:
            tv_url = _embed_url_for_provider(embed_host, scheme, imdb_id, imdb_id, "serija", 1, 1)
            it = _item(f"{title_base} S01E01", tv_url, base=tv_url, source_id=source_id,
                       source_name=effective_name, kind="serija",
                       year=info.get("year", 0), image=info.get("image", ""),
                       season=1, episode=1, description=info.get("description", ""))
            return [it] if it else []

    # 2. Specifična povezava do filma (/movie/ ali /embed/movie/)
    match_movie = re.search(r"/(?:movie|embed/movie)/([^/]+)", url)
    if match_movie:
        imdb_id = match_movie.group(1).lower()
        info = KNOWN_IMDB.get(imdb_id, {})
        clean_title = info.get("title") or f"{source_name or 'Film'} ({imdb_id})"
        item = _item(clean_title, url, base=url, source_id=source_id, source_name=source_name or "VidSrc",
                     kind="film", year=info.get("year", 0), image=info.get("image", ""),
                     description=info.get("description", ""))
        return [item] if item else []

    # 3. Korenska domena embed ponudnika — generiraj katalog prepoznanih filmov/serij
    if is_embed_domain and (not path or path in ("/", "/index.html", "/v2", "/v2/")):
        items = []
        embed_host = parsed.netloc or "vidsrc.cc"
        scheme = parsed.scheme or "https"
        effective_name = source_name if source_name and source_name != embed_host else embed_host.split(".")[0].capitalize()

        # Zgradimo obratno preslikavo: IMDb ID → TMDB ID
        imdb_to_tmdb: dict[str, str] = {}
        for tmdb_k, info_v in KNOWN_IMDB.items():
            if not tmdb_k.startswith("tt"):
                # To je TMDB alias — poišči original IMDb ključ
                for imdb_k2, info2 in KNOWN_IMDB.items():
                    if imdb_k2.startswith("tt") and info2.get("title") == info_v.get("title"):
                        imdb_to_tmdb[imdb_k2] = tmdb_k
                        break

        for imdb_id, meta in KNOWN_IMDB.items():
            if not imdb_id.startswith("tt"):
                continue  # preskoči TMDB aliase, obdelamo le IMDb ključe
            tmdb_id = imdb_to_tmdb.get(imdb_id, imdb_id)

            if meta.get("kind") == "film":
                movie_url = _embed_url_for_provider(embed_host, scheme, imdb_id, tmdb_id, "film")
                it = _item(meta["title"], movie_url, base=movie_url, source_id=source_id,
                           source_name=effective_name, kind="film",
                           year=meta.get("year", 0), image=meta.get("image", ""),
                           description=meta.get("description", ""))
                if it:
                    items.append(it)
            elif meta.get("kind") == "serija":
                for s, e, ep_name in meta.get("episodes", []):
                    tv_url = _embed_url_for_provider(embed_host, scheme, imdb_id, tmdb_id, "serija", s, e)
                    full_title = f"{meta['title']} S{s:02d}E{e:02d} - {ep_name}"
                    it = _item(full_title, tv_url, base=tv_url, source_id=source_id,
                               source_name=effective_name, kind="serija",
                               year=meta.get("year", 0), image=meta.get("image", ""),
                               season=s, episode=e, description=meta.get("description", ""))
                    if it:
                        items.append(it)
        return items

    # 4. Splošen neposredni tok ali vdelana stran
    kind = _kind("", url, source_name)
    title = source_name if source_name and source_name != parsed.netloc else (parsed.netloc or "Vdelana vsebina")
    it = _item(title, url, base=url, source_id=source_id, source_name=source_name, kind=kind)
    return [it] if it else []


def _parse_m3u(text: str, base: str, source_id: str, source_name: str) -> list[dict]:
    # HLS manifest je en prilagodljiv tok, ne katalog segmentov. LibVLC sam izbere
    # najboljšo različico glede na povezavo in zmogljivost naprave.
    if "#EXT-X-TARGETDURATION" in text or "#EXT-X-STREAM-INF" in text:
        found = _item(source_name, base, base=base, source_id=source_id,
                      source_name=source_name, kind="film", quality="adaptive")
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
        found = _item(title, url, base=base, source_id=source_id, source_name=source_name,
                      kind=enclosure.get("type", "") if enclosure is not None else "",
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


class MediaCenter:
    """Trajen katalog virov z atomskim zapisom in enotno logiko za vse platforme."""

    def __init__(self, config_dir: str, roots: Optional[Iterable[str | Path]] = None):
        self.config_dir = Path(config_dir)
        self.store_path = self.config_dir / "media.json"
        self.roots = [Path(path) for path in roots] if roots is not None else self._default_roots()
        self._lock = threading.RLock()

    @staticmethod
    def _default_roots() -> list[Path]:
        home, out = Path.home(), []
        for name in ("Music", "Glasba", "Videos", "Video", "Movies", "Filmi"):
            path = home / name
            if path.is_dir() and path not in out:
                out.append(path)
        return out

    def _load(self) -> dict:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"viri": []}
        except (OSError, ValueError):
            return {"viri": []}

    def _save(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.store_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.store_path)

    def sources(self) -> list[dict]:
        with self._lock:
            return [{k: value for k, value in source.items() if k != "vnosi"}
                    for source in self._load().get("viri", []) if isinstance(source, dict)]

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
            data.setdefault("viri", []).append(source)
            self._save(data)
        return self.refresh_source(source["id"])

    def remove_source(self, source_id: str) -> bool:
        with self._lock:
            data = self._load()
            before = len(data.get("viri", []))
            data["viri"] = [source for source in data.get("viri", []) if source.get("id") != source_id]
            if len(data["viri"]) == before:
                return False
            self._save(data)
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
        with self._lock:
            source = next((item.copy() for item in self._load().get("viri", [])
                           if item.get("id") == source_id), None)
            if source is None:
                return {"ok": False, "napaka": "ni_vira"}
        try:
            payload, content_type, final_url = self._download(source["url"])
            items = parse_payload(payload, content_type, final_url, source["id"], source["ime"])
            if not items:
                items = _resolve_embed_or_direct_source(final_url, source["id"], source["ime"])
            source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": ""})
            ok, error = True, ""
        except Exception as exc:
            items = _resolve_embed_or_direct_source(source["url"], source["id"], source["ime"])
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
               if int(source.get("posodobljeno") or 0) < cutoff]
        results = [self.refresh_source(source_id) for source_id in ids]
        return {"ok": all(item.get("ok") for item in results), "osvezenih": len(results),
                "rezultati": results}

    def _local_items(self) -> list[dict]:
        items = []
        for root in self.roots:
            if not root.is_dir():
                continue
            for base, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if not name.startswith(".")][:80]
                for filename in files:
                    path = Path(base) / filename
                    if path.suffix.lower() not in MEDIA_EXT:
                        continue
                    try:
                        modified = int(path.stat().st_mtime)
                    except OSError:
                        continue
                    kind = "glasba" if path.suffix.lower() in AUDIO else "film"
                    found = _item(path.stem, path.as_uri(), base=path.as_uri(), source_id="lokalno",
                                  source_name="Ta računalnik", kind=kind,
                                  quality=path.stem, description=str(path))
                    if found:
                        found.update({"pot": str(path), "cas": modified, "mime": mimetypes.guess_type(str(path))[0] or ""})
                        items.append(found)
                    if len(items) >= MAX_FILES:
                        return items
        return items

    def catalog(self, query: str = "", kind: str = "vse") -> dict:
        with self._lock:
            data = self._load()
        remote = [item for source in data.get("viri", []) for item in source.get("vnosi", []) if isinstance(item, dict)]
        merged = merge_duplicates(self._local_items() + remote)
        needle = _text(query, 120).casefold()
        if needle:
            merged = [item for item in merged if needle in " ".join((item.get("naslov", ""), item.get("izvajalec", ""),
                                                                      item.get("opis", ""), item.get("imdb_id", ""),
                                                                      str(item.get("tmdb_id") or ""))).casefold()]
        if kind not in ("", "vse"):
            merged = [item for item in merged if item.get("vrsta") == kind]
        return {"vnosi": merged, "viri": self.sources(), "skupaj": len(merged), "mape": [str(path) for path in self.roots]}

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
                return {"ok": False, "napaka": "V JSON podatkih ni bilo mogoče najti medijskih vsebin (preverite naslov in url)."}

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
        return next((item for item in self.catalog()["vnosi"] if item.get("id") == item_id), None)


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
