"""Vticnica TLS za dve niti (core/link_vticnik.py).

Preizkusamo s pravo povezavo TLS na zanki in s pravimi nitmi: napaka, ki jo modul odpravlja, je tekma
med bralno in pisalno nitjo v OpenSSL in je z lazno vticnico ni mogoce pokazati.

Ozadje (krog 102): navaden ssl.SSLSocket s casovno omejitvijo je ob hkratnem branju in pisanju v
delcku sekunde vrnil b"" - povezava Linka je bila videti zaprta, sredisce jo je zaprlo, kosi tokov
Safeer Internet Gatewaya so se izgubili. Skripta, ki to pokaze na surovi vticnici, je v
outputs/krog102/tls_tekma.py; tu preverjamo, da ovita vticnica tega ne pocne in da podatki pridejo celi.
"""
import hashlib
import os
import shutil
import socket
import ssl
import struct
import tempfile
import threading
import time
import unittest

from core import link_datoteke, link_hub, link_vticnik


def _par_tls(mapa: str):
    """Povezan par vticnic TLS (odjemalec, streznik) na zanki."""
    kljuc, potrdilo, _odtis = link_datoteke.zagotovi_potrdilo(mapa)
    ks = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ks.load_cert_chain(potrdilo, kljuc)
    ko = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ko.check_hostname = False
    ko.verify_mode = ssl.CERT_NONE
    posluh = socket.socket()
    posluh.bind(("127.0.0.1", 0))
    posluh.listen(1)
    sprejeta = {}

    def sprejmi():
        c, _ = posluh.accept()
        sprejeta["s"] = ks.wrap_socket(c, server_side=True)

    nit = threading.Thread(target=sprejmi, daemon=True)
    nit.start()
    odjemalec = ko.wrap_socket(socket.create_connection(posluh.getsockname(), timeout=5))
    nit.join(5)
    posluh.close()
    return odjemalec, sprejeta["s"]


class _Osnova(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-vticnik-")
        try:
            a, b = _par_tls(self.mapa)
        except Exception as e:  # noqa: BLE001 - brez orodja za potrdilo testa ni mogoce izvesti
            shutil.rmtree(self.mapa, ignore_errors=True)
            self.skipTest("potrdila ni mogoce ustvariti: %s" % e)
        for s in (a, b):
            s.settimeout(25.0)          # kot povezave Linka: z omejitvijo je vticnica pod OpenSSL neblokirajoca
        self.a = link_vticnik.zavaruj(a)
        self.b = link_vticnik.zavaruj(b)

    def tearDown(self):
        for s in (self.a, self.b):
            try:
                s.close()
            except Exception:
                pass
        shutil.rmtree(self.mapa, ignore_errors=True)


class HkratnoBranjeInPisanje(_Osnova):
    def test_velik_promet_v_eno_in_potrditve_v_drugo_smer(self):
        """Slika tokov Internet Gatewaya: veliki okvirji v eno smer, majhni v drugo, stiri niti."""
        okvirjev, velikost = 600, 34000
        majhnih, majhen = 1500, 350
        napake = []
        prejeto = {"a": hashlib.sha256(), "b": hashlib.sha256(), "a_n": 0, "b_n": 0}
        poslano = {"a": hashlib.sha256(), "b": hashlib.sha256()}
        cilj = {"a": majhnih * majhen, "b": okvirjev * velikost}

        def bralec(s, kdo):
            try:
                while prejeto[kdo + "_n"] < cilj[kdo]:
                    kos = s.recv(65536)
                    if not kos:
                        napake.append("%s: recv je vrnil b'' po %d B od %d" % (kdo, prejeto[kdo + "_n"], cilj[kdo]))
                        return
                    prejeto[kdo].update(kos)
                    prejeto[kdo + "_n"] += len(kos)
            except Exception as e:  # noqa: BLE001
                napake.append("%s branje: %s: %s" % (kdo, type(e).__name__, e))

        def pisec(s, kdo, stevilo, dolzina):
            try:
                for i in range(stevilo):
                    kos = (struct.pack(">I", i) * (dolzina // 4 + 1))[:dolzina]
                    poslano[kdo].update(kos)
                    s.sendall(kos)
            except Exception as e:  # noqa: BLE001
                napake.append("%s pisanje: %s: %s" % (kdo, type(e).__name__, e))

        niti = [threading.Thread(target=bralec, args=(self.a, "a"), daemon=True),
                threading.Thread(target=bralec, args=(self.b, "b"), daemon=True),
                threading.Thread(target=pisec, args=(self.a, "a", okvirjev, velikost), daemon=True),
                threading.Thread(target=pisec, args=(self.b, "b", majhnih, majhen), daemon=True)]
        for n in niti:
            n.start()
        for n in niti:
            n.join(40)
        self.assertEqual(napake, [])
        self.assertFalse(any(n.is_alive() for n in niti), "prenos se ni koncal")
        self.assertEqual(prejeto["b_n"], okvirjev * velikost)
        self.assertEqual(prejeto["a_n"], majhnih * majhen)
        self.assertEqual(prejeto["b"].hexdigest(), poslano["a"].hexdigest(), "veliki okvirji so prisli spremenjeni")
        self.assertEqual(prejeto["a"].hexdigest(), poslano["b"].hexdigest(), "majhni okvirji so prisli spremenjeni")

    def test_okvirja_dveh_piscev_se_ne_prepleteta(self):
        """Dve niti pisejo v isto vticnico: vsak sendall mora priti cel, ne zmesan z drugim."""
        na_pisca, napake = 300, []

        def pisec(oznaka: int, dolzina: int):
            try:
                telo = bytes([oznaka]) * dolzina
                for _ in range(na_pisca):
                    self.a.sendall(struct.pack(">BI", oznaka, dolzina) + telo)
            except Exception as e:  # noqa: BLE001
                napake.append("pisanje: %s" % e)

        pisca = [threading.Thread(target=pisec, args=(1, 20000), daemon=True),
                 threading.Thread(target=pisec, args=(2, 333), daemon=True)]
        for p in pisca:
            p.start()
        zbrano = b""
        videni = {1: 0, 2: 0}
        while videni[1] + videni[2] < 2 * na_pisca:
            while len(zbrano) < 5:
                zbrano += self.b.recv(65536)
            oznaka, dolzina = struct.unpack(">BI", zbrano[:5])
            self.assertIn(oznaka, (1, 2), "glava okvirja je pokvarjena - okvirja sta se prepletla")
            while len(zbrano) < 5 + dolzina:
                zbrano += self.b.recv(65536)
            telo, zbrano = zbrano[5:5 + dolzina], zbrano[5 + dolzina:]
            self.assertEqual(telo, bytes([oznaka]) * dolzina)
            videni[oznaka] += 1
        for p in pisca:
            p.join(10)
        self.assertEqual(napake, [])
        self.assertEqual(videni, {1: na_pisca, 2: na_pisca})


class OmejitevInKonec(_Osnova):
    def test_casovna_omejitev_velja_in_ne_pokvari_povezave(self):
        self.a.settimeout(0.2)
        zacetek = time.monotonic()
        with self.assertRaises(socket.timeout):
            self.a.recv(100)
        self.assertLess(time.monotonic() - zacetek, 2.0)
        self.assertGreaterEqual(time.monotonic() - zacetek, 0.15)
        self.b.sendall(b"potem pride")
        self.a.settimeout(5.0)
        self.assertEqual(self.a.recv(100), b"potem pride")
        self.assertEqual(self.a.gettimeout(), 5.0)

    def test_zaprtje_druge_strani_je_pravi_konec(self):
        self.b.sendall(b"zadnje")
        self.b.close()
        self.assertEqual(self.a.recv(100), b"zadnje")
        self.assertEqual(self.a.recv(100), b"")

    def test_close_zbudi_nit_ki_bere(self):
        """Bralna nit caka na podatke; close() iz druge niti jo mora zbuditi takoj, ne sele ob omejitvi."""
        izid = {}

        def beri():
            zacetek = time.monotonic()
            try:
                izid["kos"] = self.a.recv(100)
            except Exception as e:  # noqa: BLE001
                izid["napaka"] = e
            izid["cas"] = time.monotonic() - zacetek

        nit = threading.Thread(target=beri, daemon=True)
        nit.start()
        time.sleep(0.2)
        self.a.close()
        nit.join(5)
        self.assertFalse(nit.is_alive(), "bralna nit se po close() ni zbudila")
        self.assertLess(izid["cas"], 3.0)
        self.assertTrue(isinstance(izid.get("napaka"), ConnectionError) or izid.get("kos") == b"")

    def test_pisanje_po_zaprtju_je_napaka_povezave(self):
        self.a.close()
        with self.assertRaises(OSError):
            self.a.sendall(b"x")

    def test_ostalo_gre_na_pravo_vticnico(self):
        self.assertEqual(self.a.getpeername()[0], "127.0.0.1")
        self.assertTrue(str(self.a.version()).startswith("TLS"))
        self.assertGreaterEqual(self.a.fileno(), 0)


class Ovijanje(unittest.TestCase):
    def test_navadna_vticnica_ostane_kot_je(self):
        a, b = socket.socketpair()
        try:
            self.assertIs(link_vticnik.zavaruj(a), a)
            link_vticnik.brez_zamika(a)          # socketpair nima TCP_NODELAY: klic ne sme pasti
            link_vticnik.brez_zamika(object())
        finally:
            a.close()
            b.close()


def _okvir_streznika(telo: bytes, opkoda: int = 0x1, zadnji: bool = True) -> bytes:
    glava = bytes([(0x80 if zadnji else 0) | opkoda])
    if len(telo) < 126:
        glava += bytes([len(telo)])
    elif len(telo) < 65536:
        glava += bytes([126]) + struct.pack(">H", len(telo))
    else:
        glava += bytes([127]) + struct.pack(">Q", len(telo))
    return glava + telo


class OdjemalecPreziviOmejitev(unittest.TestCase):
    """WsOdjemalec.prejmi(): casovna omejitev sredi okvirja ne sme pokvariti toka."""

    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.a.settimeout(0.2)
        self.o = link_hub.WsOdjemalec("ws://127.0.0.1:1/cast/ws")
        self.o.vticnik = self.a

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_omejitev_sredi_okvirja(self):
        okvir = _okvir_streznika(("x" * 5000).encode())
        self.b.sendall(okvir[:3])                # glava in pol razsirjene dolzine
        with self.assertRaises(socket.timeout):
            self.o.prejmi()
        self.b.sendall(okvir[3:900])             # del telesa
        with self.assertRaises(socket.timeout):
            self.o.prejmi()
        self.b.sendall(okvir[900:] + _okvir_streznika(b"drugi"))
        self.assertEqual(self.o.prejmi(), "x" * 5000)
        self.assertEqual(self.o.prejmi(), "drugi")

    def test_omejitev_med_deli_razdeljenega_sporocila(self):
        self.b.sendall(_okvir_streznika(b"prvi del, ", zadnji=False))
        with self.assertRaises(socket.timeout):
            self.o.prejmi()
        self.b.sendall(_okvir_streznika(b"", opkoda=0x9))                      # ping vmes ne prekine sporocila
        self.b.sendall(_okvir_streznika(b"drugi del", opkoda=0x0, zadnji=True))
        self.assertEqual(self.o.prejmi(), "prvi del, drugi del")

    def test_prevelik_okvir_se_zavrne_pred_branjem(self):
        self.b.sendall(bytes([0x81, 127]) + struct.pack(">Q", link_hub.NAJVECJE_SPOROCILO + 1))
        with self.assertRaises(ConnectionError):
            self.o.prejmi()


if __name__ == "__main__":
    unittest.main()
