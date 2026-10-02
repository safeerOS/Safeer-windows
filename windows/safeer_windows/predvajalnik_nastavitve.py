"""Nastavitve Safeer predvajalnika — skupne za samostojno aplikacijo (Windows, Linux) in Medijski center.

Dodatki: uporabnik SAM vnese naslove svojih Stremio dodatkov. Safeer ne prilaga nobenega
kataloga in nobenega dodatka; polje je orodje, kaj vanj vnese uporabnik, je njegova stvar.
- Stremio dodatek: naslov manifesta (https://.../manifest.json; tudi oblika stremio://... se pretvori).
Dodatkov Kodi ne ponujamo: Safeer jih ne more poganjati (pravilo: cesar ne moremo poganjati, ne ponujamo).
Prej shranjeni vnosi "kodi_dodatki" se ob naslednjem shranjevanju opustijo.
Datoteka: Windows %APPDATA%\\Safeer\\predvajalnik.json, Linux $XDG_CONFIG_HOME/safeer/predvajalnik.json.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

PRIVZETO: dict = {
    "stremio_dodatki": [],   # [{"naslov": "https://.../manifest.json", "ime": "..."}]
    "pogon": "samodejno",    # samodejno | mpv | qt
}

BESEDILA = {
    "stremio_naslov": "Stremio dodatek — sem vnesi naslov dodatka (konča se z /manifest.json)",
    "stremio_namig": "Primer: https://primer.si/moj-dodatek/manifest.json  ali  stremio://primer.si/moj-dodatek/manifest.json",
    "opomba": "Safeer ne prilaga katalogov ali dodatkov. Vneseš svoje; naslovi se shranijo samo na tej napravi.",
}


def pot() -> str:
    if sys.platform == "win32":
        osnova = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(osnova, "Safeer", "predvajalnik.json")
    osnova = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(osnova, "safeer", "predvajalnik.json")


def nalozi(p: Optional[str] = None) -> dict:
    p = p or pot()
    n = json.loads(json.dumps(PRIVZETO))
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in PRIVZETO:
                if k in d and type(d[k]) is type(PRIVZETO[k]):
                    n[k] = d[k]
    except (OSError, ValueError):
        pass
    n["stremio_dodatki"] = [x for x in n["stremio_dodatki"] if isinstance(x, dict) and x.get("naslov")]
    return n


def shrani(n: dict, p: Optional[str] = None) -> bool:
    p = p or pot()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        zacasna = p + ".tmp"
        with open(zacasna, "w", encoding="utf-8") as f:
            json.dump({k: n.get(k, PRIVZETO[k]) for k in PRIVZETO}, f, ensure_ascii=False, indent=1)
        os.replace(zacasna, p)
        return True
    except OSError:
        return False


# ---- preverjanje naslovov (brez omrezja) ----
def normaliziraj_stremio(vnos: str) -> tuple[Optional[str], str]:
    """(naslov, napaka). stremio://host/pot/manifest.json -> https://host/pot/manifest.json."""
    v = (vnos or "").strip()
    if not v:
        return None, "Vnesi naslov."
    if v.lower().startswith("stremio://"):
        v = "https://" + v[len("stremio://"):]
    d = urlsplit(v)
    if d.scheme not in ("http", "https") or not d.netloc:
        return None, "Naslov mora biti http(s) ali stremio://."
    if not d.path.lower().endswith("/manifest.json"):
        return None, "Naslov Stremio dodatka se mora končati z /manifest.json."
    return urlunsplit((d.scheme, d.netloc, d.path, d.query, "")), ""


def dodaj(n: dict, vrsta: str, vnos: str, ime: str = "") -> tuple[bool, str]:
    """vrsta: 'stremio'. Vrne (uspeh, sporocilo). Podvojene naslove zavrne."""
    if vrsta != "stremio":
        return False, "Neznana vrsta dodatka."
    naslov, napaka = normaliziraj_stremio(vnos); kljuc = "stremio_dodatki"
    if not naslov:
        return False, napaka
    if any(x.get("naslov") == naslov for x in n[kljuc]):
        return False, "Ta naslov je že dodan."
    n[kljuc].append({"naslov": naslov, "ime": (ime or "").strip()[:80]})
    return True, naslov


def odstrani(n: dict, vrsta: str, naslov: str) -> bool:
    if vrsta != "stremio":
        return False
    kljuc = "stremio_dodatki"
    prej = len(n[kljuc])
    n[kljuc] = [x for x in n[kljuc] if x.get("naslov") != naslov]
    return len(n[kljuc]) != prej
