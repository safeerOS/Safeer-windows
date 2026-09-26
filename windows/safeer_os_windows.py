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

from safeer_windows.os_app import main

if __name__ == "__main__":
    sys.exit(main())
