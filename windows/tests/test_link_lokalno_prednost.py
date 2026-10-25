"""Lokalni Link ima prednost pred Global Linkom (lastnik, 13. 10. 2026): Global Link se vkljuci samo, ce seznanjena
naprava ni dosegljiva v domacem omrezju; ko se vrne domov, neposredna povezava zamenja pot prek releja."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core import link_hub_streznik as lhs
from core import link_mesh

LAN = "wss://192.0.2.77:8990/cast/ws"
RELE = "wss://127.0.0.1:45678/cast/ws"


class Povezava:
    def __init__(self, naslov):
        self.naslov = naslov
        self.podatki = {}
        self.zaprta = None

    def poslji(self, _b):
        return True

    def zapri(self, koda=1000, razlog=""):
        self.zaprta = razlog


class Zamenjava(unittest.TestCase):
    def setUp(self):
        self.hub = lhs.Hub(odtis="aa" * 32, nas_id="n-m")

    def test_domaca_zamenja_rele_ne_glede_na_zacetnika(self):
        rele = Povezava(RELE)
        self.assertTrue(self.hub.dodaj_soseda("n-z", rele, "n-m"))       # odprl manjsi id
        lan = Povezava(LAN)
        self.assertTrue(self.hub.dodaj_soseda("n-z", lan, "n-z"))        # vecji id, a doma
        self.assertIs(self.hub._sosedje["n-z"], lan)
        self.assertEqual(rele.zaprta, "podvojena sosednja povezava")

    def test_rele_nikoli_ne_zamenja_domace(self):
        lan = Povezava("192.0.2.77")                                   # dohodna: naslov je IP soseda
        self.assertTrue(self.hub.dodaj_soseda("n-z", lan, "n-z"))
        self.assertFalse(self.hub.dodaj_soseda("n-z", Povezava("127.0.0.1"), "n-m"))
        self.assertIs(self.hub._sosedje["n-z"], lan)
        self.assertIsNone(lan.zaprta)

    def test_ista_pot_po_starem_pravilu(self):
        a = Povezava(LAN)
        self.assertTrue(self.hub.dodaj_soseda("n-z", a, "n-m"))
        self.assertFalse(self.hub.dodaj_soseda("n-z", Povezava("192.0.2.77"), "n-z"))
        self.assertIs(self.hub._sosedje["n-z"], a)


class Klicanje(unittest.TestCase):
    def setUp(self):
        krog = mock.MagicMock()
        krog.clan_za_id.side_effect = lambda i: {"kljuc": "k-" + i}
        self._krog = mock.patch.object(link_mesh.link_krog, "krog", return_value=krog)
        self._krog.start()
        self.hub = lhs.Hub(odtis="aa" * 32, nas_id="n-m")
        self.m = link_mesh.MeshPovezovalec(self.hub, "n-m")

    def tearDown(self):
        self._krog.stop()

    def oglas(self, mdns=True, naslov=LAN):
        h = {"id": "n-z", "naslov": naslov, "tls": True, "mesh": link_mesh.link_hub_streznik_mesh()}
        if mdns:
            h["mdns"] = True
        return h

    def test_prek_releja_povezanega_poklicemo_doma(self):
        self.hub.dodaj_soseda("n-z", Povezava(RELE), "n-m")
        self.assertEqual([h["id"] for h in self.m.kandidati([self.oglas()], zdaj=100.0)], ["n-z"])

    def test_brez_oglasa_mdns_ne(self):
        # Zapomnjen naslov ne pove, da je naprava doma: ko je zdoma, je ne klicemo vsak krog zaman.
        self.hub.dodaj_soseda("n-z", Povezava(RELE), "n-m")
        self.assertEqual(self.m.kandidati([self.oglas(mdns=False)], zdaj=100.0), [])

    def test_doma_povezanega_ne(self):
        self.hub.dodaj_soseda("n-z", Povezava(LAN), "n-m")
        self.assertEqual(self.m.kandidati([self.oglas()], zdaj=100.0), [])

    def test_neuspeh_doma_ne_klice_releja_znova(self):
        self.hub.dodaj_soseda("n-z", Povezava(RELE), "n-m")
        klici = []
        self.m._odpri = lambda h: klici.append(h["naslov"]) or False
        self.m._klici_prek_releja = lambda h: klici.append("rele")
        self.m._neuspehi["n-z"] = 5
        self.m._klici(self.oglas())
        self.assertEqual(klici, [LAN])

    def test_en_krog_oznaci_oglase_mdns(self):
        self.m.poisci = lambda: [self.oglas(mdns=False)]
        videni = []
        self.m.kandidati = lambda oglasi, zdaj=None: videni.extend(oglasi) or []
        self.m.izmeri_poti = lambda *a, **k: None
        self.m.en_krog()
        self.assertTrue(any(h.get("mdns") for h in videni))


if __name__ == "__main__":
    unittest.main()
