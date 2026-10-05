"""Preverba knjiznic ob zagonu: dogovor med programom (safeer_windows/knjiznice.py) in zaganjalnikom (launcher_go)."""
import importlib
import importlib.machinery
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from safeer_windows import knjiznice

KOREN = Path(__file__).resolve().parents[2]


def _najdi(znani):
    def najdi(modul):
        if modul == "pokvarjen":
            raise ValueError("pokvarjen zapis modula")
        if modul.startswith("ni_starsa."):
            raise ModuleNotFoundError(modul)
        return object() if modul in znani else None
    return najdi


class Knjiznice(unittest.TestCase):
    def test_brez_narocila_zaganjalnika_se_ne_preverja(self):
        for okolje in ({}, {knjiznice.OKOLJE: "0"}, {knjiznice.OKOLJE: ""}):
            izpisi, izhodi = [], []
            preverjal = knjiznice.preveri_ob_zagonu(okolje=okolje, izpis=izpisi.append, izhod=izhodi.append,
                                                    moduli=("ni_takega",), najdi=_najdi(()))
            self.assertFalse(preverjal)
            self.assertEqual((izpisi, izhodi), ([], []))

    def test_vse_na_mestu_izpise_oznako(self):
        izpisi, izhodi = [], []
        preverjal = knjiznice.preveri_ob_zagonu(okolje={knjiznice.OKOLJE: "1"}, izpis=izpisi.append, izhod=izhodi.append,
                                                moduli=("a", "b.c"), najdi=_najdi(("a", "b.c")))
        self.assertTrue(preverjal)
        self.assertEqual((izpisi, izhodi), ([knjiznice.OZNAKA_OK], []))

    def test_manjkajoce_konca_program_s_kodo(self):
        izpisi, izhodi = [], []
        knjiznice.preveri_ob_zagonu(okolje={knjiznice.OKOLJE: "1"}, izpis=izpisi.append, izhod=izhodi.append,
                                    moduli=("a", "manjka", "ni_starsa.x", "pokvarjen"), najdi=_najdi(("a",)))
        self.assertEqual(izhodi, [knjiznice.KODA_MANJKAJO])
        self.assertEqual(izpisi, [knjiznice.OZNAKA_MANJKAJO + " manjka, ni_starsa.x, pokvarjen"])

    def test_pravi_moduli(self):
        self.assertEqual(knjiznice.manjkajoce(("json", "json.decoder", "email.mime", "xml.etree.ElementTree",
                                               "ni_takega_modula_safeer", "ni_takega_paketa_safeer.pod", "json.ni_takega")),
                         ["ni_takega_modula_safeer", "ni_takega_paketa_safeer.pod", "json.ni_takega"])

    def test_podmodula_ne_isce_z_uvozom_starsev(self):
        # Uvoz starsev (winrt.windows.media) je pocasen; preverba sme samo pogledati na disk.
        with tempfile.TemporaryDirectory() as mapa:
            paket = Path(mapa) / "safeer_preizkusni_paket"
            (paket / "a" / "b").mkdir(parents=True)
            (paket / "prazna").mkdir()
            (paket / "__init__.py").write_text("raise RuntimeError('paket se ne sme uvoziti')\n", encoding="utf-8")
            (paket / "a" / "__init__.py").write_text("raise RuntimeError('podpaket se ne sme uvoziti')\n", encoding="utf-8")
            (paket / "a" / "b" / "__init__.py").write_text("", encoding="utf-8")
            (paket / "a" / "modul.py").write_text("", encoding="utf-8")
            (paket / "a" / ("razsiritev" + importlib.machinery.EXTENSION_SUFFIXES[0])).write_bytes(b"")
            sys.path.insert(0, mapa)
            importlib.invalidate_caches()
            try:
                for modul in ("safeer_preizkusni_paket", "safeer_preizkusni_paket.a", "safeer_preizkusni_paket.a.b",
                              "safeer_preizkusni_paket.a.modul", "safeer_preizkusni_paket.a.razsiritev"):
                    self.assertIsNotNone(knjiznice.najdi(modul), modul)
                for modul in ("safeer_preizkusni_paket.prazna", "safeer_preizkusni_paket.a.ni", "safeer_preizkusni_paket.a.b.c"):
                    self.assertIsNone(knjiznice.najdi(modul), modul)
                self.assertEqual(knjiznice.manjkajoce(("safeer_preizkusni_paket.a.b", "safeer_preizkusni_paket.a.ni")),
                                 ["safeer_preizkusni_paket.a.ni"])
                self.assertFalse([m for m in sys.modules if m.startswith("safeer_preizkusni_paket")])
            finally:
                sys.path.remove(mapa)
                importlib.invalidate_caches()

    def _zazeni(self, moduli, okolje):
        koda = "from safeer_windows import knjiznice; knjiznice.preveri_ob_zagonu(moduli=%r); print('naprej')" % (moduli,)
        env = {k: v for k, v in os.environ.items() if k != knjiznice.OKOLJE}
        env["PYTHONPATH"] = str(KOREN / "windows")
        env.update(okolje)
        return subprocess.run([sys.executable, "-c", koda], env=env, capture_output=True, text=True, timeout=60)

    def test_pravi_zagon(self):
        p = self._zazeni(("json", "ni_takega_modula_safeer"), {knjiznice.OKOLJE: "1"})
        self.assertEqual(p.returncode, knjiznice.KODA_MANJKAJO, p.stderr)
        self.assertEqual(p.stdout.strip(), knjiznice.OZNAKA_MANJKAJO + " ni_takega_modula_safeer")
        p = self._zazeni(("json",), {knjiznice.OKOLJE: "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.split(), (knjiznice.OZNAKA_OK + " naprej").split())
        # Brez narocila zaganjalnika program tece naprej tudi brez knjiznice (kot doslej).
        p = self._zazeni(("ni_takega_modula_safeer",), {})
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "naprej"), p.stderr)

    def test_dogovor_z_zaganjalnikom(self):
        go = (KOREN / "windows" / "launcher_go" / "main.go").read_text(encoding="utf-8")
        self.assertRegex(go, r'okoljePreverbe\s*=\s*"%s"' % re.escape(knjiznice.OKOLJE))
        self.assertRegex(go, r"kodaManjkajoKnjiznice\s*=\s*%d\b" % knjiznice.KODA_MANJKAJO)
        self.assertRegex(go, r'oznakaKnjizniceOK\s*=\s*"%s"' % re.escape(knjiznice.OZNAKA_OK))
        self.assertIn('okoljePreverbe+"=1"', go)
        seznam = re.search(r"var paketiPip = \[\]string\{(.*?)\n\}", go, re.S)
        self.assertIsNotNone(seznam, "seznama paketov v zaganjalniku ni")
        paketi = [p.split("==")[0] for p in re.findall(r'"([^"]+)"', seznam.group(1))]
        for modul, paket in knjiznice.PAKETI.items():
            self.assertIn(paket, paketi, "zaganjalnik ne namesti paketa za modul " + modul)
        # Zaganjalnik sam Pythona za preverbo ne zaganja vec.
        self.assertNotIn("checkScript", go)

    def test_vstopni_skripti_preverita_pred_tezkimi_uvozi(self):
        os_skripta = (KOREN / "windows" / "safeer_os_windows.py").read_text(encoding="utf-8")
        klic = os_skripta.index("knjiznice.preveri_ob_zagonu()")
        for pozneje in ("safeer_mpv_pogon", "tls_koreni", "from safeer_windows.os_app import main"):
            self.assertLess(klic, os_skripta.index(pozneje), pozneje)
        brskalnik = (KOREN / "windows" / "launcher.py").read_text(encoding="utf-8")
        self.assertLess(brskalnik.index("knjiznice.preveri_ob_zagonu()"), brskalnik.index("from safeer_windows.browser import main"))

    def test_modul_ne_uvaza_nicesar_tezkega(self):
        vir = (KOREN / "windows" / "safeer_windows" / "knjiznice.py").read_text(encoding="utf-8")
        uvozi = re.findall(r"^(?:import|from)\s+(\S+)", vir, re.M)
        self.assertEqual(sorted(uvozi), ["importlib.machinery", "importlib.util", "os", "sys"])


if __name__ == "__main__":
    unittest.main()
