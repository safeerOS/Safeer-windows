"""Preizkusi odjemalca Safeer Huba za linuxov brskalnik.

Najpomembnejse ni, da povezava deluje, ampak da brskalnik brez Huba ne obstane
in da zeton ostane na disku z dovoljenji, ki jih ne vidi nihce drug.
"""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from core import link_hub


class Nastavitve(unittest.TestCase):

    def test_zeton_ostane_zaseben(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "link.json")
            n = link_hub.Nastavitve(pot)
            n.set("control_token", "zeton-za-preizkus")
            if os.name != "nt":      # dovoljenja POSIX; na Windows datoteke v profilu varuje ACL uporabnika
                self.assertEqual(oct(os.stat(pot).st_mode)[-3:], "600",
                                 "zeton ne sme biti berljiv drugim uporabnikom")
            znova = link_hub.Nastavitve(pot)
            self.assertEqual(znova.get("control_token"), "zeton-za-preizkus")

    def test_pokvarjena_datoteka_ne_podre_brskalnika(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "link.json")
            with open(pot, "w", encoding="utf-8") as d:
                d.write("{to ni json")
            n = link_hub.Nastavitve(pot)
            self.assertEqual(n.get("control_token"), None)


class Identiteta(unittest.TestCase):

    def test_id_je_uporaben(self):
        ident = link_hub.id_naprave()
        # Id iz kljuca (n-<16 hex>) ali, brez kljuca, stari id po imenu racunalnika (pc-...).
        self.assertTrue(ident.startswith(("n-", "pc-")), ident)
        self.assertTrue(all(z.isalnum() or z in "-_" for z in ident), ident)
        self.assertTrue(link_hub.stari_id_naprave().startswith("pc-"))


class Osnova(unittest.TestCase):

    def test_iz_ws_v_http(self):
        # 203.0.113.0/24 je obseg, namenjen dokumentaciji -- nikogarsnje omrezje.
        self.assertEqual(link_hub._osnova("ws://203.0.113.10:8990/cast/ws"),
                         "http://203.0.113.10:8990")
        self.assertEqual(link_hub._osnova("wss://hub.local:8990/cast/ws"),
                         "https://hub.local:8990")
        self.assertEqual(link_hub._osnova("http://hub.local:8990"),
                         "http://hub.local:8990")


class BrezHuba(unittest.TestCase):

    def test_iskanje_brez_huba_vrne_none(self):
        """Ko Huba v omrezju ni, mora iskanje mirno vrniti None, ne vreci napake.

        Izklopiti je treba obe poti: mDNS in HTTP. Sicer bi Hub, ki tece na tem
        racunalniku, test napacno "resil".
        """
        stari = link_hub.PRIVZETI_GOSTITELJ
        stara_vrata = link_hub.PRIVZETA_VRATA
        stari_mdns = link_hub._poisci_z_mdns
        try:
            link_hub.PRIVZETI_GOSTITELJ = "ta-gostitelj-ne-obstaja.invalid"
            link_hub.PRIVZETA_VRATA = 1
            link_hub._poisci_z_mdns = lambda cas=1.5: None
            self.assertIsNone(link_hub.poisci_hub("ws://127.0.0.1:1/cast/ws"))
        finally:
            link_hub.PRIVZETI_GOSTITELJ = stari
            link_hub.PRIVZETA_VRATA = stara_vrata
            link_hub._poisci_z_mdns = stari_mdns

    def test_povezava_brez_zetona_ne_uspe_tiho(self):
        p = link_hub.Povezava("ws://127.0.0.1:1/cast/ws", "napacen", "pc-test", "Test")
        self.assertFalse(p.poveži())
        self.assertFalse(p.tece)
        # posiljanje na zaprto povezavo ne sme vreci napake
        self.assertFalse(p.poslji({"type": "cast.url"}))


class Okvirji(unittest.TestCase):
    """Okvirje preverimo proti resnicnemu streznisko-odjemalskemu paru na localhostu."""

    def test_besedilo_gre_tja_in_nazaj(self):
        import socket
        import base64
        import hashlib
        import struct

        posluh = socket.socket()
        posluh.bind(("127.0.0.1", 0))
        posluh.listen(1)
        vrata = posluh.getsockname()[1]
        prejeto = []

        def streznik():
            povezava, _ = posluh.accept()
            zahteva = b""
            while b"\r\n\r\n" not in zahteva:
                zahteva += povezava.recv(1024)
            kljuc = ""
            for vrstica in zahteva.decode("latin-1").split("\r\n"):
                if vrstica.lower().startswith("sec-websocket-key:"):
                    kljuc = vrstica.split(":", 1)[1].strip()
            sprejem = base64.b64encode(hashlib.sha1(
                (kljuc + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            povezava.sendall((
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {sprejem}\r\n\r\n"
            ).encode())

            # preberi en maskiran okvir odjemalca
            glava = povezava.recv(2)
            dolzina = glava[1] & 0x7F
            if dolzina == 126:
                dolzina = struct.unpack("!H", povezava.recv(2))[0]
            maska = povezava.recv(4)
            telo = b""
            while len(telo) < dolzina:
                telo += povezava.recv(dolzina - len(telo))
            prejeto.append(bytes(b ^ maska[i % 4] for i, b in enumerate(telo)).decode())

            # odgovori nemaskirano (tako posilja streznik)
            odgovor = json.dumps({"type": "cast.devices", "devices": []}).encode()
            povezava.sendall(bytes([0x81, len(odgovor)]) + odgovor)
            povezava.close()

        nit = threading.Thread(target=streznik, daemon=True)
        nit.start()

        odjemalec = link_hub.WsOdjemalec(f"ws://127.0.0.1:{vrata}/cast/ws")
        odjemalec.odpri()
        odjemalec.poslji(json.dumps({"type": "cast.register"}))
        sporocilo = odjemalec.prejmi()
        odjemalec.zapri()
        nit.join(timeout=5)

        self.assertEqual(json.loads(prejeto[0])["type"], "cast.register")
        self.assertEqual(json.loads(sporocilo)["type"], "cast.devices")


if __name__ == "__main__":
    unittest.main(verbosity=2)



class OsirotelaPovezava(unittest.TestCase):
    """Sonda registracije: zavrnitev naprava_ni_povezana na sondo zapre vticnico (zanka se prijavi znova);
    isti_naprava (prijavljeni smo) ne stori nicesar; po zapri() _odpri ne odpre nove vticnice."""

    def test_sonda_zapre_osirotelo(self):
        from core import link_hub

        class Lazni:
            def __init__(self, sporocila):
                self.sporocila = list(sporocila); self.zaprt = False
            def prejmi(self):
                return self.sporocila.pop(0) if self.sporocila else None
            def zapri(self):
                self.zaprt = True
            def ping(self):
                return True
            def poslji(self, b):
                pass

        p = link_hub.Povezava("wss://x:1/cast/ws", "z", "id", "ime", odtis="ab")
        prejeta = []
        p.ob_sporocilu = prejeta.append
        p.tece = True
        p.odjemalec = Lazni([json.dumps({"type": "cast.ack", "ref_id": link_hub.SONDA_PREDPONA + "1", "status": "rejected",
                                          "error_code": "isti_naprava"}),
                             json.dumps({"type": "cast.devices", "devices": []}),
                             json.dumps({"type": "cast.ack", "ref_id": link_hub.SONDA_PREDPONA + "2", "status": "rejected",
                                          "error_code": "naprava_ni_povezana"}),
                             json.dumps({"type": "cast.devices", "devices": [1]})])
        p._poslusaj()
        self.assertEqual([m["type"] for m in prejeta], ["cast.devices"])  # sonda ni sla naprej; po sirotenju konec
        self.assertTrue(p.aktivna)

    def test_odpri_po_zapri_ne_odpre(self):
        from core import link_hub
        p = link_hub.Povezava("wss://x:1/cast/ws", "z", "id", "ime", odtis="ab")
        p.zapri()
        self.assertFalse(p.aktivna)
        with mock.patch.object(link_hub, "vzemi_vstopnico_s_kodo", return_value=("v", 200)), \
                mock.patch.object(link_hub, "WsOdjemalec") as ws:
            self.assertFalse(p._odpri())
            ws.assert_not_called()


class VabiloLastnegaHuba(unittest.TestCase):
    """Racunalnik gosti svoj Hub (wss://127.0.0.1): QR mora kazati domaci naslov, ne 127.0.0.1."""

    def test_qr_ima_domaci_naslov_in_kodo(self):
        from unittest import mock
        from core import link_hub as lh
        odgovor = {"qr_id": "q1", "secret": "s1", "fp": "ab", "pin": "123456",
                   "address": "192.168.0.135:8990", "expires_in_seconds": 300, "web_port": 0}
        with mock.patch.object(lh, "_zahteva", return_value=(200, odgovor)):
            v = lh.povabi("wss://127.0.0.1:8990/cast/ws", "z", "ab")
        self.assertEqual(v["pin"], "123456")
        self.assertIn("a=192.168.0.135:8990", v["povezava"])
        self.assertNotIn("127.0.0.1", v["povezava"])

    def test_tuj_hub_ohrani_svoj_naslov(self):
        from unittest import mock
        from core import link_hub as lh
        odgovor = {"qr_id": "q1", "secret": "s1", "fp": "ab", "address": "10.0.0.9:1", "web_port": 0}
        with mock.patch.object(lh, "_zahteva", return_value=(200, odgovor)):
            v = lh.povabi("wss://192.168.0.77:8990/cast/ws", "z", "ab")
        self.assertIn("a=192.168.0.77:8990", v["povezava"])
