"""Protocol v1: model naprave, ki ga racunalnik pove v cast.register (core/link_hub.model_naprave_v1)."""
import base64
import os
import sys
import unittest

from core import link_hub, link_krog


class ModelNapraveV1(unittest.TestCase):
    def test_control_in_brskalnik(self):
        c = link_hub.model_naprave_v1("pc-abc-control")
        self.assertEqual(c["protocol"], "1.0")
        self.assertEqual(c["platform"], "windows" if os.name == "nt" else "linux")
        self.assertEqual(c["kind"], "control")
        b = link_hub.model_naprave_v1("pc-abc")
        self.assertEqual(b["kind"], "computer")
        self.assertNotIn("priority", b, "racunalnik huba ne gosti, prioritete ne poslje")

    def test_razlicica_iz_glavnega_modula(self):
        glavni = sys.modules["__main__"]
        prej = getattr(glavni, "APP_VERSION", None)
        try:
            glavni.APP_VERSION = "9.9.9"
            self.assertEqual(link_hub.model_naprave_v1("pc-x")["version"], "9.9.9")
            glavni.APP_VERSION = ""
            self.assertNotIn("version", link_hub.model_naprave_v1("pc-x"))
        finally:
            if prej is None:
                delattr(glavni, "APP_VERSION")
            else:
                glavni.APP_VERSION = prej


class IdIzKljuca(unittest.TestCase):
    """Id iz kljuca (n-<16 hex>) in prehod: stari id ostane v krogu, nov id ga najde po kljucu."""

    KLJUC = base64.b64encode(b"\x30" + bytes(range(90))).decode()
    DRUGI = base64.b64encode(b"\x30" + bytes(range(1, 91))).decode()

    def test_oblika(self):
        self.assertTrue(link_krog.je_id_iz_kljuca("n-0123456789abcdef"))
        self.assertTrue(link_krog.je_id_iz_kljuca("n-0123456789abcdef-control"))
        self.assertFalse(link_krog.je_id_iz_kljuca("pc-uporabnik"))
        self.assertFalse(link_krog.je_id_iz_kljuca("n-0123456789abcdeg"))
        self.assertFalse(link_krog.je_id_iz_kljuca("n-0123456789abcdefos"))
        self.assertTrue(link_krog.je_id_iz_kljuca(link_krog.id_iz_kljuca(self.KLJUC)))

    def test_clan_za_id_najde_stari_vnos_po_kljucu(self):
        k = link_krog.Krog()
        k.dodaj("pc-stari-control", self.KLJUC, "Stari", "linux", "hub", 1.0)
        k.dodaj("tv-drugi", self.DRUGI, "Drugi", "tv", "hub", 1.0)
        novi = link_krog.id_iz_kljuca(self.KLJUC)
        self.assertEqual(k.clan_za_id(novi)["id"], "pc-stari-control")
        self.assertEqual(k.clan_za_id(novi + "-control")["id"], "pc-stari-control")
        self.assertEqual(k.clan_za_id("pc-stari-control")["id"], "pc-stari-control")
        self.assertIsNone(k.clan_za_id(link_krog.id_iz_kljuca(self.DRUGI) + "x"))
        self.assertIsNone(k.clan_za_id("n-ffffffffffffffff"))

    def test_id_naprave_je_iz_kljuca_ali_stari(self):
        ident = link_hub.id_naprave()
        self.assertTrue(link_krog.je_id_iz_kljuca(ident) or ident.startswith("pc-"), ident)
        self.assertEqual(ident, link_hub.id_naprave(), "id mora biti stabilen")


if __name__ == "__main__":
    unittest.main()
