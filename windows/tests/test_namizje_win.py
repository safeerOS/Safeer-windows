"""Namizje Safeer OS za Windows: skupna stran z Linuxom, metode namizja, Koš, okno pod vsemi okni."""
import os
import re
import struct
import tempfile
import unittest
from pathlib import Path

from safeer_windows import namizje_datoteke as nd

KOREN = Path(__file__).resolve().parents[2]
NAMIZJE = (KOREN / "windows" / "safeer_windows" / "namizje_win.py").read_text(encoding="utf-8")
APP = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")


class Kos(unittest.TestCase):
    def _filetime(self, unix):
        return int(unix * 1e7) + 116444736000000000

    def test_info_razlicica_2(self):
        pot = "C:\\Users\\x\\Dokumenti\\poročilo.docx"
        podatki = struct.pack("<qqqi", 2, 1234, self._filetime(1_760_000_000), len(pot) + 1) + (pot + "\0").encode("utf-16-le")
        info = nd.beri_info(podatki)
        self.assertEqual(info["izvirna"], pot)
        self.assertEqual(info["velikost"], 1234)
        self.assertAlmostEqual(info["izbrisano"], 1_760_000_000, places=0)

    def test_info_razlicica_1(self):
        pot = "D:\\slika.png"
        podatki = struct.pack("<qqq", 1, 9, self._filetime(1_700_000_000)) + (pot + "\0").encode("utf-16-le").ljust(520, b"\0")
        self.assertEqual(nd.beri_info(podatki)["izvirna"], pot)

    def test_neveljaven_info(self):
        self.assertIsNone(nd.beri_info(b"\0" * 10))
        self.assertIsNone(nd.beri_info(struct.pack("<qqq", 7, 0, 0) + b"\0" * 8))

    def test_obnovi_samo_iz_kosa(self):
        self.assertEqual(nd.obnovi_iz_smeti(os.path.abspath(__file__))["ok"], False)


class Bliznjica(unittest.TestCase):
    def _lnk(self, osnova: bytes, pripona: bytes) -> bytes:
        glava = bytearray(0x4C)
        glava[0:4] = b"\x4c\x00\x00\x00"
        struct.pack_into("<I", glava, 0x14, 0x2)            # samo HasLinkInfo
        nizi_odmik = 0x1C + 4                                # glava LinkInfo + prazen VolumeID
        osnova_odmik = nizi_odmik
        pripona_odmik = osnova_odmik + len(osnova) + 1
        velikost = pripona_odmik + len(pripona) + 1
        li = struct.pack("<IIIIIII", velikost, 0x1C, 1, 0x1C, osnova_odmik, 0, pripona_odmik)
        li += struct.pack("<I", 4) + osnova + b"\0" + pripona + b"\0"
        return bytes(glava) + li

    def test_osnova_in_pripona(self):
        self.assertEqual(nd.cilj_bliznjice(self._lnk(b"C:\\Users\\x\\", b"zapis.txt")), "C:\\Users\\x\\zapis.txt")

    def test_ni_bliznjica(self):
        self.assertEqual(nd.cilj_bliznjice(b"ni lnk"), "")


class Pregled(unittest.TestCase):
    def test_skrite_in_navadne(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.txt").write_text("x")
            Path(d, ".skrita").write_text("x")
            imena = [e["ime"] for e in nd.preglej(d)["elementi"]]
            self.assertEqual(imena, ["a.txt"])


class Stran(unittest.TestCase):
    def test_ista_stran_kot_linux(self):
        for ime in ("delovna.html", "delovna.js", "delovna.css", "iskanje.js"):
            self.assertTrue((KOREN / "assets" / "os" / ime).is_file(), ime)

    def test_metode_namizja_so_varne(self):
        # Vsak klic strani, ki ga namizje ne razresi samo, gre glavnemu oknu (neznana metoda vrne None, stran to prenese).
        klici = set(re.findall(r'klic\("([A-Za-z_]+)"', (KOREN / "assets" / "os" / "delovna.js").read_text(encoding="utf-8")))
        nase = set(re.findall(r'^\s+"([A-Za-z_]+)": lambda a', NAMIZJE, re.M))
        for m in ("mapa", "smeti", "vSmeti", "obnoviIzSmeti", "nosilci", "prostorDiska", "posljiNapravi", "zacetek"):
            self.assertIn(m, nase)
            self.assertIn(m, klici)
        self.assertIn("self.os_okno._izvedi_metodo(metoda, a)", NAMIZJE)

    def test_okno_pod_vsemi_okni(self):
        self.assertIn("WM_WINDOWPOSCHANGING", NAMIZJE)
        self.assertIn('FindWindowW("Progman", None)', NAMIZJE)
        self.assertIn("Qt.WindowType.Tool", NAMIZJE)

    def test_vklop_in_zapiranje(self):
        self.assertIn('"--namizje"', APP)
        self.assertIn('metoda == "namizjeSafeer"', APP)
        self.assertIn("Safeer OS je namizje: zapiranje okna ga le skrije", APP)


if __name__ == "__main__":
    unittest.main()


class Qml(unittest.TestCase):
    def test_namizje_qml_se_nalozi_brez_napak(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtCore import QObject, QUrl, Signal, Slot
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQuick import QQuickView
        except ImportError:
            self.skipTest("PySide6 ni na voljo")

        class Most(QObject):
            odgovor = Signal(int, bool, str)
            dogodek = Signal(str, str)

            @Slot(str, str, result=int)
            def klic(self, _m, _a):
                return 1

            @Slot(str, result=str)
            def datotekaUrl(self, p):
                return p

        app = QGuiApplication.instance() or QGuiApplication([])
        most = Most()
        pogled = QQuickView()
        pogled.rootContext().setContextProperty("Most", most)
        pogled.setSource(QUrl.fromLocalFile(str(KOREN / "windows" / "safeer_windows" / "qml" / "Namizje.qml")))
        self.assertEqual([e.toString() for e in pogled.errors()], [])
        self.assertIsNotNone(pogled.rootObject())
        pogled.deleteLater()
        del app
