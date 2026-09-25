#!/usr/bin/env python3
"""Zagon samostojne aplikacije Safeer OS za Windows.

Uporaba:
    python windows/safeer_os_windows.py          # Celozaslonsko
    python windows/safeer_os_windows.py --okno   # V oknu
"""
import os
import sys

# Nastavitve za Chromium za vdelane toke in preprecevanje X-Frame-Options zavrnitev
_cr = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
_flags = "--disable-web-security --no-sandbox --disable-site-isolation-trials --disable-features=SitePerProcess,IsolateOrigins --autoplay-policy=no-user-gesture-required"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{_cr} {_flags}".strip()

# Zagotovi, da je mapa windows/ v sys.path
KOREN_WIN = os.path.dirname(os.path.abspath(__file__))
if KOREN_WIN not in sys.path:
    sys.path.insert(0, KOREN_WIN)

from safeer_windows.os_app import main

if __name__ == "__main__":
    sys.exit(main())
