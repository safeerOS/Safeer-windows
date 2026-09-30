"""Nadaljuj tam, kjer si koncal (samostojni predvajalnik in Medijski center): zadnji polozaj za vsak
naslov/datoteko, samo na tej napravi. Datoteka poleg nastavitev predvajalnika (nadaljuj.json).

Pravila (kot v Safeer OS na Androidu): shranimo, ko je predvajanih vec kot MIN_SEKUND in ostane vec kot
KONEC_SEKUND do konca; ob koncu (ali blizu konca) vnos izbrisemo; najvec MAX vnosov, najstarejsi odpadejo.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from . import predvajalnik_nastavitve as N

MIN_SEKUND = 10.0
KONEC_SEKUND = 30.0
MAX = 500


def pot() -> str:
    return os.path.join(os.path.dirname(N.pot()), "nadaljuj.json")


def nalozi(p: Optional[str] = None) -> dict:
    try:
        with open(p or pot(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def shrani(d: dict, p: Optional[str] = None) -> bool:
    p = p or pot()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        return True
    except OSError:
        return False


def zabelezi(d: dict, uri: str, polozaj: float, trajanje: float) -> bool:
    """Posodobi vnos; vrne True, ce se je slovar spremenil."""
    if not uri or not trajanje or trajanje <= 0:
        return False
    if polozaj < MIN_SEKUND or polozaj > trajanje - KONEC_SEKUND:
        return d.pop(uri, None) is not None
    d[uri] = {"polozaj": round(float(polozaj), 1), "trajanje": round(float(trajanje), 1), "cas": int(time.time())}
    if len(d) > MAX:
        for k in sorted(d, key=lambda k: d[k].get("cas", 0))[: len(d) - MAX]:
            d.pop(k, None)
    return True


def polozaj_za(d: dict, uri: str) -> float:
    v = d.get(uri) if uri else None
    try:
        return float(v["polozaj"]) if v and float(v["polozaj"]) >= MIN_SEKUND else 0.0
    except (KeyError, TypeError, ValueError):
        return 0.0


def razclleni_cas(besedilo: str) -> Optional[float]:
    """'1:23:45', '23:45', '90', '1h5m', '12.5' -> sekunde; None, ce ni razpoznavno."""
    t = (besedilo or "").strip().lower().replace(",", ".")
    if not t:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s?)?", t)
    if m and any(m.groups()) and not re.search(r":", t):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    deli = t.split(":")
    if not all(re.fullmatch(r"\d+(?:\.\d+)?", x) for x in deli) or len(deli) > 3:
        return None
    sek = 0.0
    for x in deli:
        sek = sek * 60 + float(x)
    return sek


class Sledilec:
    """Skupna logika za gostitelje (Qt widget, Medijski center): belezi polozaj vsakih ~5 s in takoj ob
    premoru/zaprtju, pogonu da nadaljevanje(uri) in ob_koncu_datoteke(uri). Izklop: SAFEER_NADALJUJ=0."""

    INTERVAL = 5.0

    def __init__(self, vklop: Optional[bool] = None):
        self.vklop = (os.environ.get("SAFEER_NADALJUJ", "1") != "0") if vklop is None else bool(vklop)
        self.d: dict = {}
        self._zadnjic = 0.0
        self._umazano = False
        self._zadnje_stanje = None

    def povezi(self, pogon) -> None:
        if not self.vklop or pogon is None:
            return
        self.d = nalozi()
        pogon.nadaljevanje = lambda uri: polozaj_za(self.d, uri)
        pogon.ob_koncu_datoteke = self.pozabi

    def pozabi(self, uri: str) -> None:
        if self.d.pop(uri, None) is not None:
            self._umazano = True
            self.shrani()

    def ob_podatkih(self, p: dict) -> None:
        """Klici ob vsakem sporocilu pogona (GUI nit)."""
        stanje = (p or {}).get("stanje")
        takoj = stanje == "premor" and self._zadnje_stanje != "premor"
        self._zadnje_stanje = stanje
        self.zabelezi(p, takoj=takoj)

    def zabelezi(self, p: dict, takoj: bool = False) -> None:
        if not self.vklop or not p or p.get("stanje") == "ustavljeno":
            return
        zdaj = time.monotonic()
        if not takoj and zdaj - self._zadnjic < self.INTERVAL:
            return
        self._zadnjic = zdaj
        if zabelezi(self.d, str(p.get("uri") or ""), float(p.get("polozaj") or 0), float(p.get("trajanje") or 0)):
            self._umazano = True
        if takoj or self._umazano:
            self.shrani()

    def shrani(self) -> None:
        if self._umazano and shrani(self.d):
            self._umazano = False
