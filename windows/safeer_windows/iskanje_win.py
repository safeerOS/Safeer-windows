"""Iskanje datotek po vseh uporabnikovih mapah na Windows - tudi tistih na drugem disku.

Lastnik 26. 10. 2026: »Safeer OS ne najde novih datotek«. Izmerjeno na testnem PC: Dokumenti, Namizje, Prenosi, Slike,
Glasba in Videi so prestavljeni na disk D: (User Shell Folders), domaca mapa je na C:. Skupni iskalnik
(core/os_iskalnik.py, enak kot na Linuxu) indeksira domaco mapo in namenoma ne hodi na drug disk - nova datoteka v
Dokumentih zato ni bila nikoli najdena (preizkus z novo datoteko: 0 zadetkov v lupi in v glavnem oknu).

Tu vsaka znana mapa zunaj domace mape dobi svoj indeks (isti razred core.os_iskalnik.Indeks, gradnja v ozadju), domaca
mapa ostane na skupnem indeksu. Zadetki vseh so razvrsceni skupaj z isto oceno kot v skupnem iskalniku; prva raven vsake
mape se pogleda v zivo (datoteka, shranjena po gradnji indeksa).
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from core import os_datoteke, os_iskalnik

#: Mapa, katere indeks se po skupnem cakanju se gradi: hoja po disku najvec toliko.
HOJA_BREZ_INDEKSA_S = 0.25
_indeksi: Dict[str, os_iskalnik.Indeks] = {}
_zaklep = threading.Lock()


def _pod(pot: str, koren: str) -> bool:
    p, k = os.path.normcase(os.path.abspath(pot)), os.path.normcase(os.path.abspath(koren))
    return p == k or p.startswith(k.rstrip("\\/") + os.sep)


def _vrsta_pogona(koren: str) -> int:
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetDriveTypeW(koren))
    except (AttributeError, OSError):
        return 0


#: GetDriveTypeW: omrezni pogon (preslikan disk, npr. Z: -> \\streznik\mapa).
DRIVE_REMOTE = 4


_POLNA_POT_POGONA = re.compile(r"[A-Za-z]:[\\/]")
_REZERVIRANA_IMENA = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                               | {"COM" + c for c in "123456789\u00b9\u00b2\u00b3"}
                               | {"LPT" + c for c in "123456789\u00b9\u00b2\u00b3"})


def _je_polna_pot_pogona(pot: str) -> bool:
    """True samo za polno pot na pogonu s crko (C:\\mapa, C:/mapa) - cisto besedilno, neodvisno od trenutne mape.
    Pregled 98, Ķ5 (26. 10. 2026): »D:.«, »D:..«, »D:mapa« in »\\mapa« je abspath razresil glede na TRENUTNO mapo
    (isti razred napake, ki ga je ujel CI z delovno mapo na D:); tok ADS (»:« za pogonom), ».«, »..«, sestavine s piko
    ali presledkom na koncu in rezervirana imena (NUL, COM1) niso mape."""
    if not isinstance(pot, str) or "\x00" in pot or not _POLNA_POT_POGONA.match(pot):
        return False
    if ":" in pot[2:]:
        return False
    for sestavina in re.split(r"[\\/]+", pot[3:]):
        if not sestavina:
            continue
        if sestavina in (".", "..") or sestavina[-1] in ". ":
            return False
        if sestavina.split(".", 1)[0].rstrip(" ").upper() in _REZERVIRANA_IMENA:
            return False
    return True


def lokalna_mapa(pot: str, vrsta_pogona: Callable[[str], int] = _vrsta_pogona) -> bool:
    """Ali smemo mapo indeksirati in po njej hoditi: ne pot UNC, ne omrezni pogon, ne koren diska. Pregled Grok 59 G3:
    znana mapa iz registra je lahko preusmerjena na streznik (pot UNC) ali na koren diska D: - jedro
    (core/os_iskalnik.py) namenoma ne hodi na omrezje in na drug disk, zato ga lastni indeks tu ne sme obiti. Preverja
    se samo niz poti in vrsta pogona, brez dostopa do mape (isdir na UNC caka na rok SMB)."""
    pot = str(pot or "")
    if not pot or pot.startswith(("\\\\", "//")):
        return False
    # Samo polna pot na pogonu (Pregled 98, Ķ5): »D:«, »D:.«, »D:mapa«, »\\mapa« bi abspath razresil glede na trenutno
    # mapo - CI Windows 26. 10. 2026 (delovna mapa na D:) je zato »D:« sprejel kot lokalno mapo.
    if not _je_polna_pot_pogona(pot):
        return False
    pogon, ostalo = os.path.splitdrive(os.path.abspath(pot))
    if pogon.startswith(("\\\\", "//")):
        return False
    if ostalo.strip("\\/") == "":
        return False                                        # koren diska (C:\, D:\): ves disk in domaca mapa dvakrat
    return not (pogon and vrsta_pogona(pogon + "\\") == DRIVE_REMOTE)


def korenine(mape: List[dict], dom: Optional[str] = None, lokalna: Callable[[str], bool] = lokalna_mapa) -> List[str]:
    """Domaca mapa in znane mape, ki niso pod njo ali pod drugo izbrano (cista funkcija; preizkus). Omrezne mape in
    koreni diskov ne dobijo svojega indeksa (G3); mapa, nadrejena domaci, jo nadomesti - domaca se ne indeksira dvakrat."""
    dom = os.path.abspath(dom or os.path.expanduser("~"))
    izid = [dom]
    for m in mape:
        pot = str(m.get("pot") or "")
        if not pot or m.get("vrsta") == "HOME" or not lokalna(pot) or not os.path.isdir(pot):
            continue
        if any(_pod(pot, k) for k in izid):
            continue
        izid = [k for k in izid if not _pod(k, pot)]  # sirsa mapa nadomesti ozjo (tudi domaco)
        izid.append(os.path.abspath(pot))
    return izid


def _indeks(koren: str, dom: str) -> os_iskalnik.Indeks:
    if os.path.normcase(koren) == os.path.normcase(dom):
        return os_iskalnik.indeks()
    with _zaklep:
        idx = _indeksi.get(os.path.normcase(koren))
        if idx is None:
            idx = _indeksi[os.path.normcase(koren)] = os_iskalnik.Indeks(koren)
        return idx


def zastarel() -> None:
    """Safeer je sam spremenil datoteke: vsi indeksi naj se ob naslednjem iskanju obnovijo."""
    os_iskalnik.zastarel()
    with _zaklep:
        for idx in _indeksi.values():
            idx.zastarel()


def _v_indeksu(niz: str, idx: os_iskalnik.Indeks, meja: int, zdaj: float) -> List[Tuple[float, int, dict]]:
    """(ocena, mesto, vnos) iz enega indeksa - enako kot core.os_iskalnik.isci, a z oceno za skupno razvrstitev."""
    if not idx.pripravljen():
        # Indeks se se gradi (cakanje je skupno v isci): tokrat kratka hoja po disku.
        return [(0.0, i, e) for i, e in enumerate(os_datoteke.isci(niz, idx.koren, rok=HOJA_BREZ_INDEKSA_S))]
    if idx.star():
        idx.zgradi_v_ozadju()
    izid: List[Tuple[float, int, dict]] = []
    for mesto, (pot, ime, _mapa, ocena) in enumerate(idx.isci(niz, meja * 2)):
        e = os_datoteke._element(pot, ime)
        if e is not None:
            izid.append((ocena + os_iskalnik.svezina(zdaj - float(e.get("spremenjeno") or 0)), mesto, e))
    sveze = os_iskalnik._sveze(niz, idx, {e["pot"] for _o, _m, e in izid})
    if sveze:
        idx.zastarel()
        izid.extend((o + os_iskalnik.svezina(zdaj - float(e.get("spremenjeno") or 0)), -1, e) for o, e in sveze)
    if not izid and idx.nepopoln:
        # hoja po disku na niti zahteve: kratko, za vsak indeks posebej (G3; prej privzetih 1,5 s na indeks)
        izid = [(0.0, i, e) for i, e in enumerate(os_datoteke.isci(niz, idx.koren, rok=HOJA_BREZ_INDEKSA_S))]
    return izid


def isci(niz: str, meja: int = os_datoteke.NAJVEC_ZADETKOV, mape: Optional[Callable[[], List[dict]]] = None) -> List[dict]:
    """Datoteke in mape po imenu v domaci mapi in vseh znanih mapah - oblika kot core.os_iskalnik.isci."""
    niz = str(niz or "").strip()
    if len(niz) < 2:
        return []
    from core import storitve_na_zahtevo
    storitve_na_zahtevo.rabi("iskalnik")
    if mape is None:
        from . import os_backend_win
        mape = os_backend_win.uporabniske_mape
    dom = os.path.abspath(os.path.expanduser("~"))
    zdaj = time.time()
    vse: List[Tuple[float, int, dict]] = []
    glavni = os_iskalnik.indeks()
    indeksi = [_indeks(koren, dom) for koren in korenine(mape(), dom)]
    # Vse gradnje hkrati in skupno cakanje (prej zaporedno po 1,5 s na mapo: prvo iskanje na testnem PC 5,0 s).
    for idx in indeksi:
        if not idx.pripravljen():
            idx.zgradi_v_ozadju()
    konec = time.monotonic() + os_iskalnik.CAKAJ_PRVI_INDEKS_S
    for idx in indeksi:
        if not idx.pripravljen():
            idx.pocakaj(max(0.0, konec - time.monotonic()))
    for idx in indeksi:
        if idx is not glavni and glavni.zastarel_ob > idx.zastarel_ob:
            idx.zastarel()  # Safeer je kaj premaknil (os_iskalnik.zastarel): velja za vse mape
        vse.extend(_v_indeksu(niz, idx, meja, zdaj))
    videne, izid = set(), []
    for _o, _m, e in sorted(vse, key=lambda o: (-o[0], o[1])):
        k = os.path.normcase(e["pot"])
        if k in videne:
            continue
        videne.add(k)
        izid.append(e)
        if len(izid) >= meja:
            break
    return izid
