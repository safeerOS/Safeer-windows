"""Stremio dodatki — odjemalec protokola dodatkov (Stremio Addon SDK, javni HTTP protokol):
manifest.json → katalogi (/catalog/{tip}/{id}.json, z iskanjem ?search= ali /catalog/{tip}/{id}/search=….json)
→ meta (/meta/{tip}/{id}.json) → tokovi (/stream/{tip}/{id}.json).

Safeer ne prilaga nobenega dodatka; uporabnik vnese naslove v Nastavitve ▸ Dodatki. Predvajamo tokove
`url` (http/https) v lastnem predvajalniku; `externalUrl` odpremo v brskalniku; tokov z `infoHash`
(torrent) tu ne predvajamo (v Safeer OS jih zna Medijski center prek magnet povezave). Brez obvodov DRM.
Vsi klici so sinhroni (urllib) — gostitelj jih pozene v niti.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

_log = logging.getLogger("safeer.stremio")
CASOVNA_OMEJITEV = 15
UPORABNISKI_AGENT = "Safeer-Predvajalnik/1.0 (+https://safeer.si)"


def osnova_iz_manifesta(naslov: str) -> str:
    """https://x.si/dodatek/manifest.json -> https://x.si/dodatek"""
    n = (naslov or "").strip()
    if n.startswith("stremio://"):
        n = "https://" + n[len("stremio://"):]
    if n.endswith("/manifest.json"):
        n = n[: -len("/manifest.json")]
    return n.rstrip("/")


def _json(url: str) -> dict:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("dovoljeni so le http/https naslovi")
    zahteva = urllib.request.Request(url, headers={"User-Agent": UPORABNISKI_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(zahteva, timeout=CASOVNA_OMEJITEV) as odg:
        podatki = odg.read(8 * 1024 * 1024)
    d = json.loads(podatki.decode("utf-8", "replace"))
    return d if isinstance(d, dict) else {}


class StremioDodatek:
    def __init__(self, naslov_manifesta: str):
        self.osnova = osnova_iz_manifesta(naslov_manifesta)
        self.manifest: dict = {}

    # ---- manifest ----
    def nalozi_manifest(self) -> dict:
        self.manifest = _json(self.osnova + "/manifest.json")
        return self.manifest

    @property
    def ime(self) -> str:
        return str(self.manifest.get("name") or self.osnova)

    def viri(self) -> set:
        """Imena virov (catalog, meta, stream, subtitles) — vnos je lahko niz ali {name, types, ...}."""
        izid = set()
        for r in self.manifest.get("resources") or []:
            izid.add(str(r if isinstance(r, str) else (r.get("name") or "")))
        return izid

    def katalogi(self) -> list:
        """[{"tip","id","ime","iskanje": bool, "obvezniFiltri": [...]}]"""
        izid = []
        for k in self.manifest.get("catalogs") or []:
            if not isinstance(k, dict) or not k.get("type") or not k.get("id"):
                continue
            extra = k.get("extra") or []
            obvezni = [e.get("name") for e in extra if isinstance(e, dict) and e.get("isRequired") and e.get("name")]
            podprti = {e.get("name") for e in extra if isinstance(e, dict)} | set(k.get("extraSupported") or [])
            obvezni = list(dict.fromkeys(obvezni + [n for n in (k.get("extraRequired") or []) if n]))
            izid.append({"tip": str(k["type"]), "id": str(k["id"]), "ime": str(k.get("name") or k["id"]),
                         "iskanje": "search" in podprti, "obvezniFiltri": obvezni})
        return izid

    # ---- katalog ----
    def katalog(self, tip: str, id_kataloga: str, iskanje: str = "", preskoci: int = 0, dodatno: Optional[dict] = None) -> list:
        """Vnosi kataloga: [{"id","tip","ime","opis","slika","leto"}]. Dodatki z isRequired filtri brez njih vrnejo prazno."""
        extra = dict(dodatno or {})
        if iskanje:
            extra["search"] = iskanje
        if preskoci:
            extra["skip"] = str(preskoci)
        pot = f"/catalog/{urllib.parse.quote(tip)}/{urllib.parse.quote(id_kataloga, safe='')}"
        if extra:
            pot += "/" + "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}" for k, v in extra.items())
        d = _json(self.osnova + pot + ".json")
        return [_vnos(m) for m in (d.get("metas") or d.get("metasDetailed") or []) if isinstance(m, dict) and m.get("id")]

    def meta(self, tip: str, id_vnosa: str) -> dict:
        d = _json(self.osnova + f"/meta/{urllib.parse.quote(tip)}/{urllib.parse.quote(id_vnosa, safe='')}.json")
        m = d.get("meta") or {}
        v = _vnos(m) if isinstance(m, dict) else {}
        # Serije: videos [{id, title, season, episode, released}]
        v["videi"] = [{"id": str(x.get("id")), "ime": str(x.get("title") or x.get("name") or x.get("id")),
                       "sezona": x.get("season"), "epizoda": x.get("episode"), "opis": str(x.get("overview") or x.get("description") or "")}
                      for x in (m.get("videos") or []) if isinstance(x, dict) and x.get("id")] if isinstance(m, dict) else []
        return v

    # ---- tokovi ----
    def tokovi(self, tip: str, id_vnosa: str) -> list:
        """[{"vrsta": "url"|"napovednik"|"torrent"|"neznano", "url", "ime", "naslov", "glave": {...}, "podnapisi": [...]}]

        Obvestil dodatka (prosnja za donacijo, vabilo v Discord, "No streams found") in zunanjih povezav (`externalUrl`)
        ni med tokovi - uporabnik jih ne vidi nikoli."""
        d = _json(self.osnova + f"/stream/{urllib.parse.quote(tip)}/{urllib.parse.quote(id_vnosa, safe='')}.json")
        izid = []
        for s in d.get("streams") or []:
            if not isinstance(s, dict):
                continue
            ime = str(s.get("name") or s.get("title") or "")
            naslov = str(s.get("title") or s.get("description") or "")
            glave = {}
            bh = s.get("behaviorHints") or {}
            if isinstance(bh, dict):
                ph = bh.get("proxyHeaders") or {}
                if isinstance(ph, dict) and isinstance(ph.get("request"), dict):
                    glave = {str(k): str(v) for k, v in ph["request"].items()}
            podnapisi = [{"url": str(p.get("url")), "jezik": str(p.get("lang") or "")} for p in (s.get("subtitles") or []) if isinstance(p, dict) and p.get("url")]
            if s.get("url"):
                u = str(s["url"])
                if je_obvestilo(s):
                    continue
                vrsta = "url" if u.lower().startswith(("http://", "https://")) else "neznano"
                izid.append({"vrsta": vrsta, "url": u, "ime": ime, "naslov": naslov, "glave": glave, "podnapisi": podnapisi})
            elif s.get("externalUrl"):
                continue          # povezava na stran (donacije, Discord, trgovina): ni tok
            elif s.get("infoHash"):
                izid.append({"vrsta": "torrent", "url": "magnet:?xt=urn:btih:" + str(s["infoHash"]), "ime": ime, "naslov": naslov, "glave": {}, "podnapisi": [],
                             "fileIdx": s.get("fileIdx")})
            elif s.get("ytId"):
                izid.append({"vrsta": "napovednik", "url": "https://www.youtube.com/watch?v=" + str(s["ytId"]), "ime": ime, "naslov": naslov, "glave": {}, "podnapisi": []})
        return izid


_GOSTITELJI_OBVESTIL = ("discord.gg", "discord.com", "discordapp.com", "ko-fi.com", "patreon.com", "buymeacoffee.com",
                        "paypal.com", "paypal.me", "t.me", "telegram.me", "opencollective.com", "liberapay.com", "boosty.to")
_RX_OBVESTILO = re.compile(r"(?i)\bdonat(e|ion)s?\b|discord|no streams? found|buy me a coffee|\bko-?fi\b|patreon")
_RX_MEDIJ = re.compile(r"(?i)\.(m3u8|mpd|mp4|mkv|webm|avi|mov|m4v|ts|mp3|m4a|aac|flac|ogg|opus|wav)(\?|$)")


def je_obvestilo(s: dict) -> bool:
    """Vnos med tokovi, ki je obvestilo dodatka: povezava na stran skupnosti ali besedilo obvestila brez znakov pravega toka."""
    url = str(s.get("url") or "")
    gostitelj = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(gostitelj == g or gostitelj.endswith("." + g) for g in _GOSTITELJI_OBVESTIL) or gostitelj.startswith("donate."):
        return True
    if not _RX_OBVESTILO.search(" ".join(str(s.get(k) or "") for k in ("name", "title", "description"))):
        return False
    namigi = s.get("behaviorHints") if isinstance(s.get("behaviorHints"), dict) else {}
    return not (bool(_RX_MEDIJ.search(url)) or any(k in namigi for k in ("filename", "videoSize", "videoHash", "proxyHeaders")))


def _vnos(m: dict) -> dict:
    return {"id": str(m.get("id")), "tip": str(m.get("type") or ""), "ime": str(m.get("name") or m.get("id")),
            "opis": str(m.get("description") or ""), "slika": str(m.get("poster") or ""), "leto": str(m.get("releaseInfo") or m.get("year") or "")}


def predvajljiv(tok: dict) -> bool:
    return tok.get("vrsta") == "url"
