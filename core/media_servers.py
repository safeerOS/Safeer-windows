"""Uradni Jellyfin, Emby, Navidrome/Subsonic in Plex odjemalci."""
from __future__ import annotations

import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class _HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("Strežnik je ponudil nezavarovano preusmeritev.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _url(base: str, path: str, params: dict | None = None) -> str:
    base = base.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, path.lstrip("/"))
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return url


def _request(url: str, headers: dict | None = None, body: dict | None = None) -> bytes:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Osebni medijski strežniki zahtevajo HTTPS.")
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Accept": "application/json, application/xml",
                                             "User-Agent": "SafeerOS/1.0", **(headers or {})},
                                    method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(_HTTPSOnlyRedirect())
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise OSError("HTTP %d" % response.status)
        return response.read(5 * 1024 * 1024 + 1)


def authenticate(kind: str, base: str, username: str, secret: str) -> dict:
    if kind in ("jellyfin", "emby"):
        auth = 'MediaBrowser Client="Safeer OS", Device="Windows", DeviceId="safeer-os", Version="1.0"'
        data = json.loads(_request(_url(base, "/Users/AuthenticateByName"),
                                  {"Authorization": auth, "Content-Type": "application/json"},
                                  {"Username": username, "Pw": secret}))
        token = data.get("AccessToken")
        user_id = (data.get("User") or {}).get("Id")
        if not token or not user_id:
            raise ValueError("Strežnik ni vrnil veljavne prijave.")
        return {"token": token, "user_id": str(user_id)}
    if kind in ("navidrome", "plex"):
        if not secret:
            raise ValueError("Vnesi geslo ali X-Plex-Token.")
        return {"token": secret}
    raise ValueError("Nepodprta vrsta strežnika.")


def _jellyfin_items(base: str, server: dict, token: str) -> list[dict]:
    user_id = server.get("user_id", "")
    raw = json.loads(_request(_url(base, "/Users/%s/Items" % urllib.parse.quote(user_id, safe=""), {
        "Recursive": "true", "IncludeItemTypes": "Movie,Episode,Audio", "Limit": 1000,
        "Fields": "Overview,RunTimeTicks,ProductionYear,Album,AlbumArtist,Artists",
    }), {"X-Emby-Token": token}))
    result = []
    for row in raw.get("Items", []):
        typ = row.get("Type")
        media_kind = "glasba" if typ == "Audio" else "serija" if typ == "Episode" else "film"
        ident = str(row.get("Id") or "")
        if not ident:
            continue
        image = _url(base, "/Items/%s/Images/Primary" % ident, {"maxHeight": 240, "api_key": token})
        stream = _url(base, "/%s/%s/stream" % ("Audio" if typ == "Audio" else "Videos", ident),
                      {"static": "true", "api_key": token})
        ticks = int(row.get("RunTimeTicks") or 0)
        result.append({"id": "server:%s:%s" % (server["id"], ident), "naslov": row.get("Name", ""),
                       "vrsta": media_kind, "url": stream, "slika": image,
                       "izvajalec": row.get("AlbumArtist") or ", ".join(row.get("Artists") or []),
                       "album": row.get("Album") or "", "leto": int(row.get("ProductionYear") or 0),
                       "opis": str(row.get("Overview") or "")[:500], "trajanje": ticks // 10_000_000,
                       "vir": server["ime"], "skupina": row.get("Album") or row.get("AlbumArtist") or ""})
    return result


def _navidrome_items(base: str, server: dict, secret: str, query: str) -> list[dict]:
    salt = secrets.token_hex(8)
    token = hashlib.md5((secret + salt).encode()).hexdigest()
    common = {"u": server.get("uporabnik", ""), "t": token, "s": salt,
              "v": "1.16.1", "c": "SafeerOS", "f": "json"}
    if query:
        params = dict(common, query=query, songCount="60", albumCount="0", artistCount="0")
        endpoint = "rest/search3.view"
        rows = (json.loads(_request(_url(base, endpoint, params))).get("subsonic-response", {})
                .get("searchResult3", {}).get("song", []))
    else:
        params = dict(common, size="60")
        data = json.loads(_request(_url(base, "rest/getRandomSongs.view", params)))
        rows = data.get("subsonic-response", {}).get("randomSongs", {}).get("song", [])
    if isinstance(rows, dict): rows = [rows]
    result = []
    for row in rows:
        ident = str(row.get("id") or "")
        if not ident: continue
        stream_params = dict(common, id=ident)
        cover_params = dict(common, id=row.get("coverArt", ident), size="240")
        result.append({"id": "navidrome:%s:%s" % (server["id"], ident), "naslov": row.get("title", ""),
                       "vrsta": "glasba", "url": _url(base, "rest/stream.view", stream_params),
                       "slika": _url(base, "rest/getCoverArt.view", cover_params),
                       "izvajalec": row.get("artist", ""), "album": row.get("album", ""),
                       "skupina": row.get("album", "") or row.get("artist", ""),
                       "trajanje": int(row.get("duration") or 0), "vir": server["ime"]})
    return result


def _plex_items(base: str, server: dict, token: str) -> list[dict]:
    headers = {"X-Plex-Token": token, "X-Plex-Client-Identifier": "safeer-os"}
    sections = ET.fromstring(_request(_url(base, "/library/sections"), headers))
    result = []
    for section in sections.findall("Directory"):
        key = section.get("key")
        if not key: continue
        root = ET.fromstring(_request(_url(base, "/library/sections/%s/all" % urllib.parse.quote(key, safe=""),
                                                   {"type": "1,4,10"}), headers))
        for row in list(root):
            ident = row.get("ratingKey") or row.get("key")
            if not ident: continue
            typ = row.get("type", "")
            media_kind = "glasba" if typ == "track" else "serija" if typ == "episode" else "film"
            media = row.find("./Media/Part")
            part = media.get("key") if media is not None else row.get("key")
            if not part: continue
            result.append({"id": "plex:%s:%s" % (server["id"], ident), "naslov": row.get("title", ""),
                           "vrsta": media_kind,
                           "url": _url(base, part, {"X-Plex-Token": token}),
                           "slika": _url(base, row.get("thumb", ""), {"X-Plex-Token": token}) if row.get("thumb") else "",
                           "izvajalec": row.get("grandparentTitle") or row.get("parentTitle") or "",
                           "album": row.get("parentTitle") or "", "leto": int(row.get("year") or 0),
                           "vir": server["ime"], "skupina": row.get("parentTitle") or row.get("grandparentTitle") or ""})
    return result


def catalog(kind: str, base: str, server: dict, secret: str, query: str = "") -> list[dict]:
    if kind in ("jellyfin", "emby"):
        rows = _jellyfin_items(base, server, secret)
    elif kind == "navidrome":
        rows = _navidrome_items(base, server, secret, query)
    elif kind == "plex":
        rows = _plex_items(base, server, secret)
    else:
        return []
    if query:
        needle = query.casefold()
        rows = [item for item in rows if needle in " ".join((item.get("naslov", ""), item.get("izvajalec", ""),
                                                                item.get("album", ""), item.get("opis", ""))).casefold()]
    return rows
