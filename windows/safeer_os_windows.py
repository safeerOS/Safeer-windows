#!/usr/bin/env python3
"""Zagon samostojne aplikacije Safeer OS za Windows.

Uporaba:
    python windows/safeer_os_windows.py          # Celozaslonsko
    python windows/safeer_os_windows.py --okno   # V oknu
"""
import os
import sys

# Zagotovi, da je mapa windows/ v sys.path
KOREN_WIN = os.path.dirname(os.path.abspath(__file__))
if KOREN_WIN not in sys.path:
    sys.path.insert(0, KOREN_WIN)
# Tudi koren repozitorija (paket core/): zagon iz registra (magnet povezava) nima PYTHONPATH zaganjalnika.
KOREN = os.path.dirname(KOREN_WIN)
if KOREN not in sys.path:
    sys.path.append(KOREN)

# Knjiznice preveri program sam, kadar ga za to prosi zaganjalnik (koda 86: zaganjalnik jih namesti in zazene znova).
from safeer_windows import knjiznice
knjiznice.preveri_ob_zagonu()

# libmpv (pravilo 6): runtime iz paketa safeer_windows/vendor/mpv/runtime PRED PySide6; brez paketa no-op.
try:
    from safeer_windows.safeer_mpv_pogon import predpripravi_runtime
    predpripravi_runtime()
except Exception:
    pass

from safeer_windows import tls_koreni
tls_koreni.namesti()

from safeer_windows.os_app import main

if __name__ == "__main__":
    sys.exit(main())
