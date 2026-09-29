"""Tok medijev z druge naprave (core/link_pretok.py): lokalni streznik na 127.0.0.1 z Range,
pripetim odtisom, zetonom v glavi in potjo prek Huba (/cast/d/, Global Link)."""
import http.client
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

from core import link_datoteke, link_hub_streznik, link_pretok, link_tls  # noqa: E402


def _beri(url, glave=None):
    z = urllib.request.Request(url, headers=glave or {})
    try:
        with urllib.request.urlopen(z, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Pretok(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapa = tempfile.mkdtemp(prefix="safeer-pretok-")
        cls.deljena = os.path.join(cls.mapa, "Glasba")
        os.makedirs(cls.deljena)
        cls.podatki = bytes(range(256)) * 4000          # ~1 MB
        with open(os.path.join(cls.deljena, "pesem.mp3"), "wb") as d:
            d.write(cls.podatki)
        cls.tls = os.path.join(cls.mapa, "tls")
        cls.dat = link_datoteke.Datoteke([cls.deljena], tls_mapa=cls.tls)
        cls.dat.streznik.zazeni()
        cls.zeton = cls.dat.streznik.zeton_za("n-tv")
        cls.streznik = {"base_url": cls.dat.streznik.osnova("127.0.0.1"), "fp": cls.dat.streznik.odtis,
                        "token": cls.zeton}
        # Hub z istim potrdilom (kot v Controlu): /cast/d/ za pot prek releja.
        cls.hub = link_hub_streznik.HubStreznik(tls_mapa=cls.tls)
        cls.hub._ze_gosti_lokalno = staticmethod(lambda: False)
        cls.hub.datoteke = cls.dat.streznik
        with mock.patch.object(link_hub_streznik, "PRIVZETA_VRATA", 0):
            assert cls.hub.zazeni()

    @classmethod
    def tearDownClass(cls):
        cls.hub.ustavi()
        cls.dat.ustavi()
        shutil.rmtree(cls.mapa, ignore_errors=True)

    def setUp(self):
        self.p = link_pretok.LokalniPretok()

    def tearDown(self):
        self.p.ustavi()

    def vir(self, **k):
        return link_pretok.vir_iz_streznika(dict(self.streznik, **k), "share:0:pesem.mp3", mime="audio/mpeg")

    def test_cela_datoteka_in_previjanje(self):
        url = self.p.dodaj(self.vir())
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertNotIn(self.zeton, url)                       # zeton nikoli v naslovu
        koda, glave, telo = _beri(url)
        self.assertEqual((koda, telo), (200, self.podatki))
        self.assertEqual(glave.get("Content-Type"), "audio/mpeg")
        self.assertEqual(glave.get("Accept-Ranges"), "bytes")
        koda, glave, telo = _beri(url, {"Range": "bytes=1000-1999"})
        self.assertEqual((koda, telo), (206, self.podatki[1000:2000]))
        self.assertEqual(glave.get("Content-Range"), "bytes 1000-1999/%d" % len(self.podatki))
        koda, _g, telo = _beri(url, {"Range": "bytes=-10"})
        self.assertEqual((koda, telo), (206, self.podatki[-10:]))

    def test_neznana_pot_in_napacen_zeton(self):
        self.p.zazeni()
        self.assertEqual(_beri("http://127.0.0.1:%d/m/%s" % (self.p.vrata, "0" * 32))[0], 404)
        koda, _g, _t = _beri(self.p.dodaj(self.vir(token="napacen")))
        self.assertEqual(koda, 401)

    def test_tuja_naprava_na_istem_naslovu(self):
        # Zunaj doma je na istem zasebnem naslovu lahko druga naprava: brez pravega odtisa ni toka.
        koda, _g, _t = _beri(self.p.dodaj(self.vir(fp="ab" * 32)))
        self.assertEqual(koda, 502)

    def test_zeton_potece(self):
        s = link_datoteke.StreznikDatotek(link_datoteke.DeljeneMape([]))
        v = link_datoteke.ZETON_VELJA_S
        z = s.zeton_za("n-a", zdaj=1000.0)
        self.assertEqual(s.zeton_za("n-a", zdaj=1000.0 + 60), z)          # isti v prvi polovici roka
        self.assertNotEqual(s.zeton_za("n-a", zdaj=1000.0 + v / 2 + 1), z)
        self.assertTrue(s.zeton_velja(z, zdaj=1000.0 + v - 1))           # film, ki tece, ne pade
        # Raba ga drzi pri zivljenju (album s ponavljanjem, dolga pavza) ...
        self.assertTrue(s.zeton_velja(z, zdaj=1000.0 + 2 * v - 2))
        # ... neraben pa potece, in nikoli ne zivi dlje od NAJDLJE_S.
        self.assertFalse(s.zeton_velja(z, zdaj=1000.0 + 3 * v))
        z2 = s.zeton_za("n-b", zdaj=0.0)
        for ura in range(1, int(link_datoteke.NAJDLJE_S // 3600) + 2):
            ziv = s.zeton_velja(z2, zdaj=ura * 3600.0)
        self.assertFalse(ziv)
        self.assertFalse(s.zeton_velja("", zdaj=1000.0))
        z3 = s.zeton_za("n-c")
        self.assertEqual(s.preklici("n-c"), 1)
        self.assertFalse(s.zeton_velja(z3))

    def test_tiha_povezava_ne_ustavi_streznika(self):
        import socket as _s
        tiha = _s.create_connection(("127.0.0.1", self.hub.vrata))     # nic ne poslje
        tiha2 = _s.create_connection(("127.0.0.1", self.dat.streznik.vrata))
        try:
            koda, _g, telo = _beri(self.p.dodaj(self.vir()), {"Range": "bytes=0-9"})
            self.assertEqual((koda, telo), (206, self.podatki[:10]))
            povezava = link_tls._PripetaHttps("127.0.0.1", self.hub.vrata, self.hub.odtis, 5.0)
            povezava.request("HEAD", "/cast/d/share:0:pesem.mp3", headers={"X-Safeer-Token": self.zeton})
            self.assertEqual(povezava.getresponse().status, 200)
            povezava.close()
        finally:
            tiha.close()
            tiha2.close()

    def test_prek_releja_ko_neposredno_ni(self):
        # Neposredni naslov je mrtev (naprava je zunaj doma); rele pripelje do vrat Huba.
        hub_vrata = self.hub.vrata
        _odtis, kljuc = link_tls.potrdilo_huba("wss://127.0.0.1:%d/" % hub_vrata)

        class Rele:
            vrata = hub_vrata
            def zapri(self): pass
        p = link_pretok.LokalniPretok(rele_za=lambda cilj: Rele())
        try:
            mrtev = dict(self.streznik, base_url="https://127.0.0.1:9")
            vir = link_pretok.vir_iz_streznika(mrtev, "share:0:pesem.mp3", kljuc=kljuc)
            koda, _g, telo = _beri(p.dodaj(vir), {"Range": "bytes=0-99"})
            self.assertEqual((koda, telo), (206, self.podatki[:100]))
            self.assertTrue(p.pot(vir).rele)
            # Brez kljuca iz kroga (ali z drugim kljucem) prek releja ne gremo.
            tuj = link_pretok.vir_iz_streznika(mrtev, "share:0:pesem.mp3", kljuc="drug")
            self.assertEqual(_beri(p.dodaj(tuj))[0], 502)
        finally:
            p.ustavi()

    def test_hub_brez_datotek(self):
        self.hub.datoteke = None
        try:
            povezava = link_tls._PripetaHttps("127.0.0.1", self.hub.vrata, self.hub.odtis, 5.0)
            povezava.request("GET", "/cast/d/share:0:pesem.mp3", headers={"X-Safeer-Token": self.zeton})
            self.assertEqual(povezava.getresponse().status, 404)
        finally:
            self.hub.datoteke = self.dat.streznik

    def test_hub_z_vec_strezniki(self):
        # Windows: loceni streznik za omejen dostop in za cel disk; Hub izbere tistega, ki pozna zeton.
        drug = link_datoteke.StreznikDatotek(link_datoteke.DeljeneMape([]))
        self.hub.datoteke = lambda: [drug, self.dat.streznik]
        try:
            povezava = link_tls._PripetaHttps("127.0.0.1", self.hub.vrata, self.hub.odtis, 5.0)
            povezava.request("GET", "/cast/d/share:0:pesem.mp3", headers={"X-Safeer-Token": self.zeton, "Range": "bytes=0-9"})
            r = povezava.getresponse()
            self.assertEqual((r.status, r.read()), (206, self.podatki[:10]))
            povezava.close()
        finally:
            self.hub.datoteke = self.dat.streznik

    def test_vir_samo_https_s_pripetim_odtisom(self):
        self.assertIsNone(link_pretok.vir_iz_streznika({"base_url": "http://x:1", "fp": "a", "token": "t"}, "id"))
        self.assertIsNone(link_pretok.vir_iz_streznika({"base_url": "https://x:1", "fp": "", "token": "t"}, "id"))
        self.assertIsNone(link_pretok.vir_iz_streznika({"base_url": "https://x:1", "fp": "a", "token": ""}, "id"))
        # Samo naslovi v domacem omrezju (naprava racunalnika ne pošlje na internet) ...
        dobri = {"base_url": "https://192.168.0.77:40000", "fp": "a", "token": "t"}
        self.assertIsNotNone(link_pretok.vir_iz_streznika(dobri, "id"))
        for osnova in ("https://8.8.8.8:443", "https://primer.si:443", "https://[2001:4860::1]:443"):
            self.assertIsNone(link_pretok.vir_iz_streznika(dict(dobri, base_url=osnova), "id"), osnova)
        # ... in vrsta brez novih vrstic (gre v glavo odgovora).
        self.assertEqual(link_pretok.vir_iz_streznika(dobri, "id", mime="audio/mpeg").mime, "audio/mpeg")
        self.assertEqual(link_pretok.vir_iz_streznika(dobri, "id", mime="audio/mpeg\r\nSet-Cookie: x=1").mime, "")


if __name__ == "__main__":
    unittest.main()
