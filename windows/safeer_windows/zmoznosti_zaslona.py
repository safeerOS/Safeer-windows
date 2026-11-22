"""Zmoznosti televizorja iz screen.start (codecs, maxsize) za NavidezniZaslon.zacni_sejo.

Enako kot core/link_daljinec.py (_zmoznosti_zaslona): Windows paketa linuxovega daljinca
brskalnika ne uvaza, zato je funkcija tu prepisana z istimi pravili validacije.
"""

from __future__ import annotations

#: Enako kot core/link_daljinec.py: "codecs" najvec toliko nizov, vsak najvec toliko znakov.
KODEKI_NAJVEC, KODEK_NAJVEC_ZNAKOV = 8, 16


def zmoznosti_zaslona(parametri) -> dict:
    """Enako kot core/link_daljinec.py: izrecne zmoznosti za zacni_sejo (kodeki=, najvecja=).

    "codecs" velja samo kot seznam (list) z najvec KODEKI_NAJVEC nizi (str) dolzine do
    KODEK_NAJVEC_ZNAKOV; "maxsize" samo kot slovar (dict). Kar ni tako, se prezre.
    """
    dodatno: dict = {}
    if not isinstance(parametri, dict):
        # Ni slovar: nic izrecnega, klic ostane kot doslej
        return dodatno
    kodeki = parametri.get("codecs")
    if (isinstance(kodeki, list) and len(kodeki) <= KODEKI_NAJVEC
            and all(isinstance(k, str) and len(k) <= KODEK_NAJVEC_ZNAKOV for k in kodeki)):
        dodatno["kodeki"] = list(kodeki)
    najvecja = parametri.get("maxsize")
    if isinstance(najvecja, dict):
        dodatno["najvecja"] = dict(najvecja)
    return dodatno


def zacni_sejo_s_parametri(navidezni, posiljatelj, kakovost, parametri):
    """Klic navidezni.zacni_sejo iz screen.start; brez veljavnih kljucev natanko kot doslej."""
    return navidezni.zacni_sejo(posiljatelj, kakovost=kakovost, **zmoznosti_zaslona(parametri))
