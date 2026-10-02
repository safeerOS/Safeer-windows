"""Uvoz seznama predvajanja iz YouTuba ali Spotifyja v sezname predvajanja Medijskega centra.

Enako kot v Safeer OS za Android (UvozSeznama.kt): uporabnik prilepi povezavo javnega ali nenavedenega seznama,
preberemo naslove, izvajalce in slike. YouTube: vsak posnetek ima svoj id. Spotify svojih tokov ne daje drugim
predvajalnikom, zato prenesemo SEZNAM SKLADB (naslov, izvajalec, dolzina); posnetek zanjo poiscemo ob predvajanju
(najdi) in si ga zapomnimo. Brez prijave: zasebnih seznamov ne beremo.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

NAJVEC = 400
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0 Safari/537.36")
_RAZLICICA = "2.20261001.01.00"


def youtube_id(vnos: str) -> str:
    u = str(vnos or "").strip()
    if not re.search(r"(?i)(^|[/.@])(youtube\.com|youtu\.be|youtube-nocookie\.com)/", u):
        return ""
    m = re.search(r"[?&]list=([A-Za-z0-9_-]{10,})", u)
    return m.group(1) if m else ""


def spotify_id(vnos: str) -> Optional[tuple[str, str]]:
    u = str(vnos or "").strip()
    m = (re.search(r"(?i)open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?(playlist|album)/([A-Za-z0-9]{10,})", u)
         or re.search(r"(?i)spotify:(playlist|album):([A-Za-z0-9]{10,})", u))
    return (m.group(1).lower(), m.group(2)) if m else None


def je_povezava(vnos: str) -> bool:
    return bool(youtube_id(vnos) or spotify_id(vnos))


def povezava_iz(besedilo: str) -> str:
    """Povezava seznama v prilepljenem besedilu ("Poslusaj ta seznam: https://...") ali prazno."""
    for m in re.finditer(r"(?:https?://|spotify:)\S+", str(besedilo or "")):
        kandidat = m.group(0).rstrip(".,)")
        if je_povezava(kandidat):
            return kandidat
    return ""


def _beri(naslov: str, youtube: bool = False, telo: Optional[dict] = None, cas: float = 15.0) -> str:
    glave = {"User-Agent": _UA, "Accept-Language": "en"}
    if youtube:
        # Brez tega piskotka YouTube v EU namesto seznama vrne stran za soglasje ("samo nujni", nic osebnega).
        glave["Cookie"] = "SOCS=CAI"
    podatki = None
    if telo is not None:
        podatki = json.dumps(telo).encode("utf-8")
        glave["Content-Type"] = "application/json"
    zahteva = urllib.request.Request(naslov, data=podatki, headers=glave)
    with urllib.request.urlopen(zahteva, timeout=cas) as odgovor:  # noqa: S310 - samo https naslovi zgoraj
        return odgovor.read(6_000_000).decode("utf-8", "replace")


def json_za(html: str, ime: str) -> Optional[dict]:
    """Objekt JSON, ki ga stran priredi spremenljivki (var ytInitialData = {...};)."""
    m = re.search(re.escape(ime) + r"\s*=\s*\{", html)
    if not m:
        return None
    od = m.end() - 1
    konec = html.find(";</script>", od)
    if konec < 0:
        return None
    try:
        return json.loads(html[od:konec])
    except ValueError:
        return None


def _besedilo(o: Any) -> str:
    if not isinstance(o, dict):
        return ""
    if o.get("simpleText"):
        return str(o["simpleText"])
    if o.get("content"):
        return str(o["content"])
    return "".join(str(r.get("text") or "") for r in (o.get("runs") or []) if isinstance(r, dict))


def iz_youtube(d: Any) -> dict:
    """Posnetki seznama iz podatkov strani; razume staro (playlistVideoRenderer) in novo obliko (lockupViewModel)."""
    izid = {"ime": "", "vnosi": [], "nadaljevanje": ""}

    def hodi(x: Any, globina: int) -> None:
        if globina > 60:
            return
        if isinstance(x, list):
            for v in x:
                hodi(v, globina + 1)
            return
        if not isinstance(x, dict):
            return
        meta = x.get("playlistMetadataRenderer")
        if isinstance(meta, dict) and not izid["ime"]:
            izid["ime"] = str(meta.get("title") or "")
        ukaz = x.get("continuationCommand")
        if isinstance(ukaz, dict) and "BROWSE" in str(ukaz.get("request") or "") and ukaz.get("token"):
            izid["nadaljevanje"] = str(ukaz["token"])
        stari = x.get("playlistVideoRenderer")
        novi = x.get("lockupViewModel")
        if isinstance(stari, dict) and stari.get("videoId"):
            izid["vnosi"].append({"id": str(stari["videoId"]), "naslov": _besedilo(stari.get("title")),
                                  "kanal": _besedilo(stari.get("shortBylineText")), "glasba": False})
            return
        if isinstance(novi, dict) and novi.get("contentId") and "VIDEO" in str(novi.get("contentType") or ""):
            m = ((novi.get("metadata") or {}).get("lockupMetadataViewModel") or {})
            try:
                kanal = m["metadata"]["contentMetadataViewModel"]["metadataRows"][0]["metadataParts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                kanal = None
            izid["vnosi"].append({"id": str(novi["contentId"]), "naslov": _besedilo(m.get("title")),
                                  "kanal": _besedilo(kanal),
                                  "glasba": '"imageName": "MUSIC"' in json.dumps(novi.get("contentImage") or {})})
            return
        for v in x.values():
            hodi(v, globina + 1)

    hodi(d, 0)
    izid["vnosi"] = [v for v in izid["vnosi"] if v["naslov"]]
    return izid


def _youtube_skladba(v: dict) -> dict:
    naslov = v["naslov"]
    kanal = re.sub(r"( - Topic|VEVO)$", "", v.get("kanal") or "").strip()
    i = naslov.find(" - ")
    if 0 < i < len(naslov) - 3:
        izvajalec, naslov_cist = naslov[:i].strip(), naslov[i + 3:].strip()
    else:
        izvajalec, naslov_cist = kanal, naslov
    return {"naslov": naslov_cist or naslov, "izvajalec": izvajalec or "YouTube", "youtube": v["id"],
            "slika": "https://i.ytimg.com/vi/%s/mqdefault.jpg" % v["id"], "sekund": 0}


def _uvozi_youtube(ident: str) -> Optional[dict]:
    html = _beri("https://www.youtube.com/playlist?list=%s&hl=en" % ident, youtube=True)
    podatki = json_za(html, "ytInitialData")
    if podatki is None:
        return None
    prva = iz_youtube(podatki)
    skladbe: dict[str, dict] = {}
    for v in prva["vnosi"]:
        skladbe.setdefault(v["id"], v)
    m = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
    razlicica = m.group(1) if m else _RAZLICICA
    zeton = prva["nadaljevanje"]
    krogov = 0
    while zeton and len(skladbe) < NAJVEC and krogov < 6:
        krogov += 1
        try:
            o = json.loads(_beri("https://www.youtube.com/youtubei/v1/browse?prettyPrint=false", youtube=True,
                                 telo={"context": {"client": {"clientName": "WEB", "clientVersion": razlicica, "hl": "en"}},
                                       "continuation": zeton}))
        except Exception:
            break
        stran = iz_youtube(o)
        prej = len(skladbe)
        for v in stran["vnosi"]:
            skladbe.setdefault(v["id"], v)
        if len(skladbe) == prej:
            break
        zeton = stran["nadaljevanje"]
    if not skladbe:
        return None
    vnosi = list(skladbe.values())[:NAJVEC]
    return {"ime": prva["ime"] or "YouTube", "vir": "YouTube", "skladbe": [_youtube_skladba(v) for v in vnosi]}


def iz_spotify(html: str) -> Optional[dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        e = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError):
        return None
    try:
        ovitek = str(e["coverArt"]["sources"][0]["url"])
    except (KeyError, IndexError, TypeError):
        ovitek = ""
    album = e.get("type") == "album"
    skladbe = []
    for t in e.get("trackList") or []:
        if not isinstance(t, dict):
            continue
        naslov = str(t.get("title") or "").strip()
        izvajalec = str(t.get("subtitle") or "").replace(" ", " ").strip() or (str(e.get("subtitle") or "") if album else "")
        if naslov:
            skladbe.append({"naslov": naslov, "izvajalec": izvajalec, "youtube": "", "slika": ovitek,
                            "sekund": int(t.get("duration") or 0) // 1000})
    return {"ime": str(e.get("name") or e.get("title") or "Spotify"), "vir": "Spotify", "skladbe": skladbe[:NAJVEC]}


def uvozi(vnos: str) -> Optional[dict]:
    """{"ime", "vir", "skladbe": [{naslov, izvajalec, youtube, slika, sekund}]} ali None (ni javen, ni seznam)."""
    povezava = povezava_iz(vnos) or str(vnos or "").strip()
    yt = youtube_id(povezava)
    try:
        if yt:
            return _uvozi_youtube(yt)
        sp = spotify_id(povezava)
        if sp:
            izid = iz_spotify(_beri("https://open.spotify.com/embed/%s/%s" % sp))
            return izid if izid and izid["skladbe"] else None
    except Exception:
        return None
    return None


def zadetki_iskanja(d: Any) -> list[tuple[str, int]]:
    """(id, dolzina v sekundah) zadetkov iskanja po vrsti."""
    izhod: list[tuple[str, int]] = []

    def sekunde(t: str) -> int:
        deli = [p for p in str(t or "").strip().split(":") if p.isdigit()]
        if len(deli) not in (2, 3):
            return 0
        s = 0
        for p in deli:
            s = s * 60 + int(p)
        return s

    def hodi(x: Any, globina: int) -> None:
        if globina > 60 or len(izhod) >= 12:
            return
        if isinstance(x, list):
            for v in x:
                hodi(v, globina + 1)
            return
        if not isinstance(x, dict):
            return
        v = x.get("videoRenderer")
        if isinstance(v, dict) and v.get("videoId"):
            izhod.append((str(v["videoId"]), sekunde((v.get("lengthText") or {}).get("simpleText") or "")))
            return
        for y in x.values():
            hodi(y, globina + 1)

    hodi(d, 0)
    return izhod


def izberi_zadetek(z: list[tuple[str, int]], sekund: int, brez: tuple[str, ...] = ()) -> str:
    z = [x for x in z if x[0] not in brez]
    if not z:
        return ""
    if sekund <= 0:
        return z[0][0]
    blizu = [x for x in z[:6] if x[1] > 0 and abs(x[1] - sekund) <= 12]
    if blizu:
        return min(blizu, key=lambda x: abs(x[1] - sekund))[0]
    # Zamenjava zavrnjenega posnetka: brez ujemanja dolzine raje nic kot poljuben posnetek (odziv, priredba).
    return "" if brez else z[0][0]


def najdi(naslov: str, izvajalec: str, sekund: int = 0, brez: tuple[str, ...] = ()) -> str:
    """Id posnetka za skladbo (prvi zadetki iskanja, najblizji po dolzini); [brez]: posnetki, ki jih ne zelimo."""
    poizvedba = ("%s %s" % (izvajalec or "", naslov or "")).strip()
    if not poizvedba:
        return ""
    try:
        podatki = json.loads(_beri("https://www.youtube.com/youtubei/v1/search?prettyPrint=false", youtube=True,
                                   telo={"context": {"client": {"clientName": "WEB", "clientVersion": _RAZLICICA, "hl": "en"}},
                                         "query": poizvedba}))
    except Exception:
        try:
            podatki = json_za(_beri("https://www.youtube.com/results?search_query=%s&hl=en"
                                    % urllib.parse.quote_plus(poizvedba), youtube=True), "ytInitialData")
        except Exception:
            return ""
    return izberi_zadetek(zadetki_iskanja(podatki), int(sekund or 0), brez)
