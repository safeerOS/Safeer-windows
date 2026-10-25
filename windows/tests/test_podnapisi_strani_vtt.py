"""Podnapisi strani (WebVTT za <track>) iz lokalnega toka: `import urllib.request` znotraj funkcije je naredil ime
`urllib` lokalno za vso funkcijo, zato je `urllib.parse.urlsplit` padel z UnboundLocalError (ruff F823, najdeno
25. 10. 2026) - podnapisi iz toka se niso nikoli pokazali."""
import os
import sys
import types

import pytest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from safeer_windows import os_app  # noqa: E402


def test_tok_drugega_gostitelja_zavrnjen_brez_napake():
    okno = types.SimpleNamespace(_podnapisi_strani={"p1": ("url", "http://192.168.0.5:8080/p.vtt", "p")})
    assert os_app.SafeerOsWindow._podnapis_vtt(okno, "p1") == ""


def test_neznana_oznaka():
    okno = types.SimpleNamespace(_podnapisi_strani={})
    assert os_app.SafeerOsWindow._podnapis_vtt(okno, "x") == ""
