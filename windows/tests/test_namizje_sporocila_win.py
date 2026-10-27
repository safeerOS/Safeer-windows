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


NL = chr(10)
KONEC_FUNKCIJE, KONEC_POJDI, KONEC_BLOKA = NL + "        }" + NL, NL + "  };", NL + "    }" + NL
OSJS = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")


class IskanjePogovorov(unittest.TestCase):
    def test_lupa_isce_pogovore_kot_linux(self):
        isci = QML.split("function isci(q) {", 1)[1].split(KONEC_FUNKCIJE, 1)[0]
        self.assertIn('koren.klic("sporocilaSeznam", [""]', isci)
        self.assertIn("Date.now() - sporocilaCas < 30000", isci)       # ne ob vsaki crki
        self.assertIn("if (q.length >= 2)", isci)
        self.assertIn('kljuc: "pogovor:" + p.kanal_id + ":" + p.id', QML)

    def test_zadetek_odpre_pogovor(self):
        izberi = QML.split("function izberi(i) {", 1)[1].split(KONEC_FUNKCIJE, 1)[0]
        self.assertIn('else if (z.vrsta === "pogovor") koren.klic("odpriRazdelek", [z.kljuc])', izberi)
        # Pogovor ni Splet: brez te veje bi sel v spletNaNamizju (zadnja veja).
        self.assertLess(izberi.index('z.vrsta === "pogovor"'), izberi.index("spletNaNamizju"))

    def test_okno_sporocila_odpre_pogovor_brez_kroga(self):
        pojdi = OSJS.split("window.safeerOsPojdi = function (kam) {", 1)[1].split(KONEC_POJDI, 1)[0]
        blok = pojdi.split('if (kam.indexOf("pogovor:") === 0) {', 1)[1].split(KONEC_BLOKA, 1)[0]
        self.assertIn("odpriPogovor(najden[0], najden[1])", blok)
        self.assertIn('klic("odpriRazdelek", [kam])', blok)      # drugo okno: cel cilj naprej, ne samo »sporocila«
        self.assertNotIn("pojdi(kam)", blok)                     # pojdi() »pogovor:« ne pozna -> krog okno <-> stran
        self.assertLess(pojdi.index('kam.indexOf("pogovor:") === 0'), pojdi.index("pojdi(kam);"))


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
