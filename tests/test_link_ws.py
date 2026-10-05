"""Streznikova stran WebSocketa: rokovanje, okvirji in izmet naprave, ki ne bere.

Preizkusamo s pravima vticnikoma (socketpair), ne z lazmi: okvirji so bajti in prav tam se napake
skrijejo. Odjemalec v testu je isti WsOdjemalec, ki ga uporablja Safeer Control.
"""
import socket
import struct
import threading
import time
import unittest

from core import link_ws


def _maskiran(opkoda: int, telo: bytes, maska: bytes = b"\x01\x02\x03\x04") -> bytes:
    """Okvir, kakrsnega poslje odjemalec (maskiran)."""
    dolzina = len(telo)
    glava = bytes([0x80 | opkoda])
    if dolzina < 126:
        glava += bytes([0x80 | dolzina])
    elif dolzina < 65536:
        glava += bytes([0x80 | 126]) + struct.pack(">H", dolzina)
    else:
        glava += bytes([0x80 | 127]) + struct.pack(">Q", dolzina)
    zakrito = bytes(b ^ maska[i % 4] for i, b in enumerate(telo))
    return glava + maska + zakrito


class Rokovanje(unittest.TestCase):
    def test_sprejemni_kljuc_po_standardu(self):
        """Primer iz RFC 6455: kljuc dGhlIHNhbXBsZSBub25jZQ== da s3pPLMBiTxaQ9kYGzzhZRbK+xOo=."""
        self.assertEqual(link_ws.sprejemni_kljuc("dGhlIHNhbXBsZSBub25jZQ=="),
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_odgovor_ima_prave_glave(self):
        o = link_ws.odgovor_rokovanja("dGhlIHNhbXBsZSBub25jZQ==").decode()
        self.assertTrue(o.startswith("HTTP/1.1 101 "))
        self.assertIn("Upgrade: websocket", o)
        self.assertIn("Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", o)
        self.assertTrue(o.endswith("\r\n\r\n"))

    def test_prepozna_nadgradnjo_ne_glede_na_velikost_crk(self):
        self.assertTrue(link_ws.je_nadgradnja({"Upgrade": "websocket", "Sec-WebSocket-Key": "abc"}))
        self.assertTrue(link_ws.je_nadgradnja({"UPGRADE": "WebSocket", "sec-websocket-key": "abc"}))
        self.assertFalse(link_ws.je_nadgradnja({"Upgrade": "h2c", "Sec-WebSocket-Key": "abc"}))
        self.assertFalse(link_ws.je_nadgradnja({"Upgrade": "websocket"}), "brez kljuca ni rokovanja")


class Okvirji(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.prejeto = []
        self.koncano = threading.Event()
        self.p = link_ws.Povezava(self.a, "127.0.0.1",
                                  lambda _p, s: self.prejeto.append(s),
                                  lambda _p: self.koncano.set())
        self.nit = threading.Thread(target=self.p.zanka_branja, daemon=True)
        self.nit.start()

    def tearDown(self):
        self.p.zapri()
        for v in (self.a, self.b):
            try:
                v.close()
            except Exception:
                pass

    def _pocakaj(self, koliko=1, rok=2.0):
        konec = time.time() + rok
        while len(self.prejeto) < koliko and time.time() < konec:
            time.sleep(0.01)

    def test_besedilo_pride_skozi(self):
        self.b.sendall(_maskiran(link_ws.OPKODA_BESEDILO, "pozdravljen".encode()))
        self._pocakaj()
        self.assertEqual(self.prejeto, ["pozdravljen"])

    def test_sumniki_prezivijo(self):
        self.b.sendall(_maskiran(link_ws.OPKODA_BESEDILO, "čšž ↔ Safeer".encode("utf-8")))
        self._pocakaj()
        self.assertEqual(self.prejeto, ["čšž ↔ Safeer"])

    def test_dolgo_sporocilo(self):
        dolgo = "x" * 70000          # gre cez mejo 126 in 65535
        self.b.sendall(_maskiran(link_ws.OPKODA_BESEDILO, dolgo.encode()))
        self._pocakaj()
        self.assertEqual(self.prejeto, [dolgo])

    def test_razdeljeno_sporocilo_se_sestavi(self):
        prvi = bytes([link_ws.OPKODA_BESEDILO]) + bytes([0x80 | 3]) + b"\x00\x00\x00\x00" + b"Saf"
        drugi = bytes([0x80 | link_ws.OPKODA_NADALJEVANJE]) + bytes([0x80 | 3]) + b"\x00\x00\x00\x00" + b"eer"
        self.b.sendall(prvi + drugi)
        self._pocakaj()
        self.assertEqual(self.prejeto, ["Safeer"])

    def test_nemaskiran_okvir_zapre_povezavo(self):
        """Odjemalec mora maskirati; kdor ne, ni skladen in ga ne beremo naprej."""
        self.b.sendall(link_ws.okvir(link_ws.OPKODA_BESEDILO, b"brez maske"))
        self.assertTrue(self.koncano.wait(2))
        self.assertEqual(self.prejeto, [])

    def test_preveliko_sporocilo_zapre_povezavo(self):
        glava = bytes([0x80 | link_ws.OPKODA_BESEDILO]) + bytes([0x80 | 127])
        glava += struct.pack(">Q", link_ws.NAJVECJE_SPOROCILO + 1) + b"\x00\x00\x00\x00"
        self.b.sendall(glava)
        self.assertTrue(self.koncano.wait(2))

    def test_ping_dobi_pong(self):
        self.b.sendall(_maskiran(link_ws.OPKODA_PING, b"zivjo"))
        self.b.settimeout(2)
        glava = self.b.recv(2)
        self.assertEqual(glava[0] & 0x0F, link_ws.OPKODA_PONG)
        self.assertEqual(self.b.recv(glava[1] & 0x7F), b"zivjo")

    def test_zaprtje_odjemalca_konca_zanko(self):
        self.b.sendall(_maskiran(link_ws.OPKODA_ZAPRI, b"\x03\xe8"))
        self.assertTrue(self.koncano.wait(2))

    def test_poslano_pride_nemaskirano(self):
        self.p.poslji("odgovor")
        self.b.settimeout(2)
        glava = self.b.recv(2)
        self.assertEqual(glava[0] & 0x0F, link_ws.OPKODA_BESEDILO)
        self.assertFalse(glava[1] & 0x80, "streznik ne sme maskirati")
        self.assertEqual(self.b.recv(glava[1] & 0x7F).decode(), "odgovor")


class GluhaNaprava(unittest.TestCase):
    def test_naprava_ki_ne_bere_izpade(self):
        """Namesto da bi rasel pomnilnik (in zadrzeval ostale), tako povezavo zapremo."""
        a, b = socket.socketpair()
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2048)
            p = link_ws.Povezava(a, "127.0.0.1", lambda _p, _s: None)
            nit = threading.Thread(target=p.zanka_branja, daemon=True)
            nit.start()
            time.sleep(0.05)
            # b nikoli ne bere; vrsta se napolni in povezava mora izpasti
            konec = time.time() + 5
            izpadla = False
            while time.time() < konec:
                if not p.poslji("x" * 20000):
                    izpadla = True
                    break
            self.assertTrue(izpadla, "gluha naprava mora izpasti, ne rasti v pomnilniku")
            self.assertTrue(p.zaprta)
        finally:
            for v in (a, b):
                try:
                    v.close()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
