"""Stabilnost Safeer OS in Safeer Controla na racunalniku: sled ob sesutju in varni nacin.

Do 20. 9. 2026 se je ob sesutju (SIGSEGV v knjiznici C) zgodilo natanko nic: okno je izginilo,
uporabnik ni vedel zakaj, mi pa nismo imeli sledi - sesutje je bilo videti samo v sistemskem
dnevniku jedra. Tu je troje, kar to odpravi:

  * `faulthandler` zapise sled Pythona tudi ob SIGSEGV, SIGABRT, SIGBUS in SIGFPE. Sled pove,
    katera vrstica nase kode je tekla, ko je padla knjiznica C pod njo.
  * Neujete izjeme (tudi v nitih) gredo v isti dnevnik, ne le na zaslon, ki ga nihce ne vidi.
  * Stejemo zagone in sesutja: ce se program v kratkem casu sesuje veckrat, naslednjic tece v
    **varnem nacinu** - brez delov, ki so zadnjic padli (npr. seznam oken prek libwnck).

Dnevnik je v ~/.cache/safeer-os/ (oz. safeer-control) in se sam obrezuje.
"""

from __future__ import annotations

import datetime
import faulthandler
import json
import os
import sys
import threading
from typing import Optional

NAJVECJI_DNEVNIK = 256 * 1024
#: Toliko sesutij v tem casu pomeni, da nekaj ni v redu in je pametneje teci okrnjeno.
OKNO_SESUTIJ_S = 10 * 60
SESUTIJ_ZA_VARNI_NACIN = 2

_datoteka = None


def _mapa(ime: str) -> str:
    koren = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    pot = os.path.join(koren, ime)
    os.makedirs(pot, exist_ok=True)
    return pot


def _obrezi(pot: str) -> None:
    try:
        if os.path.getsize(pot) > NAJVECJI_DNEVNIK:
            with open(pot, "rb") as d:
                d.seek(-NAJVECJI_DNEVNIK // 2, os.SEEK_END)
                rep = d.read()
            with open(pot, "wb") as d:
                d.write(b"... (starejsi zapisi so odrezani)\n" + rep)
    except OSError:
        pass


def zapisi(ime_programa: str, besedilo: str) -> None:
    """Vrstica v dnevnik programa (z uro). Nikoli ne vrze izjeme."""
    try:
        pot = os.path.join(_mapa(ime_programa), "dnevnik.log")
        _obrezi(pot)
        with open(pot, "a", encoding="utf-8") as d:
            d.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), besedilo))
    except Exception:  # noqa: BLE001
        pass


def _stanje_pot(ime_programa: str) -> str:
    return os.path.join(_mapa(ime_programa), "zagoni.json")


def _beri_stanje(ime_programa: str) -> dict:
    try:
        with open(_stanje_pot(ime_programa), encoding="utf-8") as d:
            s = json.load(d)
            return s if isinstance(s, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _pisi_stanje(ime_programa: str, s: dict) -> None:
    try:
        with open(_stanje_pot(ime_programa), "w", encoding="utf-8") as d:
            json.dump(s, d)
    except Exception:  # noqa: BLE001
        pass


def zabelezi_sesutje(ime_programa: str, koda: int, cas: Optional[float] = None) -> int:
    """Zaganjalnik javi, da se je program koncal nenormalno. Vrne stevilo sesutij v zadnjem oknu."""
    import time
    zdaj = cas if cas is not None else time.time()
    s = _beri_stanje(ime_programa)
    sesutja = [t for t in s.get("sesutja", []) if isinstance(t, (int, float)) and zdaj - t < OKNO_SESUTIJ_S]
    sesutja.append(zdaj)
    s["sesutja"] = sesutja[-10:]
    _pisi_stanje(ime_programa, s)
    zapisi(ime_programa, "sesutje (koda %s); v zadnjih %d minutah: %d" % (koda, OKNO_SESUTIJ_S // 60, len(sesutja)))
    return len(sesutja)


def naj_bo_varni_nacin(ime_programa: str, cas: Optional[float] = None) -> bool:
    """Ali naj se program zdaj zazene okrnjeno (zaradi ponovljenih sesutij)."""
    import time
    zdaj = cas if cas is not None else time.time()
    sesutja = [t for t in _beri_stanje(ime_programa).get("sesutja", [])
               if isinstance(t, (int, float)) and zdaj - t < OKNO_SESUTIJ_S]
    return len(sesutja) >= SESUTIJ_ZA_VARNI_NACIN


def pozabi_sesutja(ime_programa: str) -> None:
    """Program je dolgo tekel brez tezav: zgodovina sesutij ni vec pomembna."""
    s = _beri_stanje(ime_programa)
    if s.get("sesutja"):
        s["sesutja"] = []
        _pisi_stanje(ime_programa, s)


def vkljuci(ime_programa: str = "safeer-os") -> str:
    """Vklopi zapisovanje sledi in dnevnik neujetih izjem. Vrne pot dnevnika sledi."""
    global _datoteka
    pot = os.path.join(_mapa(ime_programa), "sled.log")
    try:
        _obrezi(pot)
        _datoteka = open(pot, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 - odprto, dokler tece program
        _datoteka.write("\n=== %s zagon %d (%s) ===\n" % (
            ime_programa, os.getpid(), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        faulthandler.enable(file=_datoteka, all_threads=True)
    except Exception as e:  # noqa: BLE001
        print("[stabilnost] sledi ni mogoce zapisovati:", e)

    def ob_izjemi(vrsta, vrednost, sled):
        import traceback
        besedilo = "".join(traceback.format_exception(vrsta, vrednost, sled))
        zapisi(ime_programa, "neujeta izjema:\n" + besedilo)
        sys.__excepthook__(vrsta, vrednost, sled)

    def ob_izjemi_niti(podatki):
        import traceback
        besedilo = "".join(traceback.format_exception(podatki.exc_type, podatki.exc_value, podatki.exc_traceback))
        zapisi(ime_programa, "neujeta izjema v niti %s:\n%s" % (getattr(podatki.thread, "name", "?"), besedilo))

    sys.excepthook = ob_izjemi
    try:
        threading.excepthook = ob_izjemi_niti
    except Exception:  # noqa: BLE001
        pass
    return pot
