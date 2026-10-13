"""Safeer DRM (Widevine) za Windows: prenos ob prvem zagonu, ne v vsaki posodobitvi Safeer OS.

Podpisan paket (castLabs ECS + VMP podpis, ~160 MB) je sredstvo predizdaje safeer-drm-v<VERZIJA> v repozitoriju
Safeer-windows. Safeer OS ga v ozadju prenese enkrat, preveri SHA-256 in razpakira v %LOCALAPPDATA%/SafeerOS/SafeerDRM.
Do takrat (ali brez omrezja) predvaja WebView2 - uporabnik razlike ne vidi. Logika predvajalnika (main.js) pride s
Safeer OS in se ob vsakem zagonu uskladi v paket (podpisan je le izvrsljivi del, main.js podpisa ne razveljavi).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

VERZIJA = "0.2.0"
URL = ("https://github.com/safeerOS/Safeer-windows/releases/download/"
       f"safeer-drm-v{VERZIJA}/SafeerDRM-{VERZIJA}-win-x64.zip")
SHA256 = "8863f6ac8c39e67fc32aaca724baa3d1b29dab92d810b89b239e1007dce5e618"
OZNAKA = ".preverjeno"
_zaklep = threading.Lock()


def koren() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "SafeerOS" / "SafeerDRM"


def mapa_verzije() -> Path:
    return koren() / VERZIJA


def izvrsljiva() -> Optional[Path]:
    """Pot do safeer-drm.exe, ce je paket prenesen in preverjen; sicer None."""
    mapa = mapa_verzije()
    exe = mapa / "safeer-drm.exe"
    return exe if (mapa / OZNAKA).is_file() and exe.is_file() else None


def uskladi_logiko(exe: Path, vir: Path) -> None:
    """main.js in package.json iz Safeer OS (windows/safeer_drm) v resources/app prenesenega paketa."""
    cilj = exe.parent / "resources" / "app"
    for ime in ("main.js", "package.json"):
        izvor = vir / ime
        if not izvor.is_file():
            continue
        try:
            if (cilj / ime).is_file() and (cilj / ime).read_bytes() == izvor.read_bytes():
                continue
            cilj.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(izvor, cilj / ime)
        except OSError:
            pass


def _varno_razpakiraj(paket: Path, cilj: Path) -> None:
    with zipfile.ZipFile(paket) as arhiv:
        for ime in arhiv.namelist():
            pot = Path(ime)
            if pot.is_absolute() or ".." in pot.parts or ":" in ime:
                raise ValueError(f"nevarna pot v paketu: {ime}")
        arhiv.extractall(cilj)


def prenesi(url: str = URL, sha256: str = SHA256) -> bool:
    """Prenese, preveri in namesti paket. Vrne True, ce je paket na voljo."""
    with _zaklep:
        if izvrsljiva() is not None:
            return True
        koren().mkdir(parents=True, exist_ok=True)
        zacasno = koren() / f"prenos-{VERZIJA}.part"
        nova = koren() / f"{VERZIJA}.nova"
        try:
            odtis = hashlib.sha256()
            zahteva = urllib.request.Request(url, headers={"User-Agent": "SafeerOS"})
            with urllib.request.urlopen(zahteva, timeout=60) as odziv, open(zacasno, "wb") as izhod:
                while True:
                    kos = odziv.read(1 << 20)
                    if not kos:
                        break
                    odtis.update(kos)
                    izhod.write(kos)
            if odtis.hexdigest() != sha256:
                print("[SafeerDRM] SHA-256 se ne ujema, paket zavrzen", flush=True)
                return False
            shutil.rmtree(nova, ignore_errors=True)
            _varno_razpakiraj(zacasno, nova)
            if not (nova / "safeer-drm.exe").is_file():
                print("[SafeerDRM] v paketu ni safeer-drm.exe", flush=True)
                return False
            (nova / OZNAKA).write_text(sha256, encoding="utf-8")
            shutil.rmtree(mapa_verzije(), ignore_errors=True)
            os.replace(nova, mapa_verzije())
            # Starejse razlicice (ce niso v uporabi) pospravimo.
            for stara in koren().iterdir():
                if stara.is_dir() and stara.name != VERZIJA:
                    shutil.rmtree(stara, ignore_errors=True)
            print(f"[SafeerDRM] {VERZIJA} pripravljen", flush=True)
            return True
        except Exception as e:  # noqa: BLE001 - brez Safeer DRM predvaja WebView2
            print(f"[SafeerDRM] prenos ni uspel: {e}", flush=True)
            return False
        finally:
            try:
                zacasno.unlink()
            except OSError:
                pass
            shutil.rmtree(nova, ignore_errors=True)


def prenesi_v_ozadju(zamik_s: float = 60.0) -> None:
    """Ob zagonu Safeer OS: po zamiku (da ne upocasni zagona) v ozadju; ob neuspehu znova cez 6 ur."""
    if izvrsljiva() is not None:
        return

    def delo() -> None:
        time.sleep(zamik_s)
        while not prenesi():
            time.sleep(6 * 3600)

    threading.Thread(target=delo, name="safeer-drm-prenos", daemon=True).start()
