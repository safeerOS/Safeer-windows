"""Izbira najboljsega toka brez uporabnikovega klika: film se zacne takoj, seznam virov je le rocna moznost.

Ista pravila kot na Androidu (os/TokIzbira.kt), da se Safeer na vseh napravah odloca enako: "najboljsi" je tok,
ki ga TA naprava res predvaja (slika in zvok) in se zacne hitro - ne nujno najvecji.
"""
from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Zmoznosti:
    """Kaj naprava zmore. Racunalnik z libmpv dekodira vse (programsko), zato so privzeto vsi dekodirniki na voljo."""
    visina: int = 1080
    hevc: bool = True
    av1: bool = True
    hdr: bool = True          # mpv HDR preslika na zaslon SDR (tone mapping)
    dolby_vision: bool = True
    eac3: bool = True
    ac3: bool = True
    dts: bool = True
    truehd: bool = True


@dataclass(frozen=True)
class Opis:
    visina: int
    hevc: bool
    av1: bool
    hdr: bool
    dv: bool
    zvok: str
    slab_posnetek: bool
    gb: float


_V = ((2160, re.compile(r"2160p?|\b4k\b|\buhd\b")), (1440, re.compile(r"1440p")), (1080, re.compile(r"1080[pi]?|\bfhd\b|full[ .-]?hd")),
      (720, re.compile(r"720p?")), (480, re.compile(r"480p?|576p?|\bsd\b|dvdrip")), (360, re.compile(r"360p?|240p?")))
_HEVC = re.compile(r"x265|h[ .]?265|hevc")
_AV1 = re.compile(r"\bav1\b")
_DV = re.compile(r"\bdv\b|dolby[ .]?vision|\bdovi\b")
_HDR = re.compile(r"hdr")
_ZVOK = (("truehd", re.compile(r"true[ .-]?hd")), ("dts", re.compile(r"\bdts")), ("eac3", re.compile(r"\bddp|dd\+|e-?ac-?3|atmos")),
         ("ac3", re.compile(r"\bdd[ .]?[257]|\bac-?3\b|dolby digital")))
_SLAB = re.compile(r"\b(cam|hdcam|camrip|ts|hdts|telesync|tc|telecine|scr|screener)\b")
_VELIKOST = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gb|gib|mb|mib)")


_SEJALCI = re.compile("(?:\U0001F464|seed(?:er)?s?\\s*[:=]?)\\s*(\\d{1,6})")


_PODPIS_DATUM = re.compile(r"[?&]X-(?:Amz|Goog)-Date=(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", re.I)
_PODPIS_VELJA = re.compile(r"[?&]X-(?:Amz|Goog)-Expires=(\d{1,9})(?=&|$)", re.I)
_IZTEK_UNIX = re.compile(r"[?&](?:expires?|exp)=(\d{10})(?:\d{3})?(?=&|$)", re.I)
_IZTEK_ZETON = re.compile(r"[?&](?:hdnts|hdnea|hdntl|token)=(?:[^&]*?[~_-])?exp=(\d{10})", re.I)
_IZTEK_ISO = re.compile(r"[?&]se=(\d{4})-(\d{2})-(\d{2})T(\d{2})(?:%3A|:)(\d{2})(?:(?:%3A|:)(\d{2}))?Z", re.I)


def _epoha(deli) -> Optional[int]:
    try:
        return calendar.timegm(tuple(int(x or 0) for x in deli) + (0, 0, 0))
    except (ValueError, OverflowError):
        return None


def velja_se(naslov: str, zdaj_s: float) -> Optional[int]:
    """Koliko sekund je naslov toka se veljaven, kadar to pove sam: podpisana, casovno omejena povezava do shrambe v
    oblaku ali CDN (X-Amz-Date + X-Amz-Expires, X-Goog-*, Expires=<cas>, se=<datum>, exp= v zetonu). None = naslov roka
    ne pove (trajna povezava ali neznan zapis). Negativno = ze potekla.

    Zakaj (3. 10. 2026: "prvi vir ponavadi ne deluje, sele naslednji"): dodatki take povezave hranijo v predpomnilniku
    in jih ponudijo tudi, ko so ze potekle - streznik potem odgovori 403. Potekle povezave zato sploh ne poskusamo, med
    enakovrednima tokoma pa ima prednost tisti brez roka. Ista pravila kot TokIzbira.veljaSe na Androidu."""
    n = str(naslov or "")
    d = _PODPIS_DATUM.search(n)
    v = _PODPIS_VELJA.search(n) if d else None
    if d and v:
        e = _epoha(d.groups())
        return None if e is None else e + int(v.group(1)) - int(zdaj_s)
    d = _IZTEK_ISO.search(n)
    if d:
        e = _epoha(d.groups())
        return None if e is None else e - int(zdaj_s)
    m = _IZTEK_UNIX.search(n) or _IZTEK_ZETON.search(n)
    if not m:
        return None
    unix = int(m.group(1))
    # Samo verjeten cas izteka (2017-2100): parameter z istim imenom je lahko tudi kaj drugega.
    return unix - int(zdaj_s) if 1_500_000_000 <= unix <= 4_102_444_800 else None


def potekla(naslov: str, zdaj_s: float) -> bool:
    """Povezava, ki je po lastnem zapisu ze potekla (ali potece v minuti): streznik je ne bo vec dal."""
    v = velja_se(naslov, zdaj_s)
    return v is not None and v <= 60


def sejalci(besedilo: str) -> int:
    """Koliko sejalcev navaja opis torrenta ("\U0001F464 123", "Seeders: 12"); -1 = opis tega ne pove."""
    m = _SEJALCI.search(str(besedilo or "").lower())
    return int(m.group(1)) if m else -1


def opisi(besedilo: str) -> Opis:
    t = str(besedilo or "").lower()
    visina = next((v for v, vzorec in _V if vzorec.search(t)), 0)
    zvok = next((ime for ime, vzorec in _ZVOK if vzorec.search(t)), "")
    m = _VELIKOST.search(t)
    gb = 0.0
    if m:
        try:
            gb = float(m.group(1).replace(",", "."))
        except ValueError:
            gb = 0.0
        if m.group(2).startswith("m"):
            gb /= 1024.0
    return Opis(visina, bool(_HEVC.search(t)), bool(_AV1.search(t)), bool(_HDR.search(t)), bool(_DV.search(t)), zvok, bool(_SLAB.search(t)), gb)


def ocena(besedilo: str, z: Zmoznosti, velja_s: Optional[int] = None) -> int:
    """Vecja ocena = boljsi tok za to napravo. `velja_s`: koliko sekund je povezava se veljavna (velja_se); None = brez roka."""
    o = opisi(besedilo)
    v = o.visina or 700                      # neznana locljivost: med 720p in 480p
    tocke = v if v <= z.visina else z.visina - (v - z.visina) // 4
    if o.hevc and not z.hevc:
        tocke -= 3000
    if o.av1 and not z.av1:
        tocke -= 3000
    if o.dv and not z.dolby_vision:
        tocke -= 60 if o.hdr else 900
    if o.hdr and not z.hdr:
        tocke -= 150
    zvok_gre = {"truehd": z.truehd, "dts": z.dts, "eac3": z.eac3, "ac3": z.ac3}.get(o.zvok, True)
    if not zvok_gre:
        tocke -= 1200
    if o.slab_posnetek:
        tocke -= 800
    tocke -= int(min(o.gb, 40.0) * 4)        # med enakovrednimi se manjsa datoteka zacne hitreje
    # Torrent: zacetek predvajanja doloca roj, ne naprava (izmerjeno 3. 10. 2026). Kjer opis pove stevilo sejalcev,
    # ima podprt torrent prednost tudi pred eno stopnjo visjo locljivostjo; brez sejalcev je zadnji.
    s = sejalci(besedilo)
    if s == 0:
        tocke -= 2500
    elif 1 <= s <= 4:
        tocke -= 600
    elif 5 <= s <= 19:
        tocke -= 150
    elif s >= 20:
        tocke += min(60, s // 20)
    # Casovno omejena povezava: potekla ne dela (zadnja od vseh), tik pred iztekom se ustavi sredi filma (za drugimi
    # iste locljivosti); sicer ima med enakovrednima prednost trajna povezava.
    if velja_s is not None:
        tocke -= 6000 if velja_s <= 60 else 300 if velja_s < 20 * 60 else 15
    return tocke


def uredi(tokovi: Sequence[T], besedilo: Callable[[T], str], z: Zmoznosti,
          naslov: Optional[Callable[[T], str]] = None, zdaj_s: Optional[float] = None) -> List[T]:
    """Tokovi od najboljsega do najslabsega za to napravo; pri enaki oceni ostane vrstni red dodatka. Z `naslov` se
    uposteva tudi rok veljavnosti povezave (velja_se) ob casu `zdaj_s` (sekunde od 1970; privzeto zdaj)."""
    zdaj = time.time() if zdaj_s is None else zdaj_s
    ocene = [(-ocena(besedilo(t), z, velja_se(naslov(t), zdaj) if naslov else None), i) for i, t in enumerate(tokovi)]
    return [tokovi[i] for _, i in sorted(ocene)]
