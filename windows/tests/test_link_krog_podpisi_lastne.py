"""21. 11. 2026: vnos glavnega id-ja racunalnika je bil v krogu brez podpisa (dodal ga je isti racunalnik pod drugim
id-jem). Sosedje nepodpisane vnose zavrnejo, zato televizor z novo identiteto racunalnika ni videl. Krog.podpisi_lastne
jih podpise ob zagonu Huba (kot KrogZaupanja.podpisiLastne na Androidu)."""
import os
import shutil
import tempfile
import unittest

from core import link_krog


class PodpisiLastne(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-krog-lastne-")
        self.nas = link_krog.javni_kljuc_b64()
        self.id = link_krog.id_iz_kljuca(self.nas)
        self.control = self.id + "-control"

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)

    def _krog_z_nepodpisanim(self):
        k = link_krog.Krog(os.path.join(self.mapa, "krog.json"))
        k.clani[self.control] = {"kljuc": self.nas, "ime": "PC", "platforma": "linux", "dodano": 90.0, "dodal": "tablica",
                                 "podpis": "tuj-podpis"}
        k.clani[self.id] = {"kljuc": self.nas, "ime": "PC", "platforma": "linux", "dodano": 100.0, "dodal": self.control}
        k.clani["tuja-naprava"] = {"kljuc": self.nas, "ime": "X", "platforma": "tv", "dodano": 101.0, "dodal": "nekdo-drug"}
        return k

    def test_podpise_samo_svoje_nepodpisane(self):
        k = self._krog_z_nepodpisanim()
        self.assertEqual(k.podpisi_lastne(), [self.id])
        c = k.clani[self.id]
        self.assertTrue(link_krog.preveri_podpis(
            self.nas, link_krog.podatki_clana(self.id, c["kljuc"], c["platforma"], c["dodano"], c["dodal"]), c["podpis"]))
        self.assertEqual(k.clani[self.control]["podpis"], "tuj-podpis")        # ze podpisanega ne spreminjamo
        self.assertNotIn("podpis", k.clani["tuja-naprava"])                    # tujega vnosa ne podpisujemo
        self.assertEqual(k.podpisi_lastne(), [])                               # drugic nic vec
        self.assertTrue(link_krog.Krog(os.path.join(self.mapa, "krog.json")).clani[self.id].get("podpis"))   # shranjeno

    def test_sosed_sprejme_sele_podpisan_vnos(self):
        k = self._krog_z_nepodpisanim()
        vnos = lambda: {"clani": {self.id: dict(k.clani[self.id])}}
        sosed = link_krog.Krog()
        sosed.zdruzi({"clani": {self.control: {"kljuc": self.nas, "ime": "PC", "platforma": "linux", "dodano": 90.0,
                                               "dodal": "tablica"}}}, lokalno=True)
        sosed.zdruzi(vnos(), preveri_podpise=True)
        self.assertFalse(sosed.je_clan(self.id))            # brez podpisa: sosed ga zavrne (to je bila napaka)
        k.podpisi_lastne()
        sosed.zdruzi(vnos(), preveri_podpise=True)
        self.assertTrue(sosed.je_clan(self.id))


if __name__ == "__main__":
    unittest.main()
