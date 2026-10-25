"""most_metode_win.py (imena metod zaledja Windows za zmoznosti()) se ujema s kodo zaledja - os_app.py, namizje_win.py,
namizje_qml.py (scripts/most_pregled.py). Nova metoda v zaledju: dodaj jo tudi v most_metode_win.py."""
import importlib.util
import unittest
from pathlib import Path

from safeer_windows import most_metode_win as mw

KOREN = Path(__file__).resolve().parents[2]


def _pregled():
    spec = importlib.util.spec_from_file_location("most_pregled", KOREN / "scripts" / "most_pregled.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class MostMetodeWin(unittest.TestCase):
    def test_ujema_s_kodo(self):
        z = _pregled().zaledje(KOREN)
        self.assertEqual(sorted(mw.HTML ^ z["html"]), [], "os_app.py: metode in most_metode_win.HTML se razlikujejo")
        self.assertEqual(sorted(mw.DELOVNA ^ z["delovna"]), [], "namizje_win.metode in DELOVNA se razlikujejo")
        self.assertEqual(sorted(mw.QML ^ z["qml"]), [], "namizje_qml.izvedi in QML se razlikujejo")

    def test_dispecer_zmoznosti(self):
        from core import os_most_metode
        d = os_most_metode.Dispecer(None, mw.HTML, platforma="windows")
        z = d.zmoznosti()
        self.assertIn("mediaKatalog", z)          # metoda zaledja Windows
        self.assertIn("diski", z)                 # skupna metoda jedra
        self.assertIn("zmoznosti", z)


if __name__ == "__main__":
    unittest.main()
