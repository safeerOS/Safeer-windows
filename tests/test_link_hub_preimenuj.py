"""»Preimenuj napravo« prek sredisca na racunalniku (POST /cast/devices/rename).

Ime naprave zivi v krogu zaupanja in ga vidijo vse naprave. Do 2.1.45 sredisce na racunalniku te poti ni imelo (404),
Safeer Control pa je zahteval zeton seznanitve, ki ga racunalnik kot lastno sredisce nima."""
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from core import link_hub_streznik, link_kripto, link_krog

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Preizkus z oznako bere Safeer Control za Linux; v repozitoriju Safeer OS za Windows (isto jedro) ga ni.
JE_CONTROL_ZA_LINUX = os.path.isfile(os.path.join(KOREN, "safeer_control.py"))


def _javni(mapa: str, ime: str) -> str:
    """Javni kljuc nove naprave (SPKI DER v base64): s knjiznico jedra, kot program - tudi brez programa openssl."""
    pot = os.path.join(mapa, ime + ".pem")
    link_kripto.ustvari_kljuc_in_potrdilo(pot, os.path.join(mapa, ime + "-potrdilo.pem"), ime)
    return base64.b64encode(link_kripto.javni_kljuc_der(pot)).decode("ascii")


class LaznaPovezava:
    def __init__(self):
        self.poslano = []

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))
        return True

    def zapri(self, *_a, **_k):
        pass

    def zadnji(self, tip):
        return next((s for s in reversed(self.poslano) if s.get("type") == tip), None)


def _prijava(id_naprave, ime):
    return json.dumps({"id": "r1", "type": "cast.register",
                       "payload": {"device_id": id_naprave, "name": ime, "role": "receiver", "capabilities": ["url"],
                                   "platform": "tv", "protocol": "1", "kind": "tv", "version": "2.1.169"}})


class Preimenovanje(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-preimenuj-")
        self.addCleanup(shutil.rmtree, self.mapa, ignore_errors=True)
        self.k_tv, self.k_pc = _javni(self.mapa, "tv"), _javni(self.mapa, "pc")
        self.tv = link_krog.id_iz_kljuca(self.k_tv)
        self.pc = link_krog.id_iz_kljuca(self.k_pc)
        self.krog = link_krog.Krog()
        self.krog.dodaj(self.tv, self.k_tv, "Android TV", "tv", self.tv, dodano=100.0)
        self.krog.dodaj(self.pc, self.k_pc, "Racunalnik", "linux", self.tv, dodano=101.0)
        self.krog.dodaj(self.pc + "-control", self.k_pc, "Safeer Control (pc)", "linux", self.tv, dodano=102.0)
        p = mock.patch.object(link_krog, "krog", return_value=self.krog)
        p.start()
        self.addCleanup(p.stop)
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id=self.pc)
        self.hub._zetoni["zeton"] = (self.pc + "-control", "Safeer Control (pc)", time.time())
        self.zaslon = LaznaPovezava()
        self.hub.obdelaj(self.zaslon, _prijava(self.tv, "Android TV"))

    def test_ime_gre_v_krog_in_k_napravam(self):
        koda, odgovor = self.hub.preimenuj_napravo("zeton", self.tv, "  Dnevna soba ")
        self.assertEqual((koda, odgovor), (200, {"id": self.tv, "name": "Dnevna soba"}))
        self.assertEqual(self.krog.clan(self.tv)["ime"], "Dnevna soba")
        self.assertGreater(self.krog.json()["clani"][self.tv]["imenovano"], 0)
        seznam = self.zaslon.zadnji("cast.devices")
        self.assertEqual([(d["name"], d["own_name"]) for d in seznam["devices"]], [("Dnevna soba", "Android TV")])
        self.assertIsNotNone(self.zaslon.zadnji("trust.update"), "krog z novim imenom dobijo povezane naprave")

    def test_vsi_clani_z_istim_kljucem(self):
        self.assertEqual(self.hub.preimenuj_napravo("zeton", self.pc + "-control", "Pisarna")[0], 200)
        self.assertEqual((self.krog.clan(self.pc)["ime"], self.krog.clan(self.pc + "-control")["ime"]), ("Pisarna", "Pisarna"))
        self.assertEqual(self.krog.clan(self.tv)["ime"], "Android TV", "druge naprave ostanejo")

    def test_prazno_ime_vrne_lastno(self):
        self.hub.preimenuj_napravo("zeton", self.tv, "Dnevna soba")
        koda, odgovor = self.hub.preimenuj_napravo("zeton", self.tv, "")
        self.assertEqual((koda, odgovor["name"]), (200, "Android TV"), "ime, ki ga naprava pove o sebi")

    def test_novejse_ime_zmaga_tudi_ob_zamaknjeni_uri(self):
        self.krog.preimenuj(self.tv, "Iz prihodnosti", ob=4_000_000_000.0)
        self.assertEqual(self.hub.preimenuj_napravo("zeton", self.tv, "Spalnica")[1]["name"], "Spalnica")
        self.assertGreater(self.krog.json()["clani"][self.tv]["imenovano"], 4_000_000_000.0)

    def test_zavrnitve(self):
        self.assertEqual(self.hub.preimenuj_napravo("napacen", self.tv, "x")[0], 401)
        self.assertEqual(self.hub.preimenuj_napravo("zeton", "", "x")[1]["koda"], "manjka_device_id")
        koda, odgovor = self.hub.preimenuj_napravo("zeton", "n-0000000000000000", "x")
        self.assertEqual((koda, odgovor["koda"]), (404, "naprava_ni_v_krogu"))
        self.assertEqual(self.krog.clan(self.tv)["ime"], "Android TV")

    def test_ime_je_ocisceno_in_omejeno(self):
        ime = self.hub.preimenuj_napravo("zeton", self.tv, "<b>Soba\x07</b>" + "a" * 200)[1]["name"]
        self.assertNotIn("<", ime)
        self.assertNotIn("\x07", ime)
        self.assertLessEqual(len(ime), link_hub_streznik.NAJVEC_IMENA)

    def test_pot_obstaja(self):
        with open(os.path.join(KOREN, "core", "link_hub_streznik.py"), encoding="utf-8") as f:
            hub = f.read()
        self.assertIn("if pot == POT_PREIMENUJ:", hub)
        self.assertEqual(link_hub_streznik.POT_PREIMENUJ, "/cast/devices/rename")

    @unittest.skipUnless(JE_CONTROL_ZA_LINUX, "Safeer Control za Linux")
    def test_control_uporablja_zeton_za_http(self):
        with open(os.path.join(KOREN, "safeer_control.py"), encoding="utf-8") as f:
            control = f.read()
        blok = control[control.index('if metoda == "Preimenuj":'):control.index('if metoda == "Upravljaj":')]
        self.assertIn("link._zeton_http()", blok)
        self.assertNotIn("link._zeton()", blok)


class PreimenovanjeVZivo(unittest.TestCase):
    """Cela zica cez TLS z isto funkcijo, kot jo klice Safeer Control (link_deljenje.preimenuj_napravo)."""

    def test_control_preimenuje_napravo_s_sejo_iz_podpisa(self):
        from core import link_deljenje, link_hub
        streznik = link_hub_streznik.HubStreznik()
        if not streznik.zazeni():
            self.skipTest("huba ni bilo mogoce zagnati")
        self.addCleanup(streznik.ustavi)
        naslov = "wss://127.0.0.1:%d%s" % (streznik.vrata, link_hub_streznik.POT_WS)
        jaz = link_krog.id_iz_kljuca(link_krog.javni_kljuc_b64())
        mapa = tempfile.mkdtemp(prefix="safeer-preimenuj-")
        self.addCleanup(shutil.rmtree, mapa, ignore_errors=True)
        k_tv = _javni(mapa, "tv")
        tv = link_krog.id_iz_kljuca(k_tv)
        krog = link_krog.Krog()
        krog.dodaj(jaz, link_krog.javni_kljuc_b64(), "Racunalnik", "linux", jaz, dodano=100.0)
        krog.dodaj(tv, k_tv, "Android TV", "tv", jaz, dodano=101.0)
        with mock.patch.object(link_krog, "krog", return_value=krog):
            seja = link_hub.seja_s_podpisom(naslov, jaz, streznik.odtis, "Racunalnik")
            self.assertTrue(seja)
            ok, ime, napaka = link_deljenje.preimenuj_napravo(naslov, seja, streznik.odtis, tv, "Dnevna soba")
            self.assertEqual((ok, ime, napaka), (True, "Dnevna soba", {}))
            self.assertEqual(krog.clan(tv)["ime"], "Dnevna soba")
            ok, _ime, napaka = link_deljenje.preimenuj_napravo(naslov, "napacen-zeton", streznik.odtis, tv, "X")
            self.assertEqual((ok, napaka["koda"]), (False, "naprava_ni_seznanjena"))
            self.assertEqual(krog.clan(tv)["ime"], "Dnevna soba")
            koda, _ = link_hub._zahteva(link_hub._osnova(naslov) + link_hub_streznik.POT_PREIMENUJ, None, odtis=streznik.odtis)
            self.assertEqual(koda, 405, "GET pove, da pot obstaja")


if __name__ == "__main__":
    unittest.main()
