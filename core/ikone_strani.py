"""Ikone spletnih strani za zacetno stran Splet: prenesene NEPOSREDNO s strani (brez tujih storitev za ikone),
shranjene v predpomnilnik (~/.cache/safeer-os/ikone), da se prenesejo samo enkrat. Ista logika kot na Windows."""
import hashlib
import html.parser
import json
import os
import urllib.parse
from typing import Dict, List, Tuple

# XDG_CACHE_HOME: Safeer Browser v Flatpaku (od 1.0.127 brez doma) pise samo v svojo zasebno mapo; Safeer OS in .deb
# ostaneta na ~/.cache.
MAPA = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "safeer-os",
                    "ikone")


class _IkonePovezave(html.parser.HTMLParser):
    """Poisce <link rel="icon|apple-touch-icon" href sizes> v glavi strani."""

    def __init__(self) -> None:
        super().__init__()
        self.ikone: List[Tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        if "icon" not in rel or not a.get("href"):
            return
        velikost = 0
        for del_ in a.get("sizes", "").lower().split():
            if "x" in del_ and del_.split("x")[0].isdigit():
                velikost = max(velikost, int(del_.split("x")[0]))
        if "apple-touch-icon" in rel and not velikost:
            velikost = 180
        if a.get("href", "").lower().endswith(".svg") or "svg" in a.get("type", ""):
            velikost = max(velikost, 256)
        self.ikone.append((velikost or 16, a["href"]))


def _prenesi(url: str, meja: int, cas: float = 6.0) -> Tuple[bytes, str]:
    import urllib.request
    zahteva = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                                                   "Accept": "*/*"})
    with urllib.request.urlopen(zahteva, timeout=cas) as odziv:
        vrsta = (odziv.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return odziv.read(meja + 1)[:meja + 1], vrsta


def ikona_strani(url: str) -> str:
    """Ikona spletne strani kot data URL, prenesena NEPOSREDNO s te strani (brez tujih storitev za ikone).

    Najprej najvecja ikona iz <link rel=icon/apple-touch-icon>, sicer /apple-touch-icon.png in /favicon.ico.
    Prazen niz, ce ikone ni (ploscica potem pokaze crko)."""
    import base64
    try:
        razcl = urllib.parse.urlsplit(url)
        if razcl.scheme not in ("http", "https") or not razcl.hostname:
            return ""
        koren = f"{razcl.scheme}://{razcl.netloc}"
        kandidati: List[str] = []
        try:
            vsebina, _ = _prenesi(url, 400_000)
            iskalnik = _IkonePovezave()
            iskalnik.feed(vsebina.decode("utf-8", "ignore"))
            for _, href in sorted(iskalnik.ikone, key=lambda x: -x[0]):
                kandidati.append(urllib.parse.urljoin(url, href))
        except Exception:
            pass
        kandidati += [koren + "/apple-touch-icon.png", koren + "/favicon.ico"]
        for kandidat in kandidati:
            if not kandidat.startswith(("http://", "https://")):
                continue
            try:
                podatki, vrsta = _prenesi(kandidat, 300_000)
            except Exception:
                continue
            if not podatki or len(podatki) > 300_000:
                continue
            if not vrsta.startswith("image/"):
                if podatki[:4] == b"\x89PNG":
                    vrsta = "image/png"
                elif podatki[:4] == b"\x00\x00\x01\x00":
                    vrsta = "image/x-icon"
                elif b"<svg" in podatki[:400].lower():
                    vrsta = "image/svg+xml"
                else:
                    continue
            return f"data:{vrsta};base64," + base64.b64encode(podatki).decode("ascii")
    except Exception:
        return ""
    return ""



def _pot(url: str) -> str:
    return os.path.join(MAPA, hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()[:24] + ".json")


def iz_predpomnilnika(url: str) -> str:
    try:
        with open(_pot(url), encoding="utf-8") as d:
            return str(json.load(d).get("ikona") or "")
    except (OSError, ValueError):
        return ""


def shrani(url: str, ikona: str) -> None:
    try:
        os.makedirs(MAPA, exist_ok=True)
        with open(_pot(url), "w", encoding="utf-8") as d:
            json.dump({"url": url, "ikona": ikona}, d)
    except OSError:
        pass


def z_ikonami(portali: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """Portalom doda ikone iz predpomnilnika; vrne se seznam naslovov brez ikone."""
    izid, manjkajo = [], []
    for p in portali or []:
        p = dict(p)
        url = str(p.get("url") or "")
        if url and not str(p.get("favicon") or "").startswith("data:"):
            ikona = iz_predpomnilnika(url)
            if ikona:
                p["favicon"] = ikona
            else:
                manjkajo.append(url)
        izid.append(p)
    return izid, manjkajo
