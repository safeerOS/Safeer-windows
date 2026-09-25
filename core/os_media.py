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


def _kind(value: Any, url: str = "", title: str = "") -> str:
    hint = f"{value or ''} {url} {title}".lower()
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if ext in AUDIO or any(x in hint for x in ("audio", "music", "song", "track", "album", "glasba")):
        return "glasba"
    if any(x in hint for x in ("series", "episode", "season", "show", "tv", "serija", "epizoda")):
        return "serija"
    return "film"


def _resolution(value: Any, *hints: str) -> int:
    joined = " ".join([_text(value)] + [_text(x) for x in hints]).lower()
    if "8k" in joined or "4320" in joined:
        return 4320
    if "4k" in joined or "2160" in joined or "uhd" in joined:
        return 2160
    matches = [int(x) for x in re.findall(r"(?<!\d)(360|480|576|720|1080|1440|2160|4320)p?", joined)]
    return max(matches, default=0)


def _quality_label(resolution: int) -> str:
    if resolution >= 2160:
        return "4K"
    if resolution >= 1080:
        return "1080p"
    if resolution >= 720:
        return "720p"
    return f"{resolution}p" if resolution else "Samodejno"


def _item(title: Any, url: Any, *, base: str, source_id: str, source_name: str,
          kind: Any = "", year: Any = 0, image: Any = "", artist: Any = "",
          quality: Any = "", resolution: Any = 0, bitrate: Any = 0,
          season: Any = 0, episode: Any = 0, description: Any = "") -> Optional[dict]:
    media_url = _absolute(base, url)
    clean_title = _text(title, 200)
    if not media_url or not clean_title:
        return None
    try:
        year_int = int(year or 0)
    except (TypeError, ValueError):
        match = re.search(r"\b(19\d{2}|20\d{2})\b", clean_title)
        year_int = int(match.group(1)) if match else 0
    try:
        bitrate_int = int(float(bitrate or 0))
    except (TypeError, ValueError):
        bitrate_int = 0
    res = _resolution(resolution, quality, media_url, clean_title)
    result = {
        "naslov": clean_title,
        "url": media_url,
        "vrsta": _kind(kind, media_url, clean_title),
        "leto": year_int if 1900 <= year_int <= 2200 else 0,
        "slika": _absolute(base, image),
        "izvajalec": _text(artist, 160),
        "locljivost": res,
        "kakovost": _quality_label(res),
        "bitrate": max(0, bitrate_int),
        "sezona": int(season or 0) if str(season or "").isdigit() else 0,
        "epizoda": int(episode or 0) if str(episode or "").isdigit() else 0,
        "opis": _text(description, 500),
        "vir_id": source_id,
        "vir": source_name,
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
    inherited = inherited or {}
    if isinstance(data, list):
        for value in data[:MAX_SOURCE_ITEMS]:
            out.extend(_items_from_json(value, base, source_id, source_name, inherited))
        return out
    if not isinstance(data, dict):
        return out

    title = _first(data, ("title", "name", "naslov", "label")) or inherited.get("title", "")
    context = {
        "title": title,
        "kind": _first(data, ("type", "kind", "media_type", "vrsta", "category")) or inherited.get("kind", ""),
        "year": _first(data, ("year", "release_year", "datePublished")) or inherited.get("year", 0),
        "image": _first(data, ("image", "poster", "poster_url", "thumbnail", "artwork")) or inherited.get("image", ""),
        "artist": _first(data, ("artist", "author", "creator", "albumArtist")) or inherited.get("artist", ""),
        "season": _first(data, ("season", "season_number")) or inherited.get("season", 0),
        "episode": _first(data, ("episode", "episode_number")) or inherited.get("episode", 0),
        "description": _first(data, ("description", "overview", "summary")) or inherited.get("description", ""),
    }
    url = _first(data, ("stream_url", "playback_url", "media_url", "file", "src", "url", "contentUrl"))
    if title and url and not isinstance(url, (dict, list)):
        found = _item(title, url, base=base, source_id=source_id, source_name=source_name,
                      kind=context["kind"], year=context["year"], image=context["image"],
                      artist=context["artist"], season=context["season"], episode=context["episode"],
                      description=context["description"],
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
        if tag == "a" and values.get("href"):
            path = urllib.parse.urlsplit(values["href"]).path.lower()
            if Path(path).suffix in MEDIA_EXT:
                title = values.get("title") or Path(path).stem
                found = _item(title, values["href"], base=self.base, source_id=self.source_id,
                              source_name=self.source_name)
                if found:
                    self.items.append(found)

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

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title = _text(self.title + " " + data, 200)
        if self.script_type:
            self.script_parts.append(data)

    def finish(self) -> list[dict]:
        for media_key, kind in (("og:video", "film"), ("og:video:url", "film"),
                                ("og:audio", "glasba"), ("og:audio:url", "glasba")):
            if self.meta.get(media_key):
                found = _item(self.meta.get("og:title") or self.title or self.source_name,
                              self.meta[media_key], base=self.base, source_id=self.source_id,
                              source_name=self.source_name, kind=kind,
                              image=self.meta.get("og:image", ""),
                              description=self.meta.get("og:description", ""))
                if found:
                    self.items.append(found)
        return self.items[:MAX_SOURCE_ITEMS]


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


def merge_duplicates(items: Iterable[dict]) -> list[dict]:
    """En rezultat na vsebino; vse različice ostanejo dosegljive, najboljša je prva."""
    title_groups: dict[str, list[dict]] = {}
    seen_urls: set[str] = set()
    for item in items:
        url = str(item.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title_groups.setdefault(_identity(item, include_year=False), []).append(dict(item))

    # Neznano leto združimo z edinim znanim letnikom. Če obstajata dve pravi
    # predelavi z različnima letoma, ostaneta ločeni in neznani vnos ostane zase.
    groups: dict[str, list[dict]] = {}
    for base_identity, candidates in title_groups.items():
        def item_year(value: dict) -> int:
            try:
                return int(value.get("leto") or 0)
            except (TypeError, ValueError):
                return 0

        known_years = {item_year(item) for item in candidates if item_year(item)}
        for item in candidates:
            year = item_year(item)
            effective_year = year or (next(iter(known_years)) if len(known_years) == 1 else 0)
            groups.setdefault(f"{base_identity}|{effective_year}", []).append(item)
    result = []
    for identity, variants in groups.items():
        variants.sort(key=_score, reverse=True)
        best = dict(variants[0])
        best["id"] = hashlib.sha256(identity.encode()).hexdigest()[:20]
        best["razlicice"] = [{k: value for k, value in item.items()
                              if k in ("url", "vir", "vir_id", "kakovost", "locljivost", "bitrate")}
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
            "User-Agent": "Safeer-OS-Media/1.0",
            "Accept": "application/json, application/rss+xml, application/xml, audio/x-mpegurl, text/html;q=0.9, */*;q=0.5",
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
            source.update({"vnosi": items, "stevilo": len(items), "posodobljeno": int(time.time()), "napaka": ""})
            ok, error = True, ""
        except Exception as exc:
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
                                                                      item.get("opis", ""))).casefold()]
        if kind not in ("", "vse"):
            merged = [item for item in merged if item.get("vrsta") == kind]
        return {"vnosi": merged, "viri": self.sources(), "skupaj": len(merged), "mape": [str(path) for path in self.roots]}

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
