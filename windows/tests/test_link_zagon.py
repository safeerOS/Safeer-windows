"""Safeer Link ob zagonu Safeer OS za Windows: povezava ne caka na stvari, ki jih ne potrebuje.

Izmerjeno 5. 10. 2026 na testnem racunalniku (casi korakov v dnevniku programa, stirje zagoni): od prvega vprasanja
strani do prijave v Safeer Link 11-18 s, od tega
  - seznanitev lastnega Controla z lastnim Hubom s kodo (SPAKE2 na obeh koncih istega procesa): 2,6-4,8 s,
  - oglas mDNS (uvoz knjiznice in registracija), na katerega je cakal klic znanih sosedov: 2,3-8,1 s,
  - katalog programov z ikonami vseh 128 programov menija Start pred prijavo: prijava je zato trajala 3-5 s.
Povezovanje je sprozila sele nalozena zacetna stran; zastavica »povezujem« se je postavila sele po zagonu Huba.
"""
import inspect
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_hub_streznik
from safeer_windows import control_backend as CB
from safeer_windows import navidezni_zaslon as NZ
from safeer_windows import os_app, os_backend_win

ODTIS = "ab" * 32


def _obvestilo(_ime: str, _koda: str) -> None:
    """Kot link_hub_streznik._obvestilo_kode: nova naprava caka na kodo, racunalnik jo pokaze."""


class _Streznik:
    """Ponaredek HubStreznik: pravi Hub (register naprav, zetoni), brez vticnika."""

    def __init__(self, mapa: str) -> None:
        self.hub = link_hub_streznik.Hub(odtis=ODTIS, pot_zetonov=os.path.join(mapa, "hub-zetoni.json"))
        self.hub.ob_kodi = _obvestilo          # HubStreznik.zazeni naredi isto
        self.vrata = 45678
        self.odtis = ODTIS
        self.datoteke = None
        self._tece = False
        self.ustavljen = False

    def zazeni(self) -> bool:
        self._tece = True
        return True

    def tece(self) -> bool:
        return self._tece

    def ustavi(self) -> None:
        self._tece = False
        self.ustavljen = True


def _backend(td: str) -> "CB.SafeerControlBackend":
    b = CB.SafeerControlBackend(config_pot=os.path.join(td, "link.json"))
    b.nastavitve.clear()
    return b


def _pocakaj(pogoj, najvec: float = 3.0) -> bool:
    konec = time.monotonic() + najvec
    while time.monotonic() < konec:
        if pogoj():
            return True
        time.sleep(0.01)
    return bool(pogoj())


class ZetonLastneNaprave(unittest.TestCase):
    """Hub da napravi, ki ga gosti v istem procesu, zeton brez seznanitve s kodo."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.pot = os.path.join(self._td.name, "hub-zetoni.json")
        self.ura = [1_000_000.0]
        self.hub = link_hub_streznik.Hub(odtis=ODTIS, ura=lambda: self.ura[0], pot_zetonov=self.pot)

    def tearDown(self):
        self._td.cleanup()

    def test_zeton_velja(self):
        z = self.hub.zeton_lastne_naprave("n-0123456789abcdef-control", "Safeer Control (pisarna)")
        self.assertTrue(z and z.startswith("saf_pc_"))
        self.assertEqual(self.hub.naprava_zetona(z), ("n-0123456789abcdef-control", "Safeer Control (pisarna)"))
        self.assertIsNotNone(self.hub.vstopnica_z_zetonom(z))

    def test_brez_id_ni_zetona(self):
        self.assertIsNone(self.hub.zeton_lastne_naprave("", "ime"))
        self.assertIsNone(self.hub.zeton_lastne_naprave("   ", "ime"))

    def test_nov_zamenja_prejsnjega_iste_naprave(self):
        prvi = self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        drugi = self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        self.assertNotEqual(prvi, drugi)
        self.assertIsNone(self.hub.naprava_zetona(prvi))
        self.assertEqual(self.hub.naprava_zetona(drugi)[0], "n-pc-control")

    def test_zagoni_ne_izrinejo_zetonov_drugih_naprav(self):
        # Prej: vsak zagon programa = nova seznanitev = nov zeton; po 32 zagonih je iz shrambe izpadel najstarejsi,
        # torej zeton telefona, ki se je s tem racunalnikom povezal s kodo.
        with self.hub._zaklep:
            self.hub._zetoni["saf_pc_telefon"] = ("n-telefon", "Telefon", self.ura[0])
        for _ in range(link_hub_streznik.NAJVEC_ZETONOV + 8):
            self.ura[0] += 60
            self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        self.assertEqual(self.hub.naprava_zetona("saf_pc_telefon"), ("n-telefon", "Telefon"))
        self.assertEqual(sum(1 for v in self.hub._zetoni.values() if v[0] == "n-pc-control"), 1)

    def test_shramba_ostane_omejena(self):
        with self.hub._zaklep:
            for i in range(link_hub_streznik.NAJVEC_ZETONOV):
                self.hub._zetoni["saf_pc_%d" % i] = ("n-%d" % i, "N", self.ura[0] + i)
        z = self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        self.assertEqual(len(self.hub._zetoni), link_hub_streznik.NAJVEC_ZETONOV)
        self.assertIsNone(self.hub.naprava_zetona("saf_pc_0"))          # najstarejsi je izpadel
        self.assertIsNotNone(self.hub.naprava_zetona(z))

    def test_zapisan_na_disk(self):
        z = self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        with open(self.pot, encoding="utf-8") as d:
            self.assertEqual(json.load(d)[z][:2], ["n-pc-control", "PC"])
        drugi = link_hub_streznik.Hub(odtis=ODTIS, ura=lambda: self.ura[0], pot_zetonov=self.pot)
        self.assertEqual(drugi.naprava_zetona(z), ("n-pc-control", "PC"))

    def test_potece_kot_drugi_zetoni(self):
        z = self.hub.zeton_lastne_naprave("n-pc-control", "PC")
        self.ura[0] += link_hub_streznik.ZETON_VELJA_S + 1
        self.assertIsNone(self.hub.naprava_zetona(z))


class LastniHubBrezKode(unittest.TestCase):
    """Control se na Hub v istem procesu prijavi brez seznanitve s kodo."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.streznik = _Streznik(self._td.name)
        self._zaplate = [
            mock.patch.object(CB.link_hub_streznik, "HubStreznik", lambda *a, **k: self.streznik),
            # Seznanitev s kodo po omrezju (SPAKE2) se ne sme vec zgoditi.
            mock.patch.object(CB.link_hub, "zacni_seznanitev", side_effect=AssertionError("seznanitev s kodo")),
            mock.patch.object(CB.link_hub, "potrdi_kodo", side_effect=AssertionError("seznanitev s kodo")),
        ]
        for z in self._zaplate:
            z.start()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_zeton_brez_seznanitve(self):
        dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: dogodki.append((vrsta, podatki)))
        izid = self.b.zagotovi_lokalni_hub()
        self.assertEqual(izid, {"naslov": "wss://127.0.0.1:45678/cast/ws", "fp": ODTIS, "lokalni": True})
        self.assertEqual(self.b.hub_url(), "wss://127.0.0.1:45678/cast/ws")
        self.assertEqual(self.b.hub_fp(), ODTIS)
        self.assertEqual(self.streznik.hub.naprava_zetona(self.b.zeton())[0], self.b.device_id)
        with open(self.b.config_pot, encoding="utf-8") as d:
            self.assertEqual(json.load(d)["control_token"], self.b.zeton())
        self.assertIn("hub", [v for v, _ in dogodki])

    def test_obvestilo_o_kodi_ostane(self):
        # Prej je lokalna seznanitev Hubu za stalno zamenjala obvestilo o kodi z zbiralnikom: nova naprava, ki se je
        # hotela povezati s kodo, je na tem racunalniku ni vec videla.
        self.b.zagotovi_lokalni_hub()
        self.assertIs(self.streznik.hub.ob_kodi, _obvestilo)

    def test_ponoven_zagon_programa_ne_kopici_zetonov(self):
        self.b.zagotovi_lokalni_hub()
        prvi = self.b.zeton()
        # Nov zagon programa: nov Hub nad isto shrambo zetonov, nov Control.
        self.streznik = _Streznik(self._td.name)
        b2 = _backend(self._td.name)
        b2.zagotovi_lokalni_hub()
        self.assertNotEqual(b2.zeton(), prvi)
        self.assertIsNone(self.streznik.hub.naprava_zetona(prvi))
        self.assertEqual(len(self.streznik.hub._zetoni), 1)

    def test_ze_tece_ne_zamenja_zetona(self):
        self.b.zagotovi_lokalni_hub()
        prvi = self.b.zeton()
        self.assertEqual(self.b.zagotovi_lokalni_hub()["naslov"], "wss://127.0.0.1:45678/cast/ws")
        self.assertEqual(self.b.zeton(), prvi)

    def test_brez_zetona_se_hub_ustavi(self):
        with mock.patch.object(self.streznik.hub, "zeton_lastne_naprave", return_value=None):
            self.assertIsNone(self.b.zagotovi_lokalni_hub())
        self.assertTrue(self.streznik.ustavljen)
        self.assertIsNone(self.b._lokalni_hub)


class _Oglas:
    """Ponaredek oglasa mDNS: registracija traja, dokler je preizkus ne sprosti."""
    primerki = []

    def __init__(self) -> None:
        self.zacet = threading.Event()
        self.sprosti = threading.Event()
        self.registriran = False
        self.koncan = 0
        self.klic = None
        _Oglas.primerki.append(self)

    def zacni(self, vrata, odtis, id_naprave, ime) -> bool:
        self.klic = (vrata, odtis, id_naprave, ime)
        self.zacet.set()
        self.sprosti.wait(5)
        self.registriran = True
        return True

    def koncaj(self) -> None:
        self.koncan += 1
        self.registriran = False


class _Mesh:
    primerki = []

    def __init__(self, hub, nas_id, ime, pot_znanih="", vrata=None) -> None:
        self.hub, self.nas_id, self.pot_znanih = hub, nas_id, pot_znanih
        self.zagnan = False
        self.oglas_ob_zagonu = None
        _Mesh.primerki.append(self)

    def zazeni(self) -> None:
        self.zagnan = True
        # Ali je bil oglas ob zagonu povezovalca ze registriran (prej: da, povezovalec je cakal nanj).
        self.oglas_ob_zagonu = [o.registriran for o in _Oglas.primerki]

    def ustavi(self) -> None:
        self.zagnan = False


class OglasVOzadju(unittest.TestCase):
    """Klic znanih sosedov in prijava Controla ne cakata na oglas mDNS."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.streznik = _Streznik(self._td.name)
        self.streznik.zazeni()
        self.b._lokalni_hub = self.streznik
        _Oglas.primerki.clear()
        _Mesh.primerki.clear()
        self._zaplate = [
            mock.patch.object(CB.link_hub_streznik, "mesh_vklopljen", return_value=True),
            mock.patch("core.link_krog.lahko_s_podpisom", return_value=True),
            mock.patch("core.link_krog._mapa_nastavitev", return_value=self._td.name),
            mock.patch.object(CB.link_hub_streznik, "id_za_oglas", return_value="n-0123456789abcdef-control"),
            mock.patch.object(CB.link_hub_streznik, "Oglas", _Oglas),
            mock.patch("core.link_mesh.MeshPovezovalec", _Mesh),
            mock.patch("safeer_windows.ffmpeg_win.zagotovi_v_ozadju", lambda *a, **k: None),
        ]
        for z in self._zaplate:
            z.start()

    def tearDown(self):
        for o in _Oglas.primerki:
            o.sprosti.set()
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_mesh_ne_caka_na_oglas(self):
        t0 = time.monotonic()
        self.b._zagotovi_mesh()
        self.assertLess(time.monotonic() - t0, 1.5)          # prej: do konca registracije oglasa
        self.assertEqual(len(_Mesh.primerki), 1)
        mesh, oglas = _Mesh.primerki[0], _Oglas.primerki[0]
        self.assertTrue(mesh.zagnan)
        self.assertEqual(mesh.oglas_ob_zagonu, [])            # povezovalec je stekel, preden se je oglas sploh zacel
        self.assertEqual(mesh.nas_id, "n-0123456789abcdef-control")
        self.assertEqual(mesh.pot_znanih, os.path.join(self._td.name, "mesh-sosedje.json"))
        self.assertEqual(self.streznik.hub.nas_id, "n-0123456789abcdef-control")
        self.assertTrue(oglas.zacet.wait(2))
        self.assertFalse(oglas.registriran)
        self.assertEqual(oglas.klic, (45678, ODTIS, "n-0123456789abcdef-control", self.b.device_ime))
        oglas.sprosti.set()
        self.assertTrue(_pocakaj(lambda: oglas.registriran))
        self.assertIs(self.b._oglas, oglas)
        self.assertEqual(oglas.koncan, 0)

    def test_drugi_klic_ne_zazene_drugega_oglasa(self):
        self.b._zagotovi_mesh()
        self.b._zagotovi_mesh()
        self.assertEqual(len(_Mesh.primerki), 1)
        self.assertEqual(len(_Oglas.primerki), 1)

    def test_konec_med_registracijo_ne_pusti_oglasa(self):
        self.b._zagotovi_mesh()
        oglas = _Oglas.primerki[0]
        self.assertTrue(oglas.zacet.wait(2))
        self.b.koncaj()                       # program se zapira, registracija se tece
        self.assertIsNone(self.b._oglas)
        oglas.sprosti.set()
        self.assertTrue(_pocakaj(lambda: oglas.koncan >= 2))      # enkrat koncaj(), enkrat nit po registraciji
        self.assertFalse(oglas.registriran)

    def test_konec_po_registraciji(self):
        self.b._zagotovi_mesh()
        oglas = _Oglas.primerki[0]
        oglas.sprosti.set()
        self.assertTrue(_pocakaj(lambda: oglas.registriran))
        self.b.koncaj()
        self.assertFalse(oglas.registriran)
        self.assertEqual(oglas.koncan, 1)


class KatalogBrezIkon(unittest.TestCase):
    """Prijava v Safeer Link poslje imena in vrste programov; ikon zanjo ne rise."""

    def setUp(self):
        self.risanj = 0
        self.pregledov = []

        def ikona(pot, ime=""):
            self.risanj += 1
            return "data:image/png;base64,AAAA"

        pravi = os_backend_win.poisci_start_menu_programe

        def pregled(z_ikonami=True):
            self.pregledov.append(z_ikonami)
            return pravi(z_ikonami=z_ikonami)

        self._zaplate = [
            mock.patch.object(os_backend_win, "pridobi_ikono_programa", ikona),
            mock.patch.object(os_backend_win, "poisci_start_menu_programe", pregled),
        ]
        for z in self._zaplate:
            z.start()
        self.zaslon = NZ.NavidezniZaslon()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()

    def test_pregled_brez_ikon_ima_iste_programe(self):
        polni = os_backend_win.poisci_start_menu_programe()
        self.assertGreaterEqual(len(polni), 7)                # vsaj sistemska orodja
        self.assertEqual(self.risanj, len(polni))
        self.risanj = 0
        brez = os_backend_win.poisci_start_menu_programe(z_ikonami=False)
        self.assertEqual(self.risanj, 0)
        kljuci = ("id", "ime", "skupina", "pot", "opis")
        self.assertEqual([[p[k] for k in kljuci] for p in brez], [[p[k] for k in kljuci] for p in polni])
        self.assertTrue(all(p["ikona"] == "" for p in brez))
        self.assertTrue(all(p["ikona"] for p in polni))

    def test_katalog_za_prijavo_ne_rise_ikon(self):
        kat = self.zaslon.katalog_aplikacij()
        self.assertEqual(self.risanj, 0)                      # prej: ikona za vsak program menija Start
        self.assertEqual(self.pregledov, [False])
        self.assertIn("app_brskalnik", kat)
        self.assertGreaterEqual(len(kat), 8)
        self.assertTrue(all(set(v) == {"name", "kind"} for v in kat.values()))

    def test_katalog_je_enak_kot_s_polnim_seznamom(self):
        brez_ikon = self.zaslon.katalog_aplikacij()
        self.zaslon.seznam_programov_za_daljinec()            # poln seznam (z ikonami) napolni predpomnilnik
        self.assertGreater(self.risanj, 0)
        s_polnim = self.zaslon.katalog_aplikacij()
        self.assertEqual(s_polnim, brez_ikon)
        self.assertEqual(list(s_polnim), list(brez_ikon))     # tudi vrstni red (katalog je omejen na 200)

    def test_katalog_ne_nadomesti_polnega_seznama(self):
        self.zaslon.katalog_aplikacij()
        self.assertEqual(self.zaslon._sistemski_programi, [])
        seznam = self.zaslon.seznam_programov_za_daljinec()
        self.assertGreater(self.risanj, 0)
        self.assertGreaterEqual(len(seznam["apps"]), 7)
        self.assertTrue(all(a["icon"] for a in seznam["apps"]))

    def test_svez_poln_seznam_se_uporabi_brez_novega_pregleda(self):
        self.zaslon.seznam_programov_za_daljinec()
        self.pregledov.clear()
        self.zaslon.katalog_aplikacij()
        self.assertEqual(self.pregledov, [])


class EnoPovezovanje(unittest.TestCase):
    """Povezovanje tece naenkrat enkrat in se zacne ob zagonu programa."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_hkratna_klica_zazeneta_hub_enkrat(self):
        vstopov = []
        sprosti = threading.Event()

        def pocasen_zagon():
            # Zagon lastnega Huba traja; zastavica »povezujem« mora veljati ze med njim.
            vstopov.append(self.b._povezovanje)
            sprosti.wait(5)

        with mock.patch.object(self.b, "_zagotovi_mesh", pocasen_zagon):
            niti = [threading.Thread(target=self.b.povezi_se, daemon=True) for _ in range(4)]
            for n in niti:
                n.start()
            self.assertTrue(_pocakaj(lambda: len(vstopov) >= 1))
            time.sleep(0.15)
            self.assertEqual(vstopov, [True])                 # prej: vsi klici so zagnali Hub, zastavica False
            sprosti.set()
            for n in niti:
                n.join(3)
        self.assertFalse(self.b._povezovanje)

    def test_zastavica_se_sprosti_tudi_ob_napaki(self):
        with mock.patch.object(self.b, "_povezi_se", side_effect=RuntimeError("napaka")):
            with self.assertRaises(RuntimeError):
                self.b.povezi_se()
        self.assertFalse(self.b._povezovanje)

    def test_ob_zagonu_se_povezan_racunalnik_poveze_sam(self):
        klici = []
        self.b.nastavitve.update({"control_token": "saf_pc_x", "hub_url": "wss://127.0.0.1:8990/cast/ws"})
        with mock.patch.object(self.b, "povezi_se", lambda: klici.append(threading.current_thread().name)):
            self.assertTrue(self.b.povezi_ob_zagonu())
            self.assertTrue(_pocakaj(lambda: klici))
        self.assertEqual(klici, ["safeer-link-zagon"])        # v svoji niti, ne v niti klicatelja

    def test_ob_zagonu_se_nepovezan_racunalnik_ne_povezuje(self):
        with mock.patch.object(self.b, "povezi_se", side_effect=AssertionError("ne sme")):
            self.assertFalse(self.b.povezi_ob_zagonu())
            time.sleep(0.1)

    def test_ob_zagonu_v_ozadju_kot_prej_brez_pogoja(self):
        klici = []
        with mock.patch.object(self.b, "povezi_se", lambda: klici.append(1)):
            self.assertTrue(self.b.povezi_ob_zagonu(vedno=True))
            self.assertTrue(_pocakaj(lambda: klici))

    def test_ob_zagonu_ne_podvoji_povezovanja(self):
        self.b.nastavitve.update({"control_token": "saf_pc_x", "hub_url": "wss://127.0.0.1:8990/cast/ws"})
        self.b._povezovanje = True
        with mock.patch.object(self.b, "povezi_se", side_effect=AssertionError("ne sme")):
            self.assertFalse(self.b.povezi_ob_zagonu())
            time.sleep(0.1)

    def test_program_ob_zagonu_ne_caka_na_povezavo(self):
        vir = inspect.getsource(os_app.main)
        self.assertIn("control_backend.povezi_ob_zagonu(", vir)
        # V glavni niti (pred zanko dogodkov) se ne povezujemo vec.
        self.assertNotIn("control_backend.povezi_se()", vir)


if __name__ == "__main__":
    unittest.main()
