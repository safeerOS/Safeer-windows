"""Lastnik 27. 10. 2026: na namizju Safeer za Windows manjkajo Sporocila - gumb pod iskanjem z neprebranimi (znacka)
kot na namizju Linux (popis 3.1); klik odpre okno Sporocila."""
import re
import sys
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

QML = (KOREN / "windows" / "safeer_windows" / "qml" / "Namizje.qml").read_text(encoding="utf-8")
PY = (KOREN / "windows" / "safeer_windows" / "namizje_qml.py").read_text(encoding="utf-8")

try:
    from safeer_windows import namizje_qml  # noqa: E402
except Exception:  # noqa: BLE001 - brez PySide6 ostanejo preverbe izvora
    namizje_qml = None


class GumbSporocila(unittest.TestCase):
    def test_gumb_odpre_sporocila(self):
        telo = QML.split('objectName: "gumbSporocila"', 1)[1].split("\n    }\n", 1)[0]
        self.assertIn('onClicked: koren.klic("odpriRazdelek", ["sporocila"])', telo)
        self.assertIn('Keys.onReturnPressed: koren.klic("odpriRazdelek", ["sporocila"])', telo)
        self.assertIn("visible: koren.sporocilNeprebranih > 0", telo)

    def test_stevilo_iz_mostu_in_dogodka(self):
        self.assertIn('koren.klic("sporocilaNeprebrana", []', QML)
        self.assertIn('vrsta === "sporocilaStevilo"', QML)
        self.assertIn('if metoda == "sporocilaNeprebrana":', PY)

    def test_besedila_v_vseh_jezikih(self):
        for j in ("sl", "en", "de", "es", "fr", "it"):
            vrstica = re.search(r"^\s+" + j + r": \{ (.*)$", QML, re.M).group(1)
            self.assertIn("sporocilaGumb: ", vrstica, j)
            self.assertIn("sporocilaNeprebrana: ", vrstica, j)
            self.assertIn("{n}", vrstica.split("sporocilaNeprebrana: ", 1)[1].split('",', 1)[0], j)


@unittest.skipIf(namizje_qml is None, "namizje_qml se ne uvozi (PySide6)")
class SteviloNeprebranih(unittest.TestCase):
    def test_vsota_skupin(self):
        s = {"skupine": [{"neprebrano": 2, "pogovori": [{"neprebrano": 2}]}, {"neprebrano": 3}, {"neprebrano": 0}]}
        self.assertEqual(namizje_qml.stevilo_neprebranih(s), 5)

    def test_brez_sporocil_ali_napacni_podatki(self):
        for s in (None, {}, {"skupine": None}, {"skupine": [None, {"neprebrano": "x"}, {"neprebrano": -4}]}, []):
            self.assertEqual(namizje_qml.stevilo_neprebranih(s), 0)


if __name__ == "__main__":
    unittest.main()
