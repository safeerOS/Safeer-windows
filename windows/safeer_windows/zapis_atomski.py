"""Atomski zapis datoteke JSON za Safeer na Windows (revizija 4. 11. 2026).

Prej je sedem modulov pisalo v stalno zacasno ime `<pot>.tmp`: dve niti (ali dva procesa) sta pisali v ISTO zacasno
datoteko - ena je drugi odnesla datoteko izpod rok (os.replace FileNotFoundError, shramba ni shranjena) ali v cilj
zapisala mesanico obeh vsebin. Zdaj edinstveno ime (tempfile.mkstemp v isti mapi, da je os.replace atomski), fsync,
os.replace; ob napaki se zacasna datoteka odstrani.

Na Windows os.replace vrze PermissionError, ko cilj za hip drzi drug proces (protivirusni program, indeksiranje, drug
Safeer proces bere): zato nekaj kratkih ponovitev, skupaj najvec ~0,5 s. core/shramba_json.zapisi_atomsko je skupna
koda z Linuxom (skupna-koda.json, mora ostati enaka), zato ponovitev za Windows zivi tu.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Optional

#: Premori med ponovitvami os.replace ob PermissionError na Windows (s); skupaj 0,47 s.
PREMORI_PONOVITEV = (0.01, 0.03, 0.06, 0.12, 0.25)
_WINDOWS = os.name == "nt"


def _zamenjaj(zacasna: str, pot: str) -> None:
    for premor in PREMORI_PONOVITEV if _WINDOWS else ():
        try:
            os.replace(zacasna, pot)
            return
        except PermissionError:
            time.sleep(premor)
    os.replace(zacasna, pot)


def zapisi_json(pot: str, podatki: Any, *, indent: Optional[int] = None, ensure_ascii: bool = False) -> None:
    """Zapise podatki kot JSON v pot atomsko. Ob napaki vrze izjemo (OSError, TypeError), stara datoteka ostane."""
    mapa = os.path.dirname(os.path.abspath(pot))
    os.makedirs(mapa, exist_ok=True)
    fd, zacasna = tempfile.mkstemp(prefix=os.path.basename(pot) + ".", suffix=".tmp", dir=mapa)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(podatki, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        _zamenjaj(zacasna, pot)
    except BaseException:
        try:
            os.unlink(zacasna)
        except OSError:
            pass
        raise
