"""Datoteke za Safeer OS na Linuxu: uporabnikove mape, pregled mape, iskanje in odpiranje.

Datoteke odpira program, ki ga ima uporabnik v Mintu nastavljenega za to vrsto (xdg-open /
Gio), mape pa Nemo, ce zeli vec, kot pokaze Safeer OS. Nic ne brise in ne premika.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import subprocess
import time
from collections import deque
from typing import List, Optional

NAJVEC_V_MAPI = 600
NAJVEC_ZADETKOV = 60

#: Uporabnikove mape XDG v vrstnem redu, kot jih pokaze Safeer OS.
MAPE = ("DESKTOP", "DOCUMENTS", "DOWNLOAD", "PICTURES", "MUSIC", "VIDEOS")
PRIVZETO = {"DESKTOP": "Desktop", "DOCUMENTS": "Documents", "DOWNLOAD": "Downloads", "PICTURES": "Pictures",
            "MUSIC": "Music", "VIDEOS": "Videos"}


def uporabniske_mape(dom: Optional[str] = None) -> List[dict]:
    dom = dom or os.path.expanduser("~")
    nastavljene = {}
    try:
        with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(dom, ".config"),
                               "user-dirs.dirs"), encoding="utf-8") as f:
            for vrstica in f:
                m = re.match(r'\s*XDG_([A-Z]+)_DIR="(.*)"\s*$', vrstica)
                if m:
                    nastavljene[m.group(1)] = m.group(2).replace("$HOME", dom)
    except Exception:
        pass
    izhod = [{"vrsta": "HOME", "pot": dom, "ime": os.path.basename(dom)}]
    for vrsta in MAPE:
        pot = nastavljene.get(vrsta) or os.path.join(dom, PRIVZETO[vrsta])
        if os.path.isdir(pot) and os.path.realpath(pot) != os.path.realpath(dom):
            izhod.append({"vrsta": vrsta, "pot": pot, "ime": os.path.basename(pot.rstrip("/"))})
    return izhod


def vrsta_datoteke(ime: str, je_mapa: bool = False) -> str:
    """Groba vrsta za ikono na strani: mapa, slika, video, zvok, dokument, arhiv, program, drugo."""
    if je_mapa:
        return "mapa"
    mime = mimetypes.guess_type(ime)[0] or ""
    if mime.startswith("image/"):
        return "slika"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "zvok"
    konc = os.path.splitext(ime)[1].lower()
    if konc in (".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".zst", ".deb"):
        return "arhiv"
    if konc in (".appimage", ".sh", ".run", ".exe"):
        return "program"
    if mime.startswith("text/") or konc in (".pdf", ".odt", ".ods", ".odp", ".doc", ".docx", ".xls", ".xlsx",
                                            ".ppt", ".pptx", ".md", ".rtf", ".epub", ".json", ".csv"):
        return "dokument"
    return "drugo"


def _element(pot: str, ime: str) -> Optional[dict]:
    try:
        st = os.stat(pot)
    except OSError:
        return None
    je_mapa = os.path.isdir(pot)
    return {"ime": ime, "pot": pot, "mapa": je_mapa, "velikost": 0 if je_mapa else st.st_size,
            "spremenjeno": st.st_mtime, "vrsta": vrsta_datoteke(ime, je_mapa)}


def preglej(pot: str, skrite: bool = False) -> dict:
    """Vsebina mape: mape najprej, nato datoteke; oboje po abecedi."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "~")))
    if not os.path.isdir(pot):
        return {"pot": pot, "napaka": "ni_mape", "elementi": []}
    try:
        imena = os.listdir(pot)
    except PermissionError:
        return {"pot": pot, "napaka": "ni_dovoljenja", "elementi": []}
    except OSError:
        return {"pot": pot, "napaka": "ni_mape", "elementi": []}
    elementi = []
    for ime in imena:
        if not skrite and ime.startswith("."):
            continue
        e = _element(os.path.join(pot, ime), ime)
        if e is not None:
            elementi.append(e)
    elementi.sort(key=lambda e: (not e["mapa"], e["ime"].lower()))
    stars = os.path.dirname(pot) if pot != "/" else ""
    return {"pot": pot, "stars": stars, "napaka": "", "skupaj": len(elementi),
            "elementi": elementi[:NAJVEC_V_MAPI]}


#: Mape, v katerih so datoteke programov, ne uporabnikove (iskanje jih preskoci).
PRESKOCI = {"node_modules", "__pycache__", "snap", "site-packages", "dist-packages", "venv", ".venv", "build", "dist",
            "Applications", "go", "resources", "target", "vendor"}


def isci(niz: str, dom: Optional[str] = None, rok: float = 1.5) -> List[dict]:
    """Datoteke in mape v domaci mapi, katerih ime vsebuje niz: najprej plitve (po sirini),
    brez skritih in brez map s programsko kodo; najvec 1,5 s."""
    niz = str(niz or "").strip().lower()
    if len(niz) < 2:
        return []
    dom = dom or os.path.expanduser("~")
    konec = time.monotonic() + rok
    zadetki: List[dict] = []
    vrsta = deque([dom])
    while vrsta and time.monotonic() < konec:
        mapa = vrsta.popleft()
        try:
            vnosi = sorted(os.scandir(mapa), key=lambda v: v.name.lower())
        except OSError:
            continue
        for v in vnosi:
            if v.name.startswith("."):
                continue
            try:
                je_mapa = v.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if je_mapa and v.name not in PRESKOCI:
                vrsta.append(v.path)
            if niz in v.name.lower():
                e = _element(v.path, v.name)
                if e is not None:
                    zadetki.append(e)
                    if len(zadetki) >= NAJVEC_ZADETKOV:
                        return zadetki
    return zadetki


def odpri(pot: str) -> bool:
    """Odpre datoteko s privzetim programom oz. mapo v Nemu."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot):
        return False
    for ukaz in (["xdg-open", pot], ["gio", "open", pot]):
        if shutil.which(ukaz[0]) is None:
            continue
        try:
            subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except Exception:
            continue
    return False


def pokazi_v_mapi(pot: str) -> bool:
    """Odpre Nemo z oznaceno datoteko."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot) or shutil.which("nemo") is None:
        return False
    try:
        subprocess.Popen(["nemo", pot], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False
