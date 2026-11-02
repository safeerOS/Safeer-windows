"""secrets.sync: vir Medijskega centra (core/uskladitev_kljucev_mediji.VirMedijev) s pravim core/debrid.Debrid in
dejanje `secrets.sync` v link_daljinec. Brez omrezja (preverba storitve je nadomescena)."""
import json
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import debrid, debrid_pravila as DP, link_daljinec, skrivni_dodatki  # noqa: E402
from core import uskladitev_kljucev, uskladitev_kljucev_pravila as P  # noqa: E402
from core.uskladitev_kljucev_mediji import VirMedijev  # noqa: E402
from core.uskladitev_kljucev_pravila import Zapis  # noqa: E402

TB = "0123456789ABCDEF0123456789ABCDEF01234567"


class LazniMc:
    def __init__(self):
        self.nastavitve = {}
        self.debrid = debrid.Debrid(lambda: json.loads(json.dumps(self.nastavitve)), self._pisi,
                                    lambda s: "enc:" + s, lambda s: s[4:] if s.startswith("enc:") else "")
        self._lock = threading.Lock()
        self.data = {"osebni_strezniki": []}

    def _pisi(self, d):
        self.nastavitve = d

    def _load(self):
        return self.data

    def _odkleni_dodatek(self, osnova):
        return None

    def remove_source(self, ident):
        self.data["osebni_strezniki"] = [s for s in self.data["osebni_strezniki"] if s.get("id") != ident]
        return True


class Vir(unittest.TestCase):
    def setUp(self):
        self.mc = LazniMc()
        self.vir = VirMedijev(lambda: self.mc)

    def test_samo_potrjen_kljuc_gre_z_vrednostjo(self):
        self.assertEqual(self.vir.trenutne(), ({}, set()))
        self.mc.debrid.nastavi_kljuc(DP.TORBOX, TB)                       # nepreverjen
        self.assertEqual(self.vir.trenutne(), ({}, {P.kljuc_debrid(DP.TORBOX)}))
        self.mc.debrid.nastavi_kljuc(DP.TORBOX, TB, stanje=DP.STANJE_VELJA)
        vr, nez = self.vir.trenutne()
        self.assertEqual(vr, {P.kljuc_debrid(DP.TORBOX): DP.ocisti_kljuc(TB)})
        self.assertEqual(nez, set())

    def test_prejet_kljuc_se_preveri_s_te_naprave(self):
        z = Zapis(P.kljuc_debrid(DP.TORBOX), 5, "n-tel", False, TB)
        self.assertTrue(self.vir.veljavna_vrednost(z.kljuc, z.vrednost))
        with mock.patch.object(debrid, "preveri_kljuc", return_value=(DP.PREVERBA_VELJAVEN, None)):
            shrani = self.vir.pripravi(z)
        self.assertIsNotNone(shrani)
        self.assertTrue(shrani())
        self.assertTrue(self.mc.debrid.kljuc_velja(DP.TORBOX))
        # Zavrnjen pri storitvi: ne shrani (ne prepise veljavnega).
        with mock.patch.object(debrid, "preveri_kljuc", return_value=("ne_velja", None)):
            self.assertIsNone(self.vir.pripravi(Zapis(z.kljuc, 6, "n-tel", False, "F" * 40)))
        self.assertEqual(self.mc.debrid.kljuc(DP.TORBOX), DP.ocisti_kljuc(TB))
        # Grob izbrise.
        self.assertTrue(self.vir.pripravi(Zapis(z.kljuc, 7, "n-tel", True, ""))())
        self.assertIsNone(self.mc.debrid.kljuc(DP.TORBOX))

    def test_neznani_kljuci_se_prezrejo(self):
        for k in ("usenet_ponudnik", "iptv:0123456789abcdef", "zaupanje:n-aaaaaaaaaaaaaaaa", "geslo"):
            self.assertFalse(self.vir.veljavna_vrednost(k, '{"x":1}'), k)
        self.assertFalse(self.vir.veljavna_vrednost(P.kljuc_debrid(DP.TORBOX), "x"), "oblika kljuca")
        self.assertFalse(self.vir.veljavna_vrednost(P.KLJUC_USENET, "ni json"))
        self.assertFalse(self.vir.veljavna_vrednost(P.kljuc_dodatka("0123456789abcdef"), "https://primer.test/manifest.json"))

    def test_dodatek_odtis_mora_ujemati(self):
        pravi = "https://webtor.io/token/Ab12Cd34Ef56Gh78Ij90Kl/stremio/manifest.json"   # skupni primer webtor-rezerva
        predpona = skrivni_dodatki.skrivna_predpona_dodatka(pravi)
        if predpona is None or not skrivni_dodatki.veljaven_skrivni_dodatek(pravi):
            self.skipTest("primer ni skrivni dodatek po core/skrivni_dodatki")
        self.assertTrue(self.vir.veljavna_vrednost(P.kljuc_dodatka(skrivni_dodatki.odtis(predpona)), pravi))
        self.assertFalse(self.vir.veljavna_vrednost(P.kljuc_dodatka("0" * 16), pravi), "tuj odtis")

    def test_indeksator(self):
        self.mc.debrid.nastavi_indeksator("https://idx.primer.test", "0123456789abcdef0123456789abcdef", DP.STANJE_VELJA)
        vr, _ = self.vir.trenutne()
        self.assertEqual(json.loads(vr[P.KLJUC_USENET])["key"], "0123456789abcdef0123456789abcdef")
        self.assertTrue(self.vir.veljavna_vrednost(P.KLJUC_USENET, vr[P.KLJUC_USENET]))


class Dejanje(unittest.TestCase):
    def tearDown(self):
        uskladitev_kljucev.nastavi(None)

    def test_brez_storitve_neznano(self):
        izidi = []
        link_daljinec.izvedi_control("secrets.sync", {"v": 1, "items": []}, lambda _u: None, izidi.append,
                                     posiljatelj="n-tel", zascita="n-tel")
        self.assertEqual(izidi[0].get("code"), "neznano_dejanje")

    def test_storitev_dobi_posiljatelja_in_zascito(self):
        klici = []
        dogodek = threading.Event()

        class S:
            def prejmi(self, od, ime, parametri, zascita=""):
                klici.append((od, parametri, zascita))
                return {"accepted": False, "pending": True}
        uskladitev_kljucev.nastavi(S())

        def koncaj(izid):
            klici.append(izid)
            dogodek.set()
        link_daljinec.izvedi_control("secrets.sync", {"v": 1, "items": []}, lambda _u: None, koncaj,
                                     posiljatelj="n-tel", zascita="jedro-tel")
        self.assertTrue(dogodek.wait(3))
        self.assertEqual(klici[0], ("n-tel", {"v": 1, "items": []}, "jedro-tel"))
        self.assertTrue(klici[1]["ok"])
        self.assertEqual(klici[1]["data"], {"accepted": False, "pending": True})


if __name__ == "__main__":
    unittest.main()
