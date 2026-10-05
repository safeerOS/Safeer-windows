"""Seja deljenja zaslona na Windows (safeer_windows/navidezni_zaslon.py) s pravo povezavo TLS.

Zajem zaslona in vnos sta zamenjana (lazni zajem pise bajte, lazni vnos dogodke steje - miske in tipkovnice se
preizkus ne dotakne); TLS, zeton in okvirji so pravi. Televizor je odjemalec v eni niti (neblokirajoca vticnica +
select), da sam nima tekme med branjem in pisanjem.

Kaj mora veljati (krog 106):
- slika in vnos tecejo hkrati, okvirji pridejo celi;
- nova seja med staro (druga naprava prevzame zaslon) deluje - konec stare seje je ne podre;
- naprava, ki ne bere vec, seje ne drzi v nedogled (omejitev pisanja);
- kdor pride z napacnim zetonom ali brez TLS, seje ne podre.
"""
import json
import select
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_datoteke
from safeer_windows import navidezni_zaslon as nz


class _LazniZajem:
    """Namesto zajem_zaslona.H264Zajem: brez prestanka daje kose nicel."""

    kodirnik = "lazni"
    kos = bytes(1500)
    razmik_s = 0.0005
    vsi = []

    def __init__(self, fps: int = 30, **_k) -> None:
        self.fps = fps
        self.izvor = (1280, 720)
        self.sirina, self.visina = 1280, 720
        self.zaprt = threading.Event()
        _LazniZajem.vsi.append(self)

    def okvirji(self, pogoj):
        while pogoj() and not self.zaprt.is_set():
            yield self.kos
            if self.razmik_s:
                time.sleep(self.razmik_s)

    def zapri(self) -> None:
        self.zaprt.set()


class _LazniVnos:
    """Namesto zajem_zaslona.WindowsVnos: dogodke steje, na racunalniku ne naredi nicesar."""

    vsi = []

    def __init__(self, izvor, slika) -> None:
        self.stevilo = 0
        _LazniVnos.vsi.append(self)

    def izvedi(self, dogodek) -> bool:
        self.stevilo += 1
        return True

    def sprosti_vse(self) -> None:
        pass


class _Televizor:
    """Odjemalec seje. `beri = False` pomeni napravo, ki je obstala: povezava ostane, bere pa ne vec."""

    def __init__(self, seja: dict, vnos_na_s: float = 0.0, zeton=None) -> None:
        self.vrata = seja["port"]
        self.zeton = seja["token"] if zeton is None else zeton
        self.vnos_na_s = vnos_na_s
        self.glava = None
        self.okvirjev = 0
        self.poslanih = 0
        self.napaka = ""
        self.konec_toka = False
        self.beri = True
        self.ustavi = threading.Event()
        self.povezan = threading.Event()
        self.koncan = threading.Event()
        self.nit = threading.Thread(target=self._teci, daemon=True)
        self.nit.start()

    def _razcleni(self, zbrano: bytearray) -> None:
        while len(zbrano) >= 5:
            vrsta, dolzina = zbrano[0], int.from_bytes(zbrano[1:5], "big")
            if vrsta not in (1, 2, 3) or not 0 < dolzina <= 8 * 1024 * 1024:
                self.napaka = "pokvarjen okvir: vrsta %d, dolzina %d" % (vrsta, dolzina)
                return
            if len(zbrano) < 5 + dolzina:
                return
            telo = bytes(zbrano[5:5 + dolzina])
            del zbrano[:5 + dolzina]
            if vrsta == 1 and telo.count(0) != len(telo):
                self.napaka = "pokvarjeno telo okvirja slike"
                return
            self.okvirjev += 1

    def _teci(self) -> None:
        s = None
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(socket.create_connection(("127.0.0.1", self.vrata), timeout=8))
            s.sendall(("SAFEER-ZASLON %s\n" % self.zeton).encode())
            vrstica = b""
            while not vrstica.endswith(b"\n"):
                znak = s.recv(1)
                if not znak:
                    self.konec_toka = True
                    return
                vrstica += znak
            self.glava = json.loads(vrstica)
            self.povezan.set()
            s.setblocking(False)
            zbrano = bytearray()
            caka = b""
            naslednji = time.monotonic()
            while not self.ustavi.is_set() and not self.napaka:
                zdaj = time.monotonic()
                if self.vnos_na_s and not caka and zdaj >= naslednji:
                    caka = b'{"vrsta":"premik","dx":1,"dy":0}\n'
                    naslednji = max(naslednji + 1.0 / self.vnos_na_s, zdaj - 0.01)
                if caka:
                    try:
                        poslano = s.send(caka)
                        caka = caka[poslano:]
                        if not caka:
                            self.poslanih += 1
                    except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
                        pass
                if self.beri:
                    try:
                        kos = s.recv(262144)
                        if not kos:
                            self.konec_toka = True
                            return
                        zbrano += kos
                        self._razcleni(zbrano)
                        continue
                    except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                        pass
                cakaj = 0.05
                if self.vnos_na_s:
                    cakaj = max(0.0, min(cakaj, naslednji - time.monotonic()))
                if self.beri or caka:
                    select.select([s] if self.beri else [], [s] if caka else [], [], cakaj)
                else:
                    time.sleep(cakaj)             # select brez vticnic na Windows ni dovoljen
        except (OSError, ssl.SSLError, ValueError):
            if not self.ustavi.is_set():
                self.konec_toka = True
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
            self.koncan.set()

    def zapri(self) -> None:
        self.ustavi.set()
        self.nit.join(5)


def _pocakaj(pogoj, najdlje: float = 5.0, korak: float = 0.02) -> bool:
    konec = time.monotonic() + najdlje
    while time.monotonic() < konec:
        if pogoj():
            return True
        time.sleep(korak)
    return bool(pogoj())


class _Osnova(unittest.TestCase):
    #: "hitro": veliki kosi brez razmika - vticnica se napolni takoj, ko naprava neha brati.
    HITRO = False

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-navidezni-zaslon-")
        try:
            link_datoteke.zagotovi_potrdilo(self.mapa)
        except Exception as e:  # noqa: BLE001 - brez potrdila preizkusa ni mogoce izvesti
            shutil.rmtree(self.mapa, ignore_errors=True)
            self.skipTest("potrdila ni mogoce ustvari: %s" % e)
        _LazniZajem.vsi, _LazniVnos.vsi = [], []
        popravki = [
            mock.patch.object(nz.zajem_zaslona, "H264Zajem", _LazniZajem),
            mock.patch.object(nz.zajem_zaslona, "WindowsVnos", _LazniVnos),
            mock.patch.object(nz.zajem_zaslona, "velikost_slike", lambda izvor=None: (1280, 720)),
            mock.patch.object(_LazniZajem, "kos", bytes(32768) if self.HITRO else bytes(1500)),
            mock.patch.object(_LazniZajem, "razmik_s", 0.0 if self.HITRO else 0.0005),
        ]
        for p in popravki:
            p.start()
            self.addCleanup(p.stop)
        self.z = nz.NavidezniZaslon(tls_mapa=self.mapa)
        self.televizorji = []

    def tearDown(self):
        for t in self.televizorji:
            t.zapri()
        self.z.ustavi_sejo()
        for zajem in _LazniZajem.vsi:
            zajem.zapri()
        time.sleep(0.1)
        shutil.rmtree(self.mapa, ignore_errors=True)

    def televizor(self, seja: dict, **kw) -> _Televizor:
        t = _Televizor(seja, **kw)
        self.televizorji.append(t)
        return t


class SlikaInVnos(_Osnova):
    def test_slika_in_vnos_hkrati(self):
        tv = self.televizor(self.z.zacni_sejo("tv-test"), vnos_na_s=2000)
        self.assertTrue(tv.povezan.wait(8), "naprava se ni povezala")
        self.assertEqual(tv.glava["v"], 2)
        time.sleep(3.0)
        self.assertEqual(tv.napaka, "")
        self.assertFalse(tv.konec_toka, "seja se je koncala po %d okvirjih in %d dogodkih vnosa" % (tv.okvirjev, tv.poslanih))
        self.assertGreater(tv.okvirjev, 300)
        self.assertGreater(tv.poslanih, 1000)
        self.assertTrue(_pocakaj(lambda: _LazniVnos.vsi and _LazniVnos.vsi[-1].stevilo > 1000),
                        "racunalnik je dobil premalo dogodkov vnosa")
        self.assertTrue(self.z.stanje_seje()["tece"])


class NovaSejaMedStaro(_Osnova):
    def test_druga_naprava_prevzame_zaslon(self):
        """Seja tece; `screen.start` pride znova (druga naprava ali ista po ponovnem zagonu). Nova seja mora delovati."""
        tv1 = self.televizor(self.z.zacni_sejo("tv-1"))
        self.assertTrue(tv1.povezan.wait(8))
        self.assertTrue(_pocakaj(lambda: tv1.okvirjev > 20), "slika prve seje ni stekla")
        seja2 = self.z.zacni_sejo("tablica-2")
        tv2 = self.televizor(seja2)
        self.assertTrue(tv2.povezan.wait(8), "nova seja se ni povezala: konec stare seje ji je zaprl vrata")
        self.assertTrue(_pocakaj(lambda: tv2.okvirjev > 50, 4.0), "nova seja ne dobi slike")
        self.assertTrue(_pocakaj(lambda: tv1.konec_toka, 4.0), "stara seja se ni koncala")
        time.sleep(1.0)
        pred = tv2.okvirjev
        self.assertFalse(tv2.konec_toka, "konec stare seje je zaprl novo")
        self.assertTrue(_pocakaj(lambda: tv2.okvirjev > pred + 50, 4.0), "nova seja po koncu stare ne dobi vec slike")
        self.assertTrue(self.z.stanje_seje()["tece"])
        self.assertEqual(tv2.napaka, "")


class NapravaKiNeBere(_Osnova):
    HITRO = True

    def test_seja_se_konca_po_omejitvi_pisanja(self):
        with mock.patch.object(nz, "ROK_PISANJA_S", 0.5, create=True):
            tv = self.televizor(self.z.zacni_sejo("tv-test"))
            self.assertTrue(tv.povezan.wait(8))
            self.assertTrue(_pocakaj(lambda: tv.okvirjev > 20), "slika ni stekla")
            tv.beri = False
            self.assertTrue(_pocakaj(lambda: not self.z.stanje_seje()["tece"], 8.0),
                            "naprava ne bere, seja pa po omejitvi pisanja se vedno tece")
            self.assertTrue(_pocakaj(lambda: _LazniZajem.vsi[-1].zaprt.is_set(), 4.0), "zajem zaslona po koncu seje se tece")


class TujaPovezava(_Osnova):
    def test_napacen_zeton_ne_podre_seje(self):
        seja = self.z.zacni_sejo("tv-test")
        tuj = self.televizor(seja, zeton="napacen-zeton")
        self.assertTrue(tuj.koncan.wait(8))
        self.assertIsNone(tuj.glava)                 # brez pravega zetona ne dobi niti glave
        tv = self.televizor(seja)
        self.assertTrue(tv.povezan.wait(8), "po tuji povezavi prava naprava ne pride vec do seje")
        self.assertTrue(_pocakaj(lambda: tv.okvirjev > 20), "slika ni stekla")

    def test_pozdrav_z_ne_ascii_znaki_ne_podre_seje(self):
        seja = self.z.zacni_sejo("tv-test")
        tuj = self.televizor(seja, zeton="napačen-žeton")
        self.assertTrue(tuj.koncan.wait(8))
        self.assertIsNone(tuj.glava)
        tv = self.televizor(seja)
        self.assertTrue(tv.povezan.wait(8), "po tujem pozdravu prava naprava ne pride vec do seje")

    def test_povezava_brez_tls_ne_podre_seje(self):
        seja = self.z.zacni_sejo("tv-test")
        s = socket.create_connection(("127.0.0.1", seja["port"]), timeout=5)
        s.sendall(b"GET / HTTP/1.0\r\n\r\n")
        s.settimeout(5)
        try:
            self.assertEqual(s.recv(64), b"")        # nicesar ne dobi
        except OSError:
            pass                                     # ali pa je povezava prekinjena: prav tako v redu
        s.close()
        tv = self.televizor(seja)
        self.assertTrue(tv.povezan.wait(8), "po povezavi brez TLS prava naprava ne pride vec do seje")
        self.assertTrue(_pocakaj(lambda: tv.okvirjev > 20), "slika ni stekla")


if __name__ == "__main__":
    unittest.main()
