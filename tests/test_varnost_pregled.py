"""Tocki 12 in 13 neodvisnega pregleda (29. 9. 2026): preklic zetonov umaknjene naprave, lokalni rele samo za
procese istega uporabnika."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import link_datoteke, link_krog, link_rele  # noqa: E402

KLJUC = __import__("base64").b64encode(b"\x30" + bytes(range(90))).decode()


class UmikIzKrogaTests(unittest.TestCase):
    def setUp(self):
        self.k = link_krog.Krog()
        with mock.patch.object(link_krog, "javni_kljuc_b64", side_effect=RuntimeError):
            self.k.zdruzi({"clani": {"tv-1": {"kljuc": KLJUC, "ime": "TV", "platforma": "android",
                                              "dodano": 100.0, "dodal": "pc"}}})

    def test_clan_ni_umaknjen(self):
        self.assertFalse(self.k.je_umaknjen("tv-1"))

    def test_neznana_naprava_ni_umaknjena(self):
        self.assertFalse(self.k.je_umaknjen("neznana"))
        self.assertFalse(self.k.je_umaknjen(""))

    def test_umik_novejsi_od_vpisa(self):
        self.k.zdruzi({"umiki": {"tv-1": {"umaknjeno": 200.0, "umaknil": "pc"}}})
        self.assertTrue(self.k.je_umaknjen("tv-1"))

    def test_ponoven_vpis_po_umiku(self):
        self.k.zdruzi({"umiki": {"tv-1": {"umaknjeno": 200.0, "umaknil": "pc"}}})
        self.k.zdruzi({"clani": {"tv-1": {"kljuc": KLJUC, "ime": "TV", "platforma": "android",
                                          "dodano": 300.0, "dodal": "pc"}}})
        self.assertFalse(self.k.je_umaknjen("tv-1"))

    def test_id_iz_kljuca_umaknjenega_clana(self):
        self.k.zdruzi({"umiki": {"tv-1": {"umaknjeno": 200.0, "umaknil": "pc"}}})
        self.assertTrue(self.k.je_umaknjen(link_krog.id_iz_kljuca(KLJUC)))


class ZetoniTests(unittest.TestCase):
    def setUp(self):
        self.s = link_datoteke.StreznikDatotek(link_datoteke.DeljeneMape([]), tls_mapa=tempfile.mkdtemp())
        self.umaknjene = set()
        self.s.umaknjena = lambda n: n in self.umaknjene

    def test_zeton_velja_do_umika(self):
        z = self.s.zeton_za("tv-1", zdaj=10.0)
        self.assertTrue(self.s.zeton_velja(z, zdaj=11.0))
        self.umaknjene.add("tv-1")
        self.assertFalse(self.s.zeton_velja(z, zdaj=12.0))
        # zeton je izbrisan: tudi ponovni vpis naprave ga ne obudi
        self.umaknjene.clear()
        self.assertFalse(self.s.zeton_velja(z, zdaj=13.0))

    def test_umik_ene_ne_vpliva_na_drugo(self):
        a = self.s.zeton_za("tv-1", zdaj=10.0)
        b = self.s.zeton_za("tel-1", zdaj=10.0)
        self.umaknjene.add("tv-1")
        self.assertFalse(self.s.zeton_velja(a, zdaj=11.0))
        self.assertTrue(self.s.zeton_velja(b, zdaj=11.0))

    def test_privzeto_preverja_krog(self):
        s = link_datoteke.StreznikDatotek(link_datoteke.DeljeneMape([]), tls_mapa=tempfile.mkdtemp())
        z = s.zeton_za("tv-1", zdaj=10.0)
        with mock.patch.object(link_krog, "je_umaknjen", return_value=True):
            self.assertFalse(s.zeton_velja(z, zdaj=11.0))


TABELA = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:A1B2 0100007F:1F90 01 00000000:00000000 00:00000000 00000000  1001        0 1 1 0000000000000000
   1: 0100007F:1F90 0100007F:A1B2 01 00000000:00000000 00:00000000 00000000  1000        0 2 1 0000000000000000
   2: 0100007F:C000 0100007F:1F90 01 00000000:00000000 00:00000000 00000000  1000        0 3 1 0000000000000000
"""


class LokalniReleTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.NamedTemporaryFile("w", delete=False, suffix=".tcp")
        d.write(TABELA)
        d.close()
        self.tabela = d.name
        self.addCleanup(os.unlink, d.name)

    def test_uid_odjemalca(self):
        self.assertEqual(link_rele._uid_lokalne_povezave(0xA1B2, 0x1F90, self.tabela), 1001)
        self.assertEqual(link_rele._uid_lokalne_povezave(0xC000, 0x1F90, self.tabela), 1000)
        self.assertIsNone(link_rele._uid_lokalne_povezave(0x1234, 0x1F90, self.tabela))

    def test_brez_tabele(self):
        self.assertIsNone(link_rele._uid_lokalne_povezave(1, 2, "/ni/tabele"))

    @unittest.skipUnless(hasattr(os, "getuid") and os.path.exists("/proc/net/tcp"), "samo Linux")
    def test_zavrne_tujega_uporabnika(self):
        r = link_rele.LokalniRele.__new__(link_rele.LokalniRele)
        r.vrata = 0x1F90
        with mock.patch.object(link_rele, "_uid_lokalne_povezave", return_value=os.getuid() + 1):
            self.assertFalse(r._nas_proces(("127.0.0.1", 0xA1B2)))
        with mock.patch.object(link_rele, "_uid_lokalne_povezave", return_value=os.getuid()):
            self.assertTrue(r._nas_proces(("127.0.0.1", 0xA1B2)))

    @unittest.skipUnless(hasattr(os, "getuid") and os.path.exists("/proc/net/tcp"), "samo Linux")
    def test_prava_povezava_istega_uporabnika(self):
        import socket
        s = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(s.close)
        v = s.getsockname()[1]
        c = socket.create_connection(("127.0.0.1", v))
        self.addCleanup(c.close)
        t, naslov = s.accept()
        self.addCleanup(t.close)
        self.assertEqual(link_rele._uid_lokalne_povezave(naslov[1], v), os.getuid())


if __name__ == "__main__":
    unittest.main()
