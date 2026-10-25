"""Ozji krog na Windows (lastnik, 25. 10. 2026 10:49): ena privolitev v Linku = upravljanje in vnos.

»Ce uporabnik omogoci Safeer Link, se omogoci Safeer Control za naprave, ki jih uporabnik da v ozji krog, in hkrati
tudi Safeer Vnos.« Na Windows: profil »Vse« (polno) = upravljanje tega racunalnika z misko in tipkovnico (SendInput v
seji zaslona) brez dodatnega stikala, zapisano tudi v core/link_dostop. »Samo ogled zaslona« je res samo ogled (prej je
seja dovolila vnos). »Brez dostopa« (umik iz ozjega kroga) takoj preklice zetone in konca sejo zaslona; umik iz kroga
zaupanja (core/link_krog) zavrne vse razen pomoci pri povezavi.
"""
import os
import sys
import unittest
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from core import link_dostop, link_krog  # noqa: E402

try:
    from safeer_windows import control_backend, navidezni_zaslon  # noqa: E402
except Exception as e:  # pragma: no cover - na sistemu brez Qt
    control_backend = None
    NAPAKA = e


class _Zaslon:
    def __init__(self):
        self.ustavljeno = []
        self.seje = []

    def ustavi_sejo(self, seja=None, posiljatelj=None):
        self.ustavljeno.append(posiljatelj)

    def zacni_sejo(self, posiljatelj, kakovost="najvisja", vnos=True):
        self.seje.append((posiljatelj, vnos))
        return {"port": 1, "fp": "ab", "token": "z", "v": 2}


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class OzjiKrog(unittest.TestCase):
    def setUp(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.nastavitve = {"dovoljenja_naprav": {"tv": "vprasaj"}}
        b.naprave = [{"id": "tv", "ime": "Televizor"}]
        b._opozorjena_dovoljenja = set()
        b.shrani_nastavitve = lambda: True
        self.dogodki = []
        b._oddaj_dogodek = lambda *a, **k: self.dogodki.append(a)
        b.stanje_linka = lambda: {}
        b._datoteke = {}
        self.preklicani = []
        b._preklici_zetone = lambda n: self.preklicani.append(n)
        b.navidezni_zaslon = _Zaslon()
        self.b = b
        self.zapis = {}
        p1 = mock.patch.object(link_dostop, "nastavi",
                               side_effect=lambda n, d: self.zapis.__setitem__(n, set(d)) or True)
        p2 = mock.patch.object(link_dostop, "zmoznosti", side_effect=lambda n: set(self.zapis.get(n, ())))
        p3 = mock.patch.object(link_krog, "je_umaknjen", return_value=False)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def test_vse_je_ozji_krog_z_upravljanjem_in_vnosom(self):
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "polno"))
        self.assertEqual(self.zapis["tv"], {"d", "p", "v", "z"})        # ena privolitev: tudi core/link_dostop
        for akcija in ("screen.start", "key", "mouse.click", "apps.launch", "files.list"):
            self.assertTrue(self.b._dejanje_dovoljeno("tv", akcija), akcija)

    def test_skupno_pravilo_linuxa(self):
        """Ozji krog je skupna koda (core/link_dostop.ozji_krog, Safeer-linux a26daa2): vsaka privolitev da tudi
        upravljanje in Safeer Vnos (z) in mape (d)."""
        self.assertEqual(link_dostop.ozji_krog({"p"}), {"p", "d", "z"})
        self.assertEqual(link_dostop.ozji_krog(set()), set())
        izvor = open(os.path.join(KOREN, "assets", "os", "os.js"), encoding="utf-8").read()
        self.assertIn('[["polno", t("dovoliVse")], ["brez", t("dovoliBrez")]]', izvor)   # Linux nima »samo mape/ogled«

    def test_samo_ogled_zaslona_brez_vnosa(self):
        """Profil iz prejsnjih razlicic (vmesnik ga ne ponuja vec): ostane omejena pravica ZUNAJ ozjega kroga."""
        self.zapis["tv"] = {"d", "p", "v", "z"}                     # podedovano iz starega kroga
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "zaslon"))
        self.assertEqual(self.zapis["tv"], set())
        self.assertTrue(self.b._dejanje_dovoljeno("tv", "screen.start"))
        for akcija in ("key", "mouse.click", "touch", "apps.launch", "files.list"):
            self.assertFalse(self.b._dejanje_dovoljeno("tv", akcija), akcija)

    def test_umik_iz_ozjega_kroga_takoj_preklice_vse(self):
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "polno"
        self.zapis["tv"] = {"d", "p", "v", "z"}
        self.assertTrue(self.b.nastavi_dovoljenje("tv", "brez"))
        self.assertEqual(self.b.dovoljenje_za("tv"), "brez")
        self.assertEqual(self.zapis["tv"], set())
        self.assertIn("tv", self.preklicani)                          # zetoni datotek takoj
        self.assertIn("tv", self.b.navidezni_zaslon.ustavljeno)       # seja zaslona (upravljanje) takoj
        self.assertFalse(self.b._dejanje_dovoljeno("tv", "screen.start"))
        self.assertTrue(self.b._dejanje_dovoljeno("tv", "host.info"))  # pomoc pri povezavi ostane
        # Umaknjene naprave ne sprasujemo znova za dovoljenje.
        self.dogodki.clear()
        odgovori = []
        self.b._odgovori_na_ukaz = lambda *a: odgovori.append(a)
        self.b._obdelaj_nadzorni_ukaz({"sender": "tv", "id": "1", "payload": {"action": "screen.start"}})
        self.assertFalse([d for d in self.dogodki if d and d[0] == "dovoljenjeZahtevano"])
        self.assertFalse(odgovori[-1][3]["ok"])
        self.assertEqual(odgovori[-1][3]["code"], "ni_v_ozjem_krogu")

    def test_umik_iz_kroga_zaupanja(self):
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "polno"
        with mock.patch.object(link_krog, "je_umaknjen", return_value=True):
            self.assertFalse(self.b._dejanje_dovoljeno("tv", "screen.start"))
            self.assertFalse(self.b._dejanje_dovoljeno("tv", "files.list"))
            self.assertTrue(self.b._dejanje_dovoljeno("tv", "host.info"))

    def test_zagon_uskladi_prejsnje_izbire(self):
        self.b.nastavitve["dovoljenja_naprav"] = {"tv": "polno", "tel": "zaslon", "nov": "vprasaj"}
        self.zapis["tel"] = {"d", "p", "v", "z"}                     # podedovano, uporabnik pa je izbral ogled
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis, {"tv": {"d", "p", "v", "z"}, "tel": set()})

    def test_seja_zaslona_po_profilu(self):
        odgovori = []
        self.b._odgovori_na_ukaz = lambda *a: odgovori.append(a)
        self.b._lastni_naslovi = lambda: []
        for profil, vnos in (("polno", True), ("zaslon", False)):
            self.b.nastavitve["dovoljenja_naprav"]["tv"] = profil
            self.b._obdelaj_nadzorni_ukaz({"sender": "tv", "id": profil, "payload": {"action": "screen.start"}})
            self.assertEqual(self.b.navidezni_zaslon.seje[-1], ("tv", vnos), profil)


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class VnosSeje(unittest.TestCase):
    def _beri(self, dovoljen):
        z = navidezni_zaslon.NavidezniZaslon.__new__(navidezni_zaslon.NavidezniZaslon)
        z._tece, z._seja_st, z._vnos_dovoljen = True, 1, dovoljen
        izvedeno, obdelano = [], []
        z.obdelaj_vnosni_dogodek = lambda d: obdelano.append(d)

        class Vnos:
            def izvedi(self, d):
                izvedeno.append(d)
                return True

        class Odjemalec:
            def __init__(self):
                self.kosi = [b'{"vrsta": "tocka", "x": 1, "y": 2}\n{"vrsta": "gumb", "gumb": "levi", "dol": true}\n']

            def recv(self, _n):
                return self.kosi.pop(0) if self.kosi else b""
        z._beri_povratni_vnos(Odjemalec(), Vnos(), 1)
        return izvedeno, obdelano

    def test_samo_ogled_ne_seze_do_miske(self):
        self.assertEqual(self._beri(False), ([], []))
        izvedeno, _ = self._beri(True)
        self.assertEqual(len(izvedeno), 2)


if __name__ == "__main__":
    unittest.main()
