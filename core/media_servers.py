"""Uradni odjemalci osebnih medijskih streznikov.

Jellyfin, Emby, Navidrome/Subsonic, Plex, Kodi (JSON-RPC), TVHeadend (TV v zivo s svojega sprejemnika),
AzuraCast (spletni radio), Funkwhale (glasba) in DLNA/UPnP (Gerbera, MiniDLNA, NAS). Vse prek njihovih
uradnih vmesnikov. Streznike v domacem omrezju (Kodi, TVHeadend, Gerbera) ponavadi tecejo brez HTTPS;
nezavarovan HTTP zato dovolimo samo za naslove v zasebnem omrezju, drugod ostane obvezen HTTPS.
"""
from __future__ import annotations

import base64
import concurrent.futures
import threading
import time
import hashlib
import ipaddress
import json
import platform
import re
import secrets
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional


#: Vrste osebnih streznikov, ki jih zna Medijski center.
PONUDNIKI = ("jellyfin", "emby", "navidrome", "plex", "kodi", "tvheadend", "azuracast", "funkwhale", "dlna", "stremio")


#: Glave s poverilnico (Jellyfin/Emby, Plex, Basic za Kodi/TVHeadend, Bearer, piskotki).
_POVERILNICE = frozenset({"authorization", "proxy-authorization", "cookie", "x-emby-token", "x-mediabrowser-token",
                          "x-emby-authorization", "x-plex-token"})


def _streznik(deli: urllib.parse.SplitResult) -> tuple:
    privzeta = {"http": 80, "https": 443}.get(deli.scheme, 0)
    try:
        vrata = deli.port or privzeta
    except ValueError:
        vrata = -1
    return (deli.hostname or "").lower(), vrata


class _HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Preusmeritev samo na dovoljen naslov, nikoli s https na http. Poverilnice gredo samo na isti streznik (ali isti
    gostitelj ob prehodu s http na https): urllib bi jih sicer poslal tudi novemu gostitelju - npr. prijavni strani
    pred Jellyfinom ali odprti preusmeritvi (neodvisni pregled, 19. 10. 2026)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not dovoljen_naslov(newurl):
            raise ValueError("Strežnik je ponudil nezavarovano preusmeritev.")
        star, nov = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if star.scheme == "https" and nov.scheme != "https":
            raise ValueError("Strežnik je preusmeril s HTTPS na nezavarovan HTTP.")
        nova = super().redirect_request(req, fp, code, msg, headers, newurl)
        isti = _streznik(star) == _streznik(nov) or (star.scheme == "http" and nov.scheme == "https"
                                                     and _streznik(star)[0] == _streznik(nov)[0])
        if nova is not None and not isti:
            for glave in (nova.headers, nova.unredirected_hdrs):
                for ime in [k for k in glave if k.lower() in _POVERILNICE]:
                    del glave[ime]
        return nova


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
    # ::ffff:8.8.8.8 je javni IPv4; Python pred 3.12.4 ga steje za zasebnega (CVE-2024-4032).
    naslovi = [getattr(a, "ipv4_mapped", None) or a for a in naslovi]
    return bool(naslovi) and all(a.is_private or a.is_loopback or a.is_link_local for a in naslovi)


def dovoljen_naslov(url: str) -> bool:
    deli = urllib.parse.urlsplit(url)
    return deli.scheme == "https" or (deli.scheme == "http" and je_domace_omrezje(deli.hostname or ""))


def _request(url: str, headers: dict | None = None, body: dict | None = None, raw: bytes | None = None,
             timeout: float = 10) -> bytes:
    if not dovoljen_naslov(url):
        raise ValueError("Osebni medijski strežniki zunaj domačega omrežja zahtevajo HTTPS.")
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data,
                                    headers={"Accept": "application/json, application/xml",
                                             "User-Agent": "SafeerOS/1.0", **(headers or {})},
                                    method="POST" if data is not None else "GET")
    opener = urllib.request.build_opener(_HTTPSOnlyRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError("HTTP %d" % response.status)
        return response.read(5 * 1024 * 1024 + 1)


_IZVIRNI_REQUEST = _request


def _request_z_rokom(url: str, rok: float) -> bytes:
    """Zahteva s krajsim rokom. Preizkusi zamenjajo `_request` z nadomestkom brez argumenta `timeout`."""
    if _request is _IZVIRNI_REQUEST:
        return _request(url, timeout=rok)
    return _request(url)


def tok_stanje(url: str, glave: dict | None = None, rok: float = 4.0) -> tuple[bool, int, int]:
    """(odgovarja, HTTP koda, Retry-After v s) za zahtevo prvih dveh bajtov (Range 0-1) z glavami, ki jih tok zahteva.
    Mrtva povezava (potekla, izbrisana, zavrnjena: 4xx/5xx), stran HTML namesto posnetka in neodziven streznik ne
    stejejo. 429 z Retry-After pomeni »zivo, a pocakaj« (odgovarja=True). Telesa ne beremo.
    Meritev 15. 10. 2026: streznik toka je na isti podpisani naslov z glavami dodatka petkrat v 70 s odgovoril 206 -
    ena sonda pred predvajanjem naslova ne porabi; brez glave Referer pa vedno 429 (zato predvajalnik dobi glave)."""
    if not dovoljen_naslov(url):
        return False, 0, 0
    zahteva = urllib.request.Request(url, headers={"User-Agent": "SafeerOS/1.0", "Accept": "*/*", "Range": "bytes=0-1",
                                                   **{str(k): str(v) for k, v in (glave or {}).items()}})
    try:
        with urllib.request.build_opener(_HTTPSOnlyRedirect()).open(zahteva, timeout=rok) as odgovor:
            vrsta = str(odgovor.headers.get("Content-Type") or "").lower()
            return odgovor.status in (200, 206) and not vrsta.startswith("text/html"), int(odgovor.status), 0
    except urllib.error.HTTPError as napaka:
        cakaj = str(napaka.headers.get("Retry-After") or "").strip() if napaka.headers else ""
        sekund = min(int(cakaj), 600) if cakaj.isdigit() else 0
        return napaka.code == 429 and sekund > 0, int(napaka.code), sekund
    except Exception:  # noqa: BLE001 - vsaka druga napaka pomeni "ne odgovarja"
        return False, 0, 0


def tok_odgovarja(url: str, glave: dict | None = None, rok: float = 4.0) -> bool:
    """Ali streznik toka na zahtevo prvih bajtov odgovori z vsebino (glej tok_stanje)."""
    return tok_stanje(url, glave, rok)[0]


# ---------------------------------------------------------------------------------- Jellyfin in Emby
# Jellyfin 12 (7. 9. 2026) ima stare nacine prijave privzeto izklopljene (EnableLegacyAuthorization: glavi X-Emby-Token
# in X-MediaBrowser-Token, parameter `api_key`, shema »Emby«) in nima vec /Users/{id}/Items. Vedno deluje glava
# `Authorization: MediaBrowser … Token="…"` in parameter `ApiKey` (Jellyfin 10.8+, preverjeno v izvorni kodi
# AuthorizationContext.cs 15. 10. 2026). Emby (zaprta koda) ostane pri `X-Emby-Token` in `api_key`.


def _id_racunalnika() -> bytes:
    """Stalen id tega racunalnika ali b"": Linux /etc/machine-id, Windows MachineGuid (register HKLM, kljuc
    SOFTWARE/Microsoft/Cryptography - isti id, kot ga Windows da namestitvi)."""
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as kljuc:
                return str(winreg.QueryValueEx(kljuc, "MachineGuid")[0]).strip().encode("ascii", "ignore")[:64]
        except (ImportError, OSError):
            return b""
    try:
        with open("/etc/machine-id", "rb") as f:
            return f.read(64).strip()
    except OSError:
        return b""


def _id_naprave_mediabrowser() -> str:
    """Stalen DeviceId te namestitve. Jellyfin ob prijavi z istim DeviceId odjavi prejsnjo sejo, zato vse naprave
    s Safeerjem ne smejo imeti istega (prej "safeer-os", na Windows do 25. 10. 2026 vedno). Iz id-ja racunalnika
    (_id_racunalnika) prek SHA-256: id racunalnika ne gre ven."""
    mid = _id_racunalnika()
    return "safeer-" + hashlib.sha256(b"safeer-mediabrowser:" + mid).hexdigest()[:16] if mid else "safeer-os"


def _glava_mediabrowser(zeton: str = "") -> str:
    def cisto(v: str) -> str:
        return str(v).replace('"', "").replace(",", " ")
    deli = ['Client="Safeer OS"', 'Device="%s"' % cisto(platform.system() or "Linux"),
            'DeviceId="%s"' % _id_naprave_mediabrowser(), 'Version="1.0"']
    if zeton:
        deli.append('Token="%s"' % cisto(zeton))
    return "MediaBrowser " + ", ".join(deli)


def _glave_mediabrowser(kind: str, zeton: str) -> dict:
    glave = {"Authorization": _glava_mediabrowser(zeton)}
    if kind == "emby":
        glave["X-Emby-Token"] = zeton
    return glave


def parameter_zetona(kind: str) -> str:
    """Ime parametra z zetonom v naslovu toka in slike (GStreamer in WebKit glav ne dodata)."""
    return "api_key" if kind == "emby" else "ApiKey"


def authenticate(kind: str, base: str, username: str, secret: str) -> dict:
    if kind in ("jellyfin", "emby"):
        data = json.loads(_request(_url(base, "/Users/AuthenticateByName"),
                                  {"Authorization": _glava_mediabrowser(), "Content-Type": "application/json"},
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
        stremio_manifest(base, sveze=True)
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
    # Dodatkov (vticnikov) Kodija ne kazemo: tecejo samo v Kodiju, Safeer jih ne more poganjati.
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


def ponudnikovi_idji(row: dict) -> dict:
    """ProviderIds vnosa Jellyfin/Emby (Imdb, Tmdb, Tvdb - velike in male crke) -> {"imdb_id", "tmdb_id", "tvdb_id"}.
    Po njih Safeer isti naslov s strežnika in iz dodatka Stremio (tt..., tmdb:...) pokaze enkrat (os_media.merge_duplicates)."""
    ids = row.get("ProviderIds") if isinstance(row.get("ProviderIds"), dict) else {}
    po_imenu = {str(k).lower(): str(v or "").strip() for k, v in ids.items()}
    izid = {}
    imdb = po_imenu.get("imdb", "").lower()
    if re.fullmatch(r"tt\d{5,12}", imdb):
        izid["imdb_id"] = imdb
    for kljuc, polje in (("tmdb", "tmdb_id"), ("tvdb", "tvdb_id")):
        v = po_imenu.get(kljuc, "")
        if re.fullmatch(r"\d{1,10}", v) and int(v) > 0:
            izid[polje] = int(v)
    return izid


def _jellyfin_vrstica(base: str, server: dict, token: str, kind: str, row: dict, serije: dict) -> Optional[dict]:
    typ = str(row.get("Type") or "")
    ident = str(row.get("Id") or "")
    if not ident or row.get("IsFolder"):
        return None
    zvok = typ == "Audio" or str(row.get("MediaType") or "") == "Audio"
    media_kind = ("glasba" if zvok else "serija" if typ == "Episode" else "film" if typ == "Movie" else "video")
    kljuc = parameter_zetona(kind)
    image = _url(base, "/Items/%s/Images/Primary" % ident, {"maxHeight": 240, kljuc: token})
    stream = _url(base, "/%s/%s/stream" % ("Audio" if zvok else "Videos", ident), {"static": "true", kljuc: token})
    ticks = int(row.get("RunTimeTicks") or 0)
    vrstica = {"id": "server:%s:%s" % (server["id"], ident), "naslov": row.get("Name", ""),
               "vrsta": media_kind, "url": stream, "slika": image,
               "izvajalec": row.get("AlbumArtist") or ", ".join(row.get("Artists") or []),
               "album": row.get("Album") or "", "leto": int(row.get("ProductionYear") or 0),
               "opis": str(row.get("Overview") or "")[:500], "trajanje": ticks // 10_000_000,
               "vir": server["ime"], "skupina": row.get("Album") or row.get("AlbumArtist") or ""}
    if typ == "Episode":
        # Epizoda nosi id-je SERIJE ter sezono in epizodo - tako kot epizode iz dodatkov Stremio (tt...:S:E).
        # Brez stevilke epizode je ne povezemo s serijo (lahko bi se zdruzila s kartico cele serije).
        sezona, epizoda = row.get("ParentIndexNumber"), row.get("IndexNumber")
        ime_serije = str(row.get("SeriesName") or "").strip()
        if isinstance(epizoda, int) and epizoda > 0:
            vrstica.update(serije.get(str(row.get("SeriesId") or ""), {}))
            vrstica["sezona"] = int(sezona) if isinstance(sezona, int) and sezona >= 0 else 1
            vrstica["epizoda"] = int(epizoda)
        if ime_serije:
            vrstica["naslov"] = ime_serije + (" – " + str(row.get("Name")) if row.get("Name") else "")
            vrstica["skupina"] = ime_serije
    else:
        vrstica.update(ponudnikovi_idji(row))
    return vrstica


def _jellyfin_serije(base: str, glave: dict, user_id: str, serije_id: list, kind: str) -> dict:
    """Id-ji serij (ProviderIds) za epizode v knjiznici - ena zahteva za do 200 serij."""
    if not serije_id:
        return {}
    parametri = {"Ids": ",".join(serije_id[:200]), "Fields": "ProviderIds", "Limit": 200}
    try:
        if kind == "emby":
            pot = _url(base, "/Users/%s/Items" % urllib.parse.quote(user_id, safe=""), parametri)
        else:
            pot = _url(base, "/Items", dict(parametri, userId=user_id))
        surovo = json.loads(_request(pot, glave))
    except Exception:  # noqa: BLE001 - brez id-jev serij epizode ostanejo, kot so bile
        return {}
    return {str(s.get("Id")): ponudnikovi_idji(s) for s in surovo.get("Items", []) if isinstance(s, dict) and s.get("Id")}


def _jellyfin_kanali(base: str, server: dict, token: str, glave: dict, user_id: str) -> list[dict]:
    """Vsebina kanalov iz vticnikov Jellyfina (kategorija Channels): /Channels in /Channels/{id}/Items. Oddaljeni
    posnetki kanala gredo prek strežnika (Videos/{id}/stream?static=true - VideosController jih posreduje)."""
    try:
        kanali = json.loads(_request(_url(base, "/Channels", {"userId": user_id, "limit": 20}), glave)).get("Items") or []
    except Exception:  # noqa: BLE001 - strežnik brez kanalov ali starejsi brez te poti
        return []
    kanali = [k for k in kanali[:10] if isinstance(k, dict) and re.fullmatch(r"[0-9a-fA-F-]{32,36}", str(k.get("Id") or ""))]

    def vsebina(kanal: dict) -> list:
        # Vticnik kanala vsebino pogosto bere s spleta sele ob zahtevi: kanale beremo hkrati, en pocasen ne zadrzi drugih.
        try:
            odgovor = json.loads(_request(_url(base, "/Channels/%s/Items" % kanal["Id"],
                                               {"userId": user_id, "limit": 200, "fields": "ProviderIds,Overview"}), glave))
        except Exception:  # noqa: BLE001
            return []
        vrstice = []
        for row in (odgovor.get("Items") or [])[:200]:
            v = _jellyfin_vrstica(base, server, token, "jellyfin", row, {}) if isinstance(row, dict) else None
            if v:
                v["skupina"] = str(kanal.get("Name") or v["skupina"])
                vrstice.append(v)
        return vrstice
    if not kanali:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(kanali))) as bazen:
        return [v for vrstice in bazen.map(vsebina, kanali) for v in vrstice]


def _jellyfin_items(base: str, server: dict, token: str, kind: str = "jellyfin") -> list[dict]:
    user_id = str(server.get("user_id", ""))
    parametri = {"Recursive": "true", "IncludeItemTypes": "Movie,Episode,Audio", "Limit": 1000,
                 "Fields": "Overview,RunTimeTicks,ProductionYear,Album,AlbumArtist,Artists,ProviderIds"}
    glave = _glave_mediabrowser(kind, token)
    stara_pot = _url(base, "/Users/%s/Items" % urllib.parse.quote(user_id, safe=""), parametri)
    if kind == "emby":
        raw = json.loads(_request(stara_pot, glave))
    else:
        # /Items?userId= je v Jellyfinu od 10.9, /Users/{id}/Items je 12 odstranil: starejsi strezniki vrnejo 404.
        try:
            raw = json.loads(_request(_url(base, "/Items", dict(parametri, userId=user_id)), glave))
        except urllib.error.HTTPError as napaka:
            if napaka.code != 404:
                raise
            raw = json.loads(_request(stara_pot, glave))
    vrstice = [r for r in raw.get("Items", []) if isinstance(r, dict)]
    serije_id = list(dict.fromkeys(str(r.get("SeriesId")) for r in vrstice if r.get("Type") == "Episode" and r.get("SeriesId")))
    serije = _jellyfin_serije(base, glave, user_id, serije_id, kind)
    result = [v for v in (_jellyfin_vrstica(base, server, token, kind, r, serije) for r in vrstice) if v]
    if kind == "jellyfin":
        znani = {v["id"] for v in result}
        result.extend(v for v in _jellyfin_kanali(base, server, token, glave, user_id) if v["id"] not in znani)
    return result


def _navidrome_items(base: str, server: dict, secret: str, query: str) -> list[dict]:
    salt = secrets.token_hex(8)
    token = hashlib.md5((secret + salt).encode(), usedforsecurity=False).hexdigest()
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
        rows = _jellyfin_items(base, server, secret, kind)
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


# ------------------------------------------------------------------- prijava ob predvajanju (ne v shranjenih naslovih)

#: Predpona id-ja vnosa streznika -> ali id nosi id streznika (npr. "navidrome:<streznik>:<skladba>").
_PREDPONE_STREZNIKA = ("server", "navidrome", "plex", "kodi", "tvh", "funkwhale", "dlna", "azura")


def streznik_iz_id(ident: object) -> str:
    """Id osebnega streznika iz id-ja njegovega vnosa ("" za vse drugo)."""
    deli = str(ident or "").split(":", 2)
    return deli[1] if len(deli) == 3 and deli[0] in _PREDPONE_STREZNIKA and deli[1].startswith("streznik-") else ""


def _izvor(url: str) -> tuple:
    try:
        d = urllib.parse.urlsplit(str(url or ""))
        return (d.scheme.lower(), d.netloc.rpartition("@")[2].lower())
    except ValueError:
        return ("", "")


def je_naslov_streznika(url: str, server: dict) -> bool:
    """Ali naslov kaze na ta streznik (isti protokol, gostitelj in vrata)."""
    izvor = _izvor(url)
    return bool(izvor[1]) and izvor == _izvor(str(server.get("url") or ""))


def s_prijavo(url: str, server: dict, secret: str) -> str:
    """Naslov, shranjen brez prijave (core/viri_sink.py, brez_prijave), z novo prijavo tega streznika - ob
    predvajanju in prikazu na tej napravi. Prijavo doda le naslovu na tem strezniku, drugim nikoli."""
    url = str(url or "")
    if not url.startswith(("http://", "https://")) or not je_naslov_streznika(url, server):
        return url
    from core import viri_sink
    cist = viri_sink.brez_prijave(url)
    kind = str(server.get("ponudnik") or "")
    uporabnik = str(server.get("uporabnik") or "")
    if kind in ("kodi", "tvheadend"):
        return _z_uporabnikom(cist, uporabnik, secret)
    if not secret:
        return cist
    d = urllib.parse.urlsplit(cist)
    if kind in ("jellyfin", "emby"):
        dodatek = {parameter_zetona(kind): secret}
    elif kind == "navidrome" and viri_sink.je_subsonic(d.path):
        sol = secrets.token_hex(8)
        dodatek = {"u": uporabnik, "t": hashlib.md5((secret + sol).encode(), usedforsecurity=False).hexdigest(), "s": sol}
    elif kind == "plex":
        dodatek = {"X-Plex-Token": secret}
    elif kind == "funkwhale":
        dodatek = {"token": secret}
    else:
        return cist
    poizvedba = "&".join(x for x in (d.query, urllib.parse.urlencode(dodatek)) if x)
    return urllib.parse.urlunsplit((d.scheme, d.netloc, d.path, poizvedba, d.fragment))


# ------------------------------------------------------------------------------ Stremio dodatki

#: Stremio vrste -> vrste Medijskega centra.
_STREMIO_VRSTE = {"movie": "film", "series": "serija", "tv": "tv-v-zivo", "channel": "video"}
_STREMIO_TV = {"tv", "live", "livetv", "iptv", "events", "event", "sports", "sport"}
_STREMIO_RADIO = {"radio", "radios"}
_STREMIO_GLASBA = {"music", "audio", "album", "albums", "song", "songs", "track", "tracks", "playlist", "playlists",
                   "podcast", "podcasts", "audiobook", "audiobooks"}


def stremio_vrsta(tip: str) -> str:
    """Kam sodi vsebina dodatka (enako kot Safeer za Android, Stremio.razred): glasbeni dodatek v Glasbo, radijski
    v Radio, prenosi v zivo v TV v zivo; neznan tip je video - nic se ne izgubi (lastnik, 2. 10. 2026)."""
    t = str(tip or "").strip().lower()
    if t in _STREMIO_VRSTE:
        return _STREMIO_VRSTE[t]
    if t in _STREMIO_TV:
        return "tv-v-zivo"
    if t in _STREMIO_RADIO:
        return "radio"
    if t in _STREMIO_GLASBA:
        return "glasba"
    return "video"


_GLASBENO_IME = re.compile(r"(^|[^a-z])(music|musik|musica|musique|muzika|glasba|glasbeni|songs?|concerts?|koncerti?|"
                           r"last[ .]?fm|vevo|karaoke|soundcloud|videospoti?)([^a-z]|$)")


def glasbeno_ime(ime: str) -> bool:
    """Ime dodatka ali kataloga pove, da je vsebina glasba (»Flix-Music«, »Top Music«, »Koncerti«) - enako kot
    OsPravila.glasbenoIme na Androidu."""
    t = "".join(c for c in unicodedata.normalize("NFD", str(ime or "").lower()) if not unicodedata.combining(c))
    return bool(_GLASBENO_IME.search(t))


def stremio_vrsta_kataloga(tip: str, ime_dodatka: str = "", ime_kataloga: str = "") -> str:
    """Razred kataloga: po tipu, razen kadar ime dodatka ali kataloga pove, da je glasba - glasbeni dodatek, ki se
    oglasa kot filmi ali drug video (npr. skladbe kot »movie«), sodi pod Glasbo, ne med filme (Stremio.razredKataloga
    na Androidu; lastnik, 11. 10. 2026: skladbe z isto naslovnico albuma so bile med filmi videti kot podvojene)."""
    vrsta = stremio_vrsta(tip)
    if vrsta in ("film", "serija", "video") and (glasbeno_ime(ime_dodatka) or glasbeno_ime(ime_kataloga)):
        return "glasba"
    return vrsta


_GLASBENI_ID = ("lfm:", "lastfm:", "spotify:", "deezer:", "dz:", "ytm:", "yt_music", "ytmusic:", "soundcloud:", "sc:",
                "music:", "track:", "song:", "album:", "artist:", "jamendo:", "audius:", "tidal:", "applemusic:")


def stremio_metas_glasbeni(metas: list) -> bool:
    """Katalog je glasba po VSEBINI, ne le po imenu (lastnik, 11. 10. 2026): vecina vnosov ima glasben id (Last.fm,
    Spotify, Deezer, YouTube Music ...) ali izvajalca (artist). Filmi z zvrstjo »Music« niso glasba."""
    vzorec = [m for m in (metas or [])[:30] if isinstance(m, dict)]
    if len(vzorec) < 3:
        return False
    glasbenih = sum(1 for m in vzorec
                    if str(m.get("id") or "").lower().startswith(_GLASBENI_ID) or isinstance(m.get("artist"), str) and m.get("artist"))
    return glasbenih * 10 >= len(vzorec) * 6


def stremio_toki_imdb(manifest: dict) -> bool:
    """Dodatek da tokove za filme ali serije po id-jih IMDb (tt...): tak dodatek potrebuje katalog naslovov (Cinemeta),
    sam pa ga nima nujno (npr. dodatki, ki dajo samo tokove)."""
    if not isinstance(manifest, dict):
        return False
    tipi = {str(t) for t in (manifest.get("types") or [])}
    predpone = manifest.get("idPrefixes")
    for r in manifest.get("resources") or []:
        if r == "stream" or (isinstance(r, dict) and r.get("name") == "stream"):
            rt = {str(t) for t in ((r.get("types") if isinstance(r, dict) else None) or tipi)}
            rp = (r.get("idPrefixes") if isinstance(r, dict) else None) or predpone
            if rt & {"movie", "series"} and (not rp or any(str(p).startswith("tt") for p in rp)):
                return True
    return False


CINEMETA = "https://v3-cinemeta.strem.io/manifest.json"


def _stremio_izvajalec(meta: dict) -> str:
    """Izvajalec glasbenega vnosa: artist/author, prvi igralec ali reziser (kot Stremio.kt na Androidu)."""
    for k in ("artist", "author"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    for k in ("cast", "director"):
        v = meta.get(k)
        if isinstance(v, list) and v and isinstance(v[0], str) and v[0].strip():
            return v[0].strip()[:120]
    return ""


def _stremio_ujema(ime: str, iskano: str) -> bool:
    """Vse iskane besede so v imenu (brez razlikovanja velikih crk in naglasov: "sport" najde "Šport TV")."""
    def cisto(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", str(t).casefold()) if not unicodedata.combining(c))
    besede = cisto(iskano).split()
    ime = cisto(ime)
    return bool(besede) and all(b in ime for b in besede)


def ujema_iskanje(item: dict, iskano: str) -> bool:
    """Vnos osebnega streznika ali dodatka ustreza iskanju: vse iskane besede so v naslovu, izvajalcu, albumu ali
    opisu - brez razlikovanja velikih crk in naglasov ("sport tv" najde "Šport TV 1")."""
    return _stremio_ujema(" ".join(str(item.get(k) or "") for k in ("naslov", "izvajalec", "album", "opis")), iskano)


def _stremio_koren(url: str) -> str:
    """Naslov dodatka brez /manifest.json in brez /configure (uporabnik pogosto prilepi celoten naslov manifesta ali
    naslov strani z nastavitvami dodatka; manifest je vedno v korenu, kot na Androidu - MedijskiViri.preveriDodatek)."""
    url = url.strip()
    if url.startswith("stremio://"):
        url = "https://" + url[len("stremio://"):]
    url = re.sub(r"/manifest\.json$", "", url.rstrip("/"))
    return re.sub(r"/configure$", "", url)


def stremio_naslov_dodatka(url: str) -> str:
    """Povezava »Install« (stremio://...), naslov manifesta ali korena -> https://.../manifest.json; "" ce to ne more
    biti dodatek: samo https (http samo v domacem omrezju), z gostiteljem, brez prijavnih podatkov in parametrov."""
    url = str(url or "").strip()[:1024]
    if not url or any(c.isspace() for c in url):
        return ""
    if url.startswith("stremio://"):
        url = "https://" + url[len("stremio://"):]
    try:
        d = urllib.parse.urlsplit(url)
        gostitelj = d.hostname or ""
    except ValueError:
        return ""
    if not gostitelj or d.username or d.password or d.query or d.fragment:
        return ""
    if not (d.scheme == "https" or (d.scheme == "http" and je_domace_omrezje(gostitelj))):
        return ""
    return _stremio_koren(url) + "/manifest.json"


#: Manifesti dodatkov Stremio v pomnilniku (koren -> (cas, manifest)): manifest se redko spremeni, pocasen streznik
#: dodatka pa je pri vsakem iskanju dodal vec sekund (izmerjeno 5,5 s na testnem PC, 17. 10. 2026).
_MANIFESTI: dict[str, tuple[float, dict]] = {}
_MANIFESTI_ZAKLEP = threading.Lock()
MANIFEST_VELJA_S = 30 * 60
#: Najvec toliko manifestov v pomnilniku (dolgotrajen proces; dodatki, ki jih uporabnik odstrani, ne ostanejo).
MANIFESTOV_NAJVEC = 200
#: Katalogi enega dodatka se nalagajo hkrati, vsak z rokom: en pocasen katalog ne zadrzi drugih (prej zaporedno,
#: 8 katalogov x do 10 s - iskanje »dune« je trajalo 76 s).
KATALOG_ROK_S = 6.0
KATALOGI_HKRATI = 4


def stremio_manifest(url: str, sveze: bool = False) -> dict:
    """Manifest dodatka. `sveze=True` (dodajanje vira, preverba): vedno s streznika, sicer iz pomnilnika, dokler velja."""
    koren = _stremio_koren(url)
    zdaj = time.monotonic()
    if not sveze:
        with _MANIFESTI_ZAKLEP:
            znan = _MANIFESTI.get(koren)
        if znan and zdaj - znan[0] < MANIFEST_VELJA_S:
            return znan[1]
    m = json.loads(_request(koren + "/manifest.json"))
    if not isinstance(m, dict) or not m.get("id"):
        raise ValueError("To ni Stremio dodatek (manifest.json).")
    with _MANIFESTI_ZAKLEP:
        if len(_MANIFESTI) >= MANIFESTOV_NAJVEC and koren not in _MANIFESTI:
            _MANIFESTI.clear()
        _MANIFESTI[koren] = (zdaj, m)
    return m


def stremio_je_zaseben(manifest: dict) -> bool:
    """Zaseben dodatek: v manifestu se sam oznaci z `behaviorHints.adult`. Kar pride iz njega, ostane na napravi -
    naslova in plakata ne povemo drugim napravam in ga ni na polici »Na tvojih napravah« (kot v Safeer OS za Android)."""
    namigi = manifest.get("behaviorHints") if isinstance(manifest, dict) else None
    if isinstance(namigi, dict) and namigi.get("adult"):
        return True
    if not isinstance(manifest, dict):
        return False
    # Vsi dodatki za odrasle se ne oznacijo sami (JAV Nexus, preizkus 17. 10. 2026: »adult films ... 18+«, brez
    # behaviorHints.adult) - zato tudi ime, opis in imena katalogov. Raje enkrat prevec v Zasebno kot na Domov.
    besedila = [manifest.get("name"), manifest.get("description"), manifest.get("id")]
    besedila += [c.get("name") for c in (manifest.get("catalogs") or []) if isinstance(c, dict)]
    return any(je_besedilo_za_odrasle(b) for b in besedila)


#: Oznake vsebine za odrasle v imenu ali opisu dodatka (ne v naslovih filmov - »Sex Education« ni dodatek za odrasle).
_ZA_ODRASLE = re.compile(
    r"(?<![a-z0-9])(18\+|xxx|porn\w*|nsfw|hentai|jav|erotic\w*|erotik\w*|adults?[ -]only|"
    r"adult (?:films?|movies?|videos?|content|entertainment|stream\w*))(?![a-z0-9])", re.I)


def je_besedilo_za_odrasle(besedilo) -> bool:
    return bool(besedilo) and bool(_ZA_ODRASLE.search(str(besedilo)))


def stremio_idji(mid: str) -> dict:
    """TMDB in TVDB id iz id-ja dodatka (»tmdb:603«, »tvdb:81189«), da se naslov zdruzi z istim s strežnika."""
    m = re.fullmatch(r"(tmdb|tvdb):(\d{1,10})", str(mid or "").strip().lower())
    return {m.group(1) + "_id": int(m.group(2))} if m and int(m.group(2)) > 0 else {}


def _stremio_items(base: str, server: dict, query: str) -> list[dict]:
    """Katalogi dodatka po protokolu Stremio. Predvajalne povezave (stream) poiscemo sele ob kliku."""
    koren = _stremio_koren(base)
    manifest = stremio_manifest(koren)
    rezultat = []
    naloge = []
    for katalog in (manifest.get("catalogs") or [])[:8]:
        tip, ident = str(katalog.get("type") or ""), str(katalog.get("id") or "")
        if not tip or not ident:
            continue
        vrsta = stremio_vrsta_kataloga(tip, manifest.get("name") or "", katalog.get("name") or "")
        dodatno = [e.get("name") for e in (katalog.get("extra") or []) if isinstance(e, dict)] + list(katalog.get("extraSupported") or [])
        obvezen = any(isinstance(e, dict) and e.get("isRequired") for e in (katalog.get("extra") or []))
        # Katalog kanalov, postaj ali glasbe brez lastnega iskanja (vecina dodatkov TV v zivo) preiscemo sami po imenu.
        iscem_sam = bool(query) and "search" not in dodatno
        if iscem_sam and (obvezen or vrsta not in ("tv-v-zivo", "radio", "glasba")):
            continue
        if query and not iscem_sam:
            pot = "/catalog/%s/%s/search=%s.json" % (tip, urllib.parse.quote(ident, safe=""), urllib.parse.quote(query, safe=""))
        else:
            if obvezen:
                continue
            pot = "/catalog/%s/%s.json" % (tip, urllib.parse.quote(ident, safe=""))
        naloge.append((katalog, tip, vrsta, iscem_sam, pot))

    def nalozi(naloga):
        try:
            odgovor = json.loads(_request_z_rokom(koren + naloga[4], KATALOG_ROK_S))
            return (odgovor.get("metas") if isinstance(odgovor, dict) else None) or []
        except Exception:  # noqa: BLE001 - nedosegljiv ali pokvarjen katalog preskocimo
            return []

    if len(naloge) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=KATALOGI_HKRATI) as izvajalec:
            vsi_metas = list(izvajalec.map(nalozi, naloge))
    else:
        vsi_metas = [nalozi(n) for n in naloge]
    for (katalog, tip, vrsta, iscem_sam, _pot), metas in zip(naloge, vsi_metas):
        if iscem_sam:
            metas = [m for m in metas if isinstance(m, dict) and _stremio_ujema(m.get("name", ""), query)]
        if vrsta in ("film", "serija", "video") and stremio_metas_glasbeni(metas):
            vrsta = "glasba"
        for meta in metas[:100]:
            if not isinstance(meta, dict):
                continue
            mid = str(meta.get("id") or "")
            if not mid:
                continue
            rezultat.append({"id": "stremio:%s:%s:%s" % (server["id"], tip, mid), "naslov": meta.get("name", ""),
                             "vrsta": vrsta, "url": "stremio:%s|%s|%s" % (koren, tip, mid),
                             "slika": meta.get("poster") or meta.get("logo") or meta.get("background") or meta.get("thumbnail") or "",
                             "opis": str(meta.get("description") or "")[:500], "leto": int(str(meta.get("releaseInfo") or "0")[:4] or 0)
                             if str(meta.get("releaseInfo") or "")[:4].isdigit() else 0,
                             "imdb_id": mid if mid.startswith("tt") else "", "vir": server["ime"],
                             **stremio_idji(mid),
                             "stremio": {"koren": koren, "tip": tip, "id": mid},
                             "skupina": katalog.get("name") or manifest.get("name") or ""})
            if vrsta == "glasba":
                rezultat[-1]["izvajalec"] = _stremio_izvajalec(meta)
    return rezultat


# Strani prosenj in skupnosti: povezava tja ni tok, tudi ce jo dodatek poda kot `url`.
_GOSTITELJI_OBVESTIL = ("discord.gg", "discord.com", "discordapp.com", "ko-fi.com", "patreon.com", "buymeacoffee.com",
                        "paypal.com", "paypal.me", "t.me", "telegram.me", "opencollective.com", "liberapay.com", "boosty.to")
_RX_OBVESTILO = re.compile(r"(?i)\bdonat(e|ion)s?\b|discord|no streams? found|buy me a coffee|\bko-?fi\b|patreon")
_RX_MEDIJ = re.compile(r"(?i)\.(m3u8|mpd|mp4|mkv|webm|avi|mov|m4v|ts|mp3|m4a|aac|flac|ogg|opus|wav)(\?|$)")


def stremio_je_obvestilo(t: dict) -> bool:
    """Vnos med tokovi, ki je obvestilo dodatka (prosnja za donacijo, vabilo v Discord, "No streams found"): povezava
    na stran skupnosti ali besedilo obvestila brez znakov pravega toka. Tega uporabniku nikoli ne kazemo."""
    url = str(t.get("url") or "")
    gostitelj = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(gostitelj == g or gostitelj.endswith("." + g) for g in _GOSTITELJI_OBVESTIL) or gostitelj.startswith("donate."):
        return True
    besedilo = " ".join(str(t.get(k) or "") for k in ("name", "title", "description"))
    if not _RX_OBVESTILO.search(besedilo):
        return False
    namigi = t.get("behaviorHints") if isinstance(t.get("behaviorHints"), dict) else {}
    prav_tok = bool(_RX_MEDIJ.search(url)) or any(k in namigi for k in ("filename", "videoSize", "videoHash", "proxyHeaders"))
    return not prav_tok


def stremio_prva_epizoda(koren: str, ident: str) -> str:
    """Id prve epizode serije (iz metapodatkov dodatka, ki serijo pozna); prazno, ce je ni."""
    meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
    videi = [v for v in (meta.get("videos") or []) if isinstance(v, dict) and v.get("id")]
    if not videi:
        return ""
    return str(sorted(videi, key=lambda v: (int(v.get("season") or 0) or 999, int(v.get("episode") or 0)))[0]["id"])


def stremio_poskusne_epizode(koren: str, ident: str) -> list[str]:
    """Id-ji epizod, po katerih presodimo, ali je serija na voljo: prva, prva epizoda zadnje sezone in zadnja
    (kot Safeer OS za Android). Prazno, ce dodatek epizod ne navaja."""
    meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
    videi = [v for v in (meta.get("videos") or []) if isinstance(v, dict) and v.get("id") and int(v.get("season") or 0) >= 1]
    if not videi:
        return []
    videi.sort(key=lambda v: (int(v.get("season") or 0), int(v.get("episode") or 0)))
    zadnja = int(videi[-1].get("season") or 0)
    izbor: list[str] = []
    for v in (videi[0], next(v for v in videi if int(v.get("season") or 0) == zadnja), videi[-1]):
        if str(v["id"]) not in izbor:
            izbor.append(str(v["id"]))
    return izbor


_IMDB = re.compile(r"tt\d+")
_EPIZODA = re.compile(r".+:\d+:\d+")


def stremio_je_epizoda(ident: str) -> bool:
    """Naloga 131: id epizode Stremio je »<id serije>:<sezona>:<epizoda>«. Prej je stelo, da id brez dvopicja ni
    epizoda - id serije iz kataloga z lastnimi id-ji (»tmdb:84773«) pa dvopicje ze ima, zato se epizode niso iskale."""
    return bool(_EPIZODA.fullmatch(str(ident or "")))


def stremio_imdb_iz_meta(meta: dict, ident: str) -> str:
    """Naloga 131: id IMDb serije - polje `imdb_id` metapodatkov ali id sam (tt...); prazno, ce ga ni. Dodatki s
    torrenti (Torrentio ...) poznajo samo tega, katalog z lastnimi id-ji (tmdb:...) pa jih zato ni nikoli vprasal."""
    polje = str((meta or {}).get("imdb_id") or "").strip() if isinstance(meta, dict) else ""
    if _IMDB.fullmatch(polje):
        return polje
    return ident if _IMDB.fullmatch(str(ident or "")) else ""


def stremio_id_epizode_imdb(imdb: str, id_epizode: str, sezona: int, epizoda: int) -> str:
    """Id epizode po IMDb (`tt...:S:E`), ki ga vprasamo poleg id-ja dodatka. Prazno, ce ni potreben (id ze je ta) ali
    ni mogoc (brez IMDb, posebne epizode sezone 0, brez stevilke epizode)."""
    if not _IMDB.fullmatch(str(imdb or "")) or int(sezona or 0) < 1 or int(epizoda or 0) < 1:
        return ""
    v = "%s:%d:%d" % (imdb, int(sezona), int(epizoda))
    return "" if v == id_epizode else v


def stremio_daje_meta_serij(manifest: dict, ident: str) -> bool:
    """Ali dodatek daje metapodatke serij za ta id (resource `meta`, tip `series`, predpona id-ja)."""
    if not isinstance(manifest, dict):
        return False
    tipi = {str(t) for t in (manifest.get("types") or [])}
    predpone = manifest.get("idPrefixes")
    for r in manifest.get("resources") or []:
        if r == "meta" or (isinstance(r, dict) and r.get("name") == "meta"):
            rt = {str(t) for t in ((r.get("types") if isinstance(r, dict) else None) or tipi)}
            rp = (r.get("idPrefixes") if isinstance(r, dict) else None) or predpone
            if (not rt or "series" in rt) and (not rp or any(str(ident).startswith(str(x)) for x in rp)):
                return True
    return False


def _stremio_videi_serije(meta: dict) -> list[dict]:
    return [v for v in (meta.get("videos") or []) if isinstance(v, dict) and v.get("id")] if isinstance(meta, dict) else []


def _stremio_par_epizode(v: dict, imdb: str) -> tuple[str, str]:
    return str(v["id"]), stremio_id_epizode_imdb(imdb, str(v["id"]), int(v.get("season") or 0), int(v.get("episode") or 0))


def stremio_prva_epizoda_z_imdb(koren: str, ident: str) -> tuple[str, str]:
    """Naloga 131: (id prve epizode pri dodatku, isti id po IMDb ali prazno). Prazen id, ce dodatek epizod ne navaja."""
    meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
    videi = _stremio_videi_serije(meta)
    if not videi:
        return "", ""
    prvi = sorted(videi, key=lambda v: (int(v.get("season") or 0) or 999, int(v.get("episode") or 0)))[0]
    return _stremio_par_epizode(prvi, stremio_imdb_iz_meta(meta, ident))


def stremio_poskusne_epizode_z_imdb(koren: str, ident: str) -> list[tuple[str, str]]:
    """Kot stremio_poskusne_epizode, z id-jem po IMDb za vsako (naloga 131): serija iz kataloga z lastnimi id-ji se
    ne skrije le zato, ker ima tokove samo dodatek, ki pozna IMDb."""
    meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
    imdb = stremio_imdb_iz_meta(meta, ident)
    videi = [v for v in _stremio_videi_serije(meta) if int(v.get("season") or 0) >= 1]
    if not videi:
        return []
    videi.sort(key=lambda v: (int(v.get("season") or 0), int(v.get("episode") or 0)))
    zadnja = int(videi[-1].get("season") or 0)
    izbor: list[tuple[str, str]] = []
    for v in (videi[0], next(v for v in videi if int(v.get("season") or 0) == zadnja), videi[-1]):
        par = _stremio_par_epizode(v, imdb)
        if par not in izbor:
            izbor.append(par)
    return izbor


def stremio_prva_epizoda_drugje(koreni: list[str], imdb: str) -> str:
    """Naloga 131: dodatek kartice serije ni dal epizod - prva epizoda po IMDb pri drugem uporabnikovem dodatku, ki
    daje metapodatke serij (Cinemete koda ne doda sama). Prazno, ce je ne pozna nihce."""
    if not _IMDB.fullmatch(str(imdb or "")):
        return ""
    for k in koreni:
        try:
            if not stremio_daje_meta_serij(stremio_manifest(k), imdb):
                continue
            prvi, _ = stremio_prva_epizoda_z_imdb(k, imdb)
        except Exception:  # noqa: BLE001 - nedosegljiv dodatek preskocimo
            continue
        if prvi:
            return prvi
    return ""


def stremio_tokovi(koren: str, tip: str, ident: str) -> list[dict]:
    """Predvajalne povezave dodatka: samo neposredni tokovi HTTP(S). Zunanjih povezav (`externalUrl`) in obvestil
    dodatka (donacije, Discord, "No streams found") ni med njimi. Tok `infoHash` (torrent) vrnemo z vsem, kar
    potrebuje motor (hash, indeks datoteke, ime, sledilniki): predvaja ga racunalnik, ki zna prenasati torrente
    (core/os_torrent_tok.py) - kot Safeer OS za Android."""
    if tip == "series" and not stremio_je_epizoda(ident):
        meta = json.loads(_request(koren + "/meta/series/%s.json" % urllib.parse.quote(ident, safe=""))).get("meta") or {}
        videi = [v for v in (meta.get("videos") or []) if v.get("id")]
        if not videi:
            return []
        ident = str(sorted(videi, key=lambda v: (int(v.get("season") or 0) or 999, int(v.get("episode") or 0)))[0]["id"])
    data = json.loads(_request(koren + "/stream/%s/%s.json" % (tip, urllib.parse.quote(ident, safe=":"))))
    surovi = data.get("streams") or []
    if not surovi and stremio_vrsta(tip) in ("glasba", "video"):
        # Album, seznam ali kanal z videi: tokove ima posnetek (videos), ne enota sama - vzamemo prvega.
        try:
            meta = json.loads(_request(koren + "/meta/%s/%s.json" % (tip, urllib.parse.quote(ident, safe="")))).get("meta") or {}
        except Exception:
            meta = {}
        prvi = next((v for v in (meta.get("videos") or []) if isinstance(v, dict) and v.get("id")), None)
        if prvi:
            surovi = prvi.get("streams") or []
            if not surovi:
                surovi = json.loads(_request(koren + "/stream/%s/%s.json" % (tip, urllib.parse.quote(str(prvi["id"]), safe=":")))).get("streams") or []
    tokovi = []
    for t in surovi:
        url = str(t.get("url") or "")
        if url.startswith(("https://", "http://")):
            if stremio_je_obvestilo(t):
                continue
            tok = {"url": url, "vir": (t.get("name") or t.get("title") or "Stremio").split("\n")[0][:60],
                   "kakovost": (t.get("title") or "").split("\n")[0][:40],
                   # Celoten opis toka (locljivost, kodek, zvok, velikost) za izbiro najboljsega toka (core/tok_izbira).
                   "opis": " ".join(str(t.get(k) or "") for k in ("name", "title", "description")).replace("\n", " ")[:600]}
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
        # `externalUrl` ni tok, ampak povezava na stran (prosnja za donacijo, Discord, "No streams found", trgovina):
        # tega ne kazemo in ne odpiramo nikoli.
        elif t.get("infoHash"):
            tok = {"url": "", "torrent": True}
            hash_ = str(t.get("infoHash") or "").strip().lower()
            if re.fullmatch(r"[0-9a-f]{40}", hash_):
                namigi = t.get("behaviorHints") if isinstance(t.get("behaviorHints"), dict) else {}
                indeks = t.get("fileIdx")
                tok.update({
                    "hash": hash_,
                    "indeks": indeks if isinstance(indeks, int) and not isinstance(indeks, bool) and indeks >= 0 else None,
                    "ime": str(namigi.get("filename") or "")[:300],
                    # Sledilniki iz `sources` ("tracker:udp://..."), da motor hitreje najde vire.
                    "sledilniki": [str(v)[len("tracker:"):] for v in (t.get("sources") or [])
                                   if isinstance(v, str) and v.startswith("tracker:")][:20],
                    "vir": (t.get("name") or "Torrent").split("\n")[0][:60],
                    "kakovost": (t.get("title") or t.get("description") or "").split("\n")[0][:40],
                    "opis": " ".join(str(t.get(k) or "") for k in ("name", "title", "description")).replace("\n", " ")[:600]})
            tokovi.append(tok)
    return tokovi


def stremio_preveri(base: str) -> str:
    """Pred dodajanjem preveri, ali dodatek ponuja kaj, kar Safeer zna predvajati.

    Vrne prazen niz, ce je dodatek uporaben, sicer razlog za uporabnika. Katalog brez predvajalnih povezav v
    medijskem centru ne bi deloval; dodatek s samimi torrenti deluje na racunalniku, ki zna prenasati torrente.
    """
    koren = _stremio_koren(base)
    manifest = stremio_manifest(koren, sveze=True)
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
        from core import os_torrent_tok
        if os_torrent_tok.podprto():
            return ""
        return ("Ta dodatek ponuja samo torrent povezave. Ta racunalnik torrentov ne zna prenasati, "
                "zato dodatka nismo dodali.")
    return ""


def kodi_predvajaj(base: str, uporabnik: str, geslo: str, url: str) -> None:
    """Predvaja vsebino Medijskega centra na napravi s Kodijem (npr. na televizorju)."""
    _kodi(base, uporabnik, geslo, "Player.Open", {"item": {"file": url}})
