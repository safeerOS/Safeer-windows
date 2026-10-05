"""Kdaj naj racunalnik sam gosti Safeer Link.

Pravilo je namenoma zadrzano: gostimo samo, kadar drugega Huba ni. Televizor, ki tece, ostane
sredisce kot doslej - posodobitev ne sme cez noc premakniti sredisca hise. Ko televizor ugasne,
racunalnik prevzame; ko se vrne, se racunalnik umakne.
"""
import os
import unittest
from unittest import mock

from core import link_hub_streznik


class LazniStreznik:
    def __init__(self, uspe=True):
        self.uspe = uspe
        self.zagoni = 0
        self.ustavitve = 0
        self._tece = False
        self.vrata = 8990
        self.odtis = "ab" * 32

    def tece(self):
        return self._tece

    def zazeni(self):
        self.zagoni += 1
        self._tece = self.uspe
        return self.uspe

    def ustavi(self):
        self.ustavitve += 1
        self._tece = False


class LazniOglas:
    def __init__(self):
        self.zacetki = []
        self.konci = 0

    def zacni(self, vrata, odtis, id_naprave, ime):
        self.zacetki.append((vrata, odtis, id_naprave, ime))
        return True

    def koncaj(self):
        self.konci += 1


class Pravilo(unittest.TestCase):
    def test_brez_huba_gostimo(self):
        self.assertTrue(link_hub_streznik.naj_gostimo(None))

    def test_ob_tujem_hubu_ne_gostimo(self):
        self.assertFalse(link_hub_streznik.naj_gostimo({"naslov": "wss://tv", "id": "tv1"}, "n-pc"))

    def test_nas_lastni_oglas_ni_razlog_za_umik(self):
        """Svojega Huba ne smemo razumeti kot tujega - sicer bi se ugasnili takoj po zagonu."""
        self.assertTrue(link_hub_streznik.naj_gostimo({"naslov": "wss://pc", "id": "n-pc"}, "n-pc"))

    def test_brez_nasega_id_je_vsak_hub_tuj(self):
        self.assertFalse(link_hub_streznik.naj_gostimo({"naslov": "wss://tv", "id": ""}, ""))


class Gostitelj(unittest.TestCase):
    def _gostitelj(self, najde, streznik=None, oglas=None):
        return link_hub_streznik.HubGostitelj(poisci=najde, streznik=streznik or LazniStreznik(),
                                              oglas=oglas or LazniOglas())

    def test_prevzame_ko_huba_ni(self):
        s, o = LazniStreznik(), LazniOglas()
        g = self._gostitelj(lambda: None, s, o)
        self.assertTrue(g.preveri())
        self.assertTrue(g.gostimo())
        self.assertEqual(s.zagoni, 1)
        self.assertEqual(len(o.zacetki), 1, "oglas mora iti ven, sicer nas nihce ne najde")
        self.assertEqual(o.zacetki[0][0], 8990)

    def test_drugi_pregled_ne_zaganja_znova(self):
        s, o = LazniStreznik(), LazniOglas()
        g = self._gostitelj(lambda: None, s, o)
        g.preveri()
        g.preveri()
        self.assertEqual(s.zagoni, 1, "Hub zaganjamo enkrat, ne ob vsakem pregledu")
        self.assertEqual(len(o.zacetki), 1)

    @mock.patch.dict(os.environ, {"SAFEER_LINK_MESH": "0"})
    def test_ne_prevzame_ko_tv_tece(self):
        s, o = LazniStreznik(), LazniOglas()
        g = self._gostitelj(lambda: {"naslov": "wss://tv", "id": "tv1"}, s, o)
        self.assertFalse(g.preveri())
        self.assertEqual(s.zagoni, 0, "televizor, ki tece, ostane sredisce")

    @mock.patch.dict(os.environ, {"SAFEER_LINK_MESH": "0"})
    def test_umakne_se_ko_se_tv_vrne(self):
        s, o = LazniStreznik(), LazniOglas()
        stanje = {"tv": None}
        g = self._gostitelj(lambda: stanje["tv"], s, o)
        self.assertTrue(g.preveri())
        stanje["tv"] = {"naslov": "wss://tv", "id": "tv1"}
        self.assertFalse(g.preveri())
        self.assertFalse(g.gostimo())
        self.assertEqual(s.ustavitve, 1)
        self.assertEqual(o.konci, 1, "oglas mora ugasniti z Hubom")

    @mock.patch.dict(os.environ, {"SAFEER_LINK_MESH": "1"})
    def test_mesh_gosti_in_se_ne_umakne(self):
        """Link Mesh: vsaka naprava je vozlisce - racunalnik gosti, tudi ko televizor tece."""
        s, o = LazniStreznik(), LazniOglas()
        g = self._gostitelj(lambda: {"naslov": "wss://tv", "id": "tv1"}, s, o)
        self.assertTrue(g.preveri())
        self.assertTrue(g.preveri())
        self.assertEqual(s.zagoni, 1)
        self.assertEqual(s.ustavitve, 0)

    def test_napaka_pri_iskanju_pomeni_gostimo(self):
        """Ce iskanja ni mogoce opraviti, je bolje gostiti kot pustiti hiso brez sredisca."""
        s = LazniStreznik()

        def pade():
            raise OSError("omrezja ni")

        g = self._gostitelj(pade, s, LazniOglas())
        self.assertTrue(g.preveri())

    def test_neuspesen_zagon_ne_trdi_da_gostimo(self):
        s = LazniStreznik(uspe=False)
        g = self._gostitelj(lambda: None, s, LazniOglas())
        self.assertFalse(g.preveri())
        self.assertFalse(g.gostimo())

    def test_koncaj_pospravi_oboje(self):
        s, o = LazniStreznik(), LazniOglas()
        g = self._gostitelj(lambda: None, s, o)
        g.preveri()
        g.koncaj()
        self.assertEqual((s.ustavitve, o.konci), (1, 1))


class LastniHub(unittest.TestCase):
    """Racunalnik ne sme samega sebe razumeti kot tujega Huba - v nobeno smer."""

    def test_nas_odtis_pomeni_nas_hub(self):
        self.assertTrue(link_hub_streznik.naj_gostimo(
            {"naslov": "wss://pc", "fp": "AB" * 32}, nas_id="n-pc", nas_odtis="ab" * 32),
            "oglas brez id-ja, a z nasim odtisom, smo mi sami")

    def test_tuj_odtis_in_tuj_id_pomenita_umik(self):
        self.assertFalse(link_hub_streznik.naj_gostimo(
            {"naslov": "wss://tv", "fp": "cd" * 32, "id": "tv1"}, nas_id="n-pc", nas_odtis="ab" * 32))

    def test_ko_gostimo_nas_lastni_hub_ne_ugasne_gostovanja(self):
        """Najpogostejsa past: iskanje najde nas Hub, mi pa bi se zato ugasnili."""
        s, o = LazniStreznik(), LazniOglas()
        g = link_hub_streznik.HubGostitelj(poisci=lambda: None, streznik=s, oglas=o)
        self.assertTrue(g.preveri())
        # Odslej iskanje najde nas lastni Hub (isti odtis).
        g.poisci = lambda: {"naslov": "wss://pc", "fp": s.odtis}
        self.assertTrue(g.preveri(), "svoj Hub ni razlog za umik")
        self.assertTrue(g.gostimo())
        self.assertEqual(s.ustavitve, 0)


if __name__ == "__main__":
    unittest.main()
