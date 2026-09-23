"""Urejanje deljenih datotek Safeer Controla z naprav (televizor, tablica): Smeti, preimenovanje, premik, vrtenje slik.

Vse velja samo za datoteke, ki jih naprava ze sme videti (`DeljeneMape.razresi`). Brisanje nikoli
ni trajno: datoteka gre v Smeti racunalnika (freedesktop Trash), od koder jo uporabnik lahko obnovi.
Vrtenje fotografije JPEG z oznako EXIF Orientation spremeni samo to oznako - brez ponovnega
stiskanja, slika ostane taka, kot jo je posnel fotoaparat; druge slike zavrti Pillow.
"""

from __future__ import annotations

import datetime
import os
import shutil
import struct
import subprocess
import urllib.parse
from typing import Optional, Tuple

NAJDALJSE_IME = 255
#: Meje za vrtenje s Pillow: slika se razsiri v pomnilnik (sirina x visina x 4 bajte), zato
#: majhna datoteka z ogromnimi merami ("dekompresijska bomba") ne sme do dekodiranja.
#: 200 milijonov pik pokrije tudi 200-MP fotografije s telefonov.
NAJVEC_PIK = 200_000_000
NAJVEC_BAJTOV_SLIKE = 200 * 1024 * 1024
# EXIF Orientation po vrtenju za 90 stopinj v smeri urinega kazalca.
_V_DESNO = {1: 6, 6: 3, 3: 8, 8: 1, 2: 7, 7: 4, 4: 5, 5: 2}
_V_LEVO = {v: k for k, v in _V_DESNO.items()}


class NapakaUrejanja(Exception):
    """Sporocilo je kratka koda za napravo (npr. `obstaja`, `ni_dovoljeno`)."""


def varno_ime(ime: str) -> str:
    """Novo ime datoteke: brez poti, brez skritih imen, brez kontrolnih znakov, najvec 255 bajtov."""
    ime = str(ime or "").strip()
    if not ime or ime in (".", "..") or ime.startswith(".") or "/" in ime or "\\" in ime or "\x00" in ime:
        raise NapakaUrejanja("napacno_ime")
    if any(ord(z) < 32 for z in ime) or len(ime.encode("utf-8")) > NAJDALJSE_IME:
        raise NapakaUrejanja("napacno_ime")
    return ime


# ------------------------------------------------------------------ Smeti

def v_smeti(pot: str) -> None:
    """Premakne datoteko ali mapo v Smeti (gio trash; brez gio po specifikaciji freedesktop v ~/.local/share/Trash)."""
    if not os.path.lexists(pot):
        raise NapakaUrejanja("ni_datoteke")
    gio = shutil.which("gio")
    if gio:
        r = subprocess.run([gio, "trash", "--", pot], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return
    _v_smeti_rocno(pot)


def _v_smeti_rocno(pot: str) -> None:
    dom = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    smeti = os.path.join(dom, "Trash")
    datoteke, info = os.path.join(smeti, "files"), os.path.join(smeti, "info")
    os.makedirs(datoteke, exist_ok=True)
    os.makedirs(info, exist_ok=True)
    ime = os.path.basename(pot.rstrip(os.sep)) or "datoteka"
    cilj, k = os.path.join(datoteke, ime), 1
    while os.path.lexists(cilj) or os.path.exists(os.path.join(info, os.path.basename(cilj) + ".trashinfo")):
        koren, konc = os.path.splitext(ime)
        cilj = os.path.join(datoteke, f"{koren} ({k}){konc}")
        k += 1
    zdaj = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(info, os.path.basename(cilj) + ".trashinfo"), "w", encoding="utf-8") as d:
        d.write(f"[Trash Info]\nPath={urllib.parse.quote(pot)}\nDeletionDate={zdaj}\n")
    try:
        shutil.move(pot, cilj)
    except OSError as e:
        raise NapakaUrejanja("ni_dovoljeno") from e


# ------------------------------------------------------------------ ime in mapa

def preimenuj(pot: str, novo_ime: str) -> str:
    """Preimenuje datoteko ali mapo v isti mapi; obstojece nikoli ne prepise. Vrne novo pot."""
    novo_ime = varno_ime(novo_ime)
    cilj = os.path.join(os.path.dirname(pot), novo_ime)
    if cilj == pot:
        return pot
    if os.path.lexists(cilj):
        raise NapakaUrejanja("obstaja")
    try:
        os.rename(pot, cilj)
    except OSError as e:
        raise NapakaUrejanja("ni_dovoljeno") from e
    return cilj


def premakni(pot: str, mapa: str) -> str:
    """Premakne datoteko ali mapo v drugo mapo (znotraj deljenih); obstojece nikoli ne prepise."""
    if not os.path.isdir(mapa):
        raise NapakaUrejanja("ni_mape")
    cilj = os.path.join(mapa, os.path.basename(pot))
    if os.path.realpath(cilj) == os.path.realpath(pot):
        return pot
    if os.path.isdir(pot) and (os.path.realpath(mapa) + os.sep).startswith(os.path.realpath(pot) + os.sep):
        raise NapakaUrejanja("ni_dovoljeno")  # mape ne moremo premakniti vase
    if os.path.lexists(cilj):
        raise NapakaUrejanja("obstaja")
    try:
        shutil.move(pot, cilj)
    except OSError as e:
        raise NapakaUrejanja("ni_dovoljeno") from e
    return cilj


# ------------------------------------------------------------------ vrtenje slik

def _exif_orientacija(podatki: bytes) -> Optional[Tuple[int, str, int]]:
    """Poisce oznako EXIF Orientation v JPEG-u: (odmik vrednosti v datoteki, vrstni red bajtov, vrednost)."""
    if len(podatki) < 4 or podatki[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(podatki):
        if podatki[i] != 0xFF:
            return None
        oznaka = podatki[i + 1]
        if oznaka in (0xD8, 0x01) or 0xD0 <= oznaka <= 0xD7:
            i += 2
            continue
        if oznaka in (0xDA, 0xD9):
            return None  # zacetek slike / konec: EXIF-a ni
        dolzina = struct.unpack(">H", podatki[i + 2:i + 4])[0]
        if oznaka == 0xE1 and podatki[i + 4:i + 10] == b"Exif\x00\x00":
            tiff = i + 10
            red = podatki[tiff:tiff + 2]
            if red == b"II":
                vr = "<"
            elif red == b"MM":
                vr = ">"
            else:
                return None
            try:
                ifd = tiff + struct.unpack(vr + "I", podatki[tiff + 4:tiff + 8])[0]
                n = struct.unpack(vr + "H", podatki[ifd:ifd + 2])[0]
            except struct.error:
                return None
            for k in range(n):
                v = ifd + 2 + 12 * k
                if v + 12 > len(podatki):
                    return None
                oznaka_polja, vrsta, stevilo = struct.unpack(vr + "HHI", podatki[v:v + 8])
                if oznaka_polja == 0x0112 and vrsta == 3 and stevilo == 1:
                    vrednost = struct.unpack(vr + "H", podatki[v + 8:v + 10])[0]
                    return (v + 8, vr, vrednost)
            return None
        i += 2 + dolzina
    return None


def zavrti(pot: str, stopinje: int) -> str:
    """Zavrti sliko za 90 (v desno) ali 270 (v levo) stopinj in jo shrani na isto mesto.

    JPEG z oznako EXIF Orientation: spremeni se samo oznaka (brez izgube, hipno). Druge slike
    (PNG, WebP, JPEG brez EXIF-a) zavrti Pillow; pri JPEG-u se shrani kakovost 95 in ohrani EXIF.
    Vrne `exif` ali `pillow` - kako je bila slika zavrtena.
    """
    if stopinje not in (90, 270):
        raise NapakaUrejanja("napacen_kot")
    if not os.path.isfile(pot):
        raise NapakaUrejanja("ni_datoteke")
    koncnica = os.path.splitext(pot)[1].lower()
    if koncnica in (".jpg", ".jpeg"):
        with open(pot, "rb") as d:
            glava = d.read(256 * 1024)
        najdeno = _exif_orientacija(glava)
        if najdeno is not None:
            odmik, vr, vrednost = najdeno
            nova = (_V_DESNO if stopinje == 90 else _V_LEVO).get(vrednost, 6 if stopinje == 90 else 8)
            try:
                with open(pot, "r+b") as d:
                    d.seek(odmik)
                    d.write(struct.pack(vr + "H", nova))
            except OSError as e:
                raise NapakaUrejanja("ni_dovoljeno") from e
            return "exif"
    return _zavrti_pillow(pot, stopinje)


def _zavrti_pillow(pot: str, stopinje: int) -> str:
    try:
        from PIL import Image, ImageOps
    except ImportError as e:
        raise NapakaUrejanja("ni_pillow") from e
    try:
        # Pillow 9.1 je konstante prestavil v Image.Transpose; starejsi (Ubuntu 22.04) jih imajo
        # na Image, novejsi (Pillow 10+) samo v Transpose. Vzamemo tisto, kar je na voljo.
        vrtenje = getattr(Image, "Transpose", Image)
        if os.path.getsize(pot) > NAJVEC_BAJTOV_SLIKE:
            raise NapakaUrejanja("prevelika")
        with Image.open(pot) as slika:
            # Image.open prebere samo glavo; mere preverimo, preden se slika dekodira.
            if slika.size[0] * slika.size[1] > NAJVEC_PIK:
                raise NapakaUrejanja("prevelika")
            oblika = slika.format
            ravna = ImageOps.exif_transpose(slika) or slika
            # PIL ROTATE_90 vrti v nasprotni smeri urinega kazalca.
            zavrtena = ravna.transpose(vrtenje.ROTATE_270 if stopinje == 90 else vrtenje.ROTATE_90)
            exif = slika.getexif()
            if 0x0112 in exif:
                exif[0x0112] = 1
            zacasna = pot + ".safeer-vrtenje"
            moznosti = {}
            if oblika == "JPEG":
                moznosti = {"quality": 95}
            if len(exif):
                moznosti["exif"] = exif.tobytes()
            if oblika in ("PNG", "WEBP", "GIF") and "icc_profile" in slika.info:
                moznosti["icc_profile"] = slika.info["icc_profile"]
            zavrtena.save(zacasna, format=oblika, **moznosti)
        os.replace(zacasna, pot)
    except NapakaUrejanja:
        raise
    except Exception as e:
        try:
            os.remove(pot + ".safeer-vrtenje")
        except OSError:
            pass
        raise NapakaUrejanja("ni_slike") from e
    return "pillow"
