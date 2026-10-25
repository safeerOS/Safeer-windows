"""Izbris sporocil Safeer Chat (Safeer Link) - ciste odlocitve, enake kot Safeer OS za Android (SporocilaPravila.kt,
naloga 106/116 in pregled D4/D5; preizkus: tests/test_sporocila_izbris.py).

Lastnik, 23. 10. 2026 (OBVEZNO): sporocila med napravami morajo imeti »Izbrisi« - pri meni, pri lastnem poslanem tudi
»na vseh mojih napravah« (prek Linka) in izbris celega pogovora, s potrditvijo.

Protokol (kot Android, brez novega tipa sporocila): zahteva za izbris je `chat.send` s `payload.delete` = skupni id
sporocila (id prvotnega `chat.send`, UUID) in besedilom »🗑« - sredisce sprejme samo neprazno besedilo, naprava brez
izbrisa ga pokaze kot kos. Naprava, ki izbris zna, to pove z zmoznostjo `chat.delete` ob prijavi; brez nje zahteve ne
posljemo (pocaka do 30 dni). Prejemnik izbrise samo PREJETO sporocilo iz pogovora naprave, ki ga je poslala.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

#: Zmoznost, s katero naprava v Linku pove, da zna zahtevo za izbris (payload.delete).
ZMOZNOST_IZBRIS = "chat.delete"
#: Besedilo zahteve za izbris (sredisce sprejme samo neprazen chat.send).
BESEDILO_IZBRISA = "\U0001F5D1"

#: Lastno poslano sporocilo Linka: »chat:ven:<id>«, prejeto: »chat:<id>«; <id> je id sporocila chat.send.
PREDPONA_POSLANO = "chat:ven:"
PREDPONA_PREJETO = "chat:"
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

#: Zahteva za izbris, ki je prisla pred sporocilom: zapis velja 7 dni, najvec 500 zapisov (tuja naprava jih ne nakopici).
VNAPREJ_VELJA_S = 7 * 24 * 3600.0
VNAPREJ_NAJVEC = 500
#: Najdlje cakajoci izbris (naprava, ki se en mesec ne poveze, ga ne dobi vec).
BRISANJE_NAJDLJE_S = 30 * 24 * 3600.0

KONCANO, PONOVI, OPUSTI = 0, 1, 2
NA_DRUGI_DA, NA_DRUGI_NE, NA_DRUGI_NEZNANO = 0, 1, 2


def je_uuid(niz: object) -> bool:
    return bool(_UUID.match(str(niz or "")))


def skupni_id(lokalni_id: str, smer: str) -> Optional[str]:
    """Skupni id lastnega poslanega sporocila (ga pozna tudi prejemnik) ali None. Sporocila, poslana pred to razlicico,
    imajo krajevni id - prejemnik jih hrani pod drugim id-jem, zato zanje izbrisa na vseh napravah ni."""
    if smer != "ven" or not str(lokalni_id).startswith(PREDPONA_POSLANO):
        return None
    s = str(lokalni_id)[len(PREDPONA_POSLANO):]
    return s if je_uuid(s) else None


def prejeti_id(skupni: str) -> str:
    """Id, pod katerim prejemnik hrani sporocilo s skupnim id-jem [skupni]."""
    return PREDPONA_PREJETO + str(skupni)


def zahteva_velja(smer: str, pogovor_sporocila: str, posiljatelj: str) -> bool:
    """Izbrise se samo prejeto sporocilo v pogovoru naprave, ki ga je poslala: tuja naprava ne more izbrisati sporocil
    drugih ali nasih lastnih."""
    return smer == "noter" and bool(posiljatelj) and pogovor_sporocila == posiljatelj


def sme_zapisati_vnaprej(od: str, skupni: str) -> bool:
    """Zahteva za se neznano sporocilo sme pustiti zapis samo z znano napravo in pravim skupnim id-jem (UUID)."""
    return bool(od) and je_uuid(skupni)


def vnaprej_velja(potece: float, zdaj: float) -> bool:
    """Zapis s potekom [potece] ob [zdaj] se velja; zapis z vec kot VNAPREJ_VELJA_S do poteka (ura prestavljena nazaj)
    ne velja."""
    return zdaj < potece and potece - zdaj <= VNAPREJ_VELJA_S


def izid_brisanja(izid: str, zapisano: float, zdaj: float) -> int:
    """Kaj z zahtevo po odgovoru sredisca: »accepted« (dostavljeno) in »queued« (sredisce jo hrani do povezave naprave)
    - koncano; naprave ni vec v Linku ali je ista naprava - opusti; drugo (brez povezave, potek, naprava izbrisa se ne
    javi) - ponovi ob naslednji priloznosti, dokler zapis ni starejsi od BRISANJE_NAJDLJE_S."""
    if izid in ("accepted", "queued"):
        return KONCANO
    if izid in ("ni_naprave", "isti_naprava"):
        return OPUSTI
    if zdaj - zapisano > BRISANJE_NAJDLJE_S:
        return OPUSTI
    return PONOVI


def izbris_na_drugi(prijave: Sequence[Iterable[str]]) -> int:
    """Ali naprava pogovora zna izbris: [prijave] so zmoznosti vseh njenih prijav v seznamu Linka. Ni je v seznamu -
    neznano (izbris pocaka in se ob povezavi preveri znova)."""
    if not prijave:
        return NA_DRUGI_NEZNANO
    if any(ZMOZNOST_IZBRIS in set(z or ()) for z in prijave):
        return NA_DRUGI_DA
    return NA_DRUGI_NE
