"""Izbira predvajalnega pogona (pravilo: nadzorovan rezervni pogon, izbira je vedno v dnevniku).

Vrstni red: libmpv (SafeerMpvPogon) -> QtMultimedia (SafeerQtPogon). Nikoli tiho: vsak razlog za
preskok gre v dnevnik in v IZBRANO (za diagnostiko v aplikaciji).
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("safeer.pogon")
IZBRANO: dict = {"pogon": None, "razlog": None, "libmpv": None}


def izberi_pogon() -> str:
    """Vrne 'mpv' ali 'qt'. Spostuje SAFEER_POGON=mpv|qt (za preizkuse), sicer preveri libmpv."""
    zelja = (os.environ.get("SAFEER_POGON") or "").strip().lower()
    if zelja in ("mpv", "qt"):
        IZBRANO.update(pogon=zelja, razlog=f"SAFEER_POGON={zelja}")
        _log.info("pogon: %s (zahtevano z okoljem)", zelja)
        if zelja == "qt":
            return "qt"
    try:
        from . import safeer_mpv_pogon
        na_voljo = safeer_mpv_pogon.libmpv_na_voljo()
        IZBRANO["libmpv"] = dict(safeer_mpv_pogon.STANJE)
    except Exception as e:  # pragma: no cover
        na_voljo = False
        IZBRANO["libmpv"] = {"napaka": repr(e)}
    if na_voljo:
        IZBRANO.update(pogon="mpv", razlog="libmpv nalozen")
        _log.info("pogon: mpv (libmpv %s, msvcp140 %s)", IZBRANO["libmpv"].get("mapa"), IZBRANO["libmpv"].get("msvcp140_razlicica"))
        return "mpv"
    razlog = (IZBRANO["libmpv"] or {}).get("napaka") or "libmpv-2.dll ni najden"
    IZBRANO.update(pogon="qt", razlog=f"rezerva: {razlog}")
    _log.warning("pogon: qt (REZERVA) - %s", razlog)
    return "qt"


def ustvari_pogon(sprememba=None, konec=None, napaka=None):
    """Ustvari izbrani pogon z enotnim API. mpv: SafeerMpvPogon(cb...); qt: SafeerQtPogon (Qt signali)."""
    if izberi_pogon() == "mpv":
        from .safeer_mpv_pogon import SafeerMpvPogon
        return SafeerMpvPogon(sprememba, konec, napaka)
    from .safeer_qt_pogon import SafeerQtPogon
    p = SafeerQtPogon()
    # SafeerQtPogon sporoca prek Qt signalov; ovijemo v iste povratne klice, ce so podani.
    try:
        if sprememba is not None:
            p.stanje_spremenjeno.connect(lambda d: sprememba(d))
        if konec is not None:
            p.koncano.connect(lambda *a: konec())
        if napaka is not None and hasattr(p, "napaka"):
            p.napaka.connect(lambda s="": napaka(str(s)))
    except Exception as e:
        _log.debug("qt pogon signali: %s", e)
    return p
