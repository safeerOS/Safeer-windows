"""Oglas mDNS Huba racunalnika: ime primerka storitve je za vsako napravo drugacno.

Ugotovljeno 5. 10. 2026: ime je bilo »safeer-« + zadnjih 8 znakov id-ja, id Controla pa se konca na »-control« -
racunalnik z Linuxom in racunalnik z Windows sta se v istem omrezju oglasala z istim imenom (»safeer--control«).
Drugemu registracija ni uspela (na testnem Windows: NonUniqueNameException), napaka je bila tiho pogoltnjena in
njegovega Huba v omrezju ni bilo videti.
"""
import contextlib
import io
import sys
import types
import unittest
from unittest import mock

from core import link_hub_streznik as S

WINDOWS = "n-c50805106b98fc1c-control"
LINUX = "n-96bfc3da3b52ea80-control"


class _Info:
    def __init__(self, vrsta, ime, addresses=None, port=0, properties=None, server=""):
        self.type, self.name, self.addresses, self.port = vrsta, ime, addresses, port
        self.properties, self.server = properties or {}, server


class _Zc:
    primerki = []
    napaka = None

    def __init__(self):
        self.registrirane, self.odjavljene, self.zaprt = [], [], False
        _Zc.primerki.append(self)

    def register_service(self, info, **kw):
        if _Zc.napaka is not None:
            raise _Zc.napaka
        self.registrirane.append((info, kw))

    def unregister_service(self, info):
        self.odjavljene.append(info)

    def close(self):
        self.zaprt = True


class ImeOglasa(unittest.TestCase):
    def test_dva_racunalnika_imata_razlicni_imeni(self):
        self.assertEqual(S.ime_oglasa(WINDOWS), "safeer-05106b98fc1c")
        self.assertEqual(S.ime_oglasa(LINUX), "safeer-c3da3b52ea80")
        self.assertNotEqual(S.ime_oglasa(WINDOWS), S.ime_oglasa(LINUX))

    def test_pripona_vloge_ni_del_imena(self):
        self.assertEqual(S.ime_oglasa("n-c50805106b98fc1c-os"), S.ime_oglasa("n-c50805106b98fc1c"))
        self.assertEqual(S.ime_oglasa(WINDOWS), S.ime_oglasa("n-c50805106b98fc1c"))
        self.assertNotIn("control", S.ime_oglasa(WINDOWS))

    def test_veljavna_oznaka_dns(self):
        for i in (WINDOWS, LINUX, "hub-wp28s", "Računalnik št. 1", "x" * 200, "", None, "---"):
            ime = S.ime_oglasa(i)
            self.assertTrue(ime.startswith("safeer-") and len(ime) > len("safeer-"), ime)
            self.assertLessEqual(len(ime.encode("utf-8")), 63)
            self.assertTrue(all(z.isascii() and (z.isalnum() or z == "-") for z in ime), ime)
        self.assertEqual(S.ime_oglasa(""), "safeer-pc")


class OglasHuba(unittest.TestCase):
    def setUp(self):
        _Zc.primerki.clear()
        _Zc.napaka = None
        lazni = types.SimpleNamespace(ServiceInfo=_Info, Zeroconf=_Zc)
        self._zaplata = mock.patch.dict(sys.modules, {"zeroconf": lazni})
        self._zaplata.start()

    def tearDown(self):
        self._zaplata.stop()

    def _oglasi(self, id_naprave):
        o = S.Oglas()
        self.assertTrue(o.zacni(8990, "ab" * 32, id_naprave, "Safeer Control (pisarna)"))
        info, kw = _Zc.primerki[-1].registrirane[-1]
        return o, info, kw

    def test_ime_primerka_iz_id_naprave(self):
        _o, info, kw = self._oglasi(WINDOWS)
        self.assertEqual(info.name, "safeer-05106b98fc1c." + S.STORITEV_MDNS)
        self.assertEqual(info.type, S.STORITEV_MDNS)
        self.assertEqual(info.port, 8990)
        self.assertEqual(info.properties[b"id"], WINDOWS.encode())       # naprave Hub prepoznajo po id-ju
        self.assertEqual(info.properties[b"fp"], ("ab" * 32).encode())
        self.assertEqual(info.properties[b"mesh"], S.MESH.encode())
        self.assertTrue(kw.get("allow_name_change"))

    def test_dva_controla_v_istem_omrezju_ne_trcita(self):
        _a, info_a, _ = self._oglasi(WINDOWS)
        _b, info_b, _ = self._oglasi(LINUX)
        self.assertNotEqual(info_a.name, info_b.name)                     # prej oba »safeer--control«

    def test_neuspeh_se_zapise_in_ne_pusti_odprtega(self):
        _Zc.napaka = RuntimeError("ime je zasedeno")
        o = S.Oglas()
        izpis = io.StringIO()
        with contextlib.redirect_stdout(izpis):
            self.assertFalse(o.zacni(8990, "ab" * 32, WINDOWS, "PC"))
        self.assertIn("oglas mDNS ni uspel", izpis.getvalue())            # prej tiho
        self.assertIn("ime je zasedeno", izpis.getvalue())
        self.assertTrue(_Zc.primerki[-1].zaprt)                           # prej je ostal odprt (nit in vticnice)
        o.koncaj()                                                        # brez napake, ceprav oglasa ni

    def test_ponoven_zacetek_ne_registrira_dvakrat(self):
        o, _info, _ = self._oglasi(WINDOWS)
        self.assertTrue(o.zacni(8990, "ab" * 32, WINDOWS, "PC"))
        self.assertEqual(len(_Zc.primerki), 1)

    def test_konec_odjavi_in_zapre(self):
        o, info, _ = self._oglasi(WINDOWS)
        o.koncaj()
        zc = _Zc.primerki[-1]
        self.assertEqual(zc.odjavljene, [info])
        self.assertTrue(zc.zaprt)

    def test_brez_knjiznice_tiho(self):
        self._zaplata.stop()
        try:
            with mock.patch.dict(sys.modules, {"zeroconf": None}):
                izpis = io.StringIO()
                with contextlib.redirect_stdout(izpis):
                    self.assertFalse(S.Oglas().zacni(8990, "ab" * 32, WINDOWS, "PC"))
                self.assertEqual(izpis.getvalue(), "")
        finally:
            self._zaplata.start()


if __name__ == "__main__":
    unittest.main()
