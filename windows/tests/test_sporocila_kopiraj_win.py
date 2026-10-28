"""Kopiraj sporocilo v oknu Sporocila na Windows (lastnik 28. 10. 2026; kot Safeer-linux 1.0.108 »kopiranje108«).

Prej je meni na mehurcku imel samo izbris pri Safeer Linku, besedilo pa ni bilo izberljivo (os.css body
user-select: none) - sporocila ni bilo mogoce kopirati. Zdaj: izberljivo besedilo, desni klik / tipka Meni /
Shift+F10 odpre Kopiraj izbrano, Kopiraj sporocilo, Odpri povezavo (samo varna http/https), pri Linku se izbris.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
OS_JS = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
OS_CSS = (KOREN / "assets" / "os" / "os.css").read_text(encoding="utf-8")
BESEDILA = (KOREN / "assets" / "os" / "besedila.js").read_text(encoding="utf-8")


def _blok() -> str:
    od = OS_JS.index("/* SPOROCILA_KOPIRANJE_ZACETEK")
    do = OS_JS.index("/* SPOROCILA_KOPIRANJE_KONEC */")
    return OS_JS[od:do]


class KopirajSporocilo(unittest.TestCase):
    def test_vsi_mehurcki_imajo_meni_ne_samo_link(self):
        i = OS_JS.index("function naloziVsebinoPogovora(pogovor)")
        telo = OS_JS[i:i + 2500]
        self.assertIn('m.addEventListener("contextmenu"', telo)
        self.assertNotIn('if (pogovor.kanal_id === "safeer-link") m.addEventListener("contextmenu"', telo)
        self.assertIn('e.key !== "ContextMenu"', telo)          # tipka Meni
        self.assertIn('e.key === "F10" && e.shiftKey', telo)     # Shift+F10

    def test_besedilo_mehurcka_izberljivo(self):
        vrstica = next(v for v in OS_CSS.splitlines() if v.startswith(".mehurcek {"))
        self.assertIn("user-select:text", vrstica)

    def test_besedila_v_sestih_jezikih(self):
        for jezik in ("sl", "en", "de", "es", "fr", "it"):
            m = re.search(r"/\*kopiranje108\*/Object\.assign\(BESEDILA_OS\." + jezik + r", (\{.*?\})\);", BESEDILA)
            self.assertIsNotNone(m, jezik)
            d = json.loads(m.group(1))
            for k in ("sporKopiraj", "sporKopirajIzbrano", "sporKopirano", "sporNiKopirano", "sporOdpriPovezavo"):
                self.assertTrue(d.get(k), (jezik, k))

    def test_kopiranje_gre_v_odlozisce(self):
        self.assertIn('klic("kopiraj", [besedilo])', _blok())
        app = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn('if metoda == "kopiraj":', app)

    @unittest.skipUnless(shutil.which("node"), "node ni namescen")
    def test_postavke_menija(self):
        skripta = _blok() + r"""
var izid = {
  celo: postavkeMenijaSporocila("zivjo svet", ""),
  izbrano: postavkeMenijaSporocila("zivjo svet", "svet"),
  povezava: postavkeMenijaSporocila("https://example.org/a", ""),
  uporabnik: postavkeMenijaSporocila("https://banka.example@drugje.example/", ""),
  js: postavkeMenijaSporocila("javascript:alert(1)", ""),
  prazno: postavkeMenijaSporocila("", "")
};
console.log(JSON.stringify(izid));
"""
        r = subprocess.run(["node", "-e", skripta], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual([p[0] for p in d["celo"]], ["sporKopiraj"])
        self.assertEqual(d["celo"][0][2], "zivjo svet")
        self.assertEqual([p[0] for p in d["izbrano"]], ["sporKopirajIzbrano", "sporKopiraj"])
        self.assertEqual(d["izbrano"][0][2], "svet")
        self.assertEqual([p[0] for p in d["povezava"]], ["sporKopiraj", "sporOdpriPovezavo"])
        self.assertEqual(d["povezava"][1][2], "https://example.org/a")
        self.assertEqual([p[0] for p in d["uporabnik"]], ["sporKopiraj"])   # uporabnik@ pred gostiteljem: ne odpre
        self.assertEqual([p[0] for p in d["js"]], ["sporKopiraj"])
        self.assertEqual(d["prazno"], [])


if __name__ == "__main__":
    unittest.main()
