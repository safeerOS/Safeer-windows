"""Zaslon telefona v svojem oknu z misko in tipkovnico (lastnik, 25. 10. 2026: prej zavihek Spleta brez vnosa).

core/gledalec_vnos.py (skupna logika vnosa, Linux GLEDALEC_VNOS_JS) in safeer_windows/okno_zaslona.py (okno Windows):
preverjanje dejanj, zeton mostu, velikost okna, odziv »Safeer Vnos ni vklopljen« in zivi preizkus v QtWebEngine."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

from core import gledalec_vnos as gv  # noqa: E402
from safeer_windows import okno_zaslona  # noqa: E402


class Preveri(unittest.TestCase):
    def test_dovoljena_dejanja_in_meje(self):
        self.assertEqual(gv.preveri({"d": "input.tap", "p": {"x": 0.5, "y": 0.25, "ms": 99999}}),
                         ("input.tap", {"x": 0.5, "y": 0.25, "ms": 2000}))
        self.assertIsNone(gv.preveri({"d": "input.tap", "p": {"x": 1.5, "y": 0.2}}))      # zunaj slike
        self.assertIsNone(gv.preveri({"d": "input.tap", "p": {"x": True, "y": 0.2}}))
        self.assertIsNone(gv.preveri({"d": "input.tap", "p": {"x": float("nan"), "y": 0.2}}))
        self.assertEqual(gv.preveri({"d": "input.swipe", "p": {"x1": 0, "y1": 0.5, "x2": 1, "y2": 0.5}})[1]["ms"], 300)
        self.assertEqual(gv.preveri({"d": "input.scroll", "p": {"x": 0.5, "y": 0.5, "steps": 99}})[1]["steps"],
                         gv.NAJVEC_KORAKOV)
        self.assertIsNone(gv.preveri({"d": "input.scroll", "p": {"x": 0.5, "y": 0.5, "steps": 0}}))
        self.assertEqual(gv.preveri({"d": "input.key", "p": {"key": "back"}}), ("input.key", {"key": "back"}))
        self.assertIsNone(gv.preveri({"d": "input.key", "p": {"key": "power"}}))            # samo tipke Safeer Vnos
        self.assertEqual(len(gv.preveri({"d": "input.text", "p": {"text": "a" * 5000}})[1]["text"]), gv.NAJVEC_BESEDILA)
        self.assertEqual(gv.preveri('{"d": "input.enable"}'), ("input.enable", {}))
        self.assertEqual(gv.preveri({"d": "okno.velikost", "p": {"w": 1080, "h": 2400}}),
                         ("okno.velikost", {"w": 1080, "h": 2400}))
        for slabo in ({"d": "apps.launch", "p": {}}, {"d": "input.text", "p": {"text": ""}}, "ni json", None, []):
            self.assertIsNone(gv.preveri(slabo), slabo)

    def test_odlozisce(self):
        self.assertEqual(gv.besedilo_iz_odlozisca("a\r\nb"), {"text": "a\nb"})
        self.assertIsNone(gv.besedilo_iz_odlozisca(""))
        self.assertIsNone(gv.besedilo_iz_odlozisca(None))

    def test_velikost_okna_v_obliki_naprave(self):
        _x, _y, s, v = gv.velikost_okna(1080, 2400, (0, 0, 1920, 1040), rob_zgoraj=50)
        self.assertLessEqual(v, 1040)
        self.assertAlmostEqual((v - 50) / s, 2400 / 1080, delta=0.05)     # pokoncen telefon: visok in ozek
        _x, _y, s2, v2 = gv.velikost_okna(2400, 1080, (0, 0, 1920, 1040), rob_zgoraj=50)
        self.assertGreater(s2, v2)
        self.assertIsNone(gv.velikost_okna(0, 100, (0, 0, 1920, 1040)))

    def test_odziv(self):
        besedilo, gumb = gv.odziv({"ok": False, "koda": "vnos_ni_vklopljen"}, "sl")
        self.assertIn("Safeer Vnos", besedilo)
        self.assertIn(gv.t("odpriNastavitve", "sl"), besedilo)     # oznake menija so na vsaki napravi drugacne
        self.assertTrue(gumb)
        for koda in ("ni_dovoljeno", "ni_ozji_krog", "ni_v_ozjem_krogu"):
            besedilo, gumb = gv.odziv({"ok": False, "koda": koda}, "sl")
            self.assertIn("ožji krog", besedilo)
            self.assertFalse(gumb)
        self.assertEqual(gv.odziv({"ok": False, "koda": "nekaj_novega"}, "en")[0], gv.t("vnosNiUspel", "en"))
        self.assertEqual(gv.odziv({"ok": True}), ("", False))
        for j in ("sl", "en", "de", "es", "fr", "it"):
            self.assertEqual(set(gv.BESEDILA[j]), set(gv.BESEDILA["sl"]), j)

    def test_skripta(self):
        js = gv.skripta("SPOROCI(d, p);")
        self.assertIn("SPOROCI(d, p);", js)
        self.assertNotIn("__POSLJI__", js)
        self.assertNotIn("__KORAKI__", js)
        self.assertGreaterEqual(js.count("e.isTrusted"), 5)                 # samo dogodki uporabnika
        self.assertIn('"odlozisce.prilepi"', js)
        # Pregled S1/S2: tipke gredo napravi sele po prvem kliku v okno; AltGr (Ctrl+Alt na Windows) ni bliznjica.
        self.assertIn("!kliknjeno) return;", js)
        self.assertIn('getModifierState("AltGraph")', js)
        self.assertIn("&& !altgr", js)

    def test_most_z_zetonom(self):
        js = okno_zaslona.poslji_js("Z123")
        self.assertIn('"Z123"', js)
        dobro = okno_zaslona.PREDPONA + json.dumps({"z": "Z123", "d": "input.key", "p": {"key": "home"}})
        self.assertEqual(okno_zaslona.razberi(dobro, "Z123"), ("input.key", {"key": "home"}))
        self.assertIsNone(okno_zaslona.razberi(dobro, "drug"))
        self.assertIsNone(okno_zaslona.razberi("navaden izpis strani", "Z123"))
        self.assertIsNone(okno_zaslona.razberi(okno_zaslona.PREDPONA + "{", "Z123"))

    def test_naslov(self):
        self.assertEqual(okno_zaslona.naslov_okna("Kamera", "Samsung"), "Kamera · Samsung")
        self.assertEqual(okno_zaslona.naslov_okna("", "Samsung", "sl"), "Samsung · Zaslon")

    def test_os_app_odpre_okno(self):
        app = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn("self._odpri_okno_zaslona(p)", app)
        self.assertIn("okno_zaslona.odpri(self, podatki, ime_programa, _jezik_oken(), aktiviraj=nase)", app)
        # Pregled S1: fokus samo, ce je zaslon odprl uporabnik (Odpri tukaj / Prostori v zadnjih 120 s).
        self.assertIn("time.monotonic() - cas <= 120", app)
        okno = (KOREN / "windows" / "safeer_windows" / "okno_zaslona.py").read_text(encoding="utf-8")
        self.assertIn("WA_ShowWithoutActivating", okno)
        cb = (KOREN / "windows" / "safeer_windows" / "control_backend.py").read_text(encoding="utf-8")
        self.assertIn("def poslji_vnos(self, dejanje: str, parametri: dict) -> bool:", cb)
        self.assertIn('if ref.startswith("vnos-"):', cb)
        self.assertIn('self.ukaz_pocakaj(cilj, "apps.close", {"stream": True}, cas=5.0)', cb)


class Zivo(unittest.TestCase):
    def _zazeni(self, nacin):
        okolje = dict(os.environ)
        okolje.setdefault("QT_QPA_PLATFORM", "offscreen")
        okolje["QTWEBENGINE_CHROMIUM_FLAGS"] = (okolje.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " --disable-gpu").strip()
        try:
            r = subprocess.run([sys.executable, str(Path(__file__).with_name("_zaslon_zivo.py")), str(KOREN), nacin],
                               capture_output=True, text=True, timeout=120, env=okolje)
        except subprocess.TimeoutExpired:
            self.skipTest("QtWebEngine se v tem okolju ni odzval")
        if r.returncode == 77:
            self.skipTest("QtWebEngine v tem okolju ne nalozi strani")
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])
        vrstica = next(v for v in r.stdout.splitlines() if v.startswith("IZID "))
        konec = next(v for v in r.stdout.splitlines() if v.startswith("KONEC "))
        return json.loads(vrstica[5:]), json.loads(konec[6:]), r.stdout + r.stderr

    def test_klik_tipke_in_odziv(self):
        izid, konec, izpis = self._zazeni("prav")
        self.assertEqual(izid["naslov"], "Kamera · Telefon")
        self.assertEqual(izid["poslano"], [["input.tap", {"x": 0.5, "y": 0.5, "ms": 60}], ["input.text", {"text": "ab"}],
                                           ["input.key", {"key": "enter"}]])   # brez laznih dogodkov in izpisov strani
        self.assertTrue(izid["namig"] and izid["gumb"])
        self.assertEqual(konec, ["n-tel"])                                    # zaprto okno: naprava neha deliti
        self.assertNotIn("skrivno", izpis)                                     # kljuc ogleda ni v dnevniku

    def test_tuje_potrdilo_brez_vnosa(self):
        izid, _konec, _izpis = self._zazeni("napacno")
        self.assertEqual(izid["poslano"], [])


if __name__ == "__main__":
    unittest.main()
