"""Windows: racunalnik naj ne zaspi sam, dokler Safeer predvaja (SAFEER-ZNANJE Z4608, zapisnik 25. 10. W3).

Zaledje Windows (zahteve moci kernel32 PowerCreateRequest + PowerSetRequest, rezerva SetThreadExecutionState) je od
25. 10. 2026 v skupni core/budnost.py (BudnostWindows, Kernel32 - Safeer-linux 5a5a5ea, skupna-koda.json »skupne«):
ista koda kot na Linuxu, Budnost() tam izbere zaledje po platformi. Ta modul ima samo se pomocnike predvajalnikov
Windows (Medijski center z libmpv in LibVLC, samostojni predvajalnik): ena budnost na proces, zastavice iz podatkov
pogona ter klica ob spremembi stanja in ob ustavitvi.

SPANJE = samodejno spanje ob nedejavnosti; ZASLON = se ugasanje zaslona. Zaprt pokrov, gumb za vklop in rocno spanje
delujejo kot vedno (prenosnik v torbi mora zaspati).
"""
from __future__ import annotations

import logging
from typing import Optional

# Isti vmesnik kot prej (predvajalniki, windows/tests/test_budnost_win.py): razred, ovoj kernel32 in konstante so v
# skupni kodi, tu jih samo uvozimo.
from core.budnost import (  # noqa: F401
    ES_CONTINUOUS, ES_DISPLAY_REQUIRED, ES_SYSTEM_REQUIRED, SPANJE, ZAHTEVA_SISTEM, ZAHTEVA_ZASLON, ZASLON,
    BudnostWindows, Kernel32, dejavno, dotik, tip_reason_context)

#: Prej razred tega modula; zdaj zaledje Windows iz core.budnost (nastavi, po_dejavnosti, sprosti_vse, stanje).
Budnost = BudnostWindows

__all__ = ["Budnost", "BudnostWindows", "Kernel32", "SPANJE", "ZASLON", "budnost", "dejavno", "dotik",
           "ob_predvajanju", "sprosti", "zastavice_predvajanja"]

_log = logging.getLogger("safeer.budnost")

_skupna: Optional[BudnostWindows] = None


def budnost() -> BudnostWindows:
    """Ena budnost na proces (Medijski center, samostojni predvajalnik)."""
    global _skupna
    if _skupna is None:
        _skupna = BudnostWindows("Safeer")
    return _skupna


def zastavice_predvajanja(p: Optional[dict]) -> int:
    """Podatki pogona -> zastavice: predvaja -> SPANJE, ce ima posnetek sliko, se ZASLON (kot Linux
    _budnost_predvajanja). Premor, konec in napaka -> 0. Slika: steze.slika (izbrana video sled, ki ni naslovnica
    albuma), sicer vrsta vnosa."""
    p = p or {}
    if p.get("stanje") != "predvaja":
        return 0
    steze = p.get("steze") or {}
    if "slika" in steze:
        slika = bool(steze.get("slika"))
    else:
        slika = p.get("vrsta") in ("video", "tv")
    return SPANJE | (ZASLON if slika else 0)


def ob_predvajanju(razlog: str, p: Optional[dict]) -> None:
    """Predvajalnik jo poklice ob vsaki spremembi stanja (nit vmesnika). Napaka nikoli ne ustavi predvajanja."""
    try:
        budnost().nastavi(razlog, zastavice_predvajanja(p), "Safeer predvaja")
    except Exception as e:  # noqa: BLE001
        _log.debug("budnost: %s", e)


def sprosti(razlog: str) -> None:
    """Predvajalnik je ustavljen ali zaprt."""
    try:
        budnost().nastavi(razlog, 0)
    except Exception as e:  # noqa: BLE001
        _log.debug("budnost: %s", e)
