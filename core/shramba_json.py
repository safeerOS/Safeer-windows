"""Varno pisanje datotek JSON, ki si jih deli vec procesov Safeer (lastnik, 20. 10. 2026).

Stresni preizkus 20. 10. 2026 je pokazal, da je vsak proces (Safeer OS, Safeer Browser, Scit v svojem procesu) ob
zapisu zapisal CELO svojo kopijo - spremembo drugega procesa je tiho povozil. Prekinjen open('w') je pustil napol
zapisano datoteko, ta pa je ob naslednjem zagonu pomenila prazne (privzete) nastavitve cez uporabnikove.

  * zapisi_atomsko: mkstemp v isti mapi, fsync, 0600, os.replace, fsync mape - bralec in sesutje nikoli ne vidita
    napol zapisane datoteke, po izpadu elektrike ostane stara ali nova vsebina.
  * atomsko_odpri / atomska_pot / zapisi_besedilo_atomsko: isto za besedilo, bajte in knjiznice, ki pisejo same
    (PNG, JPEG). Stalnega imena <pot>.tmp v core/ ni (pregled 4. 11. 2026, tests/test_zacasne_datoteke.py).
  * preberi_slovar: vsebina ali None (ni, neberljiva, ni slovar JSON).
  * zaklep: flock na <pot>.lock, najvec `rok` sekund - zataknjen proces ne sme ustaviti vmesnika. Vrne, ali zaklep
    drzi; brez njega zdruzi_in_zapisi NE pise (pregled 4. 11. 2026: zapis brez zaklepa je povozil drug proces),
    Shramba ostane umazana in zapis ponovi kasneje.
  * zdruzi_in_zapisi: zapise samo kljuce, ki so se v tem procesu spremenili glede na zadnje znano stanje, na trenutno
    vsebino datoteke; kljuce, ki jih je spremenil drug proces, prevzame v pomnilnik.
  * Shramba: slovar v datoteki s temi pravili (os.json Safeer OS, core/os_programi.Shramba).
"""
from __future__ import annotations

import contextlib
import copy
import errno
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
#: Pravilo (pregled 4. 11. 2026): na flock se NIKOLI ne caka z ZAKLEP_NITI v roki. Ponovitev v ozadju je med
#: cakanjem (do 2 s) drzala globalni zaklep in vsak set() katerekoli shrambe na glavni niti je zamrznil vmesnik.


def _zacasna(pot: str):
    """Edinstvena zacasna datoteka v mapi cilja (os.replace ostane v istem datotecnem sistemu). Vrne (fd, pot).
    Ime se zacne s piko in konca s .tmp: opazovalci mape (Nemo, autostart) je ne vzamejo za pravo datoteko."""
    mapa = os.path.dirname(pot) or "."
    os.makedirs(mapa, exist_ok=True)
    return tempfile.mkstemp(prefix="." + os.path.basename(pot) + ".", suffix=".tmp", dir=mapa)


def _pospravi(zacasna: str) -> None:
    try:
        os.unlink(zacasna)
    except OSError:
        pass


def _fsync_mape(pot: str) -> None:
    try:
        dfd = os.open(os.path.dirname(pot) or ".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return                   # Windows ali mapa brez pravice branja: zapis je ze atomski
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


@contextlib.contextmanager
def atomsko_odpri(pot: str, nacin_odpiranja: str = "w", *, nacin: int = 0o600, encoding: Optional[str] = "utf-8",
                  newline: Optional[str] = None, sinhrono: bool = False):
    """Datoteka za pisanje, ki ob uspesnem koncu bloka atomsko zamenja `pot` (ob napaki ostane stara, zacasna se
    pobrise). Pregled 4. 11. 2026: stalno ime <pot>.tmp je pomenilo, da sta dve niti ali dva procesa pisala v ISTO
    zacasno datoteko - prvi os.replace je lahko premaknil napol zapisano vsebino drugega. Pravice `nacin` (privzeto
    0600) veljajo od nastanka (mkstemp). sinhrono=True doda fsync datoteke in mape (trajnost ob izpadu elektrike);
    privzeto ne, ker so ta mesta prej pisala brez fsync in vecina tece na glavni niti."""
    if "w" not in nacin_odpiranja:
        raise ValueError("atomsko_odpri je samo za pisanje")
    fd, zacasna = _zacasna(pot)
    try:
        if "b" in nacin_odpiranja:
            f = os.fdopen(fd, "wb")
        else:
            f = os.fdopen(fd, nacin_odpiranja, encoding=encoding, newline=newline)
    except BaseException:
        os.close(fd)
        _pospravi(zacasna)
        raise
    try:
        with f:
            yield f
            f.flush()
            if sinhrono:
                os.fsync(f.fileno())
        os.chmod(zacasna, nacin)
        os.replace(zacasna, pot)
    except BaseException:
        _pospravi(zacasna)
        raise
    if sinhrono:
        _fsync_mape(pot)


@contextlib.contextmanager
def atomska_pot(pot: str, *, nacin: int = 0o600, sinhrono: bool = False):
    """Kot atomsko_odpri, a da POT zacasne datoteke - za knjiznice, ki pisejo same (cairo write_to_png, GdkPixbuf
    savev, Pillow save). Zacasna datoteka ze obstaja (mkstemp, prazna, 0600)."""
    fd, zacasna = _zacasna(pot)
    os.close(fd)
    try:
        yield zacasna
        if sinhrono:
            with open(zacasna, "rb") as f:
                os.fsync(f.fileno())
        os.chmod(zacasna, nacin)
        os.replace(zacasna, pot)
    except BaseException:
        _pospravi(zacasna)
        raise
    if sinhrono:
        _fsync_mape(pot)


def zapisi_besedilo_atomsko(pot: str, vsebina, *, nacin: int = 0o600, newline: Optional[str] = None,
                            sinhrono: bool = False) -> None:
    """Niz ali bajti v `pot` atomsko (atomsko_odpri)."""
    binarno = isinstance(vsebina, (bytes, bytearray, memoryview))
    with atomsko_odpri(pot, "wb" if binarno else "w", nacin=nacin, newline=newline, sinhrono=sinhrono) as f:
        f.write(vsebina)


def zapisi_atomsko(pot: str, podatki: Any, *, indent: Optional[int] = 1, nacin: int = 0o600,
                   sinhrono: bool = True, **dump) -> None:
    """JSON v `pot`: zacasna datoteka v isti mapi (edinstveno ime: dve niti ne pisete v isto zacasno datoteko),
    fsync, chmod, os.replace in fsync mape. Ob napaki ostane stara datoteka, zacasna se pobrise. `dump` gre v
    json.dump (npr. separators, ensure_ascii)."""
    dump.setdefault("ensure_ascii", False)
    with atomsko_odpri(pot, "w", nacin=nacin, sinhrono=sinhrono) as f:
        json.dump(podatki, f, indent=indent, **dump)


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


class ZaklepZaseden(OSError):
    """Zaklepa datoteke ni bilo mogoce dobiti v roku - nic ni zapisano, spremembe ostanejo v pomnilniku."""


#: Napake flock, ki pomenijo »ta datotecni sistem zaklepa ne podpira« (ne »zaseden«): CodeRabbit, 4. 11. 2026.
_BREZ_FLOCK = frozenset(e for e in (getattr(errno, "ENOLCK", None), getattr(errno, "EOPNOTSUPP", None),
                                     getattr(errno, "ENOTSUP", None), getattr(errno, "ENOSYS", None)) if e is not None)


@contextlib.contextmanager
def zaklep(pot: str, rok: float = 2.0):
    """Izkljucen zaklep datoteke `pot` med procesi (flock na <pot>.lock), najvec `rok` sekund. Vrne (as) True, ce
    zaklep drzi, sicer False - klicatelj takrat ne sme pisati (pregled 4. 11. 2026)."""
    if fcntl is None:
        yield True               # Windows: en proces, ZAKLEP_NITI zadosca
        return
    fd = None
    drzi = False
    try:
        os.makedirs(os.path.dirname(pot) or ".", exist_ok=True)
        fd = os.open(pot + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
        meja = time.monotonic() + rok
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                drzi = True
                break
            except BlockingIOError:
                if time.monotonic() >= meja:
                    print("[Shramba] zaklep %s zaseden, zapis odlozen" % pot, flush=True)
                    break
                time.sleep(0.01)
    except OSError as e:
        if getattr(e, "errno", None) in _BREZ_FLOCK:
            # Datotecni sistem flock ne podpira (NFS brez lockd ...): zaklepa med procesi ni in ga ne bo - odlaganje
            # bi zapis za vedno ustavilo (nastavitve se nikoli ne shranijo). Velja samo ZAKLEP_NITI, kot prej.
            print("[Shramba] %s brez flock (%s): zaklep samo v procesu" % (pot, e), flush=True)
            drzi = True
        else:
            print("[Shramba] zaklep %s: %s, zapis odlozen" % (pot, e), flush=True)
    try:
        yield drzi
    finally:
        if fd is not None:
            os.close(fd)


@contextlib.contextmanager
def zaklep_zapisa(pot: str, rok: float = 2.0):
    """Najprej zaklep datoteke med procesi (cakanje BREZ ZAKLEP_NITI), nato ZAKLEP_NITI za kratko zdruzitev in zapis.
    Tudi ZAKLEP_NITI caka najvec `rok`: nit, ki ga drzi in caka na isti flock, ne sme zastaviti obeh. Vrne (as) True,
    ce drzi oba - sicer klicatelj ne sme pisati."""
    with zaklep(pot, rok) as drzi:
        if not drzi:
            yield False
            return
        if not ZAKLEP_NITI.acquire(timeout=rok):
            print("[Shramba] zaklep niti zaseden, zapis %s odlozen" % pot, flush=True)
            yield False
            return
        try:
            yield True
        finally:
            ZAKLEP_NITI.release()


def zdruzi_in_zapisi(pot: str, lokalno: Dict[str, Any], znano: Dict[str, Any], *,
                     indent: Optional[int] = 1, pristej: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Zapise kljuce, ki so v `lokalno` drugacni kot v `znano` (zadnje stanje datoteke, ki ga ta proces pozna), na
    trenutno vsebino datoteke - pod zaklepom, atomsko. Kljuce, ki jih je medtem spremenil drug proces (in jih ta ni),
    prevzame v `lokalno` (na mestu). Vrne novo znano stanje (globoka kopija `lokalno`).

    `pristej` {kljuc: n}: stevec povecaj za n glede na vrednost NA DISKU pod istim zaklepom - sicer bi proces s staro
    kopijo (Safeer OS in Safeer Browser stejeta isti stevec Scita) povecanja drugega procesa prepisal."""
    with zaklep_zapisa(pot) as drzi:
        if not drzi:
            # Brez zaklepa ne beremo ne pisemo: drug proces bi zapis povozil ali mi njegovega. `lokalno` ostane
            # nespremenjen (tudi `pristej` ne), zato isti klic kasneje zapise isto.
            raise ZaklepZaseden("zaklep %s ni na voljo" % pot)
        return zdruzi_zaklenjeno(pot, lokalno, znano, indent=indent, pristej=pristej)


def zdruzi_zaklenjeno(pot: str, lokalno: Dict[str, Any], znano: Dict[str, Any], *,
                      indent: Optional[int] = 1, pristej: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Jedro zdruzi_in_zapisi: klicatelj ze drzi zaklep_zapisa(pot) (tako lahko pod istim zaklepom shrani se novo
    znano stanje - sicer bi ga nit, ki pise za njim, prebrala staro)."""
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

    #: Zamik ponovnega zapisa, ko je bil zaklep zaseden (s).
    ZAMIK_PONOVITVE = 1.0

    def __init__(self, pot: str) -> None:
        self.pot = pot
        self._ponovitev: Optional[threading.Timer] = None
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
        # Dodelitev pod zaklepom niti: zdruzitev druge niti (tudi pod ZAKLEP_NITI) je ne more prekiniti in vrednosti
        # prepisati s staro z diska (neodvisni pregled 1.0.129). Zapis sledi BREZ ZAKLEP_NITI v roki: na flock ne
        # cakamo z globalnim zaklepom (pregled 4. 11. 2026); ce je druga nit medtem ze zapisala, je zapis prazen.
        with ZAKLEP_NITI:
            self.podatki[kljuc] = vrednost
        self.shrani()

    def shrani(self) -> bool:
        try:
            with zaklep_zapisa(self.pot) as drzi:
                if not drzi:
                    raise ZaklepZaseden("zaklep %s ni na voljo" % self.pot)
                self._znano = zdruzi_zaklenjeno(self.pot, self.podatki, self._znano)
            return True
        except ZaklepZaseden:
            # Spremembe ostanejo umazane (podatki != _znano); zapis ponovimo, ne da bi cakali na naslednji set().
            self._ponovi_kasneje()
            return False
        except Exception as e:  # noqa: BLE001 - shranjevanje ne sme podreti programa
            print("[Shramba] %s: %s" % (self.pot, e), flush=True)
            return False

    def _ponovi_kasneje(self) -> None:
        with ZAKLEP_NITI:
            if self._ponovitev is not None and self._ponovitev.is_alive():
                return
            t = threading.Timer(self.ZAMIK_PONOVITVE, self._ponovi)
            t.daemon = True
            self._ponovitev = t
            t.start()

    def _ponovi(self) -> None:
        with ZAKLEP_NITI:
            self._ponovitev = None
        self.shrani()            # cakanje na flock brez ZAKLEP_NITI (vmesnik ne sme zamrzniti)

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
