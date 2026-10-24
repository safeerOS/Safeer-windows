"""Zgodovina porabe procesov Safeer za stran safeer://procesi: povprecje in vrh za zadnjo uro (lastnik, 18. 10. 2026).

Vzorec vzame ura registra storitev (core/storitve_na_zahtevo.py) vsakih TIK_S (30 s), tudi kadar strani nihce ne gleda -
sicer ob odprtju ne bi bilo zgodovine. Zato mora biti poceni: za vsak proces v drevesu (ta proces in vsi potomci:
spletni in omrezni procesi WebKita, peskovnik, rqbit, ffmpeg ...) preberemo samo /proc/<pid>/stat (cas CPU, niti) in
statm (RSS). Izmerjeno 18. 10. 2026 (vsebnik): stat 24 us, statm 22 us na proces; smaps_rollup (PSS) bi stal 7,6 ms za
velik proces (947 preslikav) - zato ga za zgodovino ne beremo. Pomnilnik je RSS, kot ga stran kaze ze od 1.0.24.

Krozni medpomnilnik: 120 vzorcev na proces (ena ura pri 30 s), proces, ki ga ni vec, izpade ob naslednjem vzorcu.
CPU je delez enega jedra med zaporednima vzorcema (vec niti ga lahko preseze). Brez GTK - preizkusljivo s ponarejenim /proc.
"""
from __future__ import annotations

import collections
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_KB = (os.sysconf("SC_PAGE_SIZE") // 1024) if hasattr(os, "sysconf") else 4
#: Ena ura pri vzorcu vsakih 30 s.
VZORCEV = 120
URA_S = 3600.0

#: Vrste procesov v drevesu (stran procesov jih poimenuje v vseh jezikih).
GLAVNI, SPLETNI, OMREZNI, PESKOVNIK, DRUGO = "glavni", "spletni", "omrezni", "peskovnik", "drugo"
_VRSTE = {"WebKitWebProces": SPLETNI, "WebKitNetworkPr": OMREZNI, "bwrap": PESKOVNIK, "xdg-dbus-proxy": PESKOVNIK}


def _beri(pot: str) -> Optional[bytes]:
    try:
        with open(pot, "rb") as f:
            return f.read()
    except OSError:
        return None


def preberi(pid: int, proc: str = "/proc") -> Optional[Tuple[bytes, int, int, int]]:
    """(ime, tiki CPU, niti, RSS v kB) ali None, ce procesa ni."""
    stat = _beri("%s/%d/stat" % (proc, pid))
    if not stat:
        return None
    try:
        ime = stat[stat.index(b"(") + 1:stat.rindex(b")")]
        polja = stat.rsplit(b")", 1)[1].split()
        if polja[0] == b"Z":
            return None                  # zombi: ne steje
        tiki, niti = int(polja[11]) + int(polja[12]), int(polja[17])
    except (ValueError, IndexError):
        return None
    statm = _beri("%s/%d/statm" % (proc, pid))
    try:
        rss_kb = int(statm.split()[1]) * PAGE_KB if statm else 0
    except (ValueError, IndexError):
        rss_kb = 0
    return ime, tiki, niti, rss_kb


def potomci(koren: int, proc: str = "/proc") -> List[int]:
    """Vsi potomci procesa (prek /proc/<pid>/task/<tid>/children vseh niti), brez korena."""
    izid: List[int] = []
    sklad = [int(koren)]
    videni = set()
    while sklad:
        pid = sklad.pop()
        if pid in videni:
            continue
        videni.add(pid)
        try:
            niti = os.listdir("%s/%d/task" % (proc, pid))
        except OSError:
            continue
        for tid in niti:
            podatki = _beri("%s/%d/task/%s/children" % (proc, pid, tid))
            for otrok in (podatki or b"").split():
                try:
                    o = int(otrok)
                except ValueError:
                    continue
                if o not in videni:
                    izid.append(o)
                    sklad.append(o)
    return izid


def vrsta(ime, pid: int, koren: int) -> str:
    """Vrsta procesa po imenu (/proc/<pid>/comm je odrezan na 15 znakov)."""
    if pid == koren:
        return GLAVNI
    if isinstance(ime, bytes):
        ime = ime.decode("utf-8", "replace")
    return _VRSTE.get(ime, DRUGO)


class Zgodovina:
    """Vzorci drevesa procesov v krožnem medpomnilniku. vzorci() je varna iz katerekoli niti."""

    def __init__(self, koren: Optional[int] = None, proc: str = "/proc", vzorcev: int = VZORCEV) -> None:
        self.koren = int(koren or os.getpid())
        self.proc = proc
        self.vzorcev = int(vzorcev)
        #: pid -> deque[(cas, tiki, niti, rss_kb)]
        self._vzorci: Dict[int, collections.deque] = {}
        self._imena: Dict[int, bytes] = {}
        self._zaklep = threading.Lock()
        #: Trajanje zadnjega vzorca (s, cas ure) in njegov cas CPU (s) - koliko vzorec stane. Cena je cas CPU: na
        #: obremenjenem racunalniku cas ure steje tudi cakanje na jedro (preizkus 18. 10. 2026: 60 ms ure za 224 procesov).
        self.zadnji_s = 0.0
        self.zadnji_cpu_s = 0.0

    def vzorci(self, zdaj: Optional[float] = None) -> int:
        """En vzorec vseh procesov drevesa. Vrne stevilo procesov."""
        t0, c0 = time.perf_counter(), time.thread_time()
        zdaj = time.monotonic() if zdaj is None else zdaj
        pidi = [self.koren] + potomci(self.koren, self.proc)
        branja = {}
        for pid in pidi:
            b = preberi(pid, self.proc)
            if b is not None:
                branja[pid] = b
        with self._zaklep:
            for pid in [p for p in self._vzorci if p not in branja]:
                del self._vzorci[pid]
                self._imena.pop(pid, None)
            for pid, (ime, tiki, niti, rss) in branja.items():
                if self._imena.get(pid, ime) != ime:
                    self._vzorci.pop(pid, None)       # isti PID, drug program (exec ali ponovna raba PID)
                self._imena[pid] = ime
                vrsta_ = self._vzorci.setdefault(pid, collections.deque(maxlen=self.vzorcev))
                vrsta_.append((zdaj, tiki, niti, rss))
        self.zadnji_s = time.perf_counter() - t0
        self.zadnji_cpu_s = time.thread_time() - c0
        return len(branja)

    def ima_vzorce(self) -> bool:
        with self._zaklep:
            return bool(self._vzorci)

    def procesi(self) -> List[dict]:
        """Procesi iz zadnjega vzorca: pid, ime, vrsta (GLAVNI, SPLETNI ...)."""
        with self._zaklep:
            return [{"pid": pid, "ime": self._imena.get(pid, b"").decode("utf-8", "replace"),
                     "vrsta": vrsta(self._imena.get(pid, b""), pid, self.koren)} for pid in self._vzorci]

    def povzetek(self, pid: int, zdaj: Optional[float] = None, okno_s: float = URA_S) -> Optional[dict]:
        """Povprecje in vrh CPU (delez jedra) in RSS (MB) v zadnjem `okno_s`, ali None brez vsaj enega vzorca.
        CPU potrebuje dva vzorca; z enim je None."""
        zdaj = time.monotonic() if zdaj is None else zdaj
        with self._zaklep:
            vrsta_ = list(self._vzorci.get(int(pid), ()))
        vrsta_ = [v for v in vrsta_ if zdaj - v[0] <= okno_s]
        if not vrsta_:
            return None
        rss = [v[3] for v in vrsta_]
        cpu = []
        for a, b in zip(vrsta_, vrsta_[1:]):
            if b[0] > a[0]:
                cpu.append(max(0.0, (b[1] - a[1]) / CLK_TCK / (b[0] - a[0])))
        return {"cpu_povp": (sum(cpu) / len(cpu)) if cpu else None, "cpu_vrh": max(cpu) if cpu else None,
                "cpu_zadnji": cpu[-1] if cpu else None,
                "rss_povp_mb": int(round(sum(rss) / len(rss) / 1024)), "rss_vrh_mb": int(round(max(rss) / 1024)),
                "vzorcev": len(vrsta_), "od_s": zdaj - vrsta_[0][0]}


_skupna: Optional[Zgodovina] = None
_skupna_zaklep = threading.Lock()


def skupna() -> Zgodovina:
    """Zgodovina tega procesa (en primerek na proces); prvi klic jo priklopi na uro registra storitev."""
    global _skupna
    with _skupna_zaklep:
        if _skupna is None:
            _skupna = Zgodovina()
            from core import storitve_na_zahtevo
            storitve_na_zahtevo.ob_tiku(_skupna.vzorci)
        return _skupna


def trenutno(pid: int, prej: Optional[Tuple[float, int]], proc: str = "/proc") -> Optional[dict]:
    """Trenutna poraba procesa za osvezitev strani: niti, RSS (MB) in CPU od prejsnjega branja `prej` (cas, tiki).
    Vrne tudi novo branje pod kljucem "branje"."""
    b = preberi(pid, proc)
    if b is None:
        return None
    ime, tiki, niti, rss = b
    zdaj = time.monotonic()
    cpu = None
    if prej is not None and zdaj > prej[0]:
        cpu = max(0.0, (tiki - prej[1]) / CLK_TCK / (zdaj - prej[0]))
    return {"ime": ime.decode("utf-8", "replace"), "niti": niti, "rss_mb": rss // 1024, "cpu": cpu,
            "branje": (zdaj, tiki)}
