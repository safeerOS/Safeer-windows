"""Kdaj in kako pogosto iscemo Safeer Hub, ko povezave ni.

Fiksno cakanje je najslabse od obojega: ce je drug Hub na voljo takoj, uporabnik po nepotrebnem
gleda prazen seznam; ce ga ni, pa eno samo iskanje pomeni, da se naprava, ki se prizge pozneje,
ne pojavi nikoli.

Zato dvoje:

  * **hitro iskanje** - prvi poskus takoj, nato ob 0,3 / 0,8 / 1,5 s, konec najpozneje po treh
    sekundah **ali prej, takoj ko Hub najdemo**. Ce ga najdemo po 120 ms, se povezemo takoj in
    preostanka ne cakamo;
  * **pocasno iskanje** - ce hitro ni naslo nicesar, uporabnik to izve, iskanje pa tece naprej
    vsakih nekaj sekund, da se pozneje prizgana naprava pojavi sama.

Modul je namenoma brez GTK in brez omrezja: sama politika, zato je preizkusljiva do zadnjega
koraka. Kaj je »poskus« in kaj »povezave ni«, pove klicatelj.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

#: Zamiki poskusov hitrega iskanja (sekunde od zacetka).
HITRO = (0.0, 0.3, 0.8, 1.5)
#: Zgornja meja hitrega iskanja. Ni cakanje - je meja.
MEJA = 3.0
#: Razmik pocasnega iskanja v ozadju.
POCASNO = 15.0


def isci_hub(poskus: Callable[[], bool],
             povezave_ni: Callable[[], bool],
             ob_neuspehu: Callable[[], None],
             spi: Callable[[float], None] = time.sleep,
             ura: Callable[[], float] = time.monotonic,
             hitro: Sequence[float] = HITRO,
             meja: float = MEJA,
             pocasno: float = POCASNO) -> bool:
    """Isce, dokler Huba ne najde ali dokler povezava ni spet vzpostavljena.

    `poskus()` naredi en poskus in vrne True, ce je Hub najden; `povezave_ni()` pove, ali iskanje
    sploh se ima smisel (povezava se je lahko vrnila sama); `ob_neuspehu()` se poklice natanko
    enkrat, ko hitro iskanje mine brez uspeha - to je trenutek, ko stran pokaze »ni naprav«.

    Vrne True, ce je Hub najden.
    """
    zacetek = ura()
    for zamik in hitro:
        preostanek = zacetek + zamik - ura()
        if preostanek > 0:
            spi(preostanek)
        if not povezave_ni():
            return False
        if poskus():
            return True
        if ura() - zacetek >= meja:
            break
    if not povezave_ni():
        return False
    ob_neuspehu()
    while povezave_ni():
        spi(pocasno)
        if not povezave_ni():
            return False
        if poskus():
            return True
    return False
