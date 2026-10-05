"""Povezava gledalca oddaljenega zaslona (safeer_windows/oddaljeni_zaslon_povezava.py) s pravo povezavo TLS.

Gledalec bere okvirje v dekodirni niti in posilja vnos (miska, tipke) iz glavne niti okna. Navaden ssl.SSLSocket s
casovno omejitvijo tega ne prenese: na Windows pisanje pade z WinError 10035, na Linuxu bralna nit lazno javi konec
povezave - oddaljeni zaslon se prekine, medtem ko uporabnik premika misko.

Naprava v preizkusu je namenoma ena sama nit z neblokirajoco vticnico (select): sama nima te napake in preizkus
meri samo gledalca.
"""
import json
import select
import shutil
import socket
import ssl
import struct
import tempfile
import threading
import time
import unittest

from core import link_datoteke
from safeer_windows.oddaljeni_zaslon_povezava import PovezavaGledalca, PrekinjenaPovezava
from safeer_windows.oddaljeni_zaslon_protokol import Seja

#: Okvir slike v preizkusu in razmik med okvirji. Majhni in pogosti okvirji pomenijo, da bralna nit velikokrat
#: izprazni vticnico - prav takrat se pokaze tekma s pisalno nitjo.
TELO = b"x" * 1500
RAZMIK_S = 0.0005


class _Naprava:
    """Naprava, ki deli zaslon. nacin: "tok" (okvirji brez konca), "trije" (trije okvirji in konec),
    "pol" (pol okvirja in konec), "tiho" (samo glava)."""

    def __init__(self, mapa: str, nacin: str = "tok") -> None:
        kljuc, potrdilo, self.odtis = link_datoteke.zagotovi_potrdilo(mapa)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(potrdilo, kljuc)
        self.posluh = socket.socket()
        self.posluh.bind(("127.0.0.1", 0))
        self.posluh.listen(1)
        self.vrata = self.posluh.getsockname()[1]
        self.nacin = nacin
        self.vnosov = 0
        self.konec = threading.Event()
        self.napaka = ""
        self.nit = threading.Thread(target=self._teci, daemon=True)
        self.nit.start()

    def seja(self, odtis: str = "") -> Seja:
        return Seja("127.0.0.1", self.vrata, odtis or self.odtis, "zeton")

    def _teci(self) -> None:
        s = None
        try:
            surov, _ = self.posluh.accept()
            surov.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s = self.ctx.wrap_socket(surov, server_side=True)
            vrstica = b""
            while not vrstica.endswith(b"\n"):
                znak = s.recv(1)
                if not znak:
                    return
                vrstica += znak
            if vrstica != b"SAFEER-ZASLON zeton\n":
                raise ValueError("napacen pozdrav")
            s.sendall((json.dumps({"v": 2, "w": 1280, "h": 720, "fps": 30}) + "\n").encode())
            okvir = bytes([1]) + struct.pack(">I", len(TELO)) + TELO
            if self.nacin == "trije":
                s.sendall(okvir * 3)
                return
            if self.nacin == "pol":
                s.sendall(okvir + okvir[:700])
                return
            if self.nacin == "tiho":
                self.konec.wait(20)
                return
            s.setblocking(False)
            caka = b""
            ostanek = b""
            naslednji = time.monotonic()
            while not self.konec.is_set():
                zdaj = time.monotonic()
                if not caka and zdaj >= naslednji:
                    caka, naslednji = okvir, max(naslednji + RAZMIK_S, zdaj - 0.01)
                if caka:
                    try:
                        poslano = s.send(caka)
                        caka = caka[poslano:]
                    except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
                        pass
                try:
                    kos = s.recv(65536)
                    if not kos:
                        break
                    ostanek += kos
                    *vrstice, ostanek = ostanek.split(b"\n")
                    self.vnosov += len(vrstice)
                    continue
                except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                    pass
                select.select([s], [s] if caka else [], [], max(0.0, min(naslednji - time.monotonic(), 0.05)))
        except Exception as e:  # noqa: BLE001
            if not self.konec.is_set():
                self.napaka = "%s: %s" % (type(e).__name__, e)
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def zapri(self) -> None:
        self.konec.set()
        try:
            self.posluh.close()
        except OSError:
            pass
        self.nit.join(5)


class _Osnova(unittest.TestCase):
    NACIN = "tok"

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-gledalec-")
        try:
            self.naprava = _Naprava(self.mapa, self.NACIN)
        except Exception as e:  # noqa: BLE001 - brez potrdila preizkusa ni mogoce izvesti
            shutil.rmtree(self.mapa, ignore_errors=True)
            self.skipTest("potrdila ni mogoce ustvariti: %s" % e)
        self.povezave = []

    def tearDown(self):
        for p in self.povezave:
            p.zapri()
        self.naprava.zapri()
        shutil.rmtree(self.mapa, ignore_errors=True)

    def povezava(self, **kw) -> PovezavaGledalca:
        p = PovezavaGledalca(self.naprava.seja(kw.pop("odtis", "")), **kw)
        self.povezave.append(p)
        return p


class OkvirjiInVnos(_Osnova):
    def test_okvirji_in_vnos_hkrati(self):
        p = self.povezava()
        glava = p.povezi()
        self.assertEqual((glava["w"], glava["h"]), (1280, 720))
        stanje = {"okvirjev": 0, "napaka": "", "poslanih": 0}
        konec = time.monotonic() + 3.0

        def beri() -> None:
            try:
                for vrsta, telo in p.okvirji():
                    if vrsta != 1 or telo != TELO:
                        stanje["napaka"] = "pokvarjen okvir (vrsta %d, %d B)" % (vrsta, len(telo))
                        return
                    stanje["okvirjev"] += 1
                    if time.monotonic() >= konec:
                        return
                if time.monotonic() < konec:
                    stanje["napaka"] = "naprava je povezavo zaprla"
            except Exception as e:  # noqa: BLE001
                if time.monotonic() < konec:
                    stanje["napaka"] = "branje %s: %s" % (type(e).__name__, e)

        def pisi() -> None:
            try:
                while time.monotonic() < konec and not stanje["napaka"]:
                    p.poslji({"vrsta": "tocka", "x": 640, "y": 360})
                    stanje["poslanih"] += 1
                    time.sleep(0.0002)
            except Exception as e:  # noqa: BLE001
                if time.monotonic() < konec:
                    stanje["napaka"] = "pisanje %s: %s" % (type(e).__name__, e)

        niti = [threading.Thread(target=beri, daemon=True), threading.Thread(target=pisi, daemon=True)]
        for n in niti:
            n.start()
        for n in niti:
            n.join(15)
        self.assertEqual(stanje["napaka"], "", "seja se je prekinila po %d okvirjih in %d dogodkih vnosa"
                         % (stanje["okvirjev"], stanje["poslanih"]))
        self.assertEqual(self.naprava.napaka, "")
        self.assertFalse(any(n.is_alive() for n in niti), "seja se ni koncala")
        self.assertGreater(stanje["okvirjev"], 300)
        self.assertGreater(stanje["poslanih"], 300)
        self.assertGreater(self.naprava.vnosov, 300)      # naprava je vnos tudi dobila

    def test_zapri_iz_druge_niti_zbudi_branje(self):
        p = self.povezava()
        p.povezi()
        izid = {}

        def beri() -> None:
            zacetek = time.monotonic()
            try:
                for _ in p.okvirji():
                    pass
                izid["konec"] = "navaden"
            except Exception as e:  # noqa: BLE001
                izid["napaka"] = e
            izid["cas"] = time.monotonic() - zacetek

        nit = threading.Thread(target=beri, daemon=True)
        nit.start()
        time.sleep(0.4)
        p.zapri()
        nit.join(5)
        self.assertFalse(nit.is_alive(), "nit, ki bere okvirje, se po zaprtju ni zbudila")
        self.assertLess(izid["cas"], 3.0)
        self.assertIsInstance(izid.get("napaka"), PrekinjenaPovezava)
        with self.assertRaises(PrekinjenaPovezava):          # zaprta povezava se ne poveze vec
            p.povezi()

    def test_napacen_odtis_potrdila(self):
        p = self.povezava(odtis="ab" * 32)
        with self.assertRaises(ssl.SSLError):
            p.povezi()

    def test_vnos_pred_povezavo_ne_naredi_nicesar(self):
        self.povezava().poslji({"vrsta": "tocka", "x": 1, "y": 1})


class NavadenKonec(_Osnova):
    NACIN = "trije"

    def test_konec_na_meji_okvirja(self):
        p = self.povezava()
        p.povezi()
        self.assertEqual([(v, len(t)) for v, t in p.okvirji()], [(1, len(TELO))] * 3)


class KonecSrediOkvirja(_Osnova):
    NACIN = "pol"

    def test_je_prekinitev(self):
        p = self.povezava()
        p.povezi()
        okvirji = p.okvirji()
        self.assertEqual(next(okvirji)[0], 1)
        with self.assertRaises(PrekinjenaPovezava):
            next(okvirji)


class Tisina(_Osnova):
    NACIN = "tiho"

    def test_je_prekinitev_brez_sistemskega_besedila(self):
        p = self.povezava(tisina_s=0.4)
        p.povezi()
        zacetek = time.monotonic()
        with self.assertRaises(PrekinjenaPovezava) as ujeto:
            next(p.okvirji())
        self.assertLess(time.monotonic() - zacetek, 3.0)
        self.assertEqual(str(ujeto.exception), "")           # okno pokaze svoje besedilo, ne "timed out"


if __name__ == "__main__":
    unittest.main()
