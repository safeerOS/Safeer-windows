"""ffmpeg za Safeer OS na Windows: pripeta LGPL gradnja (safeerOS/safeer-ffmpeg-windows), prenesena ob prvem zagonu.

Zakaj: racunalnik z Windows je v Safeer Linku pomocnik sprotnega pretvarjanja (core/link_sprotno.py) - telefon ali
televizor, ki videa ne zna predvajati, ga dobi pretvorjenega v H.264. Windows nima ffmpeg; namesto da bi uporabnik
karkoli namescal, ga Safeer OS prenese sam v ozadju (65 MB, enkrat), preveri SHA-256 (pravilo 5: pripeta razlicica,
nic "latest") in ga hrani v %LOCALAPPDATA%\\SafeerOS\\ffmpeg. Dokler ga ni, racunalnik v host.info pove, da ffmpeg
nima, in ga druge naprave ne izberejo za pomocnika.

Izvor: nespremenjena podmnozica gradnje BtbN/FFmpeg-Builds (LGPL v3), glej IZVOR-PROVENANCE.md v paketu.
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
import urllib.request
import zipfile

IZDAJA = "v9.0.2-r1"
DATOTEKA = "safeer-ffmpeg-9.0.2-win64-lgpl-r1.zip"
URL = f"https://github.com/safeerOS/safeer-ffmpeg-windows/releases/download/{IZDAJA}/{DATOTEKA}"
SHA256 = "7e368782599c659f85db9252a92204a7dce18ca5afd9c413df2b0984e66342de"
OBVEZNO = ("bin/ffmpeg.exe", "bin/ffprobe.exe", "bin/avcodec-63.dll", "bin/avformat-63.dll", "bin/avutil-61.dll",
           "bin/avfilter-12.dll", "bin/avdevice-63.dll", "bin/swscale-10.dll", "bin/swresample-7.dll", "LICENSE.txt")
NAJVEC_B = 120 * 1024 * 1024

_kljucavnica = threading.Lock()
_tece = False


def mapa() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "ffmpeg")


def pot_ffmpeg() -> str:
    """ffmpeg.exe iz nasega paketa, ce je cel in prave izdaje; sicer ''."""
    m = mapa()
    znak = os.path.join(m, ".izdaja")
    try:
        if open(znak, encoding="utf-8").read().strip() != SHA256:
            return ""
    except OSError:
        return ""
    return os.path.join(m, "bin", "ffmpeg.exe") if all(os.path.isfile(os.path.join(m, *o.split("/"))) for o in OBVEZNO) else ""


def prenesi(dnevnik=print) -> str:
    """Prenese in razpakira pripeti paket (SHA-256 preverjen). Vrne pot do ffmpeg.exe ali '' ob napaki."""
    ze = pot_ffmpeg()
    if ze:
        return ze
    dnevnik(f"[SafeerSprotno] ffmpeg: prenos {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=180) as r:
            podatki = r.read(NAJVEC_B + 1)
    except Exception as e:  # noqa: BLE001
        dnevnik(f"[SafeerSprotno] ffmpeg: prenos ni uspel ({e}); poskusim ob naslednjem zagonu")
        return ""
    if len(podatki) > NAJVEC_B:
        dnevnik("[SafeerSprotno] ffmpeg: paket je prevelik, zavrnjen")
        return ""
    vsota = hashlib.sha256(podatki).hexdigest()
    if vsota != SHA256:
        dnevnik(f"[SafeerSprotno] ffmpeg: SHA-256 ne ustreza ({vsota[:16]}... != {SHA256[:16]}...), zavrnjen")
        return ""
    try:
        zf = zipfile.ZipFile(io.BytesIO(podatki))
        imena = set(zf.namelist())
        manjka = [o for o in OBVEZNO if o not in imena]
        if manjka:
            dnevnik("[SafeerSprotno] ffmpeg: paket nepopoln, manjka " + ", ".join(manjka))
            return ""
        m = mapa()
        os.makedirs(os.path.join(m, "bin"), exist_ok=True)
        for ime in imena:
            if ime.endswith("/") or ".." in ime or ime.startswith("/"):
                continue
            cilj = os.path.join(m, *ime.split("/"))
            os.makedirs(os.path.dirname(cilj), exist_ok=True)
            with zf.open(ime) as v, open(cilj, "wb") as d:
                d.write(v.read())
        with open(os.path.join(m, ".izdaja"), "w", encoding="utf-8") as d:
            d.write(SHA256 + "\n")
    except Exception as e:  # noqa: BLE001
        dnevnik(f"[SafeerSprotno] ffmpeg: razpakiranje ni uspelo ({e})")
        return ""
    pot = pot_ffmpeg()
    dnevnik(f"[SafeerSprotno] ffmpeg: pripravljen ({pot})" if pot else "[SafeerSprotno] ffmpeg: paket po razpakiranju ni cel")
    return pot


def zagotovi_v_ozadju(dnevnik=print) -> None:
    """Ob zagonu Safeer OS: ce ffmpeg ni (ne nas paket, ne sistemski), ga prenese v niti v ozadju - enkrat na zagon."""
    global _tece
    from core import link_sprotno
    if link_sprotno.sprotno().ffmpeg():
        return
    with _kljucavnica:
        if _tece:
            return
        _tece = True
    threading.Thread(target=prenesi, args=(dnevnik,), name="SafeerFfmpegPrenos", daemon=True).start()
