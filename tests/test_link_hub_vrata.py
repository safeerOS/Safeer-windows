"""Sredisce in privzeta vrata: drug program na 8990 ne prepreci gostovanja, drugo Safeer sredisce ga.

`HubStreznik._ze_gosti_lokalno()` je gostovanje odklonil, kadarkoli je na 127.0.0.1:8990 kdorkoli poslusal. Odklonimo
samo, kadar tam poslusa Safeer Hub ali tega ne moremo izkljuciti (ne odgovori pravocasno).
"""
import os
import socket
import ssl
import tempfile
import threading
import unittest
from unittest import mock

from core import link_datoteke, link_krog, link_tls, link_hub_streznik as S


class _Poslusalec:
    """Majhen streznik na prostih vratih: `obravnava(vticnica)` za vsako povezavo, v svoji niti."""

    def __init__(self, obravnava):
        self._obravnava = obravnava
        self._v = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._v.bind(("127.0.0.1", 0))
        self._v.listen(8)
        self.vrata = self._v.getsockname()[1]
        self._tece = True
        self._odprte = []
        threading.Thread(target=self._zanka, daemon=True).start()

    def _zanka(self):
        while self._tece:
            try:
                c, _ = self._v.accept()
            except OSError:
                return
            self._odprte.append(c)
            threading.Thread(target=self._ena, args=(c,), daemon=True).start()

    def _ena(self, c):
        try:
            self._obravnava(c)
        except Exception:
            pass

    def zapri(self):
        self._tece = False
        for v in [self._v] + self._odprte:
            try:
                v.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                v.close()
            except OSError:
                pass


def _navaden_http(c):
    c.settimeout(2)
    try:
        c.recv(2048)
    except OSError:
        pass
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
    c.close()


def _molci(c):
    c.settimeout(5)
    try:
        while c.recv(2048):
            pass
    except OSError:
        pass


class NiSafeerHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        kljuc, potrdilo, _odtis = link_datoteke.zagotovi_potrdilo(cls._td.name)
        cls.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.ctx.load_cert_chain(potrdilo, kljuc)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def _streznik(self, obravnava):
        p = _Poslusalec(obravnava)
        self.addCleanup(p.zapri)
        return p.vrata

    def _tls(self, odgovor: bytes):
        def obravnava(c):
            c.settimeout(2)
            t = self.ctx.wrap_socket(c, server_side=True)
            try:
                t.recv(2048)
                t.sendall(odgovor)
            finally:
                t.close()
        return self._streznik(obravnava)

    def test_nihce_ne_poslusa(self):
        v = socket.socket()
        v.bind(("127.0.0.1", 0))
        prosta = v.getsockname()[1]
        v.close()
        self.assertFalse(S.ni_safeer_hub(prosta, timeout=0.5))

    def test_program_brez_tls_ni_sredisce(self):
        self.assertTrue(S.ni_safeer_hub(self._streznik(_navaden_http), timeout=1.5))

    def test_tls_streznik_ki_ne_pozna_poti_ni_sredisce(self):
        vrata = self._tls(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        self.assertTrue(S.ni_safeer_hub(vrata, timeout=1.5))

    def test_tls_streznik_ki_ne_govori_http_ni_sredisce(self):
        self.assertTrue(S.ni_safeer_hub(self._tls(b"220 posta pripravljena\r\n"), timeout=1.5))

    def test_sredisce_je_sredisce(self):
        for prva in (b"HTTP/1.1 200 OK", b"HTTP/1.1 401 Unauthorized", b"HTTP/1.1 403 Forbidden"):
            with self.subTest(prva=prva):
                vrata = self._tls(prva + b"\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                self.assertFalse(S.ni_safeer_hub(vrata, timeout=1.5))

    def test_tiho_poslusanje_je_dvom(self):
        # Sprejme povezavo in ne odgovori (nase sredisce med zagonom ali pod obremenitvijo): gostovanja ne tvegamo.
        self.assertFalse(S.ni_safeer_hub(self._streznik(_molci), timeout=0.4))

    def test_gostovanje_ob_drugem_programu_na_privzetih_vratih(self):
        with mock.patch.object(S, "PRIVZETA_VRATA", self._streznik(_navaden_http)):
            self.assertFalse(S.HubStreznik._ze_gosti_lokalno())       # prej True: racunalnik je ostal brez sredisca

    def test_brez_gostovanja_ob_drugem_srediscu(self):
        vrata = self._tls(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        with mock.patch.object(S, "PRIVZETA_VRATA", vrata):
            self.assertTrue(S.HubStreznik._ze_gosti_lokalno())

    def test_brez_gostovanja_ob_dvomu(self):
        with mock.patch.object(S, "PRIVZETA_VRATA", self._streznik(_molci)), \
                mock.patch.object(S.ni_safeer_hub, "__defaults__", (S.PRIVZETA_VRATA, 0.4, "127.0.0.1")):
            self.assertTrue(S.HubStreznik._ze_gosti_lokalno())

    def test_prosta_vrata_gostimo(self):
        v = socket.socket()
        v.bind(("127.0.0.1", 0))
        prosta = v.getsockname()[1]
        v.close()
        with mock.patch.object(S, "PRIVZETA_VRATA", prosta):
            self.assertFalse(S.HubStreznik._ze_gosti_lokalno())


class VratSiNeDelimo(unittest.TestCase):
    """Sredisce se ne veze na vrata, ki jih ze drzi drug program.

    Izmerjeno 5. 10. 2026 na Windows 10: vticnik s SO_REUSEADDR (tako ga odpre http.server) se je vezal na 8990, ceprav
    jih je ze drzal Safeer OS (brez nastavitve in s SO_EXCLUSIVEADDRUSE: napaka 10048). Sredisce je tako »poslusalo«
    na vratih, na katerih je povezave dobival drug proces."""

    def _zasedena(self, naslov: str, deli: bool) -> int:
        v = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if deli:
            v.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        v.bind((naslov, 0))
        v.listen(4)
        self.addCleanup(v.close)
        return v.getsockname()[1]

    def test_nastavitve_po_sistemu(self):
        self.assertEqual(S.nastavitve_vticnika("posix"), (True, False))
        self.assertEqual(S.nastavitve_vticnika("nt"), (False, True))
        self.assertEqual(S.nastavitve_vticnika(), S.nastavitve_vticnika(os.name))
        self.assertEqual(S._Streznik.allow_reuse_address, os.name != "nt")

    def test_na_zasedena_vrata_se_ne_vezemo(self):
        for naslov, deli in (("0.0.0.0", False), ("0.0.0.0", True), ("127.0.0.1", False), ("127.0.0.1", True)):
            with self.subTest(naslov=naslov, deli=deli):
                vrata = self._zasedena(naslov, deli)
                vezan = None
                try:
                    vezan = S._Streznik(("0.0.0.0", vrata), S._Obravnava)
                except OSError:
                    pass
                if vezan is not None:
                    vezan.server_close()
                self.assertIsNone(vezan, "sredisce se je vezalo na vrata, ki jih drzi drug vticnik")

    def test_prosta_vrata_dobimo_tudi_takoj_po_zaprtju(self):
        prvi = S._Streznik(("0.0.0.0", 0), S._Obravnava)
        vrata = prvi.server_address[1]
        prvi.server_close()
        drugi = S._Streznik(("0.0.0.0", vrata), S._Obravnava)
        self.assertEqual(drugi.server_address[1], vrata)
        drugi.server_close()

    def test_sredisce_ob_tujem_programu_vzame_druga_vrata_in_dela(self):
        """Cela pot zagona: na privzetih vratih poslusa drug program -> sredisce gosti na drugih in odgovarja."""
        tuj = _Poslusalec(_navaden_http)
        self.addCleanup(tuj.zapri)
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        okolje = {k: v for k, v in os.environ.items() if k != "SAFEER_HUB_DRUGI"}
        with mock.patch.object(S, "PRIVZETA_VRATA", tuj.vrata), \
                mock.patch.object(link_krog, "_mapa_nastavitev", return_value=td.name), \
                mock.patch.object(S, "_obvestilo", lambda *a, **k: None), \
                mock.patch.object(S, "_obvestilo_kode", lambda *a, **k: None), \
                mock.patch.dict(os.environ, okolje, clear=True):
            streznik = S.HubStreznik(tls_mapa=os.path.join(td.name, "tls"))
            self.assertTrue(streznik.zazeni(), "drug program na privzetih vratih ne sme prepreciti gostovanja")
            try:
                self.assertNotEqual(streznik.vrata, tuj.vrata, "vrat si s tujim programom ne delimo")
                koda, zdravje, _ = link_tls.zahteva("https://127.0.0.1:%d/cast/health" % streznik.vrata,
                                                    timeout=5.0, pripeti=streznik.odtis)
                self.assertEqual(koda, 200, zdravje)
                self.assertTrue(S.ni_safeer_hub(tuj.vrata, timeout=1.5), "na privzetih vratih je se vedno tuj program")
            finally:
                streznik.ustavi()


if __name__ == "__main__":
    unittest.main()
