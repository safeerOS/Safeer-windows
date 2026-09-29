"""Pregled 29. 9. 2026, tocka 12: znizanje pravic naprave takoj preklice njene zetone za datoteke."""
import os
import sys
import tempfile
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from core import link_datoteke  # noqa: E402

try:
    from safeer_windows import control_backend  # noqa: E402
except Exception as e:  # pragma: no cover - na sistemu brez Qt
    control_backend = None
    NAPAKA = e


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class DovoljenjaZetoniTests(unittest.TestCase):
    def setUp(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.nastavitve = {"dovoljenja_naprav": {"tv": "polno"}}
        b.naprave = []
        b._opozorjena_dovoljenja = set()
        b.shrani_nastavitve = lambda: True
        b._oddaj_dogodek = lambda *a, **k: None
        b.stanje_linka = lambda: {}
        self.b = b
        self.polno = link_datoteke.Datoteke(poti=[], tls_mapa=tempfile.mkdtemp(), ves_disk=True)
        self.izbrano = link_datoteke.Datoteke(poti=[], tls_mapa=tempfile.mkdtemp(), ves_disk=False)
        for d, cel in ((self.polno, True), (self.izbrano, False)):
            d.streznik.umaknjena = lambda n, _c=cel: not b._sme_na_streznik(n, _c)
        b._datoteke = {True: self.polno, False: self.izbrano}

    def test_polno_v_izbrano(self):
        zp = self.polno.streznik.zeton_za("tv", zdaj=1.0)
        zi = self.izbrano.streznik.zeton_za("tv", zdaj=1.0)
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "izbrano"))
        self.assertFalse(self.polno.streznik.zeton_velja(zp, zdaj=2.0))
        # izbrane mape sme se naprej, a z novim zetonom (stari je preklican ob znizanju)
        self.assertFalse(self.izbrano.streznik.zeton_velja(zi, zdaj=2.0))
        self.assertTrue(self.izbrano.streznik.zeton_velja(self.izbrano.streznik.zeton_za("tv", zdaj=3.0), zdaj=3.0))

    def test_izbrano_v_zaslon(self):
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "izbrano"
        zi = self.izbrano.streznik.zeton_za("tv", zdaj=1.0)
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "zaslon"))
        self.assertFalse(self.izbrano.streznik.zeton_velja(zi, zdaj=2.0))
        # tudi nov zeton ne velja - profil zaslon nima datotek
        self.assertFalse(self.izbrano.streznik.zeton_velja(self.izbrano.streznik.zeton_za("tv", zdaj=3.0), zdaj=3.0))

    def test_zvisanje_ne_preklice(self):
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "izbrano"
        zi = self.izbrano.streznik.zeton_za("tv", zdaj=1.0)
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "polno"))
        self.assertTrue(self.izbrano.streznik.zeton_velja(zi, zdaj=2.0))


if __name__ == "__main__":
    unittest.main()
