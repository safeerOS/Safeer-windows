"""Varovalka kode za povezavo (core/link_varovalka.py): skupna omejitev ugibanja 6-mestne kode.

Prvi del je cista logika z lazno uro. Drugi del je sredisce (Hub) s pravim SPAKE2: napadalec, ki ostane pod pragom
obrambe po viru in menja naslove, je vseeno ustavljen; domace povezovanje ne steje; vabilo zaupane naprave odpre
povezovanje tudi med zaporo. Tretji del je pravo sredisce na zanki (TLS, HTTP).
"""
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from core import link_hub, link_hub_streznik, link_krog, link_tls, link_varovalka
from core.link_varovalka import VarovalkaKode
from core.spake2 import Spake2

A, B, C, D = "192.168.0.66", "192.168.0.67", "192.168.0.68", "192.168.0.69"
URA, DAN = 3600.0, 86400.0


class Ura:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Pravila(unittest.TestCase):
    def setUp(self):
        self.ura = Ura()
        self.zapore, self.shranjeno = [], []
        self.v = VarovalkaKode(ura=self.ura, ob_zapori=self.zapore.append, shrani=self.shranjeno.append)

    def _zapri(self, v=None):
        v = v or self.v
        for _ in range(200):
            if v.zaprto():
                return
            v.poskus(A)
        self.fail("povezovanje s kodo se ni zaprlo")

    def test_dvajseti_poskus_zapre_za_eno_uro(self):
        for i in range(19):
            self.assertTrue(self.v.poskus(A if i % 3 else B), i)
        self.assertFalse(self.v.zaprto())
        self.assertEqual(self.zapore, [])
        self.assertFalse(self.v.poskus(C), "dvajsetega poskusa sredisce ne izvede")
        self.assertTrue(self.v.zaprto())
        self.assertEqual(len(self.zapore), 1)
        dogodek = self.zapore[0]
        self.assertEqual((dogodek["trajanje_s"], dogodek["razlog"], dogodek["ponovitev"]), (URA, "kode", 1))
        # Najpogostejsi vir je prvi: A 12, B 7, C 1.
        self.assertEqual(dogodek["viri"], [(A, 12), (B, 7), (C, 1)])
        stanje = self.v.stanje()
        self.assertEqual((stanje["zaprto"], stanje["se_s"], stanje["kredit"]), (True, 3600, link_varovalka.KREDIT_VABILA))
        self.assertFalse(self.v.sme_zaceti())
        self.assertFalse(self.v.zacetek(D))
        self.assertFalse(self.v.poskus(D))
        self.assertEqual(len(self.zapore), 1, "med zaporo ni novih dogodkov")

    def test_poskusi_starejsi_od_ure_ne_stejejo(self):
        for _ in range(19):
            self.assertTrue(self.v.poskus(A))
        self.ura.t += URA + 1
        for _ in range(19):
            self.assertTrue(self.v.poskus(A))
        self.assertEqual(self.zapore, [])
        self.assertEqual(self.v.stanje()["poskusov"], 19)

    def test_pocasen_napadalec_z_vec_naslovi_je_ustavljen(self):
        """Pet kod na minuto na naslov je pod pragom obrambe po viru; skupna meja ga vseeno ustavi."""
        izvedenih = 0
        for minuta in range(60):
            self.ura.t += 61
            for vir in (A, B, C, D):
                if self.v.zacetek(vir):
                    izvedenih += sum(1 for _ in range(5) if self.v.poskus(vir))
        self.assertLessEqual(izvedenih, link_varovalka.POSKUSOV)
        self.assertTrue(self.v.zaprto())

    def test_uspesna_seznanitev_ne_steje(self):
        for i in range(100):
            vir = "192.168.0.%d" % (10 + i % 5)
            self.assertTrue(self.v.zacetek(vir))
            self.assertTrue(self.v.poskus(vir))
            self.v.uspeh(vir)
        stanje = self.v.stanje()
        self.assertEqual((stanje["zaprto"], stanje["poskusov"], stanje["zacetkov"]), (False, 0, 0))
        self.assertEqual(self.zapore, [])

    def test_uspeh_vrne_samo_svoj_poskus(self):
        """Uspeh uporabnikove naprave ne zbrise napadalcevih poskusov."""
        for _ in range(10):
            self.v.poskus(A)
        self.v.zacetek(B)
        self.v.poskus(B)
        self.v.uspeh(B)
        self.v.uspeh(B)     # dvojni klic ne vzame tujega zapisa
        stanje = self.v.stanje()
        self.assertEqual((stanje["poskusov"], stanje["zacetkov"]), (10, 0))

    def test_trideseti_zacetek_zapre(self):
        for i in range(29):
            self.assertTrue(self.v.zacetek(A), i)
        self.assertFalse(self.v.zacetek(A))
        self.assertEqual((self.zapore[0]["razlog"], self.zapore[0]["viri"]), ("zacetki", [(A, 30)]))
        self.assertTrue(self.v.zaprto())

    def test_med_zaporo_z_vabilom_najvec_deset_poskusov(self):
        self._zapri()
        self.assertTrue(self.v.sme_zaceti(vabilo=True))
        self.assertTrue(self.v.zacetek(A, vabilo=True))
        for i in range(link_varovalka.KREDIT_VABILA):
            self.assertTrue(self.v.poskus(A, vabilo=True), i)
        self.assertFalse(self.v.poskus(A, vabilo=True))
        self.assertFalse(self.v.zacetek(A, vabilo=True), "kredit je porabljen: do konca zapore samo koda QR")
        self.assertFalse(self.v.sme_zaceti(vabilo=True))
        self.assertEqual(len(self.zapore), 1)

    def test_uspeh_med_zaporo_vrne_kredit(self):
        self._zapri()
        for _ in range(4):
            self.assertTrue(self.v.poskus(A, vabilo=True))
            self.v.uspeh(A)
        self.assertEqual(self.v.stanje()["kredit"], link_varovalka.KREDIT_VABILA)

    def test_vabilo_ob_sprozitvi_zapore(self):
        """Uporabnik ravno povezuje napravo (vabilo je odprto), napadalec pa porabi mejo: uporabnikov poskus velja."""
        for _ in range(19):
            self.v.poskus(A)
        self.assertTrue(self.v.poskus(B, vabilo=True))
        self.assertTrue(self.v.zaprto())
        self.assertEqual(self.v.stanje()["kredit"], link_varovalka.KREDIT_VABILA - 1)

    def test_ponovitve_ura_dan_teden_in_manjsa_meja(self):
        self._zapri()
        self.assertEqual(self.zapore[-1]["trajanje_s"], URA)
        self.ura.t += URA
        self.assertFalse(self.v.zaprto())
        self.assertEqual(self.v.stanje()["meja_poskusov"], link_varovalka.POSKUSOV_PO_ZAPORI)
        for i in range(4):
            self.assertTrue(self.v.poskus(A), i)
        self.assertFalse(self.v.poskus(A))
        self.assertEqual((self.zapore[-1]["trajanje_s"], self.zapore[-1]["ponovitev"]), (DAN, 2))
        self.ura.t += DAN
        for i in range(9):
            self.assertTrue(self.v.zacetek(A), i)
        self.assertFalse(self.v.zacetek(A), "po zapori je tudi zacetkov manj")
        self.assertEqual((self.zapore[-1]["trajanje_s"], self.zapore[-1]["razlog"]), (7 * DAN, "zacetki"))
        self.ura.t += 7 * DAN
        self._zapri()
        self.assertEqual((self.zapore[-1]["trajanje_s"], self.zapore[-1]["ponovitev"]), (7 * DAN, 4))

    def test_vztrajen_napadalec_v_enem_letu(self):
        """Stevilka iz opomb izdaje: koliko kod lahko v enem letu poskusi napadalec, ki nikoli ne odneha."""
        izvedenih, konec = 0, self.ura.t + 365 * DAN
        while self.ura.t < konec:
            if self.v.poskus(A):
                izvedenih += 1
            else:
                self.ura.t += 60.0
        self.assertLess(izvedenih, 250)
        # 900.000 moznih kod: verjetnost zadetka v enem letu je pod 0,03 %.
        self.assertLess(izvedenih / 900000.0, 0.0003)

    def test_po_tridesetih_dneh_miru_se_ponovitve_pozabijo(self):
        self._zapri()
        self.ura.t += URA + link_varovalka.POZABI_S - 10
        self.assertEqual(self.v.stanje()["meja_poskusov"], link_varovalka.POSKUSOV_PO_ZAPORI)
        self.ura.t += 20
        stanje = self.v.stanje()
        self.assertEqual((stanje["meja_poskusov"], stanje["ponovitev"]), (link_varovalka.POSKUSOV, 0))
        self._zapri()
        self.assertEqual(self.zapore[-1]["trajanje_s"], URA)

    def test_stanje_prezivi_ponovni_zagon(self):
        for _ in range(7):
            self.v.poskus(A)
        self.v.zacetek(B)
        drugi = VarovalkaKode(ura=self.ura, stanje=json.loads(json.dumps(self.shranjeno[-1])))
        stanje = drugi.stanje()
        self.assertEqual((stanje["poskusov"], stanje["zacetkov"], stanje["zaprto"]), (7, 1, False))
        self._zapri()
        self.ura.t += 600
        tretji = VarovalkaKode(ura=self.ura, stanje=json.loads(json.dumps(self.shranjeno[-1])))
        stanje = tretji.stanje()
        self.assertEqual((stanje["zaprto"], stanje["se_s"], stanje["ponovitev"]), (True, 3000, 1))
        self.assertFalse(tretji.zacetek(A), "ponovni zagon sredisca napadalcu ne vrne meje")
        self.assertEqual(tretji.izvozi(), json.loads(json.dumps(self.shranjeno[-1])))

    def test_ura_nazaj(self):
        for _ in range(10):
            self.v.poskus(A)
        self.ura.t -= DAN       # popravek ure: zapisi so zdaj »iz prihodnosti« in veljajo za pravkar narejene
        self.assertEqual(self.v.stanje()["poskusov"], 10)
        for i in range(9):
            self.assertTrue(self.v.poskus(A), i)
        self.assertFalse(self.v.poskus(A))
        self.ura.t -= 3650 * DAN  # zapora ne more trajati dlje od najdaljse
        self.assertLessEqual(self.v.stanje()["se_s"], int(link_varovalka.ZAPORE_S[-1]))

    def test_pokvarjeno_stanje_se_prezre(self):
        for stanje in ({"poskusi": "x", "zaprto_do": "abc"}, {"poskusi": [[1], ["a", "b"], None]}, [], "x",
                       {"ponovitev": -5, "kredit": 99, "zaprto_do": None}):
            v = VarovalkaKode(ura=self.ura, stanje=stanje)
            self.assertFalse(v.zaprto(), stanje)
            self.assertTrue(v.poskus(A), stanje)

    def test_napaka_pri_pisanju_ne_ustavi(self):
        def pade(_stanje):
            raise OSError("disk je poln")
        v = VarovalkaKode(ura=self.ura, shrani=pade)
        self.assertTrue(v.zacetek(A))
        self.assertTrue(v.poskus(A))
        self._zapri(v)

    def test_uporabnik_sam_konca_zaporo(self):
        self._zapri()
        self.v.odpri()
        self.assertFalse(self.v.zaprto())
        self.assertEqual(self.v.stanje()["meja_poskusov"], link_varovalka.POSKUSOV_PO_ZAPORI)


def _poskus(hub, odtis, pair_id, device_id, koda):
    """En poskus kode, kot ga naredi naprava: (izid, je_koda_prava). Napadalec po napacni kodi ne klice /finish."""
    odjemalec = Spake2.odjemalec(koda, device_id, link_hub_streznik.IDENTITETA_HUBA, odtis.encode(), pair_id.encode())
    pa, ca, napaka = hub.spake_korak1(pair_id, device_id, odjemalec.sporocilo())
    if napaka:
        return napaka, False
    _kljuc, cb = odjemalec.zakljuci(pa)
    if not odjemalec.preveri(ca):
        return "napacna", False
    zeton, napaka = hub.spake_korak2(pair_id, device_id, cb)
    return (zeton or napaka), bool(zeton)


class SredisceInKoda(unittest.TestCase):
    def setUp(self):
        self.odtis = "ab" * 32
        self.ura = Ura()
        self.hub = link_hub_streznik.Hub(odtis=self.odtis, ura=self.ura)
        self.zapore = []
        self.hub.ob_zapori_kode = self.zapore.append

    def _seznani(self, device_id, naslov):
        zacetek = self.hub.zacni_seznanitev(device_id, device_id, naslov)
        self.assertIn("pair_id", zacetek, zacetek)
        pair_id = zacetek["pair_id"]
        return _poskus(self.hub, self.odtis, pair_id, device_id, self.hub._prijave[pair_id]["pin"])

    def test_pocasno_ugibanje_z_vec_naslovov_zapre_povezovanje(self):
        izvedenih = 0
        for i, naslov in enumerate((A, B, C, D, A, B)):
            self.ura.t += 61
            zacetek = self.hub.zacni_seznanitev("vsiljivec-%d" % i, "Telefon", naslov)
            if "pair_id" not in zacetek:
                self.assertEqual(zacetek, {"napaka": "seznanitev_zaprta"})
                continue
            for _ in range(5):
                izid, prava = _poskus(self.hub, self.odtis, zacetek["pair_id"], "vsiljivec-%d" % i, "000000")
                self.assertFalse(prava)
                if izid == "napacna":
                    izvedenih += 1
                else:
                    self.assertEqual(izid, "seznanitev_zaprta")
                    break
        self.assertEqual(izvedenih, link_varovalka.POSKUSOV - 1)
        self.assertEqual([(z["razlog"], z["trajanje_s"]) for z in self.zapore], [("kode", URA)])
        self.assertEqual(self.hub._prijave, {}, "cakajoce prijave padejo, kode na zaslonih ugasnejo")
        self.assertEqual(self.hub.zacni_seznanitev("telefon", "Telefon", D), {"napaka": "seznanitev_zaprta"})

    def test_domace_povezovanje_ne_steje(self):
        for i in range(24):
            self.ura.t += 30
            izid, prava = self._seznani("naprava-%d" % i, "192.168.0.%d" % (20 + i))
            self.assertTrue(prava, izid)
        self.assertEqual(self.zapore, [])
        stanje = self.hub.varovalka.stanje()
        self.assertEqual((stanje["poskusov"], stanje["zacetkov"]), (0, 0))

    def test_vabilo_zaupane_naprave_odpre_povezovanje_med_zaporo(self):
        for _ in range(link_varovalka.POSKUSOV):
            self.hub.varovalka.poskus(A)
        self.assertEqual(self.hub.zacni_seznanitev("telefon", "Telefon", B), {"napaka": "seznanitev_zaprta"})
        qr_id, _skrivnost = self.hub.ustvari_pridruzitev()
        koda = self.hub.pin_pridruzitve(qr_id)
        zacetek = self.hub.zacni_seznanitev("telefon", "Telefon", B)
        self.assertEqual(self.hub._prijave[zacetek["pair_id"]]["pin"], koda)
        izid, prava = _poskus(self.hub, self.odtis, zacetek["pair_id"], "telefon", koda)
        self.assertTrue(prava, izid)
        self.assertEqual(self.hub.varovalka.stanje()["kredit"], link_varovalka.KREDIT_VABILA)
        # Vabilo je porabljeno (koda je enkratna): povezovanje s kodo je spet zaprto.
        self.assertEqual(self.hub.zacni_seznanitev("drugi", "Drugi", B), {"napaka": "seznanitev_zaprta"})

    def test_med_zaporo_tudi_z_vabilom_najvec_deset_poskusov(self):
        for _ in range(link_varovalka.POSKUSOV):
            self.hub.varovalka.poskus(A)
        self.hub.ustvari_pridruzitev()
        izvedenih = 0
        for i in range(4):
            zacetek = self.hub.zacni_seznanitev("vsiljivec-%d" % i, "Telefon", A)
            if "pair_id" not in zacetek:
                break
            for _ in range(5):
                izid, _prava = _poskus(self.hub, self.odtis, zacetek["pair_id"], "vsiljivec-%d" % i, "000000")
                if izid == "napacna":
                    izvedenih += 1
        self.assertEqual(izvedenih, link_varovalka.KREDIT_VABILA)
        self.assertEqual(self.hub.zacni_seznanitev("telefon", "Telefon", B), {"napaka": "seznanitev_zaprta"})

    def test_zapora_pusti_prijavo_z_odprtim_vabilom(self):
        """Uporabnik ravno povezuje napravo z vabilom; napadalec vmes sprozi zaporo - uporabnikova prijava ostane."""
        qr_id, _skrivnost = self.hub.ustvari_pridruzitev()
        koda = self.hub.pin_pridruzitve(qr_id)
        moja = self.hub.zacni_seznanitev("telefon", "Telefon", B)
        for _ in range(link_varovalka.POSKUSOV):
            self.hub.varovalka.poskus(A)
        self.assertEqual(len(self.zapore), 1)
        self.assertIn(moja["pair_id"], self.hub._prijave)
        izid, prava = _poskus(self.hub, self.odtis, moja["pair_id"], "telefon", koda)
        self.assertTrue(prava, izid)

    def test_stanje_je_na_disku_in_prezivi_ponovni_zagon(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "nastavitve", "hub-varovalka.json")
            hub = link_hub_streznik.Hub(odtis=self.odtis, ura=self.ura, pot_varovalke=pot)
            for i in range(link_varovalka.POSKUSOV):
                hub.varovalka.poskus(A)
            if os.name != "nt":      # dovoljenja POSIX; na Windows datoteke v profilu varuje ACL uporabnika
                self.assertEqual(stat.S_IMODE(os.stat(pot).st_mode), 0o600)
            self.ura.t += 120
            drugi = link_hub_streznik.Hub(odtis=self.odtis, ura=self.ura, pot_varovalke=pot)
            self.assertEqual(drugi.zacni_seznanitev("telefon", "Telefon", B), {"napaka": "seznanitev_zaprta"})
            self.assertEqual(drugi.varovalka.stanje()["se_s"], 3480)
            with open(pot, "w", encoding="utf-8") as d:
                d.write("{pokvarjeno")
            tretji = link_hub_streznik.Hub(odtis=self.odtis, ura=self.ura, pot_varovalke=pot)
            self.assertIn("pair_id", tretji.zacni_seznanitev("telefon", "Telefon", B))


class Besedila(unittest.TestCase):
    def test_obvestilo_ob_zapori_kode(self):
        dogodek = {"trajanje_s": URA, "razlog": "kode", "ponovitev": 1, "viri": [(A, 12), (B, 8)]}
        naslov, besedilo = link_hub_streznik.besedilo_zapore_kode(dogodek, True, {A: "Tablica  v dnevni"})
        self.assertEqual(naslov, "Safeer Link: povezovanje s kodo je zaprto")
        self.assertIn("Nekdo je ugibal kodo za povezavo (Tablica v dnevni (192.168.0.66), 192.168.0.67).", besedilo)
        self.assertIn("zaprto za 1 uro.", besedilo)
        self.assertIn("»Poveži naprave«", besedilo)
        naslov, besedilo = link_hub_streznik.besedilo_zapore_kode(dict(dogodek, razlog="zacetki", viri=[]), False)
        self.assertEqual(naslov, "Safeer Link: pairing by code is closed")
        self.assertIn("Someone kept starting to pair over and over. Pairing by code is closed for 1 hour.", besedilo)

    def test_obvestilo_s_kodo_je_v_jeziku_seje(self):
        """Prej je bilo obvestilo s kodo za novo napravo vedno slovensko, tudi v angleski seji."""
        self.assertEqual(link_hub_streznik.besedilo_kode("Telefon  Ana", "482913", True),
                         ("Safeer Link: nova naprava", "Telefon Ana se želi povezati. Vpiši kodo 482 913"))
        self.assertEqual(link_hub_streznik.besedilo_kode("Phone", "482913", False),
                         ("Safeer Link: new device", "Phone wants to connect. Enter the code 482 913"))

    def test_trajanje(self):
        t = link_hub_streznik._trajanje
        self.assertEqual([t(URA, True), t(2 * URA, True), t(3 * URA, True), t(5 * URA, True)],
                         ["1 uro", "2 uri", "3 ure", "5 ur"])
        self.assertEqual([t(DAN, True), t(2 * DAN, True), t(7 * DAN, True)], ["1 dan", "2 dneva", "7 dni"])
        self.assertEqual([t(URA, False), t(DAN, False), t(7 * DAN, False)], ["1 hour", "1 day", "7 days"])


class SredisceVZivo(unittest.TestCase):
    """Pravo sredisce na zanki (TLS, HTTP)."""

    @classmethod
    def setUpClass(cls):
        cls.mapa = tempfile.TemporaryDirectory()
        cls.obvestila = []
        cls.popravki = [
            mock.patch.object(link_krog, "_mapa_nastavitev", return_value=cls.mapa.name),
            mock.patch.object(link_hub_streznik.HubStreznik, "_ze_gosti_lokalno", staticmethod(lambda: False)),
            mock.patch.dict(os.environ, {"SAFEER_HUB_DRUGI": "1", "LANGUAGE": "sl_SI:sl"}),
            mock.patch.object(link_hub_streznik, "_obvestilo", lambda *a, **k: cls.obvestila.append(a)),
            mock.patch.object(link_hub_streznik, "_obvestilo_kode", lambda *a, **k: None),
        ]
        for p in cls.popravki:
            p.start()
        cls.streznik = link_hub_streznik.HubStreznik(tls_mapa=os.path.join(cls.mapa.name, "tls"))
        cls.streznik.obramba.izvzet = lambda vir: False
        if not cls.streznik.zazeni():
            for p in reversed(cls.popravki):
                p.stop()
            cls.mapa.cleanup()
            raise unittest.SkipTest("sredisca ni bilo mogoce zagnati")
        cls.osnova = "https://127.0.0.1:%d" % cls.streznik.vrata
        cls.ws = "wss://127.0.0.1:%d/cast/ws" % cls.streznik.vrata
        cls.odtis = cls.streznik.odtis

    @classmethod
    def tearDownClass(cls):
        cls.streznik.ustavi()
        for p in reversed(cls.popravki):
            p.stop()
        cls.mapa.cleanup()

    def setUp(self):
        self.obvestila.clear()
        self.zapore = []
        self.streznik.ob_zapori = lambda *a: self.zapore.append(a)
        self.streznik.obramba.sprosti("127.0.0.1")
        with self.streznik.obramba._zaklep:
            self.streznik.obramba._viri.clear()
        self.streznik.hub.varovalka = VarovalkaKode(ob_zapori=self.streznik.hub._zapora_kode)
        with self.streznik.hub._zaklep:
            self.streznik.hub._prijave.clear()

    def _post(self, pot, telo):
        koda, odgovor, _videni = link_tls.zahteva(self.osnova + pot, telo, timeout=5.0, pripeti=self.odtis)
        return koda, odgovor

    def test_vsak_krog_spake_je_poskus_kode_tudi_za_obrambo_po_viru(self):
        """Dve prijavi po pet krogov v minuti: 2 x 100 + 10 x 20 = prag; vir je zaprt, razlog je ugibanje kode."""
        krogov = 0
        for i in range(2):
            koda, odgovor = self._post("/cast/pair/start", {"device_id": "vsiljivec-%d" % i, "name": "Telefon"})
            self.assertEqual(koda, 200, odgovor)
            for _ in range(5):
                odjemalec = Spake2.odjemalec("000000", "vsiljivec-%d" % i, link_hub_streznik.IDENTITETA_HUBA,
                                             self.odtis.encode(), odgovor["pair_id"].encode())
                k, o = self._post("/cast/pair/spake", {"pair_id": odgovor["pair_id"], "device_id": "vsiljivec-%d" % i,
                                                       "pb": odjemalec.sporocilo().hex()})
                if k == 200:
                    krogov += 1
        self.assertEqual(krogov, 10)
        self.assertEqual(len(self.zapore), 1)
        self.assertTrue(self.streznik.obramba.zaprt("127.0.0.1"))

    def test_zaprto_povezovanje_odgovori_s_pojasnilom_in_obvesti_uporabnika(self):
        for _ in range(link_varovalka.POSKUSOV):
            self.streznik.hub.varovalka.poskus("192.168.0.66")
        self.assertEqual(len(self.obvestila), 1)
        self.assertEqual(self.obvestila[0][0], "Safeer Link: povezovanje s kodo je zaprto")
        self.assertIn("192.168.0.66", self.obvestila[0][1])
        koda, odgovor = self._post("/cast/pair/start", {"device_id": "telefon", "name": "Telefon"})
        self.assertEqual((koda, odgovor.get("code")), (429, "seznanitev_zaprta"))
        self.assertIn("Poveži naprave", odgovor.get("error", ""))
        # Odjemalec na racunalniku razlog prepozna in ga pove uporabniku.
        self.assertEqual(link_hub.zacni_seznanitev(self.ws, "pc-test", "Test"), {"napaka": "seznanitev_zaprta"})
        # Uporabnikova nova naprava, ki vprasa nekajkrat, zato ni zaprta.
        self.assertEqual(self.zapore, [])


if __name__ == "__main__":
    unittest.main()
