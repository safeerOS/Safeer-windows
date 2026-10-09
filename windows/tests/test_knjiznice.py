"""Preverba knjiznic ob zagonu: dogovor med programom (safeer_windows/knjiznice.py) in zaganjalnikom (launcher_go)."""
import ast
import importlib
import importlib.machinery
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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
        self.assertEqual(sorted(uvozi), ["importlib.machinery", "importlib.util", "os", "sys", "time"])


class MehkeKnjiznice(unittest.TestCase):
    """cryptography in Pillow: program tece tudi brez njiju, zato neuspela namestitev ne ustavlja vsakega zagona."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.poskus = os.path.join(self._td.name, "SafeerOS", "knjiznice-poskus.txt")
        self.zdaj = [1_800_000_000.0]

    def tearDown(self):
        self._td.cleanup()

    def _preveri(self, znani, moduli=("PySide6", "cryptography", "PIL")):
        izpisi, izhodi = [], []
        knjiznice.preveri_ob_zagonu(okolje={knjiznice.OKOLJE: "1"}, izpis=izpisi.append, izhod=izhodi.append,
                                    moduli=moduli, najdi=_najdi(znani), poskus=self.poskus, ura=lambda: self.zdaj[0])
        return izpisi, izhodi

    def test_sta_na_seznamu(self):
        self.assertEqual(knjiznice.PAKETI["cryptography"], "cryptography")
        self.assertEqual(knjiznice.PAKETI["PIL"], "Pillow")
        self.assertEqual(set(knjiznice.MEHKE), {"cryptography", "PIL", "dxcam", "soundcard"})
        self.assertTrue(set(knjiznice.MEHKE) <= set(knjiznice.POTREBNE))

    def test_prvic_prosi_zaganjalnik(self):
        izpisi, izhodi = self._preveri(("PySide6",))
        self.assertEqual(izhodi, [knjiznice.KODA_MANJKAJO])
        self.assertEqual(izpisi, [knjiznice.OZNAKA_MANJKAJO + " cryptography, PIL"])
        with open(self.poskus, encoding="ascii") as d:
            self.assertEqual(d.read(), "1800000000")

    def test_po_neuspeli_namestitvi_tece_brez_njiju(self):
        self._preveri(("PySide6",))
        self.zdaj[0] += 3600
        izpisi, izhodi = self._preveri(("PySide6",))
        self.assertEqual(izhodi, [], "isti dan zaganjalnika ne prosimo znova")
        self.assertEqual(len(izpisi), 1)
        self.assertTrue(izpisi[0].startswith(knjiznice.OZNAKA_OK), "zaganjalnik v dnevniku isce to oznako")
        self.assertIn("cryptography, PIL", izpisi[0])

    def test_naslednji_dan_poskusi_znova(self):
        self._preveri(("PySide6",))
        self.zdaj[0] += knjiznice.POSKUS_MEHKIH_S + 1
        izpisi, izhodi = self._preveri(("PySide6",))
        self.assertEqual(izhodi, [knjiznice.KODA_MANJKAJO])
        with open(self.poskus, encoding="ascii") as d:
            self.assertEqual(float(d.read()), self.zdaj[0])

    def test_trda_knjiznica_ne_caka(self):
        self._preveri(("PySide6",))                       # zapis o poskusu je svez
        izpisi, izhodi = self._preveri(())                # manjka tudi PySide6
        self.assertEqual(izhodi, [knjiznice.KODA_MANJKAJO])
        self.assertEqual(izpisi, [knjiznice.OZNAKA_MANJKAJO + " PySide6, cryptography, PIL"])

    def test_ko_sta_namesceni_je_vse_v_redu(self):
        self._preveri(("PySide6",))
        izpisi, izhodi = self._preveri(("PySide6", "cryptography", "PIL"))
        self.assertEqual((izpisi, izhodi), ([knjiznice.OZNAKA_OK], []))

    def test_pokvarjen_zapis_ali_ura_nazaj_ne_ustavita_poskusa(self):
        os.makedirs(os.path.dirname(self.poskus))
        for vsebina in ("", "ni stevilo", str(self.zdaj[0] + 5000)):
            with open(self.poskus, "w", encoding="ascii") as d:
                d.write(vsebina)
            self.assertEqual(self._preveri(("PySide6",))[1], [knjiznice.KODA_MANJKAJO], vsebina)

    def test_zapisa_ni_mogoce_shraniti(self):
        # Mapa je datoteka: zapis ne uspe, preverba vseeno odgovori.
        with open(os.path.join(self._td.name, "SafeerOS"), "w") as d:
            d.write("x")
        self.assertEqual(self._preveri(("PySide6",))[1], [knjiznice.KODA_MANJKAJO])

    def test_pot_zapisa_je_v_mapi_programa(self):
        with unittest.mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join("C:", "Users", "U", "AppData", "Local")}):
            self.assertEqual(os.path.basename(os.path.dirname(knjiznice.pot_poskusa())), "SafeerOS")


class ZunanjeKnjiznice(unittest.TestCase):
    """Vsako knjiznico zunaj Pythona, ki jo program uvozi, mora zaganjalnik namestiti - ali pa je tu zapisano, zakaj ne.

    Do 1.0.38 je program uvazal cryptography in Pillow, zaganjalnik pa ju ni namestil: na razvojnem racunalniku sta bila
    namescena rocno, na cistem racunalniku je Safeer Link ostal brez identitete (izmerjeno 5. 10. 2026)."""

    #: modul -> paket na PyPI (kot ga namesti zaganjalnik)
    MODUL_PAKET = {"PySide6": "PySide6", "qrcode": "qrcode", "vlc": "python-vlc", "mutagen": "mutagen", "av": "av",
                   "truststore": "truststore", "zeroconf": "zeroconf", "mpv": "python-mpv", "winrt": "winrt-runtime",
                   "cryptography": "cryptography", "PIL": "Pillow", "dxcam": "dxcam", "soundcard": "soundcard"}
    #: modul -> zakaj ga zaganjalnik ne namesti
    NE_NAMESTIMO = {"gi": "GTK in D-Bus: samo Linux (deli jedra, ki jih Windows ne klice)",
                    "pefile": "samo gradnja paketa (build_windows.py)"}

    def _uvozi(self):
        najdeni = {}
        for koren, globoko in ((KOREN / "core", True), (KOREN / "windows" / "safeer_windows", True),
                               (KOREN / "windows", False)):
            for pot in (koren.rglob("*.py") if globoko else koren.glob("*.py")):
                deli = pot.relative_to(KOREN).parts
                if "tests" in deli or "__pycache__" in deli or "vendor" in deli:
                    continue
                for vozel in ast.walk(ast.parse(pot.read_text(encoding="utf-8"))):
                    imena = []
                    if isinstance(vozel, ast.Import):
                        imena = [a.name for a in vozel.names]
                    elif isinstance(vozel, ast.ImportFrom) and vozel.level == 0 and vozel.module:
                        imena = [vozel.module]
                    for ime in imena:
                        najdeni.setdefault(ime.split(".")[0], str(pot.relative_to(KOREN)))
        return najdeni

    def _zunanji(self):
        zunanji = {}
        for modul, kje in self._uvozi().items():
            if modul in sys.stdlib_module_names or modul in ("core", "safeer_windows", "ui"):
                continue
            if any((KOREN / mapa / modul).is_dir() or (KOREN / mapa / (modul + ".py")).is_file()
                   for mapa in ("windows", ".")) and modul != "qrcode":
                continue                                   # nas modul v repozitoriju
            zunanji[modul] = kje
        return zunanji

    def test_vsak_zunanji_uvoz_je_namescen_ali_pojasnjen(self):
        zunanji = self._zunanji()
        self.assertIn("cryptography", zunanji, "preizkus mora videti uvoze programa")
        self.assertIn("PIL", zunanji)
        neznani = {m: kje for m, kje in zunanji.items() if m not in self.MODUL_PAKET and m not in self.NE_NAMESTIMO}
        self.assertEqual(neznani, {}, "nova zunanja knjiznica: dodaj jo zaganjalniku (paketiPip) ali zapisi, zakaj ne")

    def test_zaganjalnik_namesti_vse_kar_program_uvozi(self):
        go = (KOREN / "windows" / "launcher_go" / "main.go").read_text(encoding="utf-8")
        seznam = re.search(r"var paketiPip = \[\]string\{(.*?)\n\}", go, re.S)
        paketi = [p.split("==")[0] for p in re.findall(r'"([^"]+)"', seznam.group(1))]
        for modul in self._zunanji():
            if modul in self.NE_NAMESTIMO:
                continue
            self.assertIn(self.MODUL_PAKET[modul], paketi, "zaganjalnik ne namesti paketa za modul " + modul)

    def test_knjiznica_brez_katere_ni_safeer_linka_se_preveri_ob_zagonu(self):
        for modul in ("cryptography", "PIL", "zeroconf", "qrcode"):
            self.assertIn(modul, knjiznice.POTREBNE)


if __name__ == "__main__":
    unittest.main()
