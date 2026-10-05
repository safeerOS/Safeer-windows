"""»Poveži novo napravo« in »Odjavi ta računalnik« (core/link_hub.py): vabilo sredisca, stanje in odhod."""
import os
import unittest
from unittest import mock

from core import link_hub

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Preizkus z oznako bere vmesnik Safeer Controla za Linux; v repozitoriju Safeer OS za Windows (isto jedro) ga ni.
JE_CONTROL_ZA_LINUX = os.path.isfile(os.path.join(KOREN, "core", "safeer_link.py"))
HUB = "wss://192.168.0.77:8990/cast/ws"


def _beri(*deli):
    with open(os.path.join(KOREN, *deli), encoding="utf-8") as f:
        return f.read()


class Vabilo(unittest.TestCase):
    def test_povezava_kot_na_televizorju(self):
        klici = []

        def zahteva(url, telo=None, zeton=None, timeout=5.0, odtis=None):
            klici.append((url, telo, zeton, odtis))
            return 200, {"qr_id": "abc123", "secret": "s" * 32, "fp": "F" * 64,
                         "expires_in_seconds": 300, "pin": "907870"}
        with mock.patch.object(link_hub, "_zahteva", zahteva):
            v = link_hub.povabi(HUB, "saf_tv_x", "f" * 64)
        self.assertEqual(klici[0][0], "https://192.168.0.77:8990/cast/pair/qr/invite")
        self.assertEqual(klici[0][2], "saf_tv_x")
        self.assertEqual(v["povezava"], "https://safeer.si/p#j=abc123&s=" + "s" * 32 + "&f=" + "f" * 64 + "&a=192.168.0.77:8990")
        self.assertEqual(v["velja"], 300)
        self.assertEqual(v["pin"], "907870")

    def test_pin_iz_code_in_staro_sredisce_brez_pina(self):
        osnova = {"qr_id": "abc123", "secret": "s" * 32, "fp": "f" * 64,
                  "expires_in_seconds": 180}
        with mock.patch.object(link_hub, "_zahteva", lambda *a, **k: (200, dict(osnova, code="123456"))):
            self.assertEqual(link_hub.povabi(HUB, "z", "f")["pin"], "123456")
        with mock.patch.object(link_hub, "_zahteva", lambda *a, **k: (200, osnova)):
            v = link_hub.povabi(HUB, "z", "f")
        self.assertEqual(v["pin"], "")
        self.assertEqual(v["velja"], 180)

    def test_star_hub_in_napake(self):
        for koda, napaka in ((404, "hub_star"), (401, "ni_seznanjena"), (0, "ni_huba")):
            with mock.patch.object(link_hub, "_zahteva", lambda *a, k=koda, **kw: (k, {})):
                self.assertEqual(link_hub.povabi(HUB, "z", "f"), {"napaka": napaka})

    def test_stanje_in_odhod(self):
        with mock.patch.object(link_hub, "_zahteva", lambda *a, **k: (200, {"pending": False, "joined": True, "name": "Telefon"})):
            self.assertEqual(link_hub.stanje_vabila(HUB, "z", "f", "abc"), {"caka": False, "pridruzen": "Telefon"})
        with mock.patch.object(link_hub, "_zahteva", lambda *a, **k: (200, {"pending": True, "joined": False})):
            self.assertEqual(link_hub.stanje_vabila(HUB, "z", "f", "abc"), {"caka": True, "pridruzen": ""})
        poti = []
        with mock.patch.object(link_hub, "_zahteva", lambda url, *a, **k: (poti.append(url), (200, {"left": True}))[1]):
            self.assertTrue(link_hub.odidi(HUB, "z", "f"))
        self.assertEqual(poti, ["https://192.168.0.77:8990/cast/devices/leave"])
        with mock.patch.object(link_hub, "_zahteva", lambda *a, **k: (404, {})):
            self.assertFalse(link_hub.odidi(HUB, "z", "f"))

    @unittest.skipUnless(JE_CONTROL_ZA_LINUX, "vmesnik Safeer Controla za Linux")
    def test_stran_in_control(self):
        html = _beri("assets", "link", "index.html")
        js = _beri("assets", "link", "link.js")
        most = _beri("core", "safeer_link.py")
        control = _beri("safeer_control.py")
        self.assertIn('id="vabiloPin"', html)
        self.assertIn('id="gumbOdpriVnosKode"', html)
        self.assertIn("most.zacniVabilo", js)
        self.assertEqual(js.count('"vabiloPinNaslov":'), 6, "vseh 6 jezikov")
        self.assertIn('"pin": vabilo.get("pin", "")', most)
        for ime in ("zacniVabilo", "prekiniVabilo"):
            self.assertIn('"%s"' % ime, most)
        # Pozabi napravo = odhod tudi na sredicu; Safeer OS klice dejanja Controla.
        self.assertIn("link_hub.odidi(naslov, zeton, odtis)", most)
        for dejanje in ('"prijava"', '"nova-naprava"', '"odjava"', '"zaupanje"'):
            self.assertIn(dejanje, control)


if __name__ == "__main__":
    unittest.main()
