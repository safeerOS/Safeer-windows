"""Izbira podnapisov za predvajalnik LibVLC (brez Qt, da jo lahko preizkusimo): enaka pravila kot na Linuxu
(core/os_predvajalnik.py) in kot VLC.

- Samodejno (uporabnik ni nic izbral): pokaze se edina datoteka podnapisov ob videu ali datoteka v jeziku
  sistema oziroma v zadnjem izbranem jeziku.
- Vgrajene podnapise pokazemo samo, ce se jezik ujema ali je uporabnik podnapise izrecno vklopil.
- Uporabnikova izbira (izklop ali jezik) velja tudi za naslednje videe (core/podnapisi.shrani_nastavitve).
"""
from __future__ import annotations

import sys
from typing import Iterable, List, Optional


def koda_jezika(besedilo: str) -> str:
    """ISO 639-1 iz oznake toka (``eng``, ``en``, ``slv``, ``Slovenian``); prazno, ce je ne poznamo."""
    from core import podnapisi
    b = str(besedilo or "").strip().lower()
    if not b:
        return ""
    if b in podnapisi._JEZIKI:
        return podnapisi._JEZIKI[b]
    for del_ in b.replace("[", " ").replace("]", " ").replace("-", " ").replace("_", " ").split():
        if del_ in podnapisi._JEZIKI and len(del_) > 2:
            return podnapisi._JEZIKI[del_]
    return ""


def zeleni_jeziki(nastavitve: dict, jezik_sistema: str) -> List[str]:
    """Najprej zadnji izbrani jezik, nato jezik sistema."""
    izid = []
    for j in (str(nastavitve.get("jezik") or ""), str(jezik_sistema or "")):
        if j and j not in izid:
            izid.append(j[:2].lower())
    return izid


def samodejna_zunanja(podnapisi: List[dict], nastavitve: dict, jezik_sistema: str) -> int:
    """Indeks datoteke podnapisov, ki jo pokazemo ob zacetku videa, ali -1."""
    if nastavitve.get("izklop") is True or not podnapisi:
        return -1
    for j in zeleni_jeziki(nastavitve, jezik_sistema):
        k = next((i for i, p in enumerate(podnapisi) if str(p.get("jezik") or "")[:2].lower() == j), -1)
        if k >= 0:
            return k
    if len(podnapisi) == 1 or nastavitve.get("izklop") is False:
        return 0
    return -1


def samodejni_vgrajeni(vgrajeni: Iterable[tuple], nastavitve: dict, jezik_sistema: str) -> Optional[int]:
    """Vgrajeni tok (id) za prikaz, kadar ni datoteke ob videu; None = podnapisi ostanejo izklopljeni.

    `vgrajeni`: [(id, koda_jezika), ...] v vrstnem redu videa."""
    if nastavitve.get("izklop") is True:
        return None
    vgrajeni = list(vgrajeni)
    for j in zeleni_jeziki(nastavitve, jezik_sistema):
        for ident, koda in vgrajeni:
            if koda == j:
                return ident
    if nastavitve.get("izklop") is False and vgrajeni:
        return vgrajeni[0][0]      # uporabnik je podnapise izrecno vklopil
    return None


def po_izbiri(nastavitve: dict, kljuc: str, jezik: str = "") -> dict:
    """Nove nastavitve po uporabnikovi izbiri: "izklop" ali tok/datoteka v jeziku `jezik`."""
    prej = str(nastavitve.get("jezik") or "")
    if kljuc == "izklop":
        return {"izklop": True, "jezik": prej}
    return {"izklop": False, "jezik": (jezik or prej)[:8]}


def naslednji_kljuc(kljuci: List[str], izbran: str) -> str:
    """Tipka V (kot v VLC): izklop -> prvi -> drugi ... -> izklop."""
    if not kljuci:
        return "izklop"
    i = kljuci.index(izbran) if izbran in kljuci else 0
    return kljuci[(i + 1) % len(kljuci)]


def jezik_sistema() -> str:
    """Jezik uporabnika v Windows (GetUserDefaultLocaleName, npr. "sl-SI" -> "sl"); drugje kot na Linuxu."""
    if sys.platform == "win32":
        try:
            import ctypes
            medpomnilnik = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(medpomnilnik, 85):  # type: ignore[attr-defined]
                return medpomnilnik.value[:2].lower()
        except Exception:  # noqa: BLE001
            pass
        return ""
    from core import podnapisi
    return podnapisi.jezik_sistema()
