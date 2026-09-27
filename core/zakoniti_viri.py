"""Javni, zakoniti katalogi za Safeer Media (PeerTube, Jamendo, Radio Browser)."""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from typing import Any

PEERTUBE_INSTANCES = ("peertube.tv", "tilvids.com", "framatube.org", "peertube.uno", "video.blender.org")
JAMENDO_CLIENT_ID = "8d37f069"  # Javen client_id aplikacije Safeer TV.
RADIO_TAGS = ("jazz", "rock", "pop", "news", "classical", "electronic")
#: Glasbene zvrsti za Glasbo in Radio v Medijskem centru (kot zanri pri filmih):
#: kljuc -> (ime za uporabnika, oznaka Jamendo ali "", oznaka Radio Browser ali "").
GLASBENE_ZVRSTI = {
    "pop": ("Pop", "pop", "pop"),
    "rock": ("Rock", "rock", "rock"),
    "elektronska": ("Elektronska", "electronic", "electronic"),
    "hiphop": ("Hip-hop", "hiphop", "hip hop"),
    "jazz": ("Jazz", "jazz", "jazz"),
    "klasicna": ("Klasična", "classical", "classical"),
    "metal": ("Metal", "metal", "metal"),
    "plesna": ("Plesna", "dance", "dance"),
    "ljudska": ("Ljudska", "folk", "folk"),
    "reggae": ("Reggae", "reggae", "reggae"),
    "sprostitvena": ("Sprostitvena", "ambient", "chillout"),
    "filmska": ("Filmska", "soundtrack", "soundtrack"),
    "country": ("Country", "country", "country"),
    "novice": ("Novice in pogovor", "", "news"),
}


#: TV v zivo: samo uradni, javno objavljeni prenosi izdajateljev (preverjeno, da tecejo), brez posrednikov.
#: (id, ime, jezik, url HLS ali "", uradna stran za prenos, drzava - "" = za vse)
TV_V_ZIVO = (
    ("rtvslo", "RTV SLO v živo", "slovenščina", "", "https://365.rtvslo.si/v-zivo", "SI"),
    ("dw-en", "DW News", "angleščina", "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8", "", ""),
    ("dw-de", "DW Deutsch", "nemščina", "https://dwamdstream106.akamaized.net/hls/live/2017965/dwstream106/index.m3u8", "", ""),
    ("dw-es", "DW Español", "španščina", "https://dwamdstream104.akamaized.net/hls/live/2015530/dwstream104/index.m3u8", "", ""),
    ("f24-en", "France 24 English", "angleščina", "https://static.france24.com/live/F24_EN_HI_HLS/live_web.m3u8", "", ""),
    ("f24-fr", "France 24 Français", "francoščina", "https://static.france24.com/live/F24_FR_HI_HLS/live_web.m3u8", "", ""),
    ("f24-es", "France 24 Español", "španščina", "https://static.france24.com/live/F24_ES_HI_HLS/live_web.m3u8", "", ""),
    ("aje", "Al Jazeera English", "angleščina", "https://live-hls-apps-aje-fa.getaj.net/AJE/index.m3u8", "", ""),
    ("trt-world", "TRT World", "angleščina", "https://tv-trtworld.medya.trt.com.tr/master.m3u8", "", ""),
    ("cbs-news", "CBS News 24/7", "angleščina", "https://cbsn-us.cbsnstream.cbsnews.com/out/v1/55a8648e8f134e82a470f83d562deeca/master.m3u8", "", ""),
    ("arirang", "Arirang TV", "angleščina", "https://amdlive-ch01-ctnd-com.akamaized.net/arirang_1ch/smil:arirang_1ch.smil/playlist.m3u8", "", ""),
    ("nasa", "NASA TV", "angleščina", "https://ntv1.akamaized.net/hls/live/2014075/NASA-NTV1-HLS/master.m3u8", "", ""),
    ("redbull", "Red Bull TV", "angleščina", "https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8", "", ""),
)


def tv_v_zivo(drzava: str = "") -> list[dict]:
    """Uradni prenosi v zivo; domaci (npr. RTV SLO) samo za uporabnike iz te drzave."""
    izid = []
    for kljuc, ime, jezik, url, stran, samo in TV_V_ZIVO:
        if samo and samo != (drzava or "").upper():
            continue
        vnos = {"id": "tv:" + kljuc, "naslov": ime, "vrsta": "tv-v-zivo", "vir": ime,
                "opis": "Uradni prenos v živo · " + jezik, "slika": "", "jezik": jezik}
        if url:
            vnos.update(url=url, mime="application/vnd.apple.mpegurl")
        else:
            vnos.update(url=stran, stran=stran, opis="Uradna stran v živo · " + jezik)
        izid.append(vnos)
    return izid


def zvrsti_za(vrsta: str) -> list[dict]:
    """Zvrsti, ki jih ima smisel pokazati za 'glasba' ali 'radio' (novice so samo na radiu)."""
    indeks = 1 if vrsta == "glasba" else 2
    return [{"id": kljuc, "ime": v[0]} for kljuc, v in GLASBENE_ZVRSTI.items() if v[indeks]]
_TTL = 30 * 60
_TIMEOUT = 10


def _norm(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    return re.sub(r"[^\w]+", " ", "".join(c for c in raw if not unicodedata.combining(c))).strip()


class ZakonitiViri:
    """API odjemalec z omejenim casom in mehkim neuspehom posameznega vira."""

    def __init__(self, opener=None, clock=time.time):
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def _json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={
            "User-Agent": "SafeerOS/1.0 (+https://safeer.si)",
            "Accept": "application/json",
        })
        with self._opener(request, timeout=_TIMEOUT) as response:
            if getattr(response, "status", 200) != 200:
                raise OSError("HTTP %s" % response.status)
            return json.loads(response.read(5 * 1024 * 1024 + 1).decode("utf-8"))

    def _cached(self, key: str, fn):
        now = self._clock()
        with self._lock:
            found = self._cache.get(key)
            if found and now - found[0] < _TTL:
                return found[1]
        try:
            value = fn()
        except Exception:
            return found[1] if found else []
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def _video_hosts(self, configured: list[str]) -> list[str]:
        hosts = list(PEERTUBE_INSTANCES)
        candidates = []
        for value in configured:
            try:
                parsed = urllib.parse.urlsplit(value if "://" in value else "https://" + value)
                host = (parsed.hostname or "").lower()
                if parsed.scheme == "https" and host and host not in hosts:
                    candidates.append(host)
            except ValueError:
                pass
        candidates = list(dict.fromkeys(candidates))
        with ThreadPoolExecutor(max_workers=min(12, len(candidates) or 1)) as pool:
            for host, valid in zip(candidates, pool.map(lambda candidate: self._cached(
                    "pt-config:" + candidate, lambda: self._valid_peertube(candidate)), candidates)):
                if valid:
                    hosts.append(host)
        return hosts

    def _valid_peertube(self, host: str) -> bool:
        try:
            config = self._json("https://%s/api/v1/config" % host)
            return isinstance(config, dict) and isinstance(config.get("instance"), dict)
        except Exception:
            return False

    def _peertube_video(self, row: dict, host: str, category: str) -> dict | None:
        if not isinstance(row, dict) or row.get("nsfw"):
            return None
        title = str(row.get("name") or "").strip()
        video_id = str(row.get("uuid") or "")
        if not title or not video_id:
            return None
        channel = row.get("channel") if isinstance(row.get("channel"), dict) else {}
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        image = row.get("thumbnailPath") or row.get("previewPath") or ""
        if image.startswith("/"):
            image = "https://%s%s" % (host, image)
        live = bool(row.get("isLive"))
        duration = int(row.get("duration") or 0)
        kind = "tv-v-zivo" if live else ("film" if duration > 40 * 60 else "video")
        return {
            "id": "peertube:" + video_id, "naslov": title, "vrsta": kind,
            "url": "https://%s/videos/watch/%s" % (host, video_id),
            "slika": image, "opis": str(row.get("description") or "")[:600],
            "izvajalec": channel.get("displayName") or account.get("displayName") or host,
            "trajanje": duration, "v_zivo": live, "skupina": category,
            "vir": "PeerTube · " + host, "streznik": host,
            "peertube_uuid": video_id,
        }

    def _peer_rows(self, host: str, endpoint: str, category: str) -> list[dict]:
        key = "pt:%s:%s" % (host, endpoint)
        def fetch():
            data = self._json("https://%s%s" % (host, endpoint))
            rows = data.get("data", []) if isinstance(data, dict) else []
            return [item for row in rows if (item := self._peertube_video(row, host, category))]
        return self._cached(key, fetch)

    def _search_video(self, query: str, hosts: list[str]) -> list[dict]:
        if not query:
            return []
        encoded = urllib.parse.urlencode({"search": query, "sort": "-match", "nsfw": "false", "count": 30})
        def fetch():
            result = []
            try:
                data = self._json("https://sepiasearch.org/api/v1/search/videos?" + encoded)
                rows = data.get("data", []) if isinstance(data, dict) else []
                for row in rows:
                    host = str(row.get("host") or urllib.parse.urlsplit(str(row.get("url") or "")).hostname or "")
                    if not host and row.get("channel"):
                        host = str(row["channel"].get("host") or "")
                    item = self._peertube_video(row, host, "Iskanje")
                    if item:
                        result.append(item)
            except Exception:
                pass
            if not result:
                def server_search(host):
                    path = "/api/v1/search/videos?" + urllib.parse.urlencode({"search": query, "sort": "-match", "nsfw": "false", "count": 20})
                    return self._peer_rows(host, path, "Iskanje")
                with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
                    futures = [pool.submit(server_search, host) for host in hosts]
                    try:
                        for future in as_completed(futures, timeout=_TIMEOUT):
                            rows = future.result()
                            if rows:
                                result.extend(rows)
                                break
                    except FuturesTimeout:
                        pass
            terms = [word for word in _norm(query).split() if len(word) > 1]
            if terms:
                result = [item for item in result if all(term in _norm(" ".join((item["naslov"], item["izvajalec"], item["opis"]))) for term in terms)]
            return result[:40]
        return self._cached("pt-search:" + query.casefold(), fetch)

    def videos(self, query: str = "", configured_hosts: list[str] | None = None) -> list[dict]:
        hosts = self._video_hosts(configured_hosts or [])
        if query:
            return self._search_video(query, hosts)
        result = []
        routes = (("trending", "/api/v1/videos?sort=-trending&count=18&nsfw=false&isLocal=true"),
                  ("Najbolj gledani", "/api/v1/videos?sort=-views&count=18&nsfw=false&isLocal=true"),
                  ("Nedavno", "/api/v1/videos?sort=-publishedAt&count=18&nsfw=false&isLocal=true"))
        jobs = [(host, label, path) for label, path in routes for host in hosts]
        with ThreadPoolExecutor(max_workers=min(15, len(jobs))) as pool:
            futures = [pool.submit(self._peer_rows, host, path, label) for host, label, path in jobs]
            for future in futures:
                try: result.extend(future.result())
                except Exception: pass
        unique = {}
        for item in result:
            unique.setdefault(item["id"], item)
        return list(unique.values())

    def resolve_video(self, item: dict, configured_hosts: list[str] | None = None) -> dict | None:
        host = item.get("streznik", "")
        hosts = list(dict.fromkeys(([host] if host else []) + self._video_hosts(configured_hosts or [])))
        video_id = item.get("peertube_uuid", "")
        for server in hosts:
            try:
                data = self._json("https://%s/api/v1/videos/%s" % (server, urllib.parse.quote(video_id, safe="")))
                live = bool(data.get("isLive"))
                playlists = data.get("streamingPlaylists") or []
                for playlist in playlists:
                    url = playlist.get("playlistUrl")
                    if url and urllib.parse.urlsplit(url).scheme == "https":
                        return dict(item, url=url, v_zivo=live, mime="application/vnd.apple.mpegurl")
                files = []
                for file in data.get("files", []) + [f for p in playlists for f in p.get("files", [])]:
                    url = file.get("fileUrl")
                    height = int((file.get("resolution") or {}).get("id") or 0)
                    if url and urllib.parse.urlsplit(url).scheme == "https" and 0 < height <= 1080:
                        files.append((height, url))
                if files:
                    height, url = max(files)
                    return dict(item, url=url, locljivost=height, kakovost="%dp" % height, mime="video/mp4")
                for playlist in playlists:
                    url = playlist.get("playlistUrl")
                    if url and urllib.parse.urlsplit(url).scheme == "https":
                        return dict(item, url=url, mime="application/vnd.apple.mpegurl")
            except Exception:
                continue
        return None

    def _jamendo(self, path: str, params: dict) -> list[dict]:
        query = dict(params, client_id=JAMENDO_CLIENT_ID, format="json")
        url = "https://api.jamendo.com/v3.0/%s?%s" % (path, urllib.parse.urlencode(query))
        def fetch():
            for attempt in range(2):
                try:
                    data = self._json(url)
                    rows = [self._track(row) for row in data.get("results", [])
                            if row.get("audio", "").startswith("https://")]
                    if rows or attempt:
                        return rows
                except Exception:
                    if attempt:
                        raise
                time.sleep(0.3)
            return []
        return self._cached("jam:" + path + ":" + urllib.parse.urlencode(params), fetch)

    @staticmethod
    def _track(row: dict) -> dict:
        return {"id": "jamendo:" + str(row.get("id")), "naslov": row.get("name", ""), "vrsta": "glasba",
                "izvajalec": row.get("artist_name", ""), "url": row.get("audio", ""),
                "slika": row.get("image") or row.get("album_image", ""),
                "zunanja_povezava": row.get("shorturl") or row.get("shareurl", ""),
                "vir": "Jamendo", "opis": "Jamendo · " + str(row.get("artist_name", ""))}

    def music(self, query: str = "", zvrst: str = "") -> list[dict]:
        oznaka = GLASBENE_ZVRSTI.get(zvrst, ("", "", ""))[1]
        if zvrst and not oznaka:
            return []
        if oznaka and not query:
            # Jamendo pri nekaterih oznakah obcasno vrne prazno z `tags`; takrat poskusimo `fuzzytags`.
            zadetki = self._jamendo("tracks/", {"order": "popularity_total", "limit": 48, "audioformat": "mp32", "tags": oznaka})
            return zadetki or self._jamendo("tracks/", {"order": "popularity_total", "limit": 48, "audioformat": "mp32",
                                                         "fuzzytags": oznaka})
        if not query:
            return self._jamendo("tracks/", {"order": "popularity_total", "limit": 36, "audioformat": "mp32"})
        def fetch():
            artists = self._json("https://api.jamendo.com/v3.0/artists/?" + urllib.parse.urlencode({
                "namesearch": query, "order": "popularity_total", "limit": 8,
                "client_id": JAMENDO_CLIENT_ID, "format": "json"}))
            selected = artists.get("results", [])[:6]
            with ThreadPoolExecutor(max_workers=max(1, len(selected))) as pool:
                return [track for rows in pool.map(lambda artist: self._jamendo("tracks/", {
                    "artist_id": artist.get("id"), "order": "popularity_total", "limit": 8,
                    "audioformat": "mp32"}), selected) for track in rows]
        return self._cached("jam-search:" + query.casefold(), fetch)

    def radio(self, query: str = "", zvrst: str = "") -> list[dict]:
        ime, _, oznaka = GLASBENE_ZVRSTI.get(zvrst, ("", "", ""))
        if zvrst and not oznaka:
            return []
        if oznaka:
            tags = [(oznaka, ime)]
        else:
            tags = [(query, "Iskanje")] if query else [("SI", "Slovenija")] + [(tag, tag.title()) for tag in RADIO_TAGS] + [("", "Najbolj poslušane")]
        def load_tag(entry):
            value, label = entry
            params = {"order": "clickcount", "reverse": "true", "hidebroken": "true",
                      "limit": "60" if oznaka else "30", "is_https": "true"}
            if value == "SI": params["countrycode"] = "SI"
            elif value: params["tag"] = value
            key = "radio:" + label + ":" + value
            def fetch(params=params, label=label):
                url = "https://de1.api.radio-browser.info/json/stations/search?" + urllib.parse.urlencode(params)
                rows = self._json(url)
                return [self._station(row, label) for row in rows if isinstance(row, dict)]
            return self._cached(key, fetch)
        with ThreadPoolExecutor(max_workers=len(tags)) as pool:
            result = [station for rows in pool.map(load_tag, tags) for station in rows]
        seen = set()
        out = []
        for station in result:
            if station and station["id"] not in seen:
                seen.add(station["id"]); out.append(station)
        return out

    @staticmethod
    def _station(row: dict, group: str) -> dict | None:
        url = row.get("url_resolved") or ""
        if (not row.get("stationuuid") or not row.get("name") or not url.startswith("https://")
                or str(row.get("lastcheckok", "1")) == "0"):
            return None
        try: bitrate = int(row.get("bitrate") or 0)
        except (TypeError, ValueError): bitrate = 0
        codec = str(row.get("codec") or "").upper()
        return {"id": "radio:" + row["stationuuid"], "naslov": row["name"].strip(), "vrsta": "radio",
                "url": url, "slika": row.get("favicon") or "", "izvajalec": row.get("country") or "",
                "opis": " · ".join(part for part in (row.get("country"), codec, (str(bitrate) + " kb/s") if bitrate else "") if part),
                "codec": codec, "bitrate": bitrate, "drzava": row.get("countrycode", ""),
                "zanri": row.get("tags", ""), "skupina": group, "vir": "Radio Browser"}

    def get(self, query: str = "", configured_hosts: list[str] | None = None, zvrst: str = "") -> list[dict]:
        if zvrst:
            # Glasbena zvrst velja samo za glasbo in radio (video nima teh zvrsti).
            tasks = ((self.music, (query, zvrst)), (self.radio, (query, zvrst)))
        else:
            tasks = ((self.videos, (query, configured_hosts)), (self.music, (query,)), (self.radio, (query,)))
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(fn, *args) for fn, args in tasks]
            results = []
            for future in futures:
                try: results.extend(future.result())
                except Exception: continue
            return results
