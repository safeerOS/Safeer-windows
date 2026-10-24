"""Varno pisanje datotek JSON, ki si jih deli vec procesov Safeer (lastnik, 20. 10. 2026).

Stresni preizkus 20. 10. 2026 je pokazal, da je vsak proces (Safeer OS, Safeer Browser, Scit v svojem procesu) ob
zapisu zapisal CELO svojo kopijo - spremembo drugega procesa je tiho povozil. Prekinjen open('w') je pustil napol
zapisano datoteko, ta pa je ob naslednjem zagonu pomenila prazne (privzete) nastavitve cez uporabnikove.

  * zapisi_atomsko: mkstemp v isti mapi, fsync, 0600, os.replace, fsync mape - bralec in sesutje nikoli ne vidita
    napol zapisane datoteke, po izpadu elektrike ostane stara ali nova vsebina.
  * preberi_slovar: vsebina ali None (ni, neberljiva, ni slovar JSON).
  * zaklep: flock na <pot>.lock, najvec `rok` sekund - zataknjen proces ne sme ustaviti vmesnika.
  * zdruzi_in_zapisi: zapise samo kljuce, ki so se v tem procesu spremenili glede na zadnje znano stanje, na trenutno
    vsebino datoteke; kljuce, ki jih je spremenil drug proces, prevzame v pomnilnik.
  * Shramba: slovar v datoteki s temi pravili (os.json Safeer OS, core/os_programi.Shramba).
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional

try:
    import fcntl
except ImportError:  # Windows: en proces, brez zaklepa med procesi
    fcntl = None

_NI = object()
#: Zapisi v enem procesu (vec niti) - med procesi je zaklep flock na <pot>.lock. RLock: set() klice shrani().
ZAKLEP_NITI = threading.RLock()


def zapisi_atomsko(pot: str, podatki: Any, *, indent: Optional[int] = 1, nacin: int = 0o600) -> None:
    """Nova vsebina v zacasno datoteko v isti mapi (edinstveno ime: dve niti ne pisete v isto zacasno datoteko),
    fsync, chmod, os.replace in fsync mape. Ob napaki ostane stara datoteka, zacasna se pobrise."""
    mapa = os.path.dirname(pot) or "."
    os.makedirs(mapa, exist_ok=True)
    fd, zacasna = tempfile.mkstemp(prefix="." + os.path.basename(pot) + ".", suffix=".tmp", dir=mapa)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(podatki, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(zacasna, nacin)
        os.replace(zacasna, pot)
    except BaseException:
        try:
            os.unlink(zacasna)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(mapa, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return                   # Windows ali mapa brez pravice branja: zapis je ze atomski
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def preberi_slovar(pot: str) -> Optional[Dict[str, Any]]:
    """Vsebina datoteke kot slovar ali None (ni datoteke, ni berljiva, ni slovar JSON)."""
    try:
        with open(pot, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def umakni_pokvarjeno(pot: str, napaka: object = "") -> Optional[str]:
    """Neberljivo datoteko premakne ob stran (<pot>.pokvarjen-<cas>) - nikoli je ne prepisemo s privzetimi."""
    shramba = "%s.pokvarjen-%s" % (pot, time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(pot, shramba)
    except OSError:
        return None
    print("[Shramba] %s ni berljiva (%s); shranjena kot %s" % (pot, napaka, shramba), flush=True)
    return shramba


@contextlib.contextmanager
def zaklep(pot: str, rok: float = 2.0):
    """Izkljucen zaklep datoteke `pot` med procesi (flock na <pot>.lock), najvec `rok` sekund, nato brez njega."""
    if fcntl is None:
        yield
        return
    fd = None
    try:
        os.makedirs(os.path.dirname(pot) or ".", exist_ok=True)
        fd = os.open(pot + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
        meja = time.monotonic() + rok
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= meja:
                    print("[Shramba] zaklep %s zaseden, pisem brez njega" % pot, flush=True)
                    break
                time.sleep(0.01)
    except OSError:
        pass
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


def zdruzi_in_zapisi(pot: str, lokalno: Dict[str, Any], znano: Dict[str, Any], *,
                     indent: Optional[int] = 1, pristej: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Zapise kljuce, ki so v `lokalno` drugacni kot v `znano` (zadnje stanje datoteke, ki ga ta proces pozna), na
    trenutno vsebino datoteke - pod zaklepom, atomsko. Kljuce, ki jih je medtem spremenil drug proces (in jih ta ni),
    prevzame v `lokalno` (na mestu). Vrne novo znano stanje (globoka kopija `lokalno`).

    `pristej` {kljuc: n}: stevec povecaj za n glede na vrednost NA DISKU pod istim zaklepom - sicer bi proces s staro
    kopijo (Safeer OS in Safeer Browser stejeta isti stevec Scita) povecanja drugega procesa prepisal."""
    with ZAKLEP_NITI, zaklep(pot):
        disk = preberi_slovar(pot)
        for k, n in (pristej or {}).items():
            osnova = (disk or {}).get(k, lokalno.get(k, 0))
            if not isinstance(osnova, int) or isinstance(osnova, bool):
                osnova = 0
            lokalno[k] = osnova + int(n)
        spremenjeno = {k for k in set(lokalno) | set(znano) if lokalno.get(k, _NI) != znano.get(k, _NI)}
        if disk is None:
            izid = copy.deepcopy(lokalno)
        else:
            izid = disk
            for k in spremenjeno:
                if k in lokalno:
                    izid[k] = copy.deepcopy(lokalno[k])
                else:
                    izid.pop(k, None)
        zapisi_atomsko(pot, izid, indent=indent)
        for k, v in izid.items():
            if k not in spremenjeno and lokalno.get(k, _NI) != v:
                lokalno[k] = copy.deepcopy(v)
        return copy.deepcopy(lokalno)


class Shramba:
    """Slovar nastavitev v datoteki JSON, ki ga pise vec procesov (get/set/shrani kot prej v os_programi)."""

    def __init__(self, pot: str) -> None:
        self.pot = pot
        podatki = None
        if os.path.exists(pot):
            podatki = preberi_slovar(pot)
            if podatki is None:
                time.sleep(0.2)              # drug proces morda ravno pise (starejsa razlicica brez os.replace)
                podatki = preberi_slovar(pot)
                if podatki is None:
                    umakni_pokvarjeno(pot)
        self.podatki: Dict[str, Any] = podatki or {}
        self._znano: Dict[str, Any] = copy.deepcopy(self.podatki)

    def get(self, kljuc: str, privzeto=None):
        v = self.podatki.get(kljuc)
        return privzeto if v is None else v

    def set(self, kljuc: str, vrednost) -> None:
        # Dodelitev in zapis skupaj pod zaklepom niti: zapis druge niti med njima bi vrednost prepisal s staro z diska
        # (neodvisni pregled 1.0.129, preverjeno s prepletanjem).
        with ZAKLEP_NITI:
            self.podatki[kljuc] = vrednost
            self.shrani()

    def shrani(self) -> bool:
        try:
            self._znano = zdruzi_in_zapisi(self.pot, self.podatki, self._znano)
            return True
        except Exception as e:  # noqa: BLE001 - shranjevanje ne sme podreti programa
            print("[Shramba] %s: %s" % (self.pot, e), flush=True)
            return False

    def osvezi(self) -> None:
        """Prevzame kljuce, ki jih je spremenil drug proces (brez zapisa); lastne nezapisane spremembe ostanejo."""
        with ZAKLEP_NITI:
            disk = preberi_slovar(self.pot)
            if disk is None:
                return
            for k, v in disk.items():
                if self.podatki.get(k, _NI) == self._znano.get(k, _NI) and self.podatki.get(k, _NI) != v:
                    self.podatki[k] = copy.deepcopy(v)
            self._znano = copy.deepcopy(disk)
