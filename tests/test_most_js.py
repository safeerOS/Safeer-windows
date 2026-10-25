"""assets/os/most.js (window.SafeerMost) v node: klic, koMost, ima() iz odgovora »zmoznosti«, data-platforma.

Ista datoteka je v Safeer-linux in Safeer-windows (skupna-koda.json)."""
import shutil
import subprocess
import unittest
from pathlib import Path

MOST = Path(__file__).resolve().parents[1] / "assets" / "os" / "most.js"

# Najmanjse okolje brskalnika: window, document.documentElement, setInterval (node ga ima).
OKOLJE = r"""
const atributi = {};
global.window = global;
global.document = { documentElement: { setAttribute: (k, v) => { atributi[k] = v; } } };
const klici = [];
function zaledje(odgovor, napaka) {
  window.SafeerOS = { klic: (m, a) => { klici.push([m, a]); return napaka ? Promise.reject("neznano") :
    Promise.resolve(m === "zmoznosti" ? odgovor : {m: m}); } };
}
function koncaj(ok) { if (!ok) { console.error("NAPAKA"); process.exit(1); } }
"""


@unittest.skipUnless(shutil.which("node"), "node ni namescen")
class MostJs(unittest.TestCase):
    def _node(self, priprava, preverba):
        koda = OKOLJE + priprava + "\n" + MOST.read_text(encoding="utf-8") + "\n" + preverba
        r = subprocess.run(["node"], input=koda, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_sintaksa(self):
        subprocess.run(["node", "--check", str(MOST)], check=True, timeout=60)

    def test_zmoznosti_in_platforma(self):
        izpis = self._node('zaledje({platforma: "windows", metode: ["novaMapa", "zmoznosti"]});', r"""
        const M = window.SafeerMost;
        koncaj(!M.znano() && !M.ima("novaMapa"));            // dokler odgovora ni, je gumb skrit
        M.koZnano(() => {
          koncaj(M.ima("novaMapa") && !M.ima("wifi") && !M.ima("__proto__") && !M.ima("toString"));
          koncaj(M.platforma() === "windows" && atributi["data-platforma"] === "windows");
          M.klic("novaMapa", ["/a"]).then((r) => { koncaj(r.m === "novaMapa"); console.log("OK"); });
        });
        """)
        self.assertIn("OK", izpis)

    def test_staro_zaledje_brez_zmoznosti(self):
        izpis = self._node("zaledje(null, true);", r"""
        window.SafeerMost.koZnano(() => {
          koncaj(window.SafeerMost.ima("karkoli") && window.SafeerMost.platforma() === "");
          koncaj(atributi["data-platforma"] === undefined);
          console.log("OK");
        });
        """)
        self.assertIn("OK", izpis)

    def test_most_pride_kasneje(self):
        # Windows: Qt WebEngine most vcasih vstavi po nalaganju strani (os.js koMost) - SafeerMost pocaka.
        izpis = self._node("setTimeout(() => zaledje({platforma: 'linux', metode: ['a']}), 120);", r"""
        const M = window.SafeerMost;
        M.klic("a").catch((e) => koncaj(e === "brez mosta"));
        M.koZnano(() => { koncaj(M.imaMost() && M.ima("a") && M.platforma() === "linux"); console.log("OK"); });
        """)
        self.assertIn("OK", izpis)

    def test_ena_namestitev(self):
        izpis = self._node('zaledje({platforma: "linux", metode: []}); window.SafeerMost = {star: 1};', r"""
        koncaj(window.SafeerMost.star === 1); console.log("OK");
        """)
        self.assertIn("OK", izpis)


if __name__ == "__main__":
    unittest.main()
