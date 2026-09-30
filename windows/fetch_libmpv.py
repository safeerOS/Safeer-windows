#!/usr/bin/env python3
"""Prenese pripeti paket libmpv (lastna LGPL gradnja, izdaja na forku safeerOS/milutv-libmpv) v
windows/safeer_windows/vendor/mpv. Vir, razlicica in SHA-256 so PRIPETI tu (pravilo 5: nic "latest");
neujemanje vsote ali manjkajoca datoteka USTAVI postopek (pravilo 6).

Uporaba: python windows/fetch_libmpv.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import sys
import urllib.request
import zipfile

LIBMPV_IZDAJA = "safeer-av1-dash-snapshot-r1"
LIBMPV_URL = ("https://github.com/safeerOS/milutv-libmpv/releases/download/"
              f"{LIBMPV_IZDAJA}/milutv-libmpv-{LIBMPV_IZDAJA}-x64.zip")
LIBMPV_SHA256 = "2e9f73c1c7e293d4305018affcb7727b1976fb001c7c317c724a3b7a7c67ba14"
# Kar gre v aplikacijo (brez PDB, include, mpv.lib):
OBVEZNO = ("libmpv-2.dll", "libEGL.dll", "libGLESv2.dll", "manifest.json", "safeer-capabilities.json",
           "ffmpeg-license.txt", "runtime/msvcp140.dll", "runtime/vcruntime140.dll", "runtime/vcruntime140_1.dll",
           "licenses/COPYING.LGPL-2.1")
PREDPONE = ("runtime/", "licenses/")
CILJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safeer_windows", "vendor", "mpv")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    znak = os.path.join(CILJ, ".izdaja")
    if not a.force and os.path.isfile(znak) and open(znak, encoding="utf-8").read().strip() == LIBMPV_SHA256 \
            and all(os.path.isfile(os.path.join(CILJ, *f.split("/"))) for f in OBVEZNO):
        print(f"libmpv: {LIBMPV_IZDAJA} ze prisoten v {CILJ}"); return 0
    print(f"libmpv: prenos {LIBMPV_URL}", flush=True)
    with urllib.request.urlopen(LIBMPV_URL, timeout=120) as r:
        data = r.read()
    vsota = hashlib.sha256(data).hexdigest()
    if vsota != LIBMPV_SHA256:
        print(f"libmpv: SHA-256 NE USTREZA: {vsota} != {LIBMPV_SHA256}", file=sys.stderr); return 2
    zf = zipfile.ZipFile(io.BytesIO(data))
    imena = set(zf.namelist())
    manjka = [f for f in OBVEZNO if f not in imena]
    if manjka:
        print("libmpv: paket je nepopoln, manjka: " + ", ".join(manjka), file=sys.stderr); return 3
    shutil.rmtree(CILJ, ignore_errors=True); os.makedirs(CILJ, exist_ok=True)
    n = 0
    for ime in sorted(imena):
        if ime.endswith("/"):
            continue
        if ime in OBVEZNO or ime.startswith(PREDPONE):
            cilj = os.path.join(CILJ, *ime.split("/"))
            os.makedirs(os.path.dirname(cilj), exist_ok=True)
            with zf.open(ime) as src, open(cilj, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    open(znak, "w", encoding="utf-8").write(LIBMPV_SHA256 + "\n")
    print(f"libmpv: {LIBMPV_IZDAJA} razpakiran ({n} datotek) v {CILJ}, sha256 {vsota[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
