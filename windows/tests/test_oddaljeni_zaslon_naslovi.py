"""Oddaljeni zaslon na Windows: gledalec napravo isce na vec naslovih (docs/LINK-MESH.md, pravilo 8).

Naslov naprave v seznamu Safeer Linka pripise sredisce. V krogu 106 je bil ta naslov za napravo, pripeto na
sredisce druge naprave, 127.0.0.1 - zaslon se ni odprl, ceprav je bil racunalnik v istem omrezju. Zato racunalnik
v odgovoru na `screen.start` sam nasteje svoje naslove (`hosts`), gledalec pa jih poskusi za naslovom iz seznama.

Varnost ostane pri odtisu potrdila in enkratnem zetonu: zeton gre na pot sele po tem, ko se odtis ujema.
"""
import json
import shutil
import socket
import ssl
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_datoteke
from safeer_windows import control_backend
from safeer_windows import oddaljeni_zaslon_povezava as povezava_modul
from safeer_windows.oddaljeni_zaslon_povezava import DrugOdtis, NiDosegljiva, PovezavaGledalca, PrekinjenaPovezava
from safeer_windows.oddaljeni_zaslon_protokol import (CAS_KANDIDATA_S, NAJVEC_KANDIDATOV, Seja, kandidati_naslovov,
                                                      razcleni_odgovor)

ODTIS = "ab" * 32


class Kandidati(unittest.TestCase):
    def test_najprej_naslov_iz_seznama_nato_nasteti(self):
        self.assertEqual(kandidati_naslovov("192.168.0.135", ["192.168.0.135", "10.0.0.7"]),
                         ["192.168.0.135", "10.0.0.7"])

    def test_brez_nastetih_ostane_samo_naslov_iz_seznama(self):
        for hosts in (None, [], "192.168.0.9", {"a": 1}, 7):
            self.assertEqual(kandidati_naslovov("192.168.0.135", hosts), ["192.168.0.135"], hosts)

    def test_nasteti_naslovi_morajo_biti_stevilcni_in_dosegljivi_od_drugod(self):
        slabi = ["127.0.0.1", "127.8.9.1", "0.0.0.0", "0.1.2.3", "224.0.0.251", "240.0.0.1", "255.255.255.255",
                 "::", "::1", "ff02::1", "fe80::1", "2001:db8::5", "::ffff:192.168.0.6",
                 "racunalnik.local", "192.168.0.300", "192.168.01.5", "1.2.3", "1.2.3.4.5", "192.168.0.-5",
                 "\u0661\u0669\u0662.168.0.5", "192.168.0.5:8080", "http://192.168.0.5", "", None, 5,
                 ["192.168.0.5"], "192.168.0.5 "]
        self.assertEqual(kandidati_naslovov("192.168.0.135", slabi), ["192.168.0.135", "192.168.0.5"])

    def test_najvec_stirje(self):
        hosts = ["10.0.0.%d" % i for i in range(1, 20)]
        self.assertEqual(kandidati_naslovov("192.168.0.135", hosts),
                         ["192.168.0.135", "10.0.0.1", "10.0.0.2", "10.0.0.3"])
        self.assertEqual(len(kandidati_naslovov("", hosts)), NAJVEC_KANDIDATOV)


class Odgovor(unittest.TestCase):
    PODATKI = {"port": 40123, "fp": ODTIS, "token": "zeton-zeton-zeton", "v": 2}

    def test_naslov_iz_seznama_in_nasteti(self):
        seja = razcleni_odgovor({"ok": True, "data": dict(self.PODATKI, hosts=["192.168.0.135", "10.8.0.2"])},
                                {"naslov": "192.168.0.87"})
        self.assertEqual(seja.naslov, "192.168.0.87")
        self.assertEqual(seja.naslovi, ("192.168.0.87", "192.168.0.135", "10.8.0.2"))
        self.assertEqual((seja.vrata, seja.odtis, seja.zeton), (40123, ODTIS, "zeton-zeton-zeton"))

    def test_star_racunalnik_brez_nastetih(self):
        seja = razcleni_odgovor({"ok": True, "data": dict(self.PODATKI)}, {"naslov": "192.168.0.135"})
        self.assertEqual(seja.naslovi, ("192.168.0.135",))

    def test_brez_naslova_v_seznamu_veljajo_nasteti(self):
        seja = razcleni_odgovor({"ok": True, "data": dict(self.PODATKI, hosts=["192.168.0.135"])}, {"naslov": ""})
        self.assertEqual((seja.naslov, seja.naslovi), ("192.168.0.135", ("192.168.0.135",)))

    def test_brez_vsakega_naslova_je_napaka(self):
        for hosts in (None, [], ["127.0.0.1"], ["ni-naslov"]):
            with self.assertRaises(ValueError):
                razcleni_odgovor({"ok": True, "data": dict(self.PODATKI, hosts=hosts)}, {"naslov": ""})

    def test_seja_po_starem_ima_en_sam_naslov(self):
        seja = Seja("192.168.0.135", 40123, ODTIS, "zeton")
        self.assertEqual(seja.naslovi, ())
        self.assertEqual(seja.razlicica, 2)


class _Zaslon:
    def zacni_sejo(self, posiljatelj, kakovost="najvisja"):
        return {"port": 40123, "fp": ODTIS, "token": "zeton-zeton-zeton", "v": 2, "width": 1920, "height": 1080}


class _PovezavaHuba:
    def __init__(self):
        self.poslano = []

    def poslji(self, sporocilo):
        self.poslano.append(sporocilo)


class OdgovorRacunalnika(unittest.TestCase):
    """Ta racunalnik deli zaslon: v odgovoru na `screen.start` nasteje svoje naslove."""

    def _start(self):
        b = object.__new__(control_backend.SafeerControlBackend)
        b.navidezni_zaslon = _Zaslon()
        b.povezava = _PovezavaHuba()
        b.ob_mediju = b.ob_magnetu = None
        b.nastavitve = {"hub_url": "wss://127.0.0.1:8990/cast/ws"}
        b._dejanje_dovoljeno = lambda *_a: True
        b._oddaj_dogodek = lambda *_a, **_k: None
        b._obdelaj_nadzorni_ukaz({"sender": "telefon", "id": "1",
                                  "payload": {"action": "screen.start", "params": {"quality": "najvisja"}}})
        return b.povezava.poslano[-1]["payload"]

    def test_screen_start_nasteje_naslove(self):
        with mock.patch("core.link_zvok.lastni_naslovi", return_value=["192.168.0.220", "172.28.96.1"]) as klic:
            odgovor = self._start()
        self.assertTrue(odgovor["ok"], odgovor)
        self.assertEqual(odgovor["data"]["hosts"], ["192.168.0.220", "172.28.96.1"])
        self.assertEqual(klic.call_args[0][0], "wss://127.0.0.1:8990/cast/ws")
        self.assertEqual((odgovor["data"]["port"], odgovor["data"]["fp"], odgovor["data"]["token"]),
                         (40123, ODTIS, "zeton-zeton-zeton"))
        # Gledalec iz tega odgovora sestavi kandidate: naslov iz seznama naprav in nastete.
        seja = razcleni_odgovor(odgovor, {"naslov": "192.168.0.220"})
        self.assertEqual(seja.naslovi, ("192.168.0.220", "172.28.96.1"))

    def test_najvec_stirje_naslovi(self):
        with mock.patch("core.link_zvok.lastni_naslovi", return_value=["10.0.0.%d" % i for i in range(1, 9)]):
            odgovor = self._start()
        self.assertEqual(odgovor["data"]["hosts"], ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"])

    def test_napaka_pri_naslovih_seje_ne_podre(self):
        with mock.patch("core.link_zvok.lastni_naslovi", side_effect=OSError("ni omrezja")):
            odgovor = self._start()
        self.assertTrue(odgovor["ok"], odgovor)
        self.assertEqual(odgovor["data"]["hosts"], [])
        self.assertEqual(odgovor["data"]["port"], 40123)

    def test_pravi_naslovi_niso_zanka(self):
        odgovor = self._start()
        self.assertIsInstance(odgovor["data"]["hosts"], list)
        for naslov in odgovor["data"]["hosts"]:
            self.assertFalse(naslov.startswith("127."), naslov)
            self.assertEqual(kandidati_naslovov("", [naslov]), [naslov])


class _Naprava:
    """Naprava, ki deli zaslon, na enem naslovu zanke: po pozdravu poslje glavo in en okvir, nato molci."""

    def __init__(self, mapa: str, naslov: str, vrata: int = 0) -> None:
        kljuc, potrdilo, self.odtis = link_datoteke.zagotovi_potrdilo(mapa)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(potrdilo, kljuc)
        self.posluh = socket.socket()
        self.posluh.bind((naslov, vrata))
        self.posluh.listen(4)
        self.vrata = self.posluh.getsockname()[1]
        self.pozdravi = []
        self.povezav = 0
        self.konec = threading.Event()
        self.nit = threading.Thread(target=self._teci, daemon=True)
        self.nit.start()

    def _teci(self) -> None:
        while not self.konec.is_set():
            try:
                surov, _ = self.posluh.accept()
            except OSError:
                return
            self.povezav += 1
            threading.Thread(target=self._streci, args=(surov,), daemon=True).start()

    def _streci(self, surov) -> None:
        try:
            surov.settimeout(5)
            s = self.ctx.wrap_socket(surov, server_side=True)
            vrstica = b""
            while not vrstica.endswith(b"\n"):
                znak = s.recv(1)
                if not znak:
                    break
                vrstica += znak
            if vrstica:
                self.pozdravi.append(vrstica.decode("utf-8", "replace").strip())
                s.sendall((json.dumps({"v": 2, "w": 1280, "h": 720, "fps": 30}) + "\n").encode())
                s.sendall(bytes([1]) + struct.pack(">I", 4) + b"h264")
                self.konec.wait(6)
            s.close()
        except (OSError, ssl.SSLError):
            try:
                surov.close()
            except OSError:
                pass

    def zapri(self) -> None:
        self.konec.set()
        # Samo close() niti, ki caka v accept(), na Linuxu ne zbudi - povezava nase jo.
        try:
            socket.create_connection(self.posluh.getsockname(), 1).close()
        except OSError:
            pass
        try:
            self.posluh.close()
        except OSError:
            pass
        self.nit.join(5)


class VecNaslovov(unittest.TestCase):
    def setUp(self):
        self.mape, self.naprave, self.povezave = [], [], []

    def tearDown(self):
        for p in self.povezave:
            p.zapri()
        for n in self.naprave:
            n.zapri()
        for m in self.mape:
            shutil.rmtree(m, ignore_errors=True)

    def _naprava(self, naslov: str, vrata: int = 0) -> _Naprava:
        mapa = tempfile.mkdtemp(prefix="safeer-gledalec-")
        self.mape.append(mapa)
        try:
            n = _Naprava(mapa, naslov, vrata)
        except Exception as e:  # noqa: BLE001 - brez potrdila ali drugega naslova zanke preizkusa ni
            self.skipTest("naprave za preizkus ni mogoce pripraviti: %s" % e)
        self.naprave.append(n)
        return n

    def _povezava(self, naprava: _Naprava, naslovi, **kw) -> PovezavaGledalca:
        # Naslovi zanke v odgovoru naprave niso dovoljeni; preizkus jih zato poda seji neposredno.
        seja = Seja(naslovi[0], naprava.vrata, naprava.odtis, "zeton", 2, tuple(naslovi))
        p = PovezavaGledalca(seja, **kw)
        self.povezave.append(p)
        return p

    def test_prvi_naslov_mrtev_drugi_dela(self):
        naprava = self._naprava("127.0.0.1")
        p = self._povezava(naprava, ["127.0.0.2", "127.0.0.1"])
        zacetek = time.monotonic()
        glava = p.povezi()
        self.assertEqual((glava["w"], glava["h"]), (1280, 720))
        self.assertLess(time.monotonic() - zacetek, CAS_KANDIDATA_S + 3.0)
        self.assertEqual(next(p.okvirji()), (1, b"h264"))
        self.assertEqual(naprava.pozdravi, ["SAFEER-ZASLON zeton"])

    def test_na_prvem_naslovu_druga_naprava_zetona_ne_dobi(self):
        prava = self._naprava("127.0.0.1")
        tuja = self._naprava("127.0.0.2", prava.vrata)
        self.assertNotEqual(prava.odtis, tuja.odtis)
        p = self._povezava(prava, ["127.0.0.2", "127.0.0.1"])
        p.povezi()
        p.zapri()
        time.sleep(0.2)
        self.assertEqual(tuja.povezav, 1, "gledalec mora tujo napravo najprej poskusiti")
        self.assertEqual(tuja.pozdravi, [], "zeton ne sme do naprave z drugim potrdilom")
        self.assertEqual(prava.pozdravi, ["SAFEER-ZASLON zeton"])

    def test_samo_druga_naprava_ostane_napaka_o_odtisu(self):
        prava = self._naprava("127.0.0.1")
        tuja = self._naprava("127.0.0.2")
        p = PovezavaGledalca(Seja("127.0.0.2", tuja.vrata, prava.odtis, "zeton"))
        self.povezave.append(p)
        with self.assertRaises(DrugOdtis) as ujeto:
            p.povezi()
        self.assertIsInstance(ujeto.exception, ssl.SSLError)
        time.sleep(0.2)
        self.assertEqual(tuja.pozdravi, [])

    def test_noben_naslov_ne_dela(self):
        naprava = self._naprava("127.0.0.1")
        prost = socket.socket()
        prost.bind(("127.0.0.1", 0))
        vrata = prost.getsockname()[1]
        prost.close()                               # vrata, na katerih zdaj ni nikogar
        for naslovi in (("127.0.0.1",), ("127.0.0.1", "127.0.0.2")):
            p = PovezavaGledalca(Seja(naslovi[0], vrata, naprava.odtis, "zeton", 2, naslovi), cas_povezave=3.0)
            self.povezave.append(p)
            with self.assertRaises(NiDosegljiva) as ujeto:
                p.povezi()
            self.assertEqual(str(ujeto.exception), "", "okno pove svoj stavek, ne sistemske napake")
        self.assertEqual(naprava.povezav, 0)

    def test_en_naslov_dobi_ves_cas_vec_naslovov_si_ga_razdeli(self):
        naprava = self._naprava("127.0.0.1")
        klici = []
        pravi = socket.create_connection

        def belezi(cilj, timeout=None, *a, **k):
            klici.append((cilj[0], timeout))
            return pravi(cilj, timeout, *a, **k)

        with mock.patch.object(povezava_modul.socket, "create_connection", belezi):
            self._povezava(naprava, ["127.0.0.1"]).povezi()
            self._povezava(naprava, ["127.0.0.2", "127.0.0.1"]).povezi()
        self.assertEqual(klici[0], ("127.0.0.1", 8.0))
        self.assertEqual(klici[1:], [("127.0.0.2", CAS_KANDIDATA_S), ("127.0.0.1", CAS_KANDIDATA_S)])

    def test_zaprta_povezava_naslovov_ne_poskusa(self):
        naprava = self._naprava("127.0.0.1")
        p = self._povezava(naprava, ["127.0.0.2", "127.0.0.1"])
        p.zapri()
        with self.assertRaises(PrekinjenaPovezava):
            p.povezi()
        self.assertEqual(naprava.povezav, 0)


if __name__ == "__main__":
    unittest.main()
