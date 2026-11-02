#!/usr/bin/env python3
"""Prenese pripeti Microsoftov VC_redist.x64 in iz njega BREZ namestitve razpakira celo druzino runtime MSVC (amd64)
v windows/safeer_windows/vendor/msvc. build_windows.py iz nje poenoti vse clane druzine v paketu.

Zakaj: paket 1.0.53 (testni PC, 2. 11. 2026) je imel msvcp140/vcruntime140(_1) 14.51.36247 iz libmpv, msvcp140_1/_2
pa 14.44.35211 iz PySide6 - Microsoft zahteva v procesu isto razlicico vseh app-local DLL runtime. Runner windows-2022
ima VS 2022 redist 14.44 (prestar za libmpv), zato vir ni sistem runnerja.

Izmerjeno 2. 11. 2026: aka.ms/vc14/vc_redist.x64.exe -> spodnji URL, 14.51.36247.0, Authenticode Valid
(CN=Microsoft Corporation); msvcp140, vcruntime140 in vcruntime140_1 v njem so bajt za bajtom enaki tistim iz libmpv
(iste vsote kot PRIPETI_MSVC). Vir, vsota paketa in vsota vsake DLL so pripeti (pravilo 5); neujemanje ustavi postopek.

Uporaba: python windows/fetch_msvc_runtime.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_windows as _gradnja  # noqa: E402

REDIST_RAZLICICA = "14.51.36247.0"
REDIST_SHA256 = "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c"
REDIST_URL = ("https://download.visualstudio.microsoft.com/download/pr/ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/"
              "843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C/VC_redist.x64.exe")
CILJ = _gradnja.VENDOR_MSVC
PRIPONA = ".dll_amd64"   # imena v kabinetu paketa (npr. msvcp140_1.dll_amd64); arm64 ne jemljemo


def kabineti(data: bytes) -> list:
    """Kabineti (MSCF) v podatkih: Burn ima vsebnik paketov kot kabinet, prilepljen na exe. Velikost iz glave
    (cbCabinet), da odvecni bajti za kabinetom ne motijo razsirjanja."""
    izid, i = [], 0
    while True:
        i = data.find(b"MSCF\0\0\0\0", i)
        if i < 0:
            return izid
        velikost = struct.unpack_from("<I", data, i + 8)[0] if i + 12 <= len(data) else 0
        if 0 < velikost <= len(data) - i:
            izid.append(data[i:i + velikost])
        i += 4


def razsiri(cab: str, mapa: str) -> None:
    if sys.platform == "win32":
        expand = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "expand.exe")
        subprocess.run([expand, "-F:*", cab, mapa], check=True, capture_output=True, timeout=300)
    else:
        subprocess.run(["cabextract", "-q", "-d", mapa, cab], check=True, capture_output=True, timeout=300)


def druzina_iz_paketa(data: bytes, delo: str) -> dict:
    """{ime.dll: vsebina} vseh clanov MSVC_DRUZINA (amd64) iz paketa; kabinete razsiri tudi vgnezdene."""
    najdeno, vrsta, n = {}, [data], 0
    while vrsta:
        for cab in kabineti(vrsta.pop()):
            n += 1
            pot, mapa = os.path.join(delo, f"k{n}.cab"), os.path.join(delo, f"k{n}")
            os.makedirs(mapa)
            with open(pot, "wb") as f:
                f.write(cab)
            razsiri(pot, mapa)
            for koren, _m, datoteke in os.walk(mapa):
                for ime in datoteke:
                    with open(os.path.join(koren, ime), "rb") as f:
                        vsebina = f.read()
                    if ime.lower().endswith(PRIPONA):
                        dll = ime[:-len(PRIPONA)] + ".dll"
                        if _gradnja.MSVC_DRUZINA.match(dll):
                            najdeno[dll.lower()] = vsebina
                    elif vsebina[:4] == b"MSCF":
                        vrsta.append(vsebina)
    return najdeno


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    pricakovano = {ime.lower(): vsota for vsota, ime in _gradnja.PRIPETI_MSVC.items()}
    znak = os.path.join(CILJ, ".izdaja")
    if not a.force and os.path.isfile(znak) and open(znak, encoding="utf-8").read().strip() == REDIST_SHA256 \
            and all(os.path.isfile(os.path.join(CILJ, ime)) for ime in pricakovano):
        print(f"MSVC runtime: VC_redist {REDIST_RAZLICICA} ze prisoten v {CILJ}"); return 0
    print(f"MSVC runtime: prenos {REDIST_URL}", flush=True)
    with urllib.request.urlopen(REDIST_URL, timeout=300) as r:
        data = r.read()
    vsota = hashlib.sha256(data).hexdigest()
    if vsota != REDIST_SHA256:
        print(f"MSVC runtime: SHA-256 NE USTREZA: {vsota} != {REDIST_SHA256}", file=sys.stderr); return 2
    with tempfile.TemporaryDirectory() as delo:
        if sys.platform == "win32":   # dodatno k pripeti vsoti: veljaven podpis Microsoft Corporation
            exe = os.path.join(delo, "VC_redist.x64.exe")
            with open(exe, "wb") as f:
                f.write(data)
            if not all(_gradnja.podpis_microsoft([exe]).values()):
                # CI 41459814885 (2. 11. 2026): runner windows-2022 podpisa ne potrdi (enako kot DLL runtime v CI
                # 40361223511, PODPISNIK_MSVC), na testnem PC je »Valid«. Odloca pripeta SHA-256 zgoraj (strozja od
                # podpisa) in pripete vsote vsakega DLL spodaj; stanje podpisa izpisemo za sled.
                print("::notice::MSVC runtime: Get-AuthenticodeSignature VC_redist ni Valid na tem stroju - velja "
                      "pripeta SHA-256 " + REDIST_SHA256, flush=True)
        druzina = druzina_iz_paketa(data, delo)
    napacne = sorted(ime for ime, vsebina in druzina.items()
                     if hashlib.sha256(vsebina).hexdigest() != pricakovano.get(ime))
    manjka = sorted(set(pricakovano) - set(druzina))
    if napacne or manjka:
        print(f"MSVC runtime: paket ne ustreza pripetim DLL (vsota: {napacne}, manjka: {manjka})", file=sys.stderr)
        return 3
    shutil.rmtree(CILJ, ignore_errors=True); os.makedirs(CILJ)
    for ime, vsebina in sorted(druzina.items()):
        with open(os.path.join(CILJ, ime), "wb") as f:
            f.write(vsebina)
    open(znak, "w", encoding="utf-8").write(REDIST_SHA256 + "\n")
    print(f"MSVC runtime: VC_redist {REDIST_RAZLICICA} razpakiran ({len(druzina)} DLL) v {CILJ}: "
          + ", ".join(sorted(druzina)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
