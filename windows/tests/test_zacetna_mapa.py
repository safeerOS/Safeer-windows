"""Okna »Odpri« in »Izberi mapo« se ne odprejo v mapi programa.

Videno 5. 10. 2026 na testnem racunalniku z Windows: »Pošlji na napravo« → »Datoteka« je odprlo okno v
%LOCALAPPDATA%\\SafeerOS\\app (assets, core, ui ...). Qt brez podane zacetne mape vzame delovno mapo procesa.
"""
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from safeer_windows import control_window, zacetna_mapa

MODULI = Path(__file__).resolve().parents[1] / "safeer_windows"
IZBIRE = ("getOpenFileName", "getOpenFileNames", "getExistingDirectory")


class ZacetnaMapa(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.mapa = self._td.name
        zacetna_mapa._ZADNJA.clear()

    def tearDown(self):
        zacetna_mapa._ZADNJA.clear()
        self._td.cleanup()

    def _standardna(self, pot):
        return mock.patch("PySide6.QtCore.QStandardPaths.writableLocation", return_value=pot)

    def test_prvic_uporabnikova_mapa_ne_mapa_programa(self):
        dokumenti = os.path.join(self.mapa, "Dokumenti")
        os.mkdir(dokumenti)
        with self._standardna(dokumenti) as klic:
            self.assertEqual(zacetna_mapa.zacetna("poslji"), dokumenti)
        from PySide6.QtCore import QStandardPaths
        klic.assert_called_once_with(QStandardPaths.DocumentsLocation)

    def test_vrsta_izbere_mapo(self):
        from PySide6.QtCore import QStandardPaths
        with self._standardna(self.mapa) as klic:
            zacetna_mapa.zacetna("predvajalnik", "videi")
            zacetna_mapa.zacetna("deli-mapo", "doma")
        self.assertEqual([k.args[0] for k in klic.call_args_list], [QStandardPaths.MoviesLocation, QStandardPaths.HomeLocation])

    def test_brez_take_mape_domaca(self):
        with self._standardna(os.path.join(self.mapa, "ni-je")):
            self.assertEqual(zacetna_mapa.zacetna("poslji"), os.path.expanduser("~"))
        with self._standardna(""):
            self.assertEqual(zacetna_mapa.zacetna("poslji"), os.path.expanduser("~"))

    def test_naslednjic_zadnja_izbrana_za_isti_namen(self):
        slike = os.path.join(self.mapa, "Slike")
        os.mkdir(slike)
        datoteka = os.path.join(slike, "morje.jpg")
        Path(datoteka).write_bytes(b"x")
        zacetna_mapa.zapomni("poslji", datoteka)
        with self._standardna(self.mapa):
            self.assertEqual(zacetna_mapa.zacetna("poslji"), slike)
            self.assertEqual(zacetna_mapa.zacetna("predvajalnik", "videi"), self.mapa, "drug namen ima svojo mapo")

    def test_izbrisana_zadnja_mapa_se_ne_ponudi(self):
        stara = os.path.join(self.mapa, "stara")
        os.mkdir(stara)
        zacetna_mapa.zapomni("poslji", stara)
        os.rmdir(stara)
        with self._standardna(self.mapa):
            self.assertEqual(zacetna_mapa.zacetna("poslji"), self.mapa)

    def test_prazna_izbira_ne_spremeni_nicesar(self):
        zacetna_mapa.zapomni("poslji", "")
        zacetna_mapa.zapomni("poslji", os.path.join(self.mapa, "ni", "je.txt"))
        self.assertEqual(zacetna_mapa._ZADNJA, {})


class OknaSafeerControla(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.mapa = self._td.name
        zacetna_mapa._ZADNJA.clear()
        self.okno = types.SimpleNamespace(backend=mock.Mock())

    def tearDown(self):
        zacetna_mapa._ZADNJA.clear()
        self._td.cleanup()

    def test_poslji_datoteko_odpre_v_uporabnikovi_mapi_in_si_zapomni(self):
        datoteka = os.path.join(self.mapa, "porocilo.pdf")
        Path(datoteka).write_bytes(b"x")
        with mock.patch.object(control_window.zacetna_mapa, "zacetna", return_value="/zacetna") as zacetna, \
                mock.patch.object(control_window.QFileDialog, "getOpenFileName", return_value=(datoteka, "")) as okno:
            control_window.SafeerControlWindow._izberi_datoteko(self.okno, "n-tel")
        zacetna.assert_called_once_with("poslji")
        self.assertEqual(okno.call_args[0][2], "/zacetna")
        self.okno.backend.poslji_datoteko.assert_called_once_with("n-tel", datoteka)
        self.assertEqual(zacetna_mapa._ZADNJA, {"poslji": self.mapa})

    def test_preklicana_izbira_ne_poslje(self):
        with mock.patch.object(control_window.QFileDialog, "getOpenFileName", return_value=("", "")):
            control_window.SafeerControlWindow._izberi_datoteko(self.okno, "n-tel")
        self.okno.backend.poslji_datoteko.assert_not_called()
        self.assertEqual(zacetna_mapa._ZADNJA, {})

    def test_izberi_mapo_za_deljenje(self):
        videi = os.path.join(self.mapa, "Videi")
        os.mkdir(videi)
        with mock.patch.object(control_window.zacetna_mapa, "zacetna", return_value="/doma") as zacetna, \
                mock.patch.object(control_window.QFileDialog, "getExistingDirectory", return_value=videi) as okno:
            control_window.SafeerControlWindow._izberi_mapo(self.okno)
        zacetna.assert_called_once_with("deli-mapo", "doma")
        self.assertEqual(okno.call_args[0][2], "/doma")
        self.okno.backend.dodaj_deljeno_mapo.assert_called_once_with(videi)
        self.assertEqual(zacetna_mapa._ZADNJA, {"deli-mapo": self.mapa}, "naslednja mapa se isce ob prejsnji")

    def test_naslov_v_jeziku_vmesnika(self):
        from safeer_windows import oddaljeni_zaslon
        self.assertEqual(sorted(control_window._NASLOVI_IZBIRE), ["de", "en", "es", "fr", "it", "sl"])
        self.assertTrue(all(len(v) == 2 and all(v) for v in control_window._NASLOVI_IZBIRE.values()))
        with mock.patch.object(oddaljeni_zaslon, "_JEZIK", "de"):
            self.assertEqual(control_window._naslov_izbire(False), "Datei mit Safeer OS senden")
        with mock.patch.object(oddaljeni_zaslon, "_JEZIK", "sl"):
            self.assertEqual(control_window._naslov_izbire(True), "Izberi mapo za deljenje")
        with mock.patch.object(oddaljeni_zaslon, "_JEZIK", "xx"):
            self.assertEqual(control_window._naslov_izbire(False), "Send a file with Safeer OS")


class NobenoOknoBrezZacetneMape(unittest.TestCase):
    """Straza za vse module: QFileDialog.getOpen…/getExistingDirectory vedno dobi zacetno mapo (tretji argument),
    ki ni prazen niz - sicer se okno odpre v mapi programa."""

    def test_vsi_klici(self):
        brez = []
        for pot in sorted(MODULI.glob("*.py")):
            drevo = ast.parse(pot.read_text(encoding="utf-8"))
            for vozel in ast.walk(drevo):
                if not (isinstance(vozel, ast.Call) and isinstance(vozel.func, ast.Attribute) and vozel.func.attr in IZBIRE
                        and isinstance(vozel.func.value, ast.Name) and vozel.func.value.id == "QFileDialog"):
                    continue
                mapa = vozel.args[2] if len(vozel.args) > 2 else next((k.value for k in vozel.keywords if k.arg == "dir"), None)
                if mapa is None or (isinstance(mapa, ast.Constant) and not mapa.value):
                    brez.append("%s:%d %s" % (pot.name, vozel.lineno, vozel.func.attr))
        self.assertEqual(brez, [])


if __name__ == "__main__":
    unittest.main()
