"""Oznaka kakovosti izdaje ob imenu filma (CAM, TS, SD, HD, Full HD, 4K) - ista pravila kot Android
(KakovostPravila.Oznaka, lastnik 28. 10. 2026, razdelek 5). Na namizju jo zdaj prvi uporabi filter vira Usenet
(core/filter_vira_pravila.oznaka): znacka kartice je iz izdaj vira filtra, nikoli iz kataloga ali drugih virov.
Ciste odlocitve brez omrezja (preizkus tests/test_filter_vira_pravila.py).
"""
from __future__ import annotations

import enum
import re
from typing import Iterable, Optional


class Oznaka(enum.Enum):
    """[napis] na kartici, [rang] za »najboljso znano«, [opozorilo] = posnetek iz kina (CAM, TS) v opozorilni barvi."""
    CAM = ("CAM", 1, True)
    TS = ("TS", 2, True)
    SD = ("SD", 3, False)
    HD = ("HD", 4, False)
    FULL_HD = ("Full HD", 5, False)
    UHD = ("4K", 6, False)

    def __init__(self, napis: str, rang: int, opozorilo: bool) -> None:
        self.napis = napis
        self.rang = rang
        self.opozorilo = opozorilo

    @classmethod
    def iz_napisa(cls, napis: Optional[str]) -> Optional["Oznaka"]:
        return next((o for o in cls if o.napis == napis), None)


_CAM = {"cam", "camrip", "hdcam", "hqcam", "newcam", "camhd"}
_TS = {"ts", "hdts", "telesync", "tc", "hdtc", "telecine", "pdvd", "predvd", "tsrip", "hdtsrip"}
_UHD = {"2160p", "2160", "4k", "uhd", "4kuhd", "uhd4k"}
_FHD = {"1080p", "1080i", "1080", "fhd", "fullhd"}
_HD = {"720p", "720", "hd"}
_SD = {"480p", "480", "576p", "576", "360p", "sd", "dvdrip", "dvdscr", "xvid"}
#: Koncnica datoteke ».ts« (MPEG-TS) ni telesync.
_KONCNICA_TS = re.compile(r"\.ts(?=$|[\s)\]])")
_LOCILA = re.compile(r"[^a-z0-9]+")


def oznaka(ime: str) -> Optional[Oznaka]:
    """Oznaka iz imena izdaje. CAM in TS imata prednost pred locljivostjo (»HDCAM 1080p« je CAM). Brez znane oznake
    None (nic ne ugibamo)."""
    besedilo = _KONCNICA_TS.sub(" ", str(ime or "").lower())
    besedilo = re.sub(r"full[\s._-]*hd", " fullhd ", besedilo)
    besedilo = re.sub(r"4k[\s._-]*uhd", " 4k ", besedilo)
    besede = {b for b in _LOCILA.split(besedilo) if b}
    for mnozica, o in ((_CAM, Oznaka.CAM), (_TS, Oznaka.TS), (_UHD, Oznaka.UHD), (_FHD, Oznaka.FULL_HD),
                       (_HD, Oznaka.HD), (_SD, Oznaka.SD)):
        if besede & mnozica:
            return o
    return None


def najboljsa(imena: Iterable[str]) -> Optional[Oznaka]:
    """Najboljsa oznaka med izdajami (najvisji rang); CAM samo, ce nic boljsega ni znano."""
    znane = [o for o in (oznaka(i) for i in imena) if o is not None]
    return max(znane, key=lambda o: o.rang) if znane else None


def napis_kartice(o: Oznaka) -> str:
    """»★ 4K« za oznako iz izdaj, opozorilo »⚠ CAM«."""
    return ("⚠ " if o.opozorilo else "★ ") + o.napis
