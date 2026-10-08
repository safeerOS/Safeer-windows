"""Stevec oglasov (in obvestilo o nepodprtem videu) ne smeta biti na voljo prvi strani, ki izpise vrstico v konzolo.

Neodvisni pregled 8. 10. 2026: most Windows je javna dejanja increment_ads in media_unsupported sprejel od katerekoli strani
(console.log z oznako mosta), stevec pa je shranjen v nastavitvah. Zdaj nosi sporocilo skripte Safeer podpisno vrednost
(nakljucen zeton procesa, ki zivi samo v zaprtju skripte), brez nje pa se sporocilo zavrze; dodatno je stevec omejen na
razumno hitrost."""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from safeer_windows import policy  # noqa: E402

KOREN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Zeton(unittest.TestCase):

    def test_zeton_je_dolg_in_nakljucen(self):
        self.assertRegex(policy.STEVEC_ZETON, r"^[0-9a-f]{32}$")

    def test_brez_zetona_ni_veljavno(self):
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "count": 5}))
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "count": 5, "t": ""}))
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "t": "x" * 32}))
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "t": 12345}))
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "t": None}))
        self.assertFalse(policy.zeton_veljaven({"action": "increment_ads", "t": [policy.STEVEC_ZETON]}))
        self.assertFalse(policy.zeton_veljaven(None))

    def test_pravi_zeton_je_veljaven(self):
        self.assertTrue(policy.zeton_veljaven({"action": "increment_ads", "count": 5, "t": policy.STEVEC_ZETON}))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_skripta_safeer_nosi_zeton_stran_pa_ne(self):
        skripta = policy.wrap_script("window.webkit.messageHandlers.safeer.postMessage({action:'increment_ads',count:2});", None, None)
        js = ("const vm=require('vm');const out=[];"
              "const ctx={location:{href:'https://primer.test/'},console:{log:function(m){out.push(m);}},JSON:JSON,String:String,RegExp:RegExp};"
              "ctx.window=ctx;vm.createContext(ctx);vm.runInContext(process.argv[1],ctx);"
              "vm.runInContext(\"console.log('\"+process.argv[2]+\"'+JSON.stringify({action:'increment_ads',count:50}))\",ctx);"
              "console.log(JSON.stringify(out));")
        r = subprocess.run([shutil.which("node"), "-e", js, skripta, policy.BRIDGE_PREFIX], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        sporocila = [policy.parse_bridge_message(m) for m in json.loads(r.stdout)]
        self.assertEqual(len(sporocila), 2)
        skripta_sporocilo, stran_sporocilo = sporocila
        self.assertTrue(policy.zeton_veljaven(skripta_sporocilo), skripta_sporocilo)
        self.assertEqual(skripta_sporocilo["count"], 2)
        self.assertFalse(policy.zeton_veljaven(stran_sporocilo), stran_sporocilo)

    def test_zeton_ni_v_viru_za_javne_skripte_razen_v_zaprtju(self):
        # Vir skripte nosi zeton (to je zaprtje, ki ga stran ne more prebrati); HOME_ADAPTER_JS in zaščita shrambe ga ne smeta nositi.
        self.assertNotIn(policy.STEVEC_ZETON, policy.HOME_ADAPTER_JS)
        self.assertNotIn(policy.STEVEC_ZETON, policy.STORAGE_GUARD_JS)
        self.assertIn(policy.STEVEC_ZETON, policy.wrap_script("1;", None, None))


class Omejevalnik(unittest.TestCase):

    def test_omejuje_hitrost(self):
        o = policy.OmejevalnikStevca(najvec=300, okno=60.0)
        self.assertEqual([o.dovoli(50, t) for t in (0, 1, 2, 3, 4, 5)], [50] * 6)
        self.assertEqual(o.dovoli(50, 6), 0)
        self.assertEqual(o.dovoli(50, 30), 0)
        self.assertEqual(o.dovoli(50, 61), 50)

    def test_delno_odobri_ostanek(self):
        o = policy.OmejevalnikStevca(najvec=70, okno=60.0)
        self.assertEqual(o.dovoli(50, 0), 50)
        self.assertEqual(o.dovoli(50, 1), 20)
        self.assertEqual(o.dovoli(10, 2), 0)

    def test_nesmiselne_vrednosti(self):
        o = policy.OmejevalnikStevca()
        self.assertEqual(o.dovoli(0, 0), 0)
        self.assertEqual(o.dovoli(-5, 0), 0)
        self.assertEqual(o.dovoli(10 ** 9, 0), policy.OmejevalnikStevca().najvec_na_sporocilo)


class Priklop(unittest.TestCase):

    def test_most_preveri_zeton_pred_javnimi_dejanji(self):
        with open(os.path.join(KOREN, "windows", "safeer_windows", "browser.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("def on_bridge_message")
        telo = src[i:i + 2500]
        self.assertIn("policy.zeton_veljaven(payload)", telo)
        i = telo.index("policy.zeton_veljaven(payload)")
        self.assertLess(i, telo.index("oznaci_nepodprt_video"))
        self.assertLess(i, telo.index("_omejevalnik_stevca.dovoli"))
        self.assertIn('("media_unsupported", "increment_ads")', telo)


if __name__ == "__main__":
    unittest.main()
