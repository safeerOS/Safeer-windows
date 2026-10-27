"""Lasten ponudnik Usenet v Safeer OS za Windows (naloga 44; okno kot Linux naloga 114, material Grok naloga 112).

Vsa logika je v skupnem jedru (core/usenet_vezava.py iz Safeer-linux, skupna-koda.json): most okna (stanje, shrani,
preveri, odstrani s KODAMI iz usenet_vezava.KODE), geslo samo v sistemski zbirki (core/sporocila/skrivnosti.py =
Upravitelj poverilnic), preverba 1/min in zapah, predvajanje NZB z lastnim pogonom (Vezava.predvajaj na 127.0.0.1 z
zetonom). Tu je samo vezava na Windows:

- Nastavitev ponudnika (brez gesla) je v %LOCALAPPDATA%\\SafeerOS, ne v %APPDATA% (Roaming): Roaming se v domeni kopira
  na streznik, to bi bil prenos streznika in uporabniskega imena zunaj ozjega kroga (Grok 112).
- Ena vezava za okno in predvajanje (MediaCenter.debrid.lastni_usenet): en film naenkrat, »Pozabi« ustavi tudi
  predvajanje. Po spremembi se znova zapise izvoz virov za naprave (del »ozji«, brez gesla).
- Klic mostu na Windows ze tece v delovni niti (SafeerOsWindow.obdelaj_klic), preverba torej nikoli na glavni niti.
"""
from __future__ import annotations

import os

from core import usenet_vezava


def pot_nastavitev() -> str:
    osnova = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(osnova, "SafeerOS", usenet_vezava.IME_DATOTEKE)


def vezi(media_center, pot: str = "") -> usenet_vezava.Vezava:
    """Vezava lastnega ponudnika za Medijski center (enkrat ob zagonu okna Safeer OS)."""
    vezava = usenet_vezava.za_pot(pot or pot_nastavitev())
    vezava.ob_spremembi = media_center._viri_zapisi_izvoz
    media_center.debrid.lastni_usenet = vezava
    return vezava


def most(media_center, a: object) -> dict:
    """mediaUsenetPonudnik: odgovor je vedno slovar s kodo, nikoli geslo ali besedilo izjeme."""
    vezava = getattr(media_center.debrid, "lastni_usenet", None)
    if vezava is None:
        vezava = vezi(media_center)
    return usenet_vezava.most(vezava, list(a or []) if isinstance(a, (list, tuple)) else [])
