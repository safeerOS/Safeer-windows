"""Odjemalec releja (core/link_rele.WsOdjemalec) s pravo povezavo TLS: branje in pisanje iz dveh niti.

Kanal skozi rele nosi obe smeri hkrati (`cev`: ena nit bere iz releja, druga vanj pise). Rele v preizkusu je
krajeven: TLS, rokovanje WebSocket, nato vsak okvir vrne posiljatelju. Preverjamo, da pridejo vsi bajti nazaj
nespremenjeni in da zaprtje iz druge niti takoj zbudi nit, ki bere.
"""
import base64
import hashlib
import re
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_datoteke, link_rele, link_ws

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _Rele:
    def __init__(self, mapa: str) -> None:
        kljuc, potrdilo, _ = link_datoteke.zagotovi_potrdilo(mapa)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(potrdilo, kljuc)
        self.posluh = socket.socket()
        self.posluh.bind(("127.0.0.1", 0))
        self.posluh.listen(1)
        self.vrata = self.posluh.getsockname()[1]
        self.napaka = ""
        self.okvirjev = 0
        self.nit = threading.Thread(target=self._teci, daemon=True)
        self.nit.start()

    def _teci(self) -> None:
        s = None
        try:
            surov, _ = self.posluh.accept()
            s = self.ctx.wrap_socket(surov, server_side=True)
            zahteva = b""
            while b"\r\n\r\n" not in zahteva:
                kos = s.recv(4096)
                if not kos:
                    return
                zahteva += kos
            kljuc = re.search(rb"Sec-WebSocket-Key: (\S+)", zahteva).group(1).decode()
            sprejem = base64.b64encode(hashlib.sha1((kljuc + _GUID).encode()).digest()).decode()
            s.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Accept: %s\r\n\r\n" % sprejem).encode())
            medpomnilnik = b""

            def beri(n: int) -> bytes:
                nonlocal medpomnilnik
                while len(medpomnilnik) < n:
                    kos = s.recv(65536)
                    if not kos:
                        raise ConnectionError("konec")
                    medpomnilnik += kos
                vzeto, medpomnilnik = medpomnilnik[:n], medpomnilnik[n:]
                return vzeto

            while True:
                b0, b1 = beri(2)
                dolzina = b1 & 0x7F
                if dolzina == 126:
                    dolzina = int.from_bytes(beri(2), "big")
                elif dolzina == 127:
                    dolzina = int.from_bytes(beri(8), "big")
                maska = beri(4)
                telo = link_ws.odmaskiraj(beri(dolzina), maska)
                if b0 & 0x0F == 0x8:
                    return
                self.okvirjev += 1
                s.sendall(link_ws.okvir(b0 & 0x0F, telo))
        except ConnectionError:
            pass
        except Exception as e:  # noqa: BLE001
            self.napaka = "%s: %s" % (type(e).__name__, e)
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def zapri(self) -> None:
        try:
            self.posluh.close()
        except OSError:
            pass
        self.nit.join(5)


class OdjemalecReleja(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-rele-")
        try:
            self.rele = _Rele(self.mapa)
        except Exception as e:  # noqa: BLE001 - brez orodja za potrdilo preizkusa ni mogoce izvesti
            shutil.rmtree(self.mapa, ignore_errors=True)
            self.skipTest("potrdila ni mogoce ustvariti: %s" % e)
        self.ws = None

    def tearDown(self):
        if self.ws is not None:
            self.ws.sprosti()
        self.rele.zapri()
        shutil.rmtree(self.mapa, ignore_errors=True)

    def _povezi(self) -> link_rele.WsOdjemalec:
        """Odjemalec releja, usmerjen na krajevni rele (pravi gre na link.safeer.si:443 s preverjenim potrdilom)."""
        def kontekst():
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        prava = socket.create_connection
        with mock.patch.object(link_rele.ssl, "create_default_context", kontekst), \
                mock.patch.object(link_rele.socket, "create_connection",
                                  lambda naslov, timeout=None: prava(("127.0.0.1", self.rele.vrata), timeout=timeout)):
            self.ws = link_rele.WsOdjemalec("/v1/listen", {"X-Preizkus": "1"}, gostitelj="127.0.0.1")
        return self.ws

    def test_obe_smeri_hkrati(self):
        ws = self._povezi()
        okvirjev, velikost = 400, link_rele.KOS
        napake = []
        poslano, prejeto = hashlib.sha256(), hashlib.sha256()
        stanje = {"prejeto": 0}

        def beri() -> None:
            try:
                while stanje["prejeto"] < okvirjev * velikost:
                    op, podatki = ws.prejmi()
                    if op != 0x2:
                        napake.append("nepricakovan okvir %r" % op)
                        return
                    prejeto.update(podatki)
                    stanje["prejeto"] += len(podatki)
            except Exception as e:  # noqa: BLE001
                napake.append("branje %s: %s" % (type(e).__name__, e))

        def pisi() -> None:
            try:
                for i in range(okvirjev):
                    kos = (i.to_bytes(4, "big") * (velikost // 4 + 1))[:velikost]
                    poslano.update(kos)
                    ws.poslji(kos)
            except Exception as e:  # noqa: BLE001
                napake.append("pisanje %s: %s" % (type(e).__name__, e))

        niti = [threading.Thread(target=beri, daemon=True), threading.Thread(target=pisi, daemon=True)]
        for n in niti:
            n.start()
        for n in niti:
            n.join(30)
        self.assertEqual(napake, [])
        self.assertFalse(any(n.is_alive() for n in niti), "prenos se ni koncal (prejeto %d B)" % stanje["prejeto"])
        self.assertEqual(self.rele.napaka, "")
        self.assertEqual(stanje["prejeto"], okvirjev * velikost)
        self.assertEqual(prejeto.hexdigest(), poslano.hexdigest(), "bajti so se skozi rele vrnili spremenjeni")

    def test_zapri_iz_druge_niti_zbudi_branje(self):
        ws = self._povezi()
        izid = {}

        def beri() -> None:
            zacetek = time.monotonic()
            try:
                izid["okvir"] = ws.prejmi()
            except Exception as e:  # noqa: BLE001
                izid["napaka"] = e
            izid["cas"] = time.monotonic() - zacetek

        nit = threading.Thread(target=beri, daemon=True)
        nit.start()
        time.sleep(0.3)
        ws.zapri()
        nit.join(5)
        self.assertFalse(nit.is_alive(), "nit, ki bere iz releja, se po zaprtju ni zbudila")
        self.assertLess(izid["cas"], 3.0)
        self.assertIsInstance(izid.get("napaka"), ConnectionError)

    def test_omejitev_med_cakanjem_na_hub(self):
        """LokalniRele pred prvim sporocilom nastavi omejitev (hub mora kanal sprejeti v 20 s) in jo nato umakne."""
        ws = self._povezi()
        ws.s.settimeout(0.3)
        zacetek = time.monotonic()
        with self.assertRaises(socket.timeout):
            ws.prejmi()
        self.assertLess(time.monotonic() - zacetek, 3.0)
        ws.s.settimeout(None)
        ws.poslji(b"potem tece naprej")
        self.assertEqual(ws.prejmi(), (0x2, b"potem tece naprej"))


if __name__ == "__main__":
    unittest.main()
