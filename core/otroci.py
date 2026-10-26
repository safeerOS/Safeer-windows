"""Nasi podprocesi v svoji skupini: ob roku ali ustavitvi se konca cela skupina, ob izhodu procesa pa vsi dolgozivi.

Nacrt stabilnosti P1 (zapisnik 20. 10. 2026, naloga 41): 34 zagonov s start_new_session=True in nobenega os.killpg -
ob roku ali ustavitvi je dobil signal samo glavni proces, vnuki so ostali. Primeri: soffice (oosplash -> soffice.bin)
pri pretvorbi datotek, Electron Safeer DRM (zygote, GPU, upodabljalniki), sway s swaybg in Xwayland na drugem zaslonu.
ffmpeg pretvorbe in pretoka Linka je ob izhodu Controla ostal teci (osirotel), dokler ni koncal sam.

Samo za otroke, ki so NASI (pretvorniki, pomozni brskalniki, sestavljalnik drugega zaslona). Programov, ki jih zazene
uporabnik (meni, Odpri z, privzeti program, Nemo, nastavitve sistema), ta modul ne zaganja in ne pospravlja: preziveti
morajo Safeer OS (core/os_programi.py, os_odpri_z.py, namizni_programi.py ostanejo, kot so).

  p = otroci.zazeni(ukaz, stdout=..., dolgoziv=True)    # svoja skupina (setsid); dolgoziv: pospravi ga izhod procesa
  koda = otroci.pocakaj(p, rok=60)                      # ob roku: ustavi() in subprocess.TimeoutExpired
  otroci.ustavi(p)                                      # SIGTERM skupini, po ROK_KONCA_S SIGKILL skupini

Skupina se signalizira samo, ce jo je otrok zacel sam (pgid == pid, start_new_session) in ni nasa: nikoli killpg na
skupino Safeer OS. Brez os.killpg (Windows) ali za nadomestne objekte v preizkusih: terminate() in kill() kot prej.
"""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
import time
from typing import Any, Optional

#: Cas med SIGTERM in SIGKILL (soffice, Electron in sway koncajo v < 1 s; izmerjeno ni - stari kodi sta imeli 3-5 s).
ROK_KONCA_S = 3.0
#: Ob izhodu procesa krajse: atexit ne sme zadrzati zapiranja Safeer OS.
ROK_IZHODA_S = 1.0

_zaklep = threading.Lock()
_dolgozivi: dict = {}            # pid -> (Popen, pgid)
_skupine: dict = {}              # pid -> pgid ob zagonu (po koncu glavnega procesa getpgid ne dela vec)
_atexit = {"namescen": False}


def _ima_skupine() -> bool:
    return os.name != "nt" and hasattr(os, "killpg")


def zazeni(ukaz: list, *, dolgoziv: bool = False, **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen v svoji seji in skupini. dolgoziv=True: ob izhodu procesa (atexit) ga pospravi pospravi_vse()."""
    kwargs["start_new_session"] = True
    p = subprocess.Popen(ukaz, **kwargs)
    with _zaklep:
        _skupine[p.pid] = p.pid          # setsid: skupina ima stevilko otroka
        # Nadomestni objekt brez poll() (preizkusi nadomestijo Popen) ni pravi otrok: odstrani ga, ne podri zagona.
        for pid in [pid for pid, (q, _g) in _dolgozivi.items()
                    if not callable(getattr(q, "poll", None)) or q.poll() is not None]:
            _dolgozivi.pop(pid, None)
            _skupine.pop(pid, None)
        if dolgoziv:
            _dolgozivi[p.pid] = (p, p.pid)
            if not _atexit["namescen"]:
                atexit.register(pospravi_vse)
                _atexit["namescen"] = True
    return p


def _skupina(p: Any) -> Optional[int]:
    """Skupina otroka, ki jo smemo signalizirati, ali None (Windows, nadomestni objekt, otrok brez svoje skupine)."""
    pid = getattr(p, "pid", None)
    if not _ima_skupine() or not isinstance(pid, int) or pid <= 0:
        return None
    with _zaklep:
        skupina = _skupine.get(pid)
    if skupina is None:
        try:
            skupina = os.getpgid(pid)
        except OSError:
            return None
        if skupina != pid:
            return None          # otrok ni zacel svoje skupine: signal samo njemu (terminate)
    if skupina == os.getpgrp():
        return None              # nikoli nase skupine
    return skupina


def _zivi_clan(skupina: int) -> Optional[bool]:
    """Ali ima skupina vsaj en proces, ki ni zombi (/proc), ali None, ce /proc ni berljiv (ni Linux).

    Zombi ne steje: osiroteli vnuk (sh se je koncal) dobi starsa PID 1; v vsebniku CI brez inita (Docker, GitHub
    Actions) ga ta nikoli ne pobere. kill(pgid, 0) uspe tudi za zombija, zato je bila skupina navidez ziva do roka,
    nato pa je sledil SIGKILL na skupino s samim tujim zombijem (hitra-vrata (1), 26. 10. 2026)."""
    try:
        imena = os.listdir("/proc")
    except OSError:
        return None
    zombi = False
    for ime in imena:
        if not ime.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % ime, "rb") as f:
                polja = f.read().rsplit(b")", 1)[1].split()
        except (OSError, IndexError):
            continue                     # proces se je medtem koncal
        # polja: stanje, ppid, pgrp, ...
        if len(polja) > 2 and polja[2] == str(skupina).encode():
            if polja[0] not in (b"Z", b"X"):
                return True
            zombi = True
    # False SAMO, ce so vsi najdeni clani zombiji; ce /proc ne pokaze nobenega clana (npr. drug imenski prostor PID,
    # unshare), ne vemo - None, da ustavi() se vedno poslje SIGKILL (Nov bot 88, R1: sicer ostanejo sirote).
    return False if zombi else None


def _skupina_zivi(skupina: int) -> bool:
    try:
        os.killpg(skupina, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # kill(0) uspe tudi, ce so v skupini sami zombiji: ti ne tecejo vec in jim signal ne more nic.
    zivi = _zivi_clan(skupina)
    return True if zivi is None else zivi


def _signal_skupini(skupina: int, sig: int) -> None:
    try:
        os.killpg(skupina, sig)
    except ProcessLookupError:
        pass


def _pocakaj_skupino(p: Any, skupina: int, do: float) -> bool:
    """Do casa `do` caka, da se konca glavni proces in prazni skupina. True, ce je prazna."""
    while True:
        p.poll()                         # pobere zombija glavnega procesa (sicer skupina navidez zivi)
        if p.returncode is not None and not _skupina_zivi(skupina):
            return True
        if time.monotonic() >= do:
            return False
        time.sleep(0.05)


def ustavi(p: Any, rok: float = ROK_KONCA_S) -> Optional[int]:
    """SIGTERM celi skupini otroka, po `rok` sekundah SIGKILL. Vrne izhodno kodo glavnega procesa (ali None)."""
    if p is None:
        return None
    skupina = _skupina(p)
    try:
        if skupina is None:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=rok)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=rok)
            return getattr(p, "returncode", None)
        # Tudi ce je glavni ze koncal, vnuki v skupini lahko se tecejo (soffice.bin, upodabljalnik Electrona).
        if p.poll() is None or _skupina_zivi(skupina):
            _signal_skupini(skupina, signal.SIGTERM)
            if not _pocakaj_skupino(p, skupina, time.monotonic() + rok):
                _signal_skupini(skupina, signal.SIGKILL)
                _pocakaj_skupino(p, skupina, time.monotonic() + rok)
        return p.returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        print("[otroci] ustavitev %s: %s" % (getattr(p, "pid", "?"), e), flush=True)
        return getattr(p, "returncode", None)
    finally:
        pid = getattr(p, "pid", None)
        with _zaklep:
            _dolgozivi.pop(pid, None)
            if getattr(p, "returncode", None) is not None:
                _skupine.pop(pid, None)


def pocakaj(p: subprocess.Popen, rok: Optional[float] = None, rok_konca: float = ROK_KONCA_S) -> int:
    """p.wait(rok); ob prekoracitvi ustavi celo skupino in vrze subprocess.TimeoutExpired (kot subprocess.run)."""
    try:
        koda = p.wait(timeout=rok)
    except subprocess.TimeoutExpired:
        ustavi(p, rok=rok_konca)
        raise
    skupina = _skupina(p)
    if skupina is not None and _skupina_zivi(skupina):
        ustavi(p, rok=rok_konca)        # glavni je koncal, vnuk v nasi skupini pa ne sme ostati
    with _zaklep:
        _dolgozivi.pop(p.pid, None)
        _skupine.pop(p.pid, None)
    return koda


def dolgozivi() -> list:
    """Popen dolgozivih otrok, ki se tecejo (za preizkuse in dnevnik)."""
    with _zaklep:
        return [p for p, _g in _dolgozivi.values() if p.poll() is None]


def pospravi_vse(rok: float = ROK_IZHODA_S) -> int:
    """Ustavi vse dolgozive otroke (atexit; Safeer OS ob SIGTERM konca prek _koncaj in normalnega izhoda). Vrne stevilo."""
    with _zaklep:
        vsi = [p for p, _g in _dolgozivi.values()]
    for p in vsi:
        ustavi(p, rok=rok)
    return len(vsi)


__all__ = ["ROK_KONCA_S", "ROK_IZHODA_S", "zazeni", "ustavi", "pocakaj", "dolgozivi", "pospravi_vse"]
