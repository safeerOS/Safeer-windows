"""Prijava s QR kodo (prijavno okno Safeer Control / Safeer OS): povezava v kodi, slika kode in odziv
na odgovore huba - brez omrezja (link_tls.zahteva je zamenjana)."""
import hashlib
import os
import unittest
from unittest import mock

from core import link_hub

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Preizkus z oznako bere vmesnik Safeer Controla za Linux; v repozitoriju Safeer OS za Windows (isto jedro) ga ni.
JE_CONTROL_ZA_LINUX = os.path.isfile(os.path.join(KOREN, "core", "safeer_link.py"))


class QrPrijava(unittest.TestCase):
    def test_zacni_qr_poslje_samo_odtis_skrivnosti(self):
        poslano = {}

        def zahteva(url, telo=None, zeton=None, timeout=5.0, pripeti=None):
            poslano["url"], poslano["telo"] = url, telo
            return 200, {"qr_id": "ab" * 12, "expires_in_seconds": 300}, "F" * 64

        with mock.patch.object(link_hub.link_tls, "zahteva", zahteva):
            p = link_hub.zacni_qr("wss://192.168.0.77:8990/cast/ws", "n-pc-control", "Računalnik")
        self.assertTrue(poslano["url"].endswith("/cast/pair/qr/start"))
        telo = poslano["telo"]
        self.assertNotIn(p["skrivnost"], str(telo), "skrivnost iz QR ne sme na hub")
        self.assertEqual(telo["secret_sha256"], hashlib.sha256(p["skrivnost"].encode()).hexdigest())
        self.assertEqual(telo["poll_secret"], p["prevzem"])
        self.assertNotIn(p["prevzem"], p["povezava"], "skrivnost za prevzem ne sme biti v QR")
        self.assertTrue(p["povezava"].startswith("https://safeer.si/p#i=" + "ab" * 12 + "&s=" + p["skrivnost"]))
        self.assertIn("&f=" + "f" * 16 + "&a=", p["povezava"])
        self.assertTrue(p["povezava"].endswith("&a=192.168.0.77:8990"))
        self.assertEqual(p["naslov"], "192.168.0.77:8990")
        self.assertEqual(p["odtis"], "f" * 64)

    def test_brez_tls_in_star_hub(self):
        self.assertEqual(link_hub.zacni_qr("ws://192.168.0.77:8990/cast/ws", "x", "y"), {"napaka": "hub_brez_tls"})
        with mock.patch.object(link_hub.link_tls, "zahteva", lambda *a, **k: (404, {}, "f" * 64)):
            self.assertEqual(link_hub.zacni_qr("wss://h:8990/cast/ws", "x", "y"), {"napaka": "hub_star"})
        with mock.patch.object(link_hub.link_tls, "zahteva", lambda *a, **k: (0, {}, "")):
            self.assertIsNone(link_hub.zacni_qr("wss://h:8990/cast/ws", "x", "y"))

    def test_stanje(self):
        prijava = {"qr_id": "q", "prevzem": "p", "odtis": "f" * 64}
        with mock.patch.object(link_hub.link_tls, "zahteva", lambda *a, **k: (200, {"approved": False}, "")):
            self.assertEqual(link_hub.stanje_qr("wss://h:8990/cast/ws", prijava, "x"), (None, "caka"))
        with mock.patch.object(link_hub.link_tls, "zahteva",
                               lambda *a, **k: (200, {"approved": True, "token": "saf_tv_abc"}, "")):
            self.assertEqual(link_hub.stanje_qr("wss://h:8990/cast/ws", prijava, "x"), ("saf_tv_abc", ""))
        with mock.patch.object(link_hub.link_tls, "zahteva", lambda *a, **k: (404, {}, "")):
            self.assertEqual(link_hub.stanje_qr("wss://h:8990/cast/ws", prijava, "x"), (None, "qr_ne_obstaja"))

    def test_slika(self):
        svg = link_hub.qr_svg("https://safeer.si/p#i=0123456789abcdef01234567&s=" + "0" * 32 + "&f=" + "a" * 16)
        try:
            import qrcode  # noqa: F401
        except Exception:
            self.assertEqual(svg, "")
            return
        self.assertIn("<svg", svg)
        if os.environ.get("SAFEER_QR_IZPIS"):
            print(svg)

    @unittest.skipUnless(JE_CONTROL_ZA_LINUX, "vmesnik Safeer Controla za Linux")
    def test_stran_ima_prijavno_okno(self):
        html = open(os.path.join(KOREN, "assets", "link", "index.html"), encoding="utf-8").read()
        js = open(os.path.join(KOREN, "assets", "link", "link.js"), encoding="utf-8").read()
        for oznaka in ("zaslonPrijava", "qrSlika", "prijavaVnosKode", "gumbPrijavaKoda", "gumbBrezPovezave"):
            self.assertIn('id="' + oznaka + '"', html)
        for ime in ("zacniQr", "prekiniQr", "nadaljujBrezPovezave"):
            self.assertIn("most." + ime, js)
        most = open(os.path.join(KOREN, "core", "safeer_link.py"), encoding="utf-8").read()
        for ime in ("zacniQr", "prekiniQr", "nadaljujBrezPovezave"):
            self.assertIn('"' + ime + '"', most)


if __name__ == "__main__":
    unittest.main()
