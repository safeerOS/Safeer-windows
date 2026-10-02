"""Seznami predvajanja so enaki na vseh napravah v Safeer Linku (core/seznami_sink.py, MediaCenter.seznami_uskladi)."""
import json
import os
import sys
import tempfile
import time
import unittest

_KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _KOREN not in sys.path:
    sys.path.insert(0, _KOREN)

from core import os_media, seznami_sink as S  # noqa: E402


def skladba(naslov, izvajalec="Izvajalec", **dodatno):
    return dict({"naslov": naslov, "izvajalec": izvajalec, "youtube": "", "slika": "", "sekund": 0}, **dodatno)


class PravilaTest(unittest.TestCase):
    """Ista pravila kot SeznamiPravila.kt (Android) - isti primeri kot tests/SeznamiPravilaTest.kt."""

    def test_korak(self):
        self.assertEqual(S.korak(None, 0, (0, 5)), S.PREVZEMI)          # star seznam (cas 0) z druge naprave
        self.assertEqual(S.korak(None, 200, (100, 5)), S.NIC)           # izbrisan pozneje: ne vrnemo
        self.assertEqual(S.korak(None, 200, (0, 5)), S.NIC)
        self.assertEqual(S.korak(None, 200, (300, 5)), S.PREVZEMI)      # po izbrisu znova uvozen drugje
        self.assertEqual(S.korak(None, 0, (100, 0)), S.NIC)
        self.assertEqual(S.korak((100, 5), 0, (200, 3)), S.PREVZEMI)
        self.assertEqual(S.korak((200, 5), 0, (100, 9)), S.NIC)
        self.assertEqual(S.korak((0, 5), 0, (0, 7)), S.ZDRUZI)
        self.assertEqual(S.korak((0, 5), 0, (0, 5)), S.NIC)

    def test_izbris_zdruzi_prevzemi(self):
        self.assertTrue(S.izbris_velja(100, 200) and S.izbris_velja(0, 200))
        self.assertFalse(S.izbris_velja(300, 200) or S.izbris_velja(0, 0))
        a, b = skladba("Pesem", youtube="abc12345678"), skladba("Druga", "Nekdo")
        c, d = skladba("pesem ", " izvajalec"), skladba("Tretja", "Nekdo", url="https://primer.si/t.mp3")
        self.assertEqual(S.zdruzi([a, b], [c, d], 400), [a, b, d])
        self.assertEqual({S.kljuc(x) for x in S.zdruzi([a, b], [d], 400)}, {S.kljuc(x) for x in S.zdruzi([d], [a, b], 400)})
        prevzeto = S.prevzemi([a, b], [c, d, skladba("Pesem")], 400)
        self.assertEqual(len(prevzeto), 2)
        self.assertEqual(prevzeto[0]["youtube"], "abc12345678")         # ze najden posnetek ostane
        self.assertEqual(S.prevzemi([a], [dict(a, youtube="xyz98765432")], 400)[0]["youtube"], "xyz98765432")

    def test_cista_skladba(self):
        self.assertIsNone(S.cista_skladba("niz"))
        self.assertIsNone(S.cista_skladba({"naslov": ""}))
        c = S.cista_skladba({"naslov": "N", "youtube": "a b<script>", "url": "javascript:alert(1)", "slika": "file:///etc/passwd",
                             "sekund": "x", "neznano": 1, "video": True, "android": "{}"})
        self.assertEqual(c, {"naslov": "N", "izvajalec": "", "youtube": "", "slika": "", "sekund": 0, "video": True, "android": "{}"})


class MedNapravamaTest(unittest.TestCase):
    def setUp(self):
        self._a, self._b = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.a, self.b = os_media.MediaCenter(self._a.name, roots=[]), os_media.MediaCenter(self._b.name, roots=[])

    def tearDown(self):
        self._a.cleanup(); self._b.cleanup()

    def uskladi(self, cilj, izvor):
        return cilj.seznami_uskladi(lambda p: json.loads(json.dumps(izvor.seznami_izvoz(p))))

    def imena(self, m):
        return [(x["ime"], x["stevilo"]) for x in m.seznami()]

    def test_seznam_se_prenese_spremeni_in_izbrise(self):
        self.a._seznami_pisi([{"ime": "Moj", "vir": "Spotify", "cas": 1000, "skladbe": [skladba("S%d" % i) for i in range(250)]}])
        self.assertTrue(self.uskladi(self.b, self.a))                   # 250 skladb gre v treh straneh
        self.assertEqual(self.imena(self.b), [("Moj", 250)])
        self.assertEqual(self.b._seznami_beri()[0]["vir"], "Spotify")
        self.assertFalse(self.uskladi(self.b, self.a))                  # drugic ni kaj prevzeti
        self.assertFalse(self.uskladi(self.a, self.b))
        # B doda skladbo iz kataloga: A jo dobi.
        self.b._dynamic_items["jam:1"] = {"id": "jam:1", "naslov": "Nova", "izvajalec": "X", "vrsta": "glasba", "url": "https://cdn.example/n.mp3"}
        time.sleep(0.01)
        self.assertTrue(self.b.dodaj_na_seznam("Moj", "jam:1").get("ok"))
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertEqual(self.imena(self.a), [("Moj", 251)])
        # A seznam izbrise: izgine tudi na B in se od tam ne vrne.
        time.sleep(0.01)
        self.assertTrue(self.a.odstrani_seznam("Moj"))
        self.assertFalse(self.uskladi(self.a, self.b))                  # B ga se ima, a je starejsi od izbrisa
        self.assertEqual(self.imena(self.a), [])
        self.assertTrue(self.uskladi(self.b, self.a))
        self.assertEqual(self.imena(self.b), [])
        # Ponoven uvoz z istim imenom na B po izbrisu: A ga spet dobi.
        time.sleep(0.01)
        self.b._seznami_pisi([{"ime": "Moj", "vir": "", "cas": self.b._zdaj_ms(), "skladbe": [skladba("Ena")]}])
        self.b._zapomni_izbris("Moj")
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertEqual(self.imena(self.a), [("Moj", 1)])

    def test_ura_naprave_prehiteva(self):
        """Naprava A ima uro eno uro naprej: spremembe in izbrisi z B (prava ura) morajo vseeno veljati."""
        self.assertEqual(S.nov_cas(1000), 1000)
        self.assertEqual(S.nov_cas(1000, 5000), 5001)
        self.assertEqual(S.nov_cas(1000, 0, 7000), 7001)
        prihodnost = self.a._zdaj_ms() + 3_600_000
        self.a._seznami_pisi([{"ime": "Moj", "vir": "", "cas": prihodnost, "skladbe": [skladba("Ena"), skladba("Dve")]}])
        self.assertTrue(self.uskladi(self.b, self.a))
        # B odstrani skladbo: cas spremembe je kasnejsi od A-jevega, zato A spremembo dobi.
        sz = self.b._seznami_beri()[0]
        vnos = self.b._seznam_vnos(sz["ime"], sz.get("vir") or "", sz["skladbe"][0])
        self.assertTrue(self.b.odstrani_s_seznama("Moj", vnos["id"]))
        self.assertGreater(self.b._seznami_beri()[0]["cas"], prihodnost)
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertEqual(self.imena(self.a), [("Moj", 1)])
        # B seznam izbrise: izbris je kasnejsi od stanja na A in tam velja.
        self.assertTrue(self.b.odstrani_seznam("Moj"))
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertEqual(self.imena(self.a), [])
        # A (ura naprej) izbrise, B takoj znova ustvari seznam z istim imenom: ostane in se vrne na A.
        self.a._zapomni_izbris("Drugi", prihodnost)
        self.uskladi(self.b, self.a)                                    # B izve za izbris »iz prihodnosti«
        self.b._dynamic_items["jam:1"] = {"id": "jam:1", "naslov": "Nova", "izvajalec": "X", "vrsta": "glasba", "url": "https://cdn.example/n.mp3"}
        self.assertTrue(self.b.dodaj_na_seznam("Drugi", "jam:1").get("ok"))
        self.assertFalse(self.uskladi(self.b, self.a))                  # A-jev izbris ga ne pobrise znova
        self.assertEqual(self.imena(self.b), [("Drugi", 1)])
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertEqual(self.imena(self.a), [("Drugi", 1)])

    def test_stara_seznama_z_istim_imenom_se_zdruzita(self):
        self.a._seznami_pisi([{"ime": "Stari", "vir": "", "skladbe": [skladba("A"), skladba("B")]}])
        self.b._seznami_pisi([{"ime": "Stari", "vir": "", "skladbe": [skladba("B"), skladba("C"), skladba("D")]}])
        self.assertTrue(self.uskladi(self.a, self.b))
        self.assertTrue(self.uskladi(self.b, self.a))
        self.assertEqual({s["naslov"] for s in self.a._seznami_beri()[0]["skladbe"]}, {"A", "B", "C", "D"})
        self.assertEqual({s["naslov"] for s in self.b._seznami_beri()[0]["skladbe"]}, {"A", "B", "C", "D"})
        self.assertFalse(self.uskladi(self.a, self.b) or self.uskladi(self.b, self.a))

    def test_naprava_ki_ne_odgovori_nicesar_ne_pokvari(self):
        self.b._seznami_pisi([{"ime": "Moj", "vir": "", "cas": 5, "skladbe": [skladba("A")]}])
        self.assertFalse(self.b.seznami_uskladi(lambda p: None))
        self.a._seznami_pisi([{"ime": "Dolg", "vir": "", "cas": 9, "skladbe": [skladba("S%d" % i) for i in range(150)]}])
        klici = []
        def prekinjen(p):
            klici.append(p)
            return None if p.get("od") else json.loads(json.dumps(self.a.seznami_izvoz(p)))    # druga stran ne pride
        self.assertFalse(self.b.seznami_uskladi(prekinjen))
        self.assertEqual(self.imena(self.b), [("Moj", 1)])               # napol prenesenega seznama ne shranimo
        self.assertEqual(len(klici), 3)


if __name__ == "__main__":
    unittest.main()
