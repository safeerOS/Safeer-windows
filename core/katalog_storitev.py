"""Razsirjeni katalog storitev za Sporocila (klepeti, posta, AI asistenti) iz ferdium-recipes (MIT) - SAMO podatki.

Pravilo »brez receptov za posamezne strani« (ROADMAP.md, CONTRIBUTING.md): iz ferdium-recipes so vzeti le ime, zacetni
naslov in ociscena ikona SVG (core/ferdium_katalog/katalog-sporocila.json, izdela tools/izdelaj_katalog_sporocil.py).
Kode receptov (webview.js) ni nikjer. Licenca in vir: core/ferdium_katalog/LICENSE in polje »vir« v JSON.

Izmerjeni katalog ostane core/spletni_klepeti.KATALOG (lastnik, 15. 10. 2026, WebKitGTK 2.54.1). Ta katalog:
  * da ikono storitvam izmerjenega kataloga brez omrezja (»obstojeci«) - odprtje kataloga v carovniku se vedno ne klice
    strani storitev (os_kanali_sporocil.katalog);
  * doda neizmerjene storitve (izmerjeno=False), ki jih spletni_klepeti.po_id najde, ce jih ni v KATALOG - kanal se lahko
    doda po id (Kanali.dodaj(katalog=...)). V carovniku (za_vmesnik) jih NI: kdaj jih pokazati, odloci lastnik.
Vsak vnos se ob branju znova preveri: naslov s spletni_klepeti.preveri_naslov, ikona z varna_svg.ocisti (ikona, ki se
ob ponovnem ciscenju spremeni, ni ista kot ob izdelavi - zavrne se). Manjkajoca ali pokvarjena datoteka = prazen katalog.
"""
from __future__ import annotations

import base64
import json
import os
import re

from core import spletni_klepeti, varna_svg

AI = "ai"
VRSTE = (spletni_klepeti.KLEPET, spletni_klepeti.POSTA, AI)
POT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ferdium_katalog", "katalog-sporocila.json")
NAJVEC_DATOTEKA = 4_000_000
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_predpomnilnik: dict = {}


def _preveri(vnos, izmerjeni: set):
    if not isinstance(vnos, dict) or not _ID.match(str(vnos.get("id") or "")):
        return None
    if vnos.get("vrsta") not in VRSTE or (vnos.get("vir") or {}).get("licenca") != "MIT":
        return None
    try:
        splet = spletni_klepeti.preveri_naslov(vnos.get("splet"))
    except spletni_klepeti.NeveljavenNaslov:
        return None
    ikona = str(vnos.get("ikona_svg") or "")
    if ikona:
        try:
            if varna_svg.ocisti(ikona) != ikona:
                ikona = ""
        except varna_svg.NevarnaSvg:
            ikona = ""
    obstojeci = str(vnos.get("obstojeci") or "")
    if vnos["id"] in izmerjeni:
        obstojeci = vnos["id"]
    return {"id": vnos["id"], "ime": " ".join(str(vnos.get("ime") or vnos["id"]).split())[:spletni_klepeti.NAJDALJSE_IME],
            "vrsta": vnos["vrsta"], "splet": splet, "prenos": "", "ikona_svg": ikona, "izmerjeno": False,
            "obstojeci": obstojeci if obstojeci in izmerjeni else "", "vir": dict(vnos.get("vir") or {})}


def nalozi(pot: str = "") -> list:
    """Preverjeni vnosi (predpomnjeni do spremembe datoteke). Napaka pri branju = []."""
    pot = pot or POT
    try:
        st = os.stat(pot)
    except OSError:
        return []
    kljuc = (pot, st.st_mtime_ns, st.st_size)
    if _predpomnilnik.get("kljuc") == kljuc:
        return _predpomnilnik["vnosi"]
    vnosi = []
    try:
        if st.st_size > NAJVEC_DATOTEKA:
            raise ValueError("velikost")
        with open(pot, encoding="utf-8") as f:
            podatki = json.load(f)
        if podatki.get("oblika") != 1 or (podatki.get("vir") or {}).get("licenca") != "MIT":
            raise ValueError("oblika")
        izmerjeni = {k["id"] for k in spletni_klepeti.KATALOG}
        videni = set()
        for surovo in podatki.get("katalog") or []:
            v = _preveri(surovo, izmerjeni)
            if v is not None and v["id"] not in videni:
                videni.add(v["id"])
                vnosi.append(v)
    except (OSError, ValueError, TypeError, AttributeError):
        vnosi = []
    _predpomnilnik.update(kljuc=kljuc, vnosi=vnosi)
    return vnosi


def dodatni(pot: str = "") -> list:
    """Storitve, ki jih v izmerjenem katalogu ni."""
    return [v for v in nalozi(pot) if not v["obstojeci"]]


def po_id(kid: str, pot: str = ""):
    return next((dict(v) for v in dodatni(pot) if v["id"] == kid), None)


def ikona(kid: str, pot: str = "") -> str:
    """Ikona storitve kot data URL (za <img src>) - za dodatno storitev ali za izmerjeno (»obstojeci«); sicer ""."""
    if not kid:
        return ""
    for v in nalozi(pot):
        if v["ikona_svg"] and (v["obstojeci"] == kid or (v["id"] == kid and not v["obstojeci"])):
            return "data:image/svg+xml;base64," + base64.b64encode(v["ikona_svg"].encode("utf-8")).decode("ascii")
    return ""
