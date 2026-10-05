"""Zacetna mapa za okna »Odpri« in »Izberi mapo«.

Qt brez podane mape odpre okno v delovni mapi procesa - pri Safeer OS je to mapa programa
(%LOCALAPPDATA%\\SafeerOS\\app; videno 5. 10. 2026 pri »Pošlji datoteko«). Uporabnik tam nima kaj iskati:
okno se odpre v mapi, iz katere je za isti namen izbiral nazadnje (v tej seji), sicer v njegovih dokumentih ali videih.
"""

from __future__ import annotations

import os
from typing import Dict

#: namen okna (npr. "poslji", "deli-mapo", "predvajalnik") -> mapa zadnje izbire v tej seji
_ZADNJA: Dict[str, str] = {}

_VRSTE = {"dokumenti": "DocumentsLocation", "videi": "MoviesLocation", "doma": "HomeLocation"}


def zacetna(namen: str, vrsta: str = "dokumenti") -> str:
    """Mapa, v kateri naj se okno odpre: zadnja izbrana za ta namen, sicer uporabnikova mapa te vrste, sicer domaca."""
    zadnja = _ZADNJA.get(namen, "")
    if zadnja and os.path.isdir(zadnja):
        return zadnja
    try:
        from PySide6.QtCore import QStandardPaths
        mapa = QStandardPaths.writableLocation(getattr(QStandardPaths, _VRSTE.get(vrsta, "HomeLocation")))
        if mapa and os.path.isdir(mapa):
            return mapa
    except Exception:  # noqa: BLE001 - brez Qt ali brez take mape ostane domaca
        pass
    return os.path.expanduser("~")


def zapomni(namen: str, pot: str) -> None:
    """Po izbiri: mapa izbrane datoteke (ali izbrana mapa sama) je zacetna za naslednje okno z istim namenom."""
    pot = str(pot or "")
    mapa = pot if os.path.isdir(pot) else os.path.dirname(pot)
    if mapa and os.path.isdir(mapa):
        _ZADNJA[namen] = mapa
