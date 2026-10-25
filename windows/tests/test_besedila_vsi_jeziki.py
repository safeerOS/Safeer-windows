"""Vsa besedila vmesnika Safeer OS (assets/os/besedila.js) so v vseh sestih jezikih (pogoj trzenja, SAFEER-ZNANJE Z380).

Do 25. 10. 2026 je nemscini, spanscini, francoscini in italijanscini manjkalo 63 kljucev (nabiralnik Sporocil, kanali,
navodila za e-posto, tema, daljinec), anglescini 2 - uporabnik je tam videl slovenska besedila. Preizkus prebere
besedila.js z node (tako kot jih nalozi vmesnik: osnovni predmet + vsi Object.assign) in preveri vsak kljuc iz sl.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
BESEDILA = KOREN / "assets" / "os" / "besedila.js"
JEZIKI = ("sl", "en", "de", "es", "fr", "it")
_NALOZI = ("const fs=require('fs'),vm=require('vm');const c={window:{}};vm.createContext(c);"
           "vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';this.__B=BESEDILA_OS;',c);"
           "process.stdout.write(JSON.stringify(c.__B));")
_MESTO = re.compile(r"\{[A-Za-z0-9_]+\}")


@unittest.skipUnless(shutil.which("node"), "node ni namescen")
class VsiJeziki(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        izid = subprocess.run([shutil.which("node"), "-e", _NALOZI, str(BESEDILA)], capture_output=True, timeout=120,
                              check=True)
        cls.B = json.loads(izid.stdout.decode("utf-8"))

    def test_vsi_jeziki_so_na_voljo(self):
        self.assertEqual(sorted(self.B), sorted(JEZIKI))

    def test_vsak_kljuc_je_v_vseh_jezikih(self):
        manjka = {j: sorted(set(self.B["sl"]) - set(self.B[j])) for j in JEZIKI}
        self.assertEqual({j: m for j, m in manjka.items() if m}, {})

    def test_ni_praznih_besedil(self):
        prazni = [(j, k) for j in JEZIKI for k, v in self.B[j].items() if not (isinstance(v, str) and v.strip())]
        self.assertEqual(prazni, [])

    def test_ista_mesta_za_vrednosti(self):
        """{ime}, {n} ... morajo biti v prevodu, sicer vmesnik izpise oklepaj namesto vrednosti."""
        razlicni = []
        for k, v in self.B["sl"].items():
            mesta = sorted(set(_MESTO.findall(v)))
            for j in JEZIKI[1:]:
                if sorted(set(_MESTO.findall(self.B[j].get(k, "")))) != mesta:
                    razlicni.append((k, j))
        self.assertEqual(razlicni, [])

    def test_nabiralnik_ni_prepisana_slovenscina(self):
        for k in ("mapaPrejeto", "mapaNeprebrano", "mapaPoslano", "isciSporocila", "panoPriponke", "kanalKjeImas",
                  "navGmail", "temaOpis", "daljinec"):
            for j in ("de", "es", "fr", "it"):
                self.assertNotEqual(self.B[j][k], self.B["sl"][k], (k, j))
                self.assertNotEqual(self.B[j][k], self.B["en"][k], (k, j))

    def test_gmail_navodila_brez_gumba_ki_ga_windows_nima(self):
        """Linux ima gumb za stran z gesli za aplikacije, Windows ne: navodila povedo naslov strani."""
        for j in JEZIKI:
            self.assertIn("myaccount.google.com/apppasswords", self.B[j]["navGmail"], j)


if __name__ == "__main__":
    unittest.main()
