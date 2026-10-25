"""Tema Safeer OS na Windows kot namizje na Linuxu: barve iz os.css, ozadje namizja tudi v oknu Safeer OS."""
import http.client
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from safeer_windows import os_app, tema

KOREN = Path(__file__).resolve().parents[2]
CSS = (KOREN / "assets" / "os" / "os.css").read_text(encoding="utf-8")


class Barve(unittest.TestCase):
    def _paleta(self, css):
        with mock.patch.object(tema, "_os_css", return_value=css), mock.patch.object(tema, "trenutna", return_value="safeer"):
            tema._predpomnilnik.clear()
            try:
                return tema.paleta("safeer")
            finally:
                tema._predpomnilnik.clear()

    def test_privzeta_paleta_je_linux(self):
        # Iste barve kot Safeer-linux assets/os/tokens.css (temno modra, moder poudarek, zeleno samo za »deluje«).
        p = self._paleta(CSS)
        self.assertEqual(p["poudarek"], "#8ac7ff")
        self.assertEqual(p["ozadje"], "#0b1424")
        self.assertEqual(p["fokus"], "#9dceff")
        self.assertEqual(p["ok"], "#7fe0b6")

    def test_rezerva_brez_css_enaka(self):
        self.assertEqual(self._paleta("")["poudarek"], "#8ac7ff")

    def test_ni_vec_fiksne_zelene(self):
        # Poudarek s prosojnostjo sledi temi (color-mix z var(--zelena)), ne stari fiksni zeleni.
        self.assertIsNone(re.search(r"rgba\(\s*84\s*,\s*214\s*,\s*165", CSS))


class OzadjeOkna(unittest.TestCase):
    def _get(self, port, pot):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.request("GET", pot)
            r = c.getresponse()
            return r.status, r.getheader("Content-Type"), r.read()
        finally:
            c.close()

    def test_streze_samo_sliko(self):
        port = os_app._start_local_asset_server(str(KOREN / "assets"))
        jpeg = b"\xff\xd8\xff\xe0" + b"\0" * 64      # ozadje Windows (TranscodedWallpaper) nima koncnice
        with mock.patch.object(os_app, "_ozadje_za_splet", return_value=("application/octet-stream", jpeg)):
            status, vrsta, telo = self._get(port, "/ozadje-namizja?v=1")
        self.assertEqual((status, vrsta), (200, "image/jpeg"))
        self.assertEqual(telo, jpeg)
        with mock.patch.object(os_app, "_ozadje_za_splet", return_value=("text/plain", b"ni slika")):
            self.assertEqual(self._get(port, "/ozadje-namizja")[0], 415)
        with mock.patch.object(os_app, "_ozadje_za_splet", return_value=None):
            self.assertEqual(self._get(port, "/ozadje-namizja")[0], 404)

    def test_zacetek_poslje_ozadje(self):
        src = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn('"ozadje": "/ozadje-namizja?v=%d" % int(time.time())', src)


if __name__ == "__main__":
    unittest.main()
