"""Posodobitve Safeer OS s safeer.si (os/razlicice.json) - skupno Linuxu in Windows.

Aplikacija sama pove, da je na voljo nova razlicica, in jo na zeljo uporabnika prenese (SHA-256 preverjen) ter preda
namescanju: Linux .deb prek `pkexec apt-get install` (polkit vprasa za geslo), Flatpak prek `flatpak install --user`,
AppImage zamenja sam sebe; Windows zazene nov SafeerOS-Windows-<ver>.exe (zaganjalnik razpakira novo razlicico).
Nic se ne namesti brez uporabnika; preverba je tiha (najvec na 6 ur) in brez posledic, ce omrezja ni.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Callable, Dict, List, Optional

MANIFEST = os.environ.get("SAFEER_MANIFEST_URL") or "https://safeer.si/os/razlicice.json"   # okoljska spremenljivka za preizkuse
STRAN = "https://safeer.si/os/"
PREVERBA_S = 6 * 3600
IMENA = {"safeer-os": "Safeer OS", "safeer-control": "Safeer Control", "safeer-browser": "Safeer Browser"}


def _stevilke(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:4]) or (0,)


def novejsa(nova: str, nasa: str) -> bool:
    """Ali je razlicica `nova` ("0.4.23") novejsa od `nasa` ("0.4.22")."""
    return _stevilke(nova) > _stevilke(nasa)


def prenesi_manifest(url: str = MANIFEST, cas: float = 8.0, agent: str = "SafeerOS") -> dict:
    z = urllib.request.Request(url, headers={"User-Agent": agent, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(z, timeout=cas) as o:  # noqa: S310 - https na safeer.si
        m = json.loads(o.read().decode("utf-8"))
    if not isinstance(m, dict) or "android" not in m:
        raise ValueError("manifest ni pravi")
    return m


def nacin_namestitve() -> str:
    """Kako je Safeer OS namescen na tem racunalniku: deb | flatpak | appimage | windows | neznano."""
    if sys.platform.startswith("win"):
        return "windows"
    if os.environ.get("FLATPAK_ID"):
        return "flatpak"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if shutil.which("dpkg") and os.path.exists("/var/lib/dpkg/info/safeer-os.list"):
        return "deb"
    return "neznano"


def _vnos_datoteke(paket: dict, nacin: str) -> Optional[dict]:
    if nacin == "windows":
        return {k: paket.get(k) for k in ("url", "sha256", "velikost")} if paket.get("url") else None
    d = paket.get({"deb": "deb", "flatpak": "flatpak", "appimage": "appimage"}.get(nacin, ""))
    return d if isinstance(d, dict) and d.get("url") else None


def preveri(platforma: str, razlicice: Dict[str, str], manifest: Optional[dict] = None, nacin: Optional[str] = None) -> dict:
    """Primerja nase razlicice ({"safeer-os": "0.4.22", "safeer-control": "2.1.20"}) z manifestom.

    Vrne {"nove": [{"kljuc", "ime", "nasa", "razlicica", "datoteka": {url, sha256, velikost} ali None, "tema": {...}}],
          "nacin": deb|flatpak|appimage|windows|neznano, "stran": url, "preverjeno": cas}. Brez omrezja vrze izjemo.
    """
    m = manifest if manifest is not None else prenesi_manifest()
    nacin = nacin or ("windows" if platforma == "windows" else nacin_namestitve())
    skupina = m.get(platforma) if isinstance(m.get(platforma), dict) else {}
    nove: List[dict] = []
    for kljuc, nasa in razlicice.items():
        paket = skupina.get(kljuc)
        if not isinstance(paket, dict) or not novejsa(paket.get("razlicica", ""), nasa):
            continue
        vnos = {"kljuc": kljuc, "ime": IMENA.get(kljuc, kljuc), "nasa": nasa, "razlicica": str(paket.get("razlicica")),
                "datoteka": _vnos_datoteke(paket, nacin)}
        if kljuc == "safeer-os" and nacin == "deb" and isinstance(paket.get("tema_deb"), dict):
            vnos["tema"] = paket["tema_deb"]
        nove.append(vnos)
    novo = skupina.get("novo") if isinstance(skupina.get("novo"), dict) else {}
    return {"nove": nove, "nacin": nacin, "stran": str(m.get("stran") or STRAN), "preverjeno": int(time.time()),
            "novo": {k: str(v) for k, v in novo.items() if isinstance(v, str)}}


def opis(izid: dict) -> str:
    """"Safeer OS 0.4.23, Safeer Control 2.1.21" ali ""."""
    return ", ".join(f"{n['ime']} {n['razlicica']}" for n in izid.get("nove") or [])


def prenesi(url: str, cilj: str, sha256: str, velikost: int = 0, napredek: Optional[Callable[[int, int], None]] = None,
            prekini: Optional[Callable[[], bool]] = None, agent: str = "SafeerOS") -> str:
    """Prenese datoteko v `cilj` (prek zacasne), sproti racuna SHA-256 in jo ob neujemanju zavrze. Vrne pot."""
    os.makedirs(os.path.dirname(cilj) or ".", exist_ok=True)
    zacasna = cilj + ".del"
    h = hashlib.sha256()
    z = urllib.request.Request(url, headers={"User-Agent": agent})
    try:
        with urllib.request.urlopen(z, timeout=30) as o, open(zacasna, "wb") as f:  # noqa: S310
            skupaj = velikost or int(o.headers.get("Content-Length") or 0)
            prebrano = 0
            while True:
                if prekini is not None and prekini():
                    raise InterruptedError("prekinjeno")
                kos = o.read(1 << 16)
                if not kos:
                    break
                f.write(kos)
                h.update(kos)
                prebrano += len(kos)
                if napredek is not None:
                    napredek(prebrano, skupaj)
        if sha256 and h.hexdigest().lower() != str(sha256).lower():
            raise ValueError("SHA-256 se ne ujema")
        os.replace(zacasna, cilj)
    except BaseException:
        # Preklican, prekinjen ali pokvarjen prenos ne pusti delne datoteke (paket ima vec deset MB).
        try:
            os.remove(zacasna)
        except OSError:
            pass
        raise
    return cilj


def namesti_linux(nacin: str, poti: List[str]) -> subprocess.CompletedProcess:
    """Namestitev prenesenih datotek: deb -> pkexec apt-get install (polkit geslo), flatpak -> flatpak install --user."""
    if nacin == "deb":
        return subprocess.run(["pkexec", "apt-get", "install", "-y", "--allow-downgrades", *poti], capture_output=True, text=True, timeout=900)
    if nacin == "flatpak":
        return subprocess.run(["flatpak", "install", "--user", "-y", "--reinstall", *poti], capture_output=True, text=True, timeout=900)
    if nacin == "appimage":
        # Nova datoteka zamenja tekoco NA ISTI POTI (ime ostane): bliznjice, meni in AppImageLauncher kazejo nanjo se naprej.
        zdajsnji = os.environ.get("APPIMAGE") or ""
        if not zdajsnji or not poti:
            raise RuntimeError("AppImage ni znan")
        shutil.move(poti[0], zdajsnji)
        os.chmod(zdajsnji, 0o755)
        return subprocess.CompletedProcess(["appimage", zdajsnji], 0, zdajsnji, "")
    raise RuntimeError("neznan nacin namestitve")


class Posodabljanje:
    """Stanje enega posodabljanja za vmesnik: faza (prenos | namescanje | koncano | napaka), odstotek, sporocilo."""

    def __init__(self) -> None:
        self.faza = ""
        self.odstotek = 0
        self.sporocilo = ""
        self.prekinjeno = False
        self.nit: Optional[threading.Thread] = None

    def tece(self) -> bool:
        return self.nit is not None and self.nit.is_alive()

    def stanje(self) -> dict:
        return {"faza": self.faza, "odstotek": self.odstotek, "sporocilo": self.sporocilo, "tece": self.tece()}

    def zacni(self, delo: Callable[["Posodabljanje"], None]) -> bool:
        if self.tece():
            return False
        self.faza, self.odstotek, self.sporocilo, self.prekinjeno = "prenos", 0, "", False

        def ovoj() -> None:
            try:
                delo(self)
                if self.faza != "napaka":
                    self.faza = "koncano"
            except InterruptedError:
                self.faza, self.sporocilo = "napaka", "prekinjeno"
            except Exception as e:  # noqa: BLE001 - uporabnik dobi kratko sporocilo, podrobnosti v dnevnik
                self.faza, self.sporocilo = "napaka", str(e)
        self.nit = threading.Thread(target=ovoj, name="safeer-posodobitev", daemon=True)
        self.nit.start()
        return True
