"""Meritve odziva gostiteljev virov in skupna razvrstitev moznosti predvajanja (lastnik, 15. 10. 2026).

Safeer Player privzeto izbere NAJBOLJSI vir, izmerjen vnaprej: gostitelja vira izmerimo ze, ko ga uporabnik doda, zato
ob predvajanju ni cakanja. Meritev = cas povezave TCP (in rokovanja TLS za https) do gostitelja naslova, 3 vzorci,
mediana; zapomnjena na disku {gostitelj: {ms, ok, cas}}. Ista meritev in isto pravilo veljata za razlicice toka
(os_media.MediaCenter._izberi_najhitrejsi) in za lastne vgrajene vire (core/os_vgrajeni_viri.py) - ena razvrstitev.

Pravilo (razvrsti): lastni strežnik (Jellyfin ...) najprej, nato dosegljivi po zapomnjenem odzivu, nato se neizmerjeni;
nedosegljivi (ok=False) zadnji - lastni vgrajeni viri jih sploh ne pokazejo (os_vgrajeni_viri.moznosti_za).

Meritev nikoli ne tece v glavni niti (izmeri_v_ozadju), za gostitelja je hkrati najvec ena, gre po isti poti kot
predvajanje (sistemski razresevalnik in omrezje - Scit na ravni DNS velja tudi zanjo), domen groženj in oglasov
(adblock) ne merimo - zanje velja »ni dosegljiv«.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import statistics
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from core import shramba_json

VZORCEV = 3
CAS_VZORCA_S = 1.5
#: Dosegljiv vir izmerimo znova po 24 h, nedosegljivega po 15 min (Medijski center ga preveri v ozadju).
STAROST_DOSEGLJIV_S = 24 * 3600
STAROST_NEDOSEGLJIV_S = 15 * 60
NAJVEC_ZAPISOV = 500


def kljuc(naslov: str) -> str:
    """»gostitelj:vrata« naslova http(s); '' za drugo."""
    try:
        d = urllib.parse.urlsplit(str(naslov or ""))
        if d.scheme not in ("http", "https") or not d.hostname:
            return ""
        return "%s:%d" % (d.hostname.lower(), d.port or (443 if d.scheme == "https" else 80))
    except ValueError:
        return ""


def _privzeta_sonda(naslov: str, cas_s: float) -> float:
    """En vzorec: povezava TCP (+ rokovanje TLS za https) v milisekundah; napaka dvigne OSError."""
    d = urllib.parse.urlsplit(naslov)
    gostitelj, vrata = d.hostname, d.port or (443 if d.scheme == "https" else 80)
    zacetek = time.perf_counter()
    with socket.create_connection((gostitelj, vrata), timeout=cas_s) as vticnica:
        if d.scheme == "https":
            vticnica.settimeout(max(0.1, cas_s - (time.perf_counter() - zacetek)))
            with ssl.create_default_context().wrap_socket(vticnica, server_hostname=gostitelj):
                pass
    return (time.perf_counter() - zacetek) * 1000.0


class Meritve:
    """Zapomnjene meritve na disku (datoteka JSON), varne za vec niti."""

    def __init__(self, pot: Optional[os.PathLike] = None, sonda: Callable[[str, float], float] = _privzeta_sonda,
                 blokirano: Optional[Callable[[str], bool]] = None, ura: Callable[[], float] = time.time):
        self.pot = Path(pot) if pot else None
        self._sonda = sonda
        self._blokirano = blokirano
        self._ura = ura
        self._zaklep = threading.Lock()
        self._v_teku: set = set()
        self._podatki: dict = {}
        if self.pot is not None:
            try:
                d = json.loads(self.pot.read_text(encoding="utf-8"))
                self._podatki = {str(k): v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}
            except (OSError, ValueError):
                self._podatki = {}

    # -- branje
    def stanje(self, naslov: str) -> Optional[dict]:
        """{ms, ok, cas} ali None (se ni izmerjeno)."""
        k = kljuc(naslov)
        with self._zaklep:
            z = self._podatki.get(k)
            return dict(z, gostitelj=k) if z else None

    def zastarelo(self, naslov: str) -> bool:
        z = self.stanje(naslov)
        if z is None:
            return True
        meja = STAROST_DOSEGLJIV_S if z.get("ok") else STAROST_NEDOSEGLJIV_S
        return self._ura() - float(z.get("cas") or 0) >= meja

    def ms(self, naslov: str) -> Optional[float]:
        """Zapomnjen odziv dosegljivega gostitelja ali None."""
        z = self.stanje(naslov)
        return float(z["ms"]) if z and z.get("ok") and z.get("ms") is not None else None

    def nedosegljiv(self, naslov: str) -> bool:
        z = self.stanje(naslov)
        return bool(z) and not z.get("ok")

    # -- merjenje
    def izmeri(self, naslov: str, vzorcev: int = VZORCEV, cas_s: float = CAS_VZORCA_S) -> Optional[dict]:
        """Izmeri gostitelja (mediana vzorcev) in zapomni. Ce ga ze meri druga nit, vrne None (brez druge meritve)."""
        k = kljuc(naslov)
        if not k:
            return None
        with self._zaklep:
            if k in self._v_teku:
                return None
            self._v_teku.add(k)
        try:
            vzorci: list = []
            if not (self._blokirano and self._blokirano(naslov)):
                for _ in range(max(1, vzorcev)):
                    try:
                        vzorci.append(float(self._sonda(naslov, cas_s)))
                    except (OSError, ValueError, ssl.SSLError):
                        break               # en neuspel vzorec: gostitelj zdaj ni dosegljiv (brez cakanja na ostale)
            zapis = {"ms": round(statistics.median(vzorci), 1) if vzorci and len(vzorci) == max(1, vzorcev) else None,
                     "ok": bool(vzorci) and len(vzorci) == max(1, vzorcev), "cas": self._ura()}
            with self._zaklep:
                self._podatki[k] = zapis
                self._shrani()
            return dict(zapis, gostitelj=k)
        finally:
            with self._zaklep:
                self._v_teku.discard(k)

    def izmeri_v_ozadju(self, naslovi: Iterable[str], samo_zastarele: bool = True,
                        ob_koncu: Optional[Callable[[list], Any]] = None) -> Optional[threading.Thread]:
        """Meritve v svoji niti (nikoli v glavni zanki GTK); vsak gostitelj enkrat. ob_koncu(spremenjeni) po koncu."""
        izbrani, videni = [], set()
        for n in naslovi or []:
            k = kljuc(n)
            if k and k not in videni and (not samo_zastarele or self.zastarelo(n)):
                videni.add(k)
                izbrani.append(n)
        if not izbrani:
            return None

        def delo() -> None:
            spremenjeni = []
            for n in izbrani:
                prej = self.stanje(n)
                z = self.izmeri(n)
                if z is not None and (prej is None or bool(prej.get("ok")) != bool(z.get("ok"))):
                    spremenjeni.append(z["gostitelj"])
            if ob_koncu is not None:
                try:
                    ob_koncu(spremenjeni)
                except Exception as e:  # noqa: BLE001
                    print("[Meritve] ob koncu:", e, flush=True)
        nit = threading.Thread(target=delo, name="safeer-meritve-virov", daemon=True)
        nit.start()
        return nit

    def _shrani(self) -> None:
        """Atomaren zapis (klicano pod zaklepom); najstarejse meritve odpadejo nad NAJVEC_ZAPISOV."""
        if self.pot is None:
            return
        if len(self._podatki) > NAJVEC_ZAPISOV:
            for k, _z in sorted(self._podatki.items(), key=lambda kv: float(kv[1].get("cas") or 0))[:len(self._podatki) - NAJVEC_ZAPISOV]:
                self._podatki.pop(k, None)
        try:
            self.pot.parent.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.pot, self._podatki, indent=None)
        except OSError:  # zapisi_atomsko pobrise zacasno datoteko sam
            pass


def razvrsti(moznosti: list, meritve: Optional[Meritve], naslov: Callable[[dict], str] = lambda m: str(m.get("url") or ""),
             kakovost: Callable[[dict], int] = lambda m: int(m.get("locljivost") or 0)) -> list:
    """Skupno pravilo izbire (stabilno): lastni strežnik, dosegljivi po odzivu, neizmerjeni, nedosegljivi; znotraj
    enakih se kakovost, nato uporabnikov vrstni red."""
    vrstice = []
    for i, m in enumerate(moznosti or []):
        z = meritve.stanje(naslov(m)) if meritve is not None else None
        if z is None:
            skupina, ms = 1, 0.0
        elif z.get("ok"):
            skupina, ms = 0, float(z.get("ms") or 0)
        else:
            skupina, ms = 2, 0.0
        vrstice.append(((0 if m.get("lastni") else 1, skupina, ms, -kakovost(m), i), m))
    vrstice.sort(key=lambda v: v[0])
    return [m for _k, m in vrstice]
