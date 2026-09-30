"""Uradni odjemalci osebnih medijskih streznikov.

Jellyfin, Emby, Navidrome/Subsonic, Plex, Kodi (JSON-RPC), TVHeadend (TV v zivo s svojega sprejemnika),
AzuraCast (spletni radio), Funkwhale (glasba) in DLNA/UPnP (Gerbera, MiniDLNA, NAS). Vse prek njihovih
uradnih vmesnikov. Streznike v domacem omrezju (Kodi, TVHeadend, Gerbera) ponavadi tecejo brez HTTPS;
nezavarovan HTTP zato dovolimo samo za naslove v zasebnem omrezju, drugod ostane obvezen HTTPS.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import secrets
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


#: Vrste osebnih streznikov, ki jih zna Medijski center.
PONUDNIKI = ("jellyfin", "emby", "navidrome", "plex", "kodi", "tvheadend", "azuracast", "funkwhale", "dlna", "stremio")


class _HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not dovoljen_naslov(newurl):
            raise ValueError("Strežnik je ponudil nezavarovano preusmeritev.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _url(base: str, path: str, params: dict | None = None) -> str:
    base = base.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, path.lstrip("/"))
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return url


def je_domace_omrezje(host: str) -> bool:
    """Naslov v zasebnem omrezju (192.168.x, 10.x, fd00::, .local, .lan) - tam je HTTP sprejemljiv."""
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if host.endswith((".local", ".lan", ".home.arpa")) or host == "localhost":
        return True
    try:
        naslovi = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            naslovi = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)[:4]]
        except OSError:
            return False
    return bool(naslovi) and all(a.is_private or a.is_loopback or a.is_link_local for a in naslovi)


def dovoljen_naslov(url: str) -> bool:
    deli = urllib.parse.urlsplit(url)
    return deli.scheme == "https" or (deli.scheme == "http" and je_domace_omrezje(deli.hostname or ""))


def _request(url: str, headers: dict | None = None, body: dict | None = None, raw: bytes | None = None) -> bytes:
    if not dovoljen_naslov(url):
        raise ValueError("Osebni medijski strežniki zunaj domačega omrežja zahtevajo HTTPS.")
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data,
                                    headers={"Accept": "application/json, application/xml",
                                             "User-Agent": "SafeerOS/1.0", **(headers or {})},
                                    method="POST" if data is not None else "GET")
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
    if kind == "kodi":
        _kodi(base, username, secret, "JSONRPC.Ping")
        return {"token": secret}
    if kind == "tvheadend":
        _request(_url(base, "/api/serverinfo"), _osnovna_prijava(username, secret))
        return {"token": secret}
    if kind == "azuracast":
        _request(_url(base, "/api/stations"))
        return {"token": ""}
    if kind == "funkwhale":
        _request(_url(base, "/.well-known/nodeinfo"))
        return {"token": secret}
    if kind == "dlna":
        _dlna_opis(base)
        return {"token": ""}
    if kind == "stremio":
        stremio_manifest(base)
        return {"token": ""}
    raise ValueError("Nepodprta vrsta strežnika.")


def _osnovna_prijava(uporabnik: str, geslo: str) -> dict:
    if not uporabnik and not geslo:
        return {}
    return {"Authorization": "Basic " + base64.b64encode(f"{uporabnik}:{geslo}".encode()).decode()}


def _bearer(zeton: str) -> dict:
    return {"Authorization": "Bearer " + zeton} if zeton else {}


def _z_uporabnikom(url: str, uporabnik: str, geslo: str) -> str:
    """Predvajalnik (VLC/WebView) ne zna posebne glave, zna pa prijavo v naslovu."""
    if not uporabnik and not geslo:
        return url
    d = urllib.parse.urlsplit(url)
    prijava = urllib.parse.quote(uporabnik, safe="") + ":" + urllib.parse.quote(geslo, safe="") + "@"
    return urllib.parse.urlunsplit((d.scheme, prijava + d.netloc, d.path, d.query, d.fragment))


# ------------------------------------------------------------------------------------------ Kodi

def _kodi(base: str, uporabnik: str, geslo: str, metoda: str, params: dict | None = None) -> dict:
    odgovor = json.loads(_request(_url(base, "/jsonrpc"), dict(_osnovna_prijava(uporabnik, geslo),
                                  **{"Content-Type": "application/json"}),
                                  {"jsonrpc": "2.0", "id": 1, "method": metoda, "params": params or {}}))
    if "error" in odgovor:
        raise ValueError(str(odgovor["error"].get("message") or "Kodi napaka"))
    return odgovor.get("result") or {}


def _kodi_items(base: str, server: dict, geslo: str) -> list[dict]:
    uporabnik = server.get("uporabnik", "")
    def vfs(pot: str) -> str:
        return _z_uporabnikom(_url(base, "/vfs/" + urllib.parse.quote(pot, safe="")), uporabnik, geslo)
    def slika(pot: str) -> str:
        return vfs(urllib.parse.unquote(pot)) if pot else ""
    rezultat = []
    omejitev = {"start": 0, "end": 500}
    filmi = _kodi(base, uporabnik, geslo, "VideoLibrary.GetMovies",
                  {"properties": ["file", "year", "plot", "thumbnail", "runtime", "genre"], "limits": omejitev})
    for f in filmi.get("movies", []):
        rezultat.append({"id": "kodi:%s:m%s" % (server["id"], f.get("movieid")), "naslov": f.get("label", ""),
                         "vrsta": "film", "url": vfs(f.get("file", "")), "slika": slika(f.get("thumbnail", "")),
                         "leto": int(f.get("year") or 0), "opis": str(f.get("plot") or "")[:500],
                         "trajanje": int(f.get("runtime") or 0), "vir": server["ime"]})
    epizode = _kodi(base, uporabnik, geslo, "VideoLibrary.GetEpisodes",
                    {"properties": ["file", "showtitle", "season", "episode", "thumbnail", "plot"], "limits": omejitev})
    for e in epizode.get("episodes", []):
        rezultat.append({"id": "kodi:%s:e%s" % (server["id"], e.get("episodeid")),
                         "naslov": "%s S%02dE%02d %s" % (e.get("showtitle", ""), int(e.get("season") or 0),
                                                         int(e.get("episode") or 0), e.get("label", "")),
                         "vrsta": "serija", "url": vfs(e.get("file", "")), "slika": slika(e.get("thumbnail", "")),
                         "opis": str(e.get("plot") or "")[:500], "skupina": e.get("showtitle", ""), "vir": server["ime"]})
    # Dodatki (vticniki), namesceni v Kodi: tecejo v Kodiju, zato jih odpremo na napravi s Kodijem.
    try:
        dodatki = _kodi(base, uporabnik, geslo, "Addons.GetAddons",
                        {"type": "xbmc.python.pluginsource", "enabled": True,
                         "properties": ["name", "thumbnail", "summary", "extrainfo"]})
    except Exception:
        dodatki = {}
    for d in dodatki.get("addons", []):
        ident = str(d.get("addonid") or "")
        if not ident:
            continue
        ponuja = " ".join(str(x.get("value") or "") for x in (d.get("extrainfo") or []) if isinstance(x, dict))
        rezultat.append({"id": "kodi:%s:a%s" % (server["id"], ident), "naslov": d.get("name") or ident,
                         "vrsta": "glasba" if "audio" in ponuja and "video" not in ponuja else "video",
                         "url": "kodi-dodatek:%s|%s" % (server["id"], ident), "slika": slika(d.get("thumbnail", "")),
                         "opis": "Kodi dodatek · " + str(d.get("summary") or "")[:300], "vir": server["ime"],
                         "skupina": "Kodi dodatki"})
    pesmi = _kodi(base, uporabnik, geslo, "AudioLibrary.GetSongs",
                  {"properties": ["file", "artist", "album", "duration", "thumbnail", "genre"], "limits": omejitev})
    for p in pesmi.get("songs", []):
        rezultat.append({"id": "kodi:%s:s%s" % (server["id"], p.get("songid")), "naslov": p.get("label", ""),
                         "vrsta": "glasba", "url": vfs(p.get("file", "")), "slika": slika(p.get("thumbnail", "")),
                         "izvajalec": ", ".join(p.get("artist") or []), "album": p.get("album", ""),
                         "skupina": p.get("album", ""), "trajanje": int(p.get("duration") or 0), "vir": server["ime"],
                         "zanri": ", ".join(p.get("genre") or [])})
    return rezultat


# ------------------------------------------------------------------------------------ TVHeadend

def _tvheadend_items(base: str, server: dict, geslo: str) -> list[dict]:
    uporabnik = server.get("uporabnik", "")
    data = json.loads(_request(_url(base, "/api/channel/grid", {"limit": 1000, "sort": "number"}),
                               _osnovna_prijava(uporabnik, geslo)))
    rezultat = []
    for k in data.get("entries", []):
        uuid = str(k.get("uuid") or "")
        if not uuid or not k.get("enabled", True):
            continue
        ikona = k.get("icon_public_url") or ""
        rezultat.append({"id": "tvh:%s:%s" % (server["id"], uuid), "naslov": k.get("name", ""),
                         "vrsta": "tv-v-zivo",
                         "url": _z_uporabnikom(_url(base, "/stream/channel/" + uuid, {"profile": "pass"}), uporabnik, geslo),
                         "slika": _z_uporabnikom(_url(base, ikona), uporabnik, geslo) if ikona else "",
                         "opis": "Kanal %s · %s" % (k.get("number") or "", server["ime"]), "vir": server["ime"],
                         "skupina": "Moj sprejemnik"})
    return rezultat


# ------------------------------------------------------------------------------------ AzuraCast

def _azuracast_items(base: str, server: dict) -> list[dict]:
    rezultat = []
    for p in json.loads(_request(_url(base, "/api/stations"))):
        url = str(p.get("listen_url") or "")
        if not url or not p.get("is_public", True):
            continue
        rezultat.append({"id": "azura:%s:%s" % (server["id"], p.get("shortcode") or p.get("id")),
                         "naslov": p.get("name", ""), "vrsta": "radio", "url": url,
                         "opis": str(p.get("description") or "")[:300] or ("AzuraCast · " + server["ime"]),
                         "slika": str(p.get("art") or ""), "vir": server["ime"], "skupina": server["ime"]})
    return rezultat


# ------------------------------------------------------------------------------------ Funkwhale

def _funkwhale_items(base: str, server: dict, zeton: str, query: str) -> list[dict]:
    params = {"page_size": 60, "playable": "true", "ordering": "-creation_date"}
    if query:
        params["q"] = query
    # Funkwhale 2.x ima /api/v2, starejsi strezniki /api/v1.
    data = {}
    for razlicica in ("v2", "v1"):
        try:
            data = json.loads(_request(_url(base, "/api/%s/tracks/" % razlicica, params), _bearer(zeton)))
            break
        except Exception:
            continue
    rezultat = []
    for t in data.get("results", []):
        poslusaj = str(t.get("listen_url") or "")
        if not poslusaj:
            continue
        url = _url(base, poslusaj, {"token": zeton} if zeton else None)
        album = t.get("album") or {}
        naslovnica = (((album.get("cover") or t.get("cover") or {}).get("urls") or {}).get("medium_square_crop") or "")
        rezultat.append({"id": "funkwhale:%s:%s" % (server["id"], t.get("id")), "naslov": t.get("title", ""),
                         "vrsta": "glasba", "url": url, "slika": naslovnica,
                         "izvajalec": (t.get("artist") or {}).get("name", "") or " ".join(
                             str(a.get("credit") or "") + str(a.get("joinphrase") or "") for a in (t.get("artist_credit") or [])
                             if isinstance(a, dict)).strip(), "album": album.get("title", ""),
                         "skupina": album.get("title", ""), "vir": server["ime"],
                         "zanri": ", ".join(tag for tag in (t.get("tags") or []) if isinstance(tag, str))})
    return rezultat


# ------------------------------------------------------------------------------ DLNA / UPnP

_UPNP = "{urn:schemas-upnp-org:device-1-0}"


def odkrij_dlna(cas: float = 3.0) -> list[dict]:
    """SSDP: medijski strezniki v domacem omrezju (Gerbera, MiniDLNA, Jellyfin/Plex DLNA, NAS)."""
    sporocilo = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
                 "ST: urn:schemas-upnp-org:device:MediaServer:1\r\n\r\n").encode()
    najdeni: dict[str, dict] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.5)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.sendto(sporocilo, ("239.255.255.250", 1900))
        konec = __import__("time").monotonic() + cas
        while __import__("time").monotonic() < konec:
            try:
                podatki, _ = s.recvfrom(8192)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", podatki)
            if not m:
                continue
            lokacija = m.group(1).decode("utf-8", "replace")
            if lokacija in najdeni or not dovoljen_naslov(lokacija):
                continue
            try:
                opis = _dlna_opis(lokacija)
                najdeni[lokacija] = {"ime": opis["ime"], "url": lokacija}
            except Exception:
                continue
    finally:
        s.close()
    return list(najdeni.values())


def _dlna_opis(lokacija: str) -> dict:
    koren = ET.fromstring(_request(lokacija))
    naprava = koren.find(_UPNP + "device")
    if naprava is None:
        raise ValueError("To ni UPnP naprava.")
    for storitev in naprava.iter(_UPNP + "service"):
        if "ContentDirectory" in (storitev.findtext(_UPNP + "serviceType") or ""):
            nadzor = storitev.findtext(_UPNP + "controlURL") or ""
            return {"ime": naprava.findtext(_UPNP + "friendlyName") or "DLNA strežnik",
                    "nadzor": urllib.parse.urljoin(lokacija, nadzor)}
    raise ValueError("Naprava nima imenika vsebin (ContentDirectory).")


def _dlna_browse(nadzor: str, objekt: str) -> ET.Element:
    telo = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">'
            '<ObjectID>%s</ObjectID><BrowseFlag>BrowseDirectChildren</BrowseFlag><Filter>*</Filter>'
            '<StartingIndex>0</StartingIndex><RequestedCount>500</RequestedCount><SortCriteria></SortCriteria>'
            '</u:Browse></s:Body></s:Envelope>') % objekt.replace("&", "&amp;").replace("<", "&lt;")
    odgovor = ET.fromstring(_request(nadzor, {"Content-Type": 'text/xml; charset="utf-8"',
                                              "SOAPAction": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"'},
                                     raw=telo.encode()))
    rezultat = odgovor.find(".//Result")
    return ET.fromstring(rezultat.text or "<DIDL-Lite/>") if rezultat is not None else ET.fromstring("<DIDL-Lite/>")


def _dlna_items(base: str, server: dict) -> list[dict]:
    opis = _dlna_opis(base)
    didl = "{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}"
    dc = "{http://purl.org/dc/elements/1.1/}"
    upnp = "{urn:schemas-upnp-org:metadata-1-0/upnp/}"
    rezultat: list[dict] = []
    vrsta_map = (("audioItem", "glasba"), ("videoItem", "video"), ("imageItem", "slika"))
    obiskane: set = set()
    cakajo = ["0"]
    while cakajo and len(obiskane) < 60 and len(rezultat) < 1500:
        objekt = cakajo.pop(0)
        if objekt in obiskane:
            continue
        obiskane.add(objekt)
        try:
            koren = _dlna_browse(opis["nadzor"], objekt)
        except Exception:
            continue
        for mapa in koren.findall(didl + "container"):
            if mapa.get("id"):
                cakajo.append(mapa.get("id"))
        for predmet in koren.findall(didl + "item"):
            razred = predmet.findtext(upnp + "class") or ""
            vrsta = next((v for kljuc, v in vrsta_map if kljuc in razred), "")
            vir = predmet.find(didl + "res")
            if not vrsta or vir is None or not (vir.text or "").strip():
                continue
            url = vir.text.strip()
            if not dovoljen_naslov(url):
                continue
            rezultat.append({"id": "dlna:%s:%s" % (server["id"], predmet.get("id")),
                             "naslov": predmet.findtext(dc + "title") or "", "vrsta": vrsta, "url": url,
                             "slika": predmet.findtext(upnp + "albumArtURI") or "",
                             "izvajalec": predmet.findtext(upnp + "artist") or predmet.findtext(dc + "creator") or "",
                             "album": predmet.findtext(upnp + "album") or "",
                             "skupina": predmet.findtext(upnp + "album") or "", "vir": server["ime"],
                             "zanri": predmet.findtext(upnp + "genre") or ""})
    return rezultat


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
    elif kind == "kodi":
        rows = _kodi_items(base, server, secret)
    elif kind == "tvheadend":
        rows = _tvheadend_items(base, server, secret)
    elif kind == "azuracast":
        rows = _azuracast_items(base, server)
    elif kind == "funkwhale":
        rows = _funkwhale_items(base, server, secret, query)
        if query:
            return rows
    elif kind == "dlna":
        rows = _dlna_items(base, server)
    elif kind == "stremio":
        rows = _stremio_items(base, server, query)
        if query:
            return rows
    else:
        return []
    if query:
        needle = query.casefold()
        rows = [item for item in rows if needle in " ".join((item.get("naslov", ""), item.get("izvajalec", ""),
                                                                item.get("album", ""), item.get("opis", ""))).casefold()]
    return rows


# ------------------------------------------------------------------------------ Stremio dodatki

#: Stremio vrste -> vrste Medijskega centra.
_STREMIO_VRSTE = {"movie": "film", "series": "serija", "tv": "tv-v-zivo", "channel": "video"}


def _stremio_koren(url: str) -> str:
    """Naslov dodatka brez /manifest.json (uporabnik pogosto prilepi celoten naslov manifesta)."""
    url = url.strip()
    if url.startswith("stremio://"):
        url = "https://" + url[len("stremio://"):]
    return re.sub(r"/manifest\.json$", "", url.rstrip("/"))


def stremio_manifest(url: str) -> dict:
    koren = _stremio_koren(url)
    m = json.loads(_request(koren + "/manifest.json"))
    if not isinstance(m, dict) or not m.get("id"):
        raise ValueError("To ni Stremio dodatek (manifest.json).")
    return m


def _stremio_items(base: str, server: dict, query: str) -> list[dict]:
    """Katalogi dodatka po protokolu Stremio. Predvajalne povezave (stream) poiscemo sele ob kliku."""
    koren = _stremio_koren(base)
    manifest = stremio_manifest(koren)
    rezultat = []
    for katalog in (manifest.get("catalogs") or [])[:8]:
        tip, ident = str(katalog.get("type") or ""), str(katalog.get("id") or "")
        if tip not in _STREMIO_VRSTE or not ident:
            continue
        dodatno = [e.get("name") for e in (katalog.get("extra") or []) if isinstance(e, dict)] + list(katalog.get("extraSupported") or [])
        if query:
            if "search" not in dodatno:
                continue
            pot = "/catalog/%s/%s/search=%s.json" % (tip, urllib.parse.quote(ident, safe=""), urllib.parse.quote(query, safe=""))
        else:
            if any(isinstance(e, dict) and e.get("isRequired") for e in (katalog.get("extra") or [])):
                continue
            pot = "/catalog/%s/%s.json" % (tip, urllib.parse.quote(ident, safe=""))
        try:
            metas = json.loads(_request(koren + pot)).get("metas") or []
        except Exception:
            continue
        for meta in metas[:100]:
            mid = str(meta.get("id") or "")
            if not mid:
                continue
            rezultat.append({"id": "stremio:%s:%s:%s" % (server["id"], tip, mid), "naslov": meta.get("name", ""),
                             "vrsta": _STREMIO_VRSTE[tip], "url": "stremio:%s|%s|%s" % (koren, tip, mid),
                             "slika": meta.get("poster") or meta.get("logo") or "",
                             "opis": str(meta.get("description") or "")[:500], "leto": int(str(meta.get("releaseInfo") or "0")[:4] or 0)
                             if str(meta.get("releaseInfo") or "")[:4].isdigit() else 0,
                             "imdb_id": mid if mid.startswith("tt") else "", "vir": server["ime"],
                             "stremio": {"koren": koren, "tip": tip, "id": mid},
                             "skupina": katalog.get("name") or manifest.get("name") or ""})
    return rezultat


def stremio_tokovi(koren: str, tip: str, ident: str) -> list[dict]:
    """Predvajalne povezave dodatka. Uporabimo samo neposredne tokove HTTP(S) in uradne zunanje
    povezave; torrentov (infoHash/magnet) Safeer ne predvaja."""
    if tip == "series" and ":" not in ident:
        meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
        videi = [v for v in (meta.get("videos") or []) if v.get("id")]
        if not videi:
            return []
        ident = str(sorted(videi, key=lambda v: (int(v.get("season") or 0) or 999, int(v.get("episode") or 0)))[0]["id"])
    data = json.loads(_request(koren + "/stream/%s/%s.json" % (tip, urllib.parse.quote(ident, safe=":"))))
    tokovi = []
    for t in data.get("streams") or []:
        url = str(t.get("url") or "")
        if url.startswith(("https://", "http://")):
            tok = {"url": url, "vir": (t.get("name") or t.get("title") or "Stremio").split("\n")[0][:60],
                   "kakovost": (t.get("title") or "").split("\n")[0][:40]}
            # behaviorHints.proxyHeaders.request: glave, ki jih tok zahteva (Referer, User-Agent ...); predvajalnik
            # jih poslje sam. subtitles: podnapisi s spleta (predvajalnik jih ponudi v meniju).
            namigi = t.get("behaviorHints") if isinstance(t.get("behaviorHints"), dict) else {}
            glave = ((namigi.get("proxyHeaders") or {}).get("request") if isinstance(namigi.get("proxyHeaders"), dict) else None) or {}
            if isinstance(glave, dict) and glave:
                tok["glave"] = {str(k)[:80]: str(v)[:500] for k, v in glave.items() if "\n" not in str(v) and "\r" not in str(v)}
            podnapisi = [{"uri": str(p.get("url")), "jezik": str(p.get("lang") or "")[:12]}
                         for p in (t.get("subtitles") or []) if isinstance(p, dict) and str(p.get("url") or "").startswith(("https://", "http://"))]
            if podnapisi:
                tok["podnapisi"] = podnapisi[:24]
            tokovi.append(tok)
        elif str(t.get("externalUrl") or "").startswith("https://"):
            tokovi.append({"url": t["externalUrl"], "vir": (t.get("name") or "Stremio")[:60], "zunanje": True})
        elif t.get("infoHash"):
            tokovi.append({"url": "", "torrent": True})
    return tokovi


def stremio_preveri(base: str) -> str:
    """Pred dodajanjem preveri, ali dodatek ponuja kaj, kar Safeer zna predvajati.

    Vrne prazen niz, ce je dodatek uporaben, sicer razlog za uporabnika. Katalog brez
    predvajalnih povezav ali dodatek s samimi torrenti v medijskem centru ne bi deloval.
    """
    koren = _stremio_koren(base)
    manifest = stremio_manifest(koren)
    viri = [r if isinstance(r, str) else str((r or {}).get("name") or "") for r in (manifest.get("resources") or [])]
    if "stream" not in viri:
        return ("Ta dodatek ponuja samo seznam naslovov brez predvajalnih povezav, "
                "zato ga Safeer ne more predvajati.")
    vzorci = []
    for katalog in (manifest.get("catalogs") or [])[:4]:
        tip, ident = str(katalog.get("type") or ""), str(katalog.get("id") or "")
        if tip not in _STREMIO_VRSTE or not ident or any(
                isinstance(e, dict) and e.get("isRequired") for e in (katalog.get("extra") or [])):
            continue
        try:
            metas = json.loads(_request(koren + "/catalog/%s/%s.json" % (tip, urllib.parse.quote(ident, safe="")))).get("metas") or []
        except Exception:
            continue
        vzorci += [(tip, str(m.get("id") or "")) for m in metas[:2] if m.get("id")]
        if len(vzorci) >= 3:
            break
    if not vzorci:
        return ""  # dodatek brez lastnega kataloga (npr. samo tokovi za druge kataloge) - ne zavrnemo
    torrent = predvajljivo = 0
    for tip, mid in vzorci[:3]:
        try:
            tokovi = stremio_tokovi(koren, tip, mid)
        except Exception:
            continue
        predvajljivo += sum(1 for t in tokovi if t.get("url"))
        torrent += sum(1 for t in tokovi if t.get("torrent"))
    if not predvajljivo and torrent:
        return ("Ta dodatek ponuja samo torrent povezave. Safeer predvaja samo neposredne tokove, "
                "zato dodatka nismo dodali.")
    return ""


def kodi_odpri_dodatek(base: str, uporabnik: str, geslo: str, dodatek: str, glasba: bool = False) -> None:
    """Odpre dodatek na zaslonu naprave s Kodijem (dodatki tecejo samo v Kodiju)."""
    _kodi(base, uporabnik, geslo, "GUI.ActivateWindow",
          {"window": "music" if glasba else "videos", "parameters": ["plugin://%s/" % dodatek, "return"]})


def kodi_predvajaj(base: str, uporabnik: str, geslo: str, url: str) -> None:
    """Predvaja vsebino Medijskega centra na napravi s Kodijem (npr. na televizorju)."""
    _kodi(base, uporabnik, geslo, "Player.Open", {"item": {"file": url}})
