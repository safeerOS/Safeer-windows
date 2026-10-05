"""Varnost Safeer Linka na Linuxu: TLS z odtisom in seznanitev SPAKE2.

Brez zivega Huba: preverjamo pravila, ki napadalcu zaprejo vrata -
 - zeton nikoli ne gre po navadnem http,
 - wss brez pripetega odtisa se ne odpre,
 - Povezava brez TLS ali brez odtisa se ne vzpostavi,
 - SPAKE2 se ujema z RFC 9382 (isti vektor kot Spake2Test.kt v Androidu),
 - napacna koda da drugacen kljuc in potrditev ne sede.
"""
import unittest

from core import link_hub, link_tls, spake2


class Tls(unittest.TestCase):
    def test_zeton_ne_gre_po_http(self):
        koda, odgovor, odtis = link_tls.zahteva("http://127.0.0.1:1/cast/ticket", {}, zeton="saf_x")
        self.assertEqual((koda, odgovor, odtis), (0, {}, ""))

    def test_wss_brez_odtisa_se_ne_odpre(self):
        o = link_hub.WsOdjemalec("wss://127.0.0.1:1/cast/ws")
        with self.assertRaises(ConnectionError):
            o.odpri()

    def test_povezava_brez_tls_ali_odtisa_ne_uspe(self):
        p = link_hub.Povezava("ws://127.0.0.1:1/cast/ws", "saf_x", "pc-test", "Test", odtis="ab" * 32)
        self.assertFalse(p.poveži())
        p = link_hub.Povezava("wss://127.0.0.1:1/cast/ws", "saf_x", "pc-test", "Test")
        self.assertFalse(p.poveži())

    def test_seznanitev_brez_tls_zavrnjena(self):
        z = link_hub.zacni_seznanitev("ws://127.0.0.1:1/cast/ws", "pc-test", "Test")
        self.assertEqual(z, {"napaka": "hub_brez_tls"})

    def test_odtis_je_sha256(self):
        self.assertEqual(link_tls.odtis_potrdila(b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class Spake2Rfc(unittest.TestCase):
    """Testni vektor iz RFC 9382, dodatek C (P-256, SHA-256, HKDF, HMAC)."""

    W = int("2ee57912099d31560b3a44b1184b9b4866e904c49d12ac5042c97dca461b1a5f", 16)
    X = int("43dd0fd7215bdcb482879fca3220c6a968e66d70b1356cac18bb26c84a78d729", 16)
    Y = int("dcb60106f276b02606d8ef0a328c02e4b629f84f89786af5befb0bc75b6e66be", 16)

    def test_vektor(self):
        a = spake2.Spake2(self.W, b"server", b"client", b"", True, self.X)
        b = spake2.Spake2(self.W, b"client", b"server", b"", False, self.Y)
        pa, pb = a.sporocilo(), b.sporocilo()
        self.assertEqual(pa.hex(), "04a56fa807caaa53a4d28dbb9853b9815c61a411118a6fe516a8798434751470f9010153ac33d0d5f2047ffdb1a3e42c9b4e6be662766e1eeb4116988ede5f912c")
        self.assertEqual(pb.hex(), "0406557e482bd03097ad0cbaa5df82115460d951e3451962f1eaf4367a420676d09857ccbc522686c83d1852abfa8ed6e4a1155cf8f1543ceca528afb591a1e0b7")
        ke_a, ca = a.zakljuci(pb)
        ke_b, cb = b.zakljuci(pa)
        self.assertEqual(ke_a.hex(), "0e0672dc86f8e45565d338b0540abe69")
        self.assertEqual(ke_a, ke_b)
        self.assertEqual(ca.hex(), "58ad4aa88e0b60d5061eb6b5dd93e80d9c4f00d127c65b3b35b1b5281fee38f0")
        self.assertEqual(cb.hex(), "d3e2e547f1ae04f2dbdbf0fc4b79f8ecff2dff314b5d32fe9fcef2fb26dc459b")
        self.assertTrue(a.preveri(cb))
        self.assertTrue(b.preveri(ca))

    def test_napacna_koda_ne_sede(self):
        hub = spake2.Spake2.streznik("482913", "safeer-link-hub", "pc-test", b"odtis", b"pair1")
        pc = spake2.Spake2.odjemalec("482914", "pc-test", "safeer-link-hub", b"odtis", b"pair1")
        _, ca = hub.zakljuci(pc.sporocilo())
        _, cb = pc.zakljuci(hub.sporocilo())
        self.assertFalse(hub.preveri(cb))
        self.assertFalse(pc.preveri(ca))

    def test_drug_odtis_ne_sede(self):
        """Napadalec v sredini z lastnim potrdilom: strani vidita razlicna odtisa."""
        hub = spake2.Spake2.streznik("482913", "safeer-link-hub", "pc-test", b"odtis-huba", b"pair1")
        pc = spake2.Spake2.odjemalec("482913", "pc-test", "safeer-link-hub", b"odtis-napadalca", b"pair1")
        _, ca = hub.zakljuci(pc.sporocilo())
        _, cb = pc.zakljuci(hub.sporocilo())
        self.assertFalse(hub.preveri(cb))
        self.assertFalse(pc.preveri(ca))

    def test_prava_koda_sede(self):
        hub = spake2.Spake2.streznik("482913", "safeer-link-hub", "pc-test", b"odtis", b"pair1")
        pc = spake2.Spake2.odjemalec("482913", "pc-test", "safeer-link-hub", b"odtis", b"pair1")
        ke1, ca = hub.zakljuci(pc.sporocilo())
        ke2, cb = pc.zakljuci(hub.sporocilo())
        self.assertEqual(ke1, ke2)
        self.assertTrue(hub.preveri(cb) and pc.preveri(ca))

    def test_neveljavna_tocka_zavrnjena(self):
        pc = spake2.Spake2.odjemalec("482913", "pc-test", "hub", b"", b"p")
        with self.assertRaises(ValueError):
            pc.zakljuci(b"\x04" + b"\x01" * 64)
