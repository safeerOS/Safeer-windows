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


def _ponaredek_zapisa(t):
    """link_dostop.vsi/jedro/v_ozjem_krogu iz t.zapis (id = jedro): preizkus ne bere pravega dostop.json."""
    return (mock.patch.object(link_dostop, "vsi",
                              side_effect=lambda: {k: link_dostop.v_niz(v) for k, v in t.zapis.items()}),
            mock.patch.object(link_dostop, "jedro", side_effect=lambda n: str(n or "")),
            mock.patch.object(link_dostop, "v_ozjem_krogu",
                              side_effect=lambda n: {"d", "p", "v", "z"} <= set(t.zapis.get(n, ()))))


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
        for p in (p1, p2, p3) + _ponaredek_zapisa(self):
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
class PregledGrok(unittest.TestCase):
    """Pregled Grok 7 (25. 10. 2026): W1 dedovanje po polju device, W3 najbolj omejujoc profil, W4 krog ni berljiv,
    W5 umik ob neuspelem zapisu, W6 uskladitev ob zagonu s trenutnim profilom."""
    TEL = "n-0123456789abcdef"                     # id iz kljuca telefona (prijava s podpisom)

    def setUp(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.nastavitve = {"dovoljenja_naprav": {self.TEL: "polno"}}
        b.naprave = []
        b.device_id = "n-ta"
        b._opozorjena_dovoljenja = set()
        b.shrani_nastavitve = lambda: True
        b._oddaj_dogodek = lambda *a, **k: None
        b.stanje_linka = lambda: {}
        b._datoteke = {}
        self.preklicani = []
        b._preklici_zetone = lambda n: self.preklicani.append(n)
        b.navidezni_zaslon = _Zaslon()
        b.hub_url = lambda: ""
        self.b = b
        self.zapis = {}
        for p in (mock.patch.object(link_dostop, "nastavi",
                                    side_effect=lambda n, d: self.zapis.__setitem__(n, set(d)) or True),
                  mock.patch.object(link_dostop, "zmoznosti", side_effect=lambda n: set(self.zapis.get(n, ()))),
                  mock.patch.object(link_krog, "je_umaknjen", return_value=False),
                  mock.patch.object(control_backend.SafeerControlBackend, "_fizicna_po_krogu",
                                    staticmethod(lambda i: ""))) + _ponaredek_zapisa(self):
            p.start()
            self.addCleanup(p.stop)

    def test_w1_polje_device_ne_podeli_dostopa(self):
        """Tuja naprava, ki ji seznam huba pripise device = telefon, ne podeduje »polno«; ne kot sorodnik."""
        dov = self.b.nastavitve["dovoljenja_naprav"]
        self.assertEqual(self.b._podedovan_profil("n-ffffffffffffffff", self.TEL, dov, []), "")
        self.assertEqual(self.b._podedovan_profil("uuid-tuja", self.TEL, dov, []), "")
        # Druga identiteta istega kljuca (Safeer OS telefona) podeduje - isto jedro id-ja iz kljuca.
        self.assertEqual(self.b._podedovan_profil(self.TEL + "-os", "", dov, []), "polno")
        # Isti kljuc v krogu te naprave (seznanitev) tudi.
        with mock.patch.object(control_backend.SafeerControlBackend, "_fizicna_po_krogu",
                               staticmethod(lambda i: "n-kljuc" if i in (self.TEL, "star-id") else "")):
            self.assertEqual(self.b._podedovan_profil("star-id", "", dov, []), "polno")
        # Seznam huba sme prenesti samo omejitev.
        dov2 = {self.TEL: "brez"}
        self.assertEqual(self.b._podedovan_profil("uuid-tuja", self.TEL, dov2, []), "brez")

    def test_w1_sorodnik_iz_seznama_ne_razsiri_pravic(self):
        self.b.naprave = [{"id": self.TEL, "naprava": "X"}, {"id": "uuid-tuja", "naprava": "X"}]
        self.b.nastavitve["dovoljenja_naprav"]["uuid-tuja"] = "vprasaj"
        self.assertEqual(self.b.dovoljenje_za("uuid-tuja"), "vprasaj")
        self.assertFalse(self.b._dejanje_dovoljeno("uuid-tuja", "key"))
        # Uporabnik da telefonu »polno«: tuja identiteta s poljem naprava ga ne dobi.
        self.assertTrue(self.b.nastavi_dovoljenje(self.TEL, "polno"))
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"]["uuid-tuja"], "vprasaj")
        # Umik pa velja za vse identitete s tem poljem.
        self.assertTrue(self.b.nastavi_dovoljenje(self.TEL, "brez"))
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"]["uuid-tuja"], "brez")

    def test_w3_najbolj_omejujoc(self):
        os_id, tv_id = self.TEL + "-os", self.TEL + "-tv"
        self.b.naprave = [{"id": i, "naprava": "F"} for i in (self.TEL, os_id, tv_id)]
        self.b.nastavitve["dovoljenja_naprav"] = {self.TEL: "brez", os_id: "polno"}
        self.assertEqual(self.b.dovoljenje_za(tv_id), "brez")            # prej je zmagal »polno«
        self.assertEqual(self.b._podedovan_profil(tv_id, "", self.b.nastavitve["dovoljenja_naprav"], []), "brez")

    def test_w4_krog_ni_berljiv(self):
        with mock.patch.object(link_krog, "krog", side_effect=OSError("zaklenjeno")):
            self.assertTrue(self.b._umaknjena_iz_kroga(self.TEL))
            self.assertFalse(self.b._dejanje_dovoljeno(self.TEL, "key"))
            self.assertFalse(self.b._sme_upravljati(self.TEL))
            self.assertTrue(self.b._dejanje_dovoljeno(self.TEL, "host.info"))

    def test_w5_umik_ob_neuspelem_zapisu(self):
        self.zapis[self.TEL] = {"d", "p", "v", "z"}
        self.b.shrani_nastavitve = lambda: False
        self.assertFalse(self.b.nastavi_dovoljenje(self.TEL, "brez"))     # uporabnik izve, da zapis ni uspel
        self.assertIn(self.TEL, self.preklicani)                         # zetoni in seja vseeno takoj
        self.assertIn(self.TEL, self.b.navidezni_zaslon.ustavljeno)
        self.assertEqual(self.zapis[self.TEL], set())
        self.assertEqual(self.b.dovoljenje_za(self.TEL), "brez")
        # Vec pravic brez zapisa ne velja.
        self.assertFalse(self.b.nastavi_dovoljenje(self.TEL, "polno"))
        self.assertEqual(self.b.dovoljenje_za(self.TEL), "brez")

    def test_w6_zagon_s_trenutnim_profilom(self):
        self.b.nastavitve["dovoljenja_naprav"] = {self.TEL: "polno", "tv": "polno"}
        izvirna = self.b._uskladi_ozji_krog
        klici = []

        def uskladi(sorodniki, profil):
            klici.append((tuple(sorodniki), profil))
            if sorodniki == [self.TEL]:
                # Med uskladitvijo uporabnik umakne TV: zagon ne sme zapisati starega »polno«.
                self.b.nastavitve["dovoljenja_naprav"]["tv"] = "brez"
            return izvirna(sorodniki, profil)
        self.b._uskladi_ozji_krog = uskladi
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(klici, [((self.TEL,), "polno"), (("tv",), "brez")])
        self.assertEqual(self.zapis.get("tv", set()), set())          # »polno« iz posnetka ni zapisan

    def test_w2_seja_se_konca_ob_umiku_z_druge_naprave(self):
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "polno"
        self.assertEqual(self.b._preveri_sejo_zaslona("tv"), (True, True))
        with mock.patch.object(link_krog, "je_umaknjen", return_value=True):
            self.assertEqual(self.b._preveri_sejo_zaslona("tv"), (False, False))
        self.assertIn("tv", self.preklicani)
        self.b.nastavitve["dovoljenja_naprav"]["tv"] = "zaslon"
        self.assertEqual(self.b._preveri_sejo_zaslona("tv"), (True, False))


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class OdvzemIzSkupneKode(unittest.TestCase):
    """Safeer-linux eebfe57: core/link_dostop.ob_odvzemu - umik iz kroga ali manj pravic v kateremkoli programu tega
    procesa takoj konca sejo zaslona in zetone naprave na Windows."""

    def setUp(self):
        self.zapis = {}
        for p in _ponaredek_zapisa(self):
            p.start()
            self.addCleanup(p.stop)

    def test_odvzem_konca_sejo_in_zetone(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.shrani_nastavitve = lambda: True
        b._oddaj_dogodek = lambda *a, **k: None
        b.naprave = [{"id": "n-0123456789abcdef"}, {"id": "n-0123456789abcdef-os"}, {"id": "n-ffffffffffffffff"}]
        b.nastavitve = {"dovoljenja_naprav": {"n-0123456789abcdef-control": "polno"}}
        preklicani = []
        b._preklici_zetone = lambda n: preklicani.append(n)
        b.navidezni_zaslon = _Zaslon()
        with mock.patch.object(link_dostop, "jedro", side_effect=lambda n: str(n)[:18]):
            b._ob_odvzemu_dostopa("n-0123456789abcdef")
        pricakovano = ["n-0123456789abcdef", "n-0123456789abcdef-control", "n-0123456789abcdef-os"]
        self.assertEqual(sorted(preklicani), pricakovano)
        self.assertEqual(sorted(b.navidezni_zaslon.ustavljeno), pricakovano)

    def test_prijava_v_skupni_kodi(self):
        vir = open(os.path.join(KOREN, "windows", "safeer_windows", "control_backend.py"), encoding="utf-8").read()
        self.assertIn("link_dostop.ob_odvzemu(self._ob_odvzemu_dostopa)", vir)
        self.assertTrue(hasattr(link_dostop, "ob_odvzemu") and hasattr(link_dostop, "ob_umiku_iz_kroga"))


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class SejaPoUmiku(unittest.TestCase):
    """Grok W2/W10: tekoca seja zaslona preveri dovoljenje (najvec enkrat na sekundo) in se ob umiku konca."""

    def _zaslon(self, izid):
        z = navidezni_zaslon.NavidezniZaslon.__new__(navidezni_zaslon.NavidezniZaslon)
        z._tece, z._seja_st, z._vnos_dovoljen, z._posiljatelj_seje = True, 3, True, "tel"
        import threading
        z._kljuc = threading.RLock()
        self.klici, self.ustavljene = [], []
        z.preveri_sejo = lambda p: self.klici.append(p) or izid
        z.ustavi_sejo = lambda seja=None, posiljatelj=None: self.ustavljene.append(seja)
        return z

    def test_umik_ustavi_sejo_in_vnos(self):
        z = self._zaslon((False, False))
        self.assertFalse(z._seja_dovoljena(3))
        self.assertFalse(z._vnos_dovoljen)
        import time
        for _ in range(50):
            if self.ustavljene:
                break
            time.sleep(0.02)
        self.assertEqual(self.ustavljene, [3])

    def test_preverba_najvec_enkrat_na_sekundo(self):
        z = self._zaslon((True, True))
        for _ in range(100):
            self.assertTrue(z._seja_dovoljena(3))
        self.assertEqual(self.klici, ["tel"])
        self.assertFalse(z._seja_dovoljena(2))                       # stara seja ne velja

    def test_brez_upravljanja_samo_gledanje(self):
        z = self._zaslon((True, False))
        self.assertTrue(z._seja_dovoljena(3))
        self.assertFalse(z._vnos_dovoljen)

    def test_privzeto_brez_vnosa(self):
        import inspect
        self.assertIs(inspect.signature(navidezni_zaslon.NavidezniZaslon.zacni_sejo).parameters["vnos"].default, False)


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


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class PregledGrokX1(unittest.TestCase):
    """Pregled Grok 20, X1 (25. 10. 2026): uskladitev ob zagonu je ob vsakem zagonu iz »polno« Controla zapisala
    d,p,v,z v link_dostop - dostop, vzet drugje (umik iz kroga z druge naprave, drug program, neuspel zapis W5), se je
    vrnil brez nove privolitve. Zdaj razsiri samo enkratna selitev; pozneje velja manj pravic."""
    TEL = "n-0123456789abcdef"
    DPVZ = {"d", "p", "v", "z"}

    def setUp(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.nastavitve = {"dovoljenja_naprav": {self.TEL: "polno"}, control_backend.SELITEV_OZJEGA_KROGA: True}
        b.naprave = [{"id": self.TEL}]
        b._opozorjena_dovoljenja = set()
        self.shranjeno = []
        b.shrani_nastavitve = lambda: self.shranjeno.append(dict(b.nastavitve)) or True
        self.dogodki = []
        b._oddaj_dogodek = lambda *a, **k: self.dogodki.append(a)
        b._datoteke = {}
        self.preklicani = []
        b._preklici_zetone = lambda n: self.preklicani.append(n)
        b.navidezni_zaslon = _Zaslon()
        self.b = b
        self.zapis = {}
        self.umaknjen = False
        for p in (mock.patch.object(link_dostop, "nastavi",
                                    side_effect=lambda n, d: self.zapis.__setitem__(n, set(d)) or True),
                  mock.patch.object(link_dostop, "zmoznosti", side_effect=lambda n: set(self.zapis.get(n, ()))),
                  mock.patch.object(link_krog, "je_umaknjen", side_effect=lambda n: self.umaknjen)) + \
                _ponaredek_zapisa(self):
            p.start()
            self.addCleanup(p.stop)

    def test_zagon_ne_vrne_dostopa_vzetega_drugje(self):
        self.zapis[self.TEL] = set()                    # umik iz kroga na drugi napravi (ob_umiku_iz_kroga)
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], set())
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "brez")
        self.assertEqual(self.b.dovoljenje_za(self.TEL), "brez")
        self.assertIn(self.TEL, self.preklicani)
        self.assertTrue(self.shranjeno)

    def test_po_vrnitvi_v_krog_brez_nove_privolitve_nic(self):
        self.zapis[self.TEL] = set()
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.umaknjen = False                           # naprava je spet v krogu (nova seznanitev)
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], set())
        self.assertFalse(self.b._dejanje_dovoljeno(self.TEL, "files.list"))

    def test_delni_zapis_drugega_programa_ne_razsiri(self):
        self.zapis[self.TEL] = {"p"}                    # drug program je vzel ozji krog, pustil programe
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], {"p"})
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "brez")

    def test_selitev_enkrat_nato_samo_zozuje(self):
        del self.b.nastavitve[control_backend.SELITEV_OZJEGA_KROGA]
        self.b.uskladi_ozji_krog_ob_zagonu()            # izbira iz razlicice, ko Windows link_dostop ni pisal
        self.assertEqual(self.zapis[self.TEL], self.DPVZ)
        self.assertTrue(self.b.nastavitve[control_backend.SELITEV_OZJEGA_KROGA])
        self.assertTrue(self.shranjeno[-1][control_backend.SELITEV_OZJEGA_KROGA])
        self.zapis[self.TEL] = set()                    # nato umik drugje
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], set())

    def test_selitev_ne_vrne_izrecno_vzetega_ali_umaknjene(self):
        del self.b.nastavitve[control_backend.SELITEV_OZJEGA_KROGA]
        self.zapis[self.TEL] = set()
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], set())
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "brez")
        drugi = "n-fedcba9876543210"
        self.b.nastavitve["dovoljenja_naprav"][drugi] = "polno"
        del self.b.nastavitve[control_backend.SELITEV_OZJEGA_KROGA]
        self.umaknjen = True
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertNotIn(drugi, self.zapis)

    def test_zagon_zozi_po_izbiri_controla(self):
        self.b.nastavitve["dovoljenja_naprav"][self.TEL] = "brez"
        self.zapis[self.TEL] = set(self.DPVZ)
        self.b.uskladi_ozji_krog_ob_zagonu()
        self.assertEqual(self.zapis[self.TEL], set())

    def test_odvzem_drugje_zozi_profil_controla(self):
        self.zapis[self.TEL] = set()
        self.b._ob_odvzemu_dostopa(self.TEL)
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "brez")
        self.assertTrue(self.shranjeno)
        self.assertIn(self.TEL, self.b.navidezni_zaslon.ustavljeno)

    def test_odvzem_brez_izgube_ozjega_kroga_profila_ne_spremeni(self):
        self.zapis[self.TEL] = set(self.DPVZ)
        self.b._ob_odvzemu_dostopa(self.TEL)
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "polno")
        self.b.nastavitve["dovoljenja_naprav"][self.TEL] = "zaslon"     # izbira uporabnika ostane
        self.zapis[self.TEL] = set()
        self.b._ob_odvzemu_dostopa(self.TEL)
        self.assertEqual(self.b.nastavitve["dovoljenja_naprav"][self.TEL], "zaslon")
