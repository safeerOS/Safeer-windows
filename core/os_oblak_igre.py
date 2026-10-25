"""Igre v oblaku v Safeer OS: seznam ponudnikov, pri katerih igra tece na njihovih streznikih, na racunalnik pa pride slika.

Safeer ne prodaja nicesar in nicesar ne namesti sam. Ponudnika s tega seznama uporabnik namesti s svojim klikom, iz
ponudnikovega URADNEGA vira; nato ga Programi najdejo kot vsak drug program (core/os_programi.py) in ga oznacijo z
»Oblak · <ponudnik>«, da je vedno jasno, KJE igra tece: na tem racunalniku, na napravi v Safeer Linku ali v oblaku.
Novega ponudnika dodamo z enim vnosom v PONUDNIKI - brez posebne kode zanj.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Callable, List, Optional

#: Ponudniki iger v oblaku. `flatpak`: uradni vir ponudnika (ime oddaljenega vira, opis vira .flatpakrepo, oznaka
#: aplikacije). `zahteve`: kar objavi ponudnik in lahko preverimo; `uradno`: sistemi, ki jih ponudnik uradno navaja.
PONUDNIKI = [
    {
        "id": "com.nvidia.geforcenow",
        "ime": "GeForce NOW",
        "ponudnik": "NVIDIA",
        "stran": "https://www.nvidia.com/geforce-now/",
        "flatpak": {"vir": "GeForceNOW",
                    "repo": "https://international.download.nvidia.com/GFNLinux/flatpak/geforcenow.flatpakrepo",
                    "aplikacija": "com.nvidia.geforcenow"},
        "zahteve": {"ram_mb": 4096, "jedra": 2, "arhitektura": ("x86_64", "amd64")},
        "uradno": {"ubuntu": 24.04},
    },
]


def _ponudnik(id_: str) -> Optional[dict]:
    return next((p for p in PONUDNIKI if p["id"] == str(id_ or "")), None)


def oblak_za(oznaka: str) -> Optional[dict]:
    """Ali je namizni vnos (ime datoteke .desktop) program ponudnika iger v oblaku: {"ponudnik": ...} ali None."""
    ime = str(oznaka or "")
    if ime.endswith(".desktop"):
        ime = ime[:-8]
    p = _ponudnik(ime)
    return {"ponudnik": p["ponudnik"]} if p else None


# ---------------------------------------------------------------------- zdruzljivost
def _os_release(pot: str = "/etc/os-release") -> dict:
    izid = {}
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            for v in f:
                if "=" in v:
                    k, _, vr = v.strip().partition("=")
                    izid[k] = vr.strip().strip('"')
    except OSError:
        pass
    return izid


#: Osnove Ubuntu po kodnem imenu (Linux Mint in sorodni v os-release navedejo UBUNTU_CODENAME).
_UBUNTU = {"jammy": 22.04, "noble": 24.04, "plucky": 25.04, "questing": 25.10, "resolute": 26.04}


def _podatki_sistema() -> dict:
    """Kar lahko o racunalniku zanesljivo preberemo (brez ugibanja o graficni kartici)."""
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (ValueError, OSError):
        ram = 0
    return {"ram_mb": ram, "jedra": os.cpu_count() or 0, "arhitektura": platform.machine().lower(),
            "flatpak": bool(shutil.which("flatpak")), "os": _os_release()}


def zdruzljivost(p: dict, sistem: Optional[dict] = None) -> dict:
    """Ali racunalnik izpolnjuje objavljene zahteve ponudnika.

    stanje: "ne" (zanesljivo ne bo delovalo - razlogi povedo zakaj), "poskusi" (zahteve so izpolnjene, a sistem ni
    uradno naveden) ali "zdruzljivo". Graficne kartice in dekodiranja videa NE ocenjujemo: ponudnikov paket prinese
    svoje gonilnike (izvajalno okolje Flatpak), zato bi bila ocena z gostitelja ugibanje."""
    s = sistem if sistem is not None else _podatki_sistema()
    z = p.get("zahteve") or {}
    razlogi: List[dict] = []
    if s.get("arhitektura") not in tuple(z.get("arhitektura") or (s.get("arhitektura"),)):
        razlogi.append({"koda": "arhitektura"})
    if s.get("ram_mb", 0) and s["ram_mb"] < int(z.get("ram_mb", 0) * 0.92):       # 4 GB je v resnici ~3,8 GiB uporabnega
        razlogi.append({"koda": "ram", "potrebno": z["ram_mb"] // 1024})
    if s.get("jedra", 0) and s["jedra"] < z.get("jedra", 0):
        razlogi.append({"koda": "jedra", "potrebno": z["jedra"]})
    if not s.get("flatpak"):
        razlogi.append({"koda": "flatpak"})
    if razlogi:
        return {"stanje": "ne", "razlogi": razlogi}
    os_ = s.get("os") or {}
    uradno = p.get("uradno") or {}
    try:
        razlicica = float(os_.get("VERSION_ID", "0").split(".")[0] + "." + (os_.get("VERSION_ID", "0").split(".") + ["0"])[1])
    except ValueError:
        razlicica = 0.0
    if os_.get("ID") in uradno and razlicica >= uradno[os_["ID"]]:
        return {"stanje": "zdruzljivo", "razlogi": []}
    osnova = _UBUNTU.get(os_.get("UBUNTU_CODENAME", ""), 0.0)
    if "ubuntu" in uradno and osnova >= uradno["ubuntu"]:
        # Npr. Linux Mint 22: ni na ponudnikovem seznamu, a ima isto osnovo kot uradno podprti Ubuntu.
        return {"stanje": "poskusi", "razlogi": [{"koda": "osnova", "sistem": os_.get("NAME", ""), "osnova": "Ubuntu %.2f" % osnova}]}
    return {"stanje": "poskusi", "razlogi": [{"koda": "sistem", "sistem": os_.get("NAME", "")}]}


# ---------------------------------------------------------------------- namestitev
def _tek(ukaz: List[str], cas: int) -> tuple:
    try:
        r = subprocess.run(ukaz, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=cas)
        return r.returncode, r.stdout or ""
    except subprocess.TimeoutExpired:
        return 124, "cas je potekel"
    except OSError as e:
        return 127, str(e)


def namescen(p: dict, tek: Callable = _tek) -> bool:
    koda, _ = tek(["flatpak", "info", p["flatpak"]["aplikacija"]], 20)
    return koda == 0


def stanje(tek: Callable = _tek, sistem: Optional[dict] = None) -> List[dict]:
    """Ponudniki za stran: ime, ponudnik, stran, ali je namescen in ali je racunalnik zdruzljiv."""
    s = sistem if sistem is not None else _podatki_sistema()
    izid = []
    for p in PONUDNIKI:
        izid.append({"id": p["id"], "ime": p["ime"], "ponudnik": p["ponudnik"], "stran": p["stran"],
                     "namescen": bool(s.get("flatpak")) and namescen(p, tek), "zdruzljivost": zdruzljivost(p, s)})
    return izid


def namesti(id_: str, tek: Callable = _tek, sistem: Optional[dict] = None) -> dict:
    """Namesti ponudnikov uradni paket ZA TEGA UPORABNIKA (brez skrbniskega gesla). Klice se samo na uporabnikov klik.
    Ukaza sta nespremenljiva: vir in oznaka aplikacije prideta iz PONUDNIKI, nikoli s strani."""
    p = _ponudnik(id_)
    if p is None:
        return {"ok": False, "napaka": "ni_ponudnika"}
    z = zdruzljivost(p, sistem)
    if z["stanje"] == "ne":
        return {"ok": False, "napaka": "ni_zdruzljivo", "razlogi": z["razlogi"]}
    f = p["flatpak"]
    koda, izpis = tek(["flatpak", "remote-add", "--user", "--if-not-exists", f["vir"], f["repo"]], 120)
    if koda != 0:
        return {"ok": False, "napaka": "vir", "podrobnosti": izpis.strip()[-300:]}
    koda, izpis = tek(["flatpak", "install", "--user", "--noninteractive", "-y", f["vir"], f["aplikacija"]], 3600)
    if koda != 0:
        return {"ok": False, "napaka": "prostor" if "space" in izpis.lower() else "namestitev", "podrobnosti": izpis.strip()[-300:]}
    return {"ok": True, "id": p["id"], "vnos": f["aplikacija"] + ".desktop"}
