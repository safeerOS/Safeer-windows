"""Zacasni profili WebView2 se ne kopicijo."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from safeer_windows import webview2_media
except Exception as e:  # PySide6 manjka
    webview2_media = None
    RAZLOG = str(e)


@unittest.skipIf(webview2_media is None, "PySide6 ni na voljo")
class Seje(unittest.TestCase):
    def test_pocisti_stare_in_pusti_trenutno(self):
        koren = Path(tempfile.mkdtemp())
        stara = koren / "session-stara"; (stara / "profile").mkdir(parents=True)
        nova = koren / "session-nova"; (nova / "profile").mkdir(parents=True)
        trenutna = koren / "session-trenutna"; trenutna.mkdir()
        tuja = koren / "druga-mapa"; tuja.mkdir()
        t = time.time() - 7200
        os.utime(stara, (t, t)); os.utime(trenutna, (t, t))
        n = webview2_media.pocisti_seje(koren, razen=str(trenutna), starejse_od_s=3600)
        self.assertEqual(n, 1)
        self.assertFalse(stara.exists())
        self.assertTrue(nova.exists() and trenutna.exists() and tuja.exists())

    def test_manjkajoca_mapa(self):
        self.assertEqual(webview2_media.pocisti_seje(Path(tempfile.mkdtemp()) / "ni"), 0)


if __name__ == "__main__":
    unittest.main()
