"""Obrambni mehanizem sredisca (core/link_obramba.py): stetje sovraznih dogodkov po viru, zapora, napad.

Prvi del je cista logika z lazno uro. Drugi del je pravo sredisce na zanki (TLS, HTTP): napadalec z napacnimi zetoni
je zaprt in ne dobi vec niti rokovanja, clan kroga pa dela naprej, tudi ce odpre na stotine povezav.
"""
import importlib.util
import os
import socket
import tempfile
import unittest
from unittest import mock

from core import link_hub, link_hub_streznik, link_krog, link_obramba, link_tls
from core.link_obramba import Obramba

A, B, C = "192.168.0.66", "192.168.0.67", "192.168.0.68"


class Ura:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Pravila(unittest.TestCase):
    def setUp(self):
        self.ura = Ura()
        self.zapore, self.napadi = [], []
        self.o = Obramba(ura=self.ura, ob_zapori=lambda *a: self.zapore.append(a), ob_napadu=self.napadi.append)

    def _do_zapore(self, vir, vrsta="brez_zaupanja"):
        for _ in range(200):
            if self.o.zaprt(vir):
                return
            self.o.dogodek(vir, vrsta)
        self.fail("vir ni bil zaprt")

    def test_prag_zapre_vir(self):
        for _ in range(19):
            self.o.dogodek(A, "brez_zaupanja")
        self.assertTrue(self.o.dovoli(A))
        self.assertEqual(self.zapore, [])
        self.o.dogodek(A, "brez_zaupanja")
        self.assertEqual(self.zapore, [(A, link_obramba.ZAPORA_S, "brez_zaupanja")])
        self.assertFalse(self.o.dovoli(A))
        self.assertTrue(self.o.zaprt(A))
        self.assertTrue(self.o.dovoli(B), "zapora velja za vir, ne za vse")
        stanje = self.o.stanje()
        self.assertEqual([(z["vir"], z["razlog"], z["zapora"]) for z in stanje["zaprti"]], [(A, "brez_zaupanja", 1)])
        self.assertEqual(stanje["zavrnjenih"], 1)
        # Po izteku zapore je vir spet sprejet.
        self.ura.t += link_obramba.ZAPORA_S + 1
        self.assertTrue(self.o.dovoli(A))
        self.assertEqual(self.o.stanje()["zaprti"], [])

    def test_opozorilo_na_polovici_praga(self):
        """V dnevniku se vidi, kaj pocne naprava, ki se pragu bliza - preden je zaprta (lazni preplah prave naprave)."""
        opozorila = []
        o = Obramba(ura=self.ura, ob_opozorilu=lambda *a: opozorila.append(a), ob_zapori=lambda *a: self.zapore.append(a))
        for _ in range(9):
            o.dogodek(A, "brez_zaupanja")
        self.assertEqual(opozorila, [])
        o.dogodek(A, "brez_zaupanja")
        o.dogodek(A, "tipanje")
        self.assertEqual(opozorila, [(A, 200, {"brez_zaupanja": 200})], "eno opozorilo, ne ob vsakem dogodku")
        self.ura.t += link_obramba.OPOZORILO_VSAKIH_S + 1
        for _ in range(11):
            o.dogodek(A, "brez_zaupanja")
        self.assertEqual(len(opozorila), 2)
        self.assertEqual(self.zapore, [])
        # Ob zapori je sestava v stanju.
        for _ in range(10):
            o.dogodek(A, "brez_zaupanja")
        self.assertEqual(o.stanje()["zaprti"][0]["sestava"], {"brez_zaupanja": 400})

    def test_stari_dogodki_ne_stejejo(self):
        for _ in range(15):
            self.o.dogodek(A, "brez_zaupanja")
        self.ura.t += link_obramba.OKNO_S + 1
        for _ in range(15):
            self.o.dogodek(A, "brez_zaupanja")
        self.assertFalse(self.o.zaprt(A))

    def test_legitimna_naprava_ni_nikoli_zaprta(self):
        """Naprava, ki se prijavlja pod napacnim id-jem ali je bila umaknjena iz kroga: vsakih 15 s povezava za
        potrdilo, izziv z odgovorom 401 in se iskanje po golem HTTP (neuspelo rokovanje). Tako lahko dela ves dan."""
        for _ in range(4 * 60 * 24):
            self.assertTrue(self.o.dovoli(A))
            self.o.dogodek(A, "brez_zaupanja")
            self.assertTrue(self.o.dovoli(A))
            self.o.dogodek(A, "rokovanje")
            self.ura.t += 15
        self.assertEqual(self.zapore, [])

    def test_ugibanje_kode_je_zaprto_hitro(self):
        """Sestmestna koda: pet poskusov na prijavo. Brez zapore bi napadalec prijave samo ponavljal."""
        poskusov = 0
        while not self.o.zaprt(A):
            self.o.dogodek(A, "seznanitev")
            poskusov += 1
        self.assertEqual(poskusov, 10)
        self.assertEqual(self.zapore[0][2], "seznanitev")

    def test_zapora_se_ob_ponovitvi_podvoji(self):
        trajanja = []
        for _ in range(5):
            self._do_zapore(A)
            trajanja.append(self.zapore[-1][1])
            self.ura.t += self.zapore[-1][1] + 1
        self.assertEqual(trajanja, [600.0, 1200.0, 2400.0, 3600.0, 3600.0])
        # Po dnevu miru se stetje ponovitev zacne znova.
        self.ura.t += link_obramba.POZABI_PONOVITVE_S + 1
        self._do_zapore(A)
        self.assertEqual(self.zapore[-1][1], 600.0)

    def test_poplava_povezav(self):
        sprejetih = 0
        for _ in range(1000):
            if not self.o.dovoli(A):
                break
            sprejetih += 1
        self.assertEqual(sprejetih, 399)
        self.assertEqual(self.zapore, [(A, 600.0, "povezava")])

    def test_zaupan_vir(self):
        # Telefon, ki lista mapo s slikami: na stotine povezav. Prijavil se je s podpisom - ni poplava.
        for _ in range(300):
            self.o.dovoli(A)
        self.o.zaupaj(A)
        for _ in range(5000):
            self.assertTrue(self.o.dovoli(A))
        self.assertEqual(self.zapore, [])
        # Sovrazni dogodki zaupanega vira stejejo polovico (prag pri 40 namesto 20 zavrnitvah).
        for _ in range(39):
            self.o.dogodek(A, "brez_zaupanja")
        self.assertFalse(self.o.zaprt(A))
        self.o.dogodek(A, "brez_zaupanja")
        self.assertTrue(self.o.zaprt(A), "tudi zaupan vir ne sme ugibati brez konca")
        # Zaupanje potece.
        self.o.zaupaj(B)
        self.ura.t += link_obramba.ZAUPANJE_S + 1
        for _ in range(1000):
            if not self.o.dovoli(B):
                break
        self.assertTrue(self.o.zaprt(B))

    def test_povezana_naprava_je_zaupana_dokler_je_povezana(self):
        """Prijava je bila pred urami, povezava WebSocket je se odprta: listanje mape s slikami ni poplava."""
        povezani = {A}
        o = Obramba(ura=self.ura, ob_zapori=lambda *a: self.zapore.append(a), zaupan=lambda vir: vir in povezani)
        self.ura.t += 6 * 3600
        for _ in range(5000):
            self.assertTrue(o.dovoli(A))
        for _ in range(39):
            o.dogodek(A, "brez_zaupanja")           # polovicna teza
        self.assertFalse(o.zaprt(A))
        # Ko povezave ni vec, velja kot vsak drug vir.
        povezani.clear()
        for _ in range(1000):
            if not o.dovoli(A):
                break
        self.assertTrue(o.zaprt(A))
        # Pokvarjen povratni klic ne podre sredisca in ne podari zaupanja.
        o2 = Obramba(ura=self.ura, zaupan=lambda vir: 1 / 0)
        for _ in range(1000):
            if not o2.dovoli(B):
                break
        self.assertTrue(o2.zaprt(B))

    def test_sredisce_ve_kdo_je_povezan(self):
        hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik")
        self.assertFalse(hub.ima_povezavo_z(A))
        tv = link_hub_streznik.Naprava("tv1", "Televizor", "receiver", [], A)
        tv.povezava = object()
        odklopljena = link_hub_streznik.Naprava("tab", "Tablica", "receiver", [], B)
        with hub._zaklep:
            hub._naprave["tv1"] = tv
            hub._naprave["tab"] = odklopljena
            hub._sosedje["n-sosed"] = mock.Mock(naslov="wss://192.168.0.70:8990/cast/ws")
            hub._sosedje["n-dohodni"] = mock.Mock(naslov="192.168.0.71")
        self.assertTrue(hub.ima_povezavo_z(A))
        self.assertFalse(hub.ima_povezavo_z(B), "naprava brez odprte povezave ni povezana")
        self.assertTrue(hub.ima_povezavo_z("192.168.0.70"), "odhodna sosednja povezava")
        self.assertTrue(hub.ima_povezavo_z("192.168.0.71"), "dohodna sosednja povezava")
        self.assertFalse(hub.ima_povezavo_z(""))

    def test_ta_naprava_ni_nikoli_zaprta(self):
        for vir in ("127.0.0.1", "127.0.0.53", "::1", "::ffff:127.0.0.1", ""):
            for _ in range(500):
                self.o.dogodek(vir, "seznanitev")
                self.assertTrue(self.o.dovoli(vir), vir)
        self.assertEqual(self.zapore, [])
        self.assertFalse(link_obramba.je_ta_naprava("192.168.0.1"))
        self.assertFalse(link_obramba.je_ta_naprava("::ffff:192.168.0.1"))

    def test_napad_vec_virov(self):
        self._do_zapore(A)
        self._do_zapore(B)
        self.assertEqual(self.napadi, [])
        self._do_zapore(C)
        self.assertEqual(self.napadi, [[A, B, C]])
        self.assertTrue(self.o.stanje()["napad"])
        # Isti napad se ne javlja znova ob vsakem novem viru.
        self._do_zapore("192.168.0.69")
        self.assertEqual(len(self.napadi), 1)
        self.ura.t += link_obramba.NAPAD_OKNO_S + 1
        self.assertFalse(self.o.stanje()["napad"])

    def test_napad_vztrajen_vir(self):
        for _ in range(2):
            self._do_zapore(A)
            self.ura.t += self.zapore[-1][1] + 1
        self.assertEqual(self.napadi, [])
        self._do_zapore(A)
        self.assertEqual(self.napadi, [[A]])

    def test_spomin_je_omejen_in_zaprti_ostanejo(self):
        self._do_zapore(A)
        for i in range(link_obramba.NAJVEC_VIROV + 200):
            self.o.dogodek("10.%d.%d.%d" % (i >> 16 & 255, i >> 8 & 255, i & 255), "tipanje")
        self.assertLessEqual(len(self.o._viri), link_obramba.NAJVEC_VIROV)
        self.assertTrue(self.o.zaprt(A), "zaprt vir ne sme izpasti iz spomina")

    def test_sprosti(self):
        self._do_zapore(A)
        self.assertTrue(self.o.sprosti(A))
        self.assertTrue(self.o.dovoli(A))
        self.assertFalse(self.o.sprosti(A))
        self.assertFalse(self.o.sprosti("192.168.9.9"))

    def test_povratni_klic_ne_podre_sredisca(self):
        o = Obramba(ura=self.ura, ob_zapori=lambda *a: 1 / 0)
        for _ in range(30):
            o.dogodek(A, "brez_zaupanja")
        self.assertTrue(o.zaprt(A))

    def test_vrsta_napake(self):
        v = link_obramba.vrsta_napake
        self.assertEqual(v(401, "ni_v_krogu"), "brez_zaupanja")
        self.assertEqual(v(401, "napacna_koda"), "seznanitev")
        self.assertEqual(v(429, "prevec_poskusov"), "seznanitev")
        self.assertEqual(v(404, "ni_poti"), "tipanje")
        # 405 je del prepoznave sredisca (link_hub.je_hub), 409 in 503 sta stanje - niso sovrazni.
        self.assertEqual(v(405, "metoda_ni_dovoljena"), "")
        self.assertEqual(v(409, "manjka_korak"), "")
        self.assertEqual(v(503, "prevec_prenosov"), "")
        self.assertEqual(v(200, "ni_poti"), "")
        self.assertTrue(set(link_obramba.VRSTA_PO_NAPAKI.values()) <= set(link_obramba.TEZE))

    def test_besedilo_obvestila(self):
        naslov, besedilo = link_hub_streznik.besedilo_zapore(A, 600.0, "seznanitev", True)
        self.assertIn("Safeer Link", naslov)
        self.assertIn(A, besedilo)
        self.assertIn("10 min", besedilo)
        self.assertIn("kodo", besedilo)
        naslov, besedilo = link_hub_streznik.besedilo_zapore(A, 1200.0, "povezava", False)
        self.assertIn(A, besedilo)
        self.assertIn("20 min", besedilo)
        for razlog in list(link_obramba.TEZE) + ["nekaj_novega"]:
            for sl in (True, False):
                self.assertTrue(all(link_hub_streznik.besedilo_zapore(A, 600.0, razlog, sl)))
        self.assertIn(B, link_hub_streznik.besedilo_napada([A, B], True)[1])
        # Naprava, ki jo sredisce pozna s tega naslova: ime in kaj narediti (najbrz je uporabnikova).
        _, besedilo = link_hub_streznik.besedilo_zapore(A, 600.0, "brez_zaupanja", True, "Tablica  v\nkuhinji")
        self.assertIn("»Tablica v kuhinji« (%s)" % A, besedilo)
        self.assertIn("poveži znova", besedilo)
        self.assertIn("connect it again", link_hub_streznik.besedilo_zapore(A, 600.0, "brez_zaupanja", False, "Tablet")[1])

    def test_ime_naprave_po_naslovu(self):
        hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik")
        self.assertEqual(hub.ime_po_naslovu(A), "")
        with hub._zaklep:
            hub._naprave["tv1"] = link_hub_streznik.Naprava("tv1", "Televizor", "receiver", [], A)
            pri_sosedu = link_hub_streznik.Naprava("tab", "Tablica", "receiver", [], A)
            pri_sosedu.sosed = "n-drugi"
            hub._naprave["tab"] = pri_sosedu
        self.assertEqual(hub.ime_po_naslovu(A), "Televizor")
        self.assertEqual(hub.ime_po_naslovu(B), "")
        self.assertEqual(hub.ime_po_naslovu(""), "")
        # Sosednje sredisce (Link Mesh) ni v registru naprav: ime ima krog zaupanja. Najdeno na pravi napravi -
        # telefon, ki je sosed, je bil ustavljen z obvestilom brez imena.
        with hub._zaklep:
            hub._sosedje["n-404fedf2ed258fd9"] = mock.Mock(naslov="wss://192.168.0.70:8990/cast/ws")
            hub._sosedje["n-dohodni"] = mock.Mock(naslov="192.168.0.71")
        imena = {"n-404fedf2ed258fd9": "Telefon v kuhinji", "n-dohodni": "Tablica"}
        with mock.patch.object(link_hub_streznik.Hub, "ime_v_krogu", staticmethod(lambda device_id: imena.get(device_id))):
            self.assertEqual(hub.ime_po_naslovu("192.168.0.70"), "Telefon v kuhinji")
            self.assertEqual(hub.ime_po_naslovu("192.168.0.71"), "Tablica")
            self.assertEqual(hub.ime_po_naslovu(A), "Televizor", "naprava v registru ima prednost")
            self.assertEqual(hub.ime_po_naslovu("192.168.0.72"), "")
        # Jezik seje: LANGUAGE ima prednost pred LC_ALL (tako kot v Controlu); C in POSIX nista jezik.
        for okolje, pricakovano in (({"LANGUAGE": "sl_SI:sl", "LC_ALL": "en_US.UTF-8"}, True), ({"LANG": "sl_SI.UTF-8"}, True),
                                    ({"LC_ALL": "C", "LANG": "sl_SI.UTF-8"}, True), ({"LANG": "en_US.UTF-8"}, False), ({}, False)):
            with mock.patch.dict(os.environ, okolje, clear=True):
                self.assertEqual(link_hub_streznik._slovensko(), pricakovano, okolje)


class GumbiNaObvestilu(unittest.TestCase):
    """Izhod v sili: gumb »Sprosti« in »Odpri povezovanje s kodo« na obvestilu (dejanje po D-Busu)."""

    def setUp(self):
        self.obvestila = []
        p = mock.patch.object(link_hub_streznik, "_obvestilo", lambda *a, **k: self.obvestila.append((a, k)))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"LANGUAGE": "sl_SI:sl"})
        p.start()
        self.addCleanup(p.stop)
        self.s = link_hub_streznik.HubStreznik(tls_mapa="/ni/pomembno")
        self.s.obramba.izvzet = lambda vir: False

    def test_sprosti_na_obvestilu_o_zapori(self):
        for _ in range(20):
            self.s.obramba.dogodek(A, "brez_zaupanja")
        self.assertTrue(self.s.obramba.zaprt(A))
        (naslov, _besedilo), k = self.obvestila[-1]
        self.assertEqual(naslov, "Safeer Link: naprava ustavljena")
        kljuc, napis, klic = k["dejanja"][0]
        self.assertEqual((kljuc, napis), ("sprosti", "Sprosti"))
        klic()
        self.assertFalse(self.s.obramba.zaprt(A))
        self.assertTrue(self.s.obramba.dovoli(A))
        (naslov, besedilo), k = self.obvestila[-1]
        self.assertEqual((naslov, besedilo), ("Safeer Link: naprava sproščena", "192.168.0.66 je sproščena. Spet se lahko poveže."))
        self.assertNotIn("dejanja", k)
        # Drugi pritisk (vir ni vec zaprt) ne naredi nicesar in ne obvesti znova.
        stevilo = len(self.obvestila)
        klic()
        self.assertEqual(len(self.obvestila), stevilo)

    def test_odpri_na_obvestilu_o_zapori_kode(self):
        self.s.hub = link_hub_streznik.Hub(odtis="ab" * 32)
        self.s.hub.ob_zapori_kode = self.s._ob_zapori_kode
        self.assertFalse(self.s.odpri_povezovanje_s_kodo(), "ni zaprto: ni kaj odpreti")
        for _ in range(20):
            self.s.hub.varovalka.poskus(A)
        self.assertTrue(self.s.hub.varovalka.zaprto())
        (naslov, _besedilo), k = self.obvestila[-1]
        self.assertEqual(naslov, "Safeer Link: povezovanje s kodo je zaprto")
        kljuc, napis, klic = k["dejanja"][0]
        self.assertEqual((kljuc, napis), ("odpri", "Odpri povezovanje s kodo"))
        klic()
        self.assertFalse(self.s.hub.varovalka.zaprto())
        self.assertEqual(self.s.hub.varovalka.stanje()["meja_poskusov"], 5, "po zapori velja manjsa meja")
        self.assertEqual(self.obvestila[-1][0][0], "Safeer Link: povezovanje s kodo je odprto")
        self.assertIn("pair_id", self.s.hub.zacni_seznanitev("telefon", "Telefon", B))

    def test_signal_obvestilnega_streznika_izvede_dejanje_enkrat(self):
        klici = []
        link_hub_streznik._zapomni_dejanja(41, {"sprosti": lambda: klici.append("sprosti")})
        link_hub_streznik._zapomni_dejanja(42, {"odpri": lambda: klici.append("odpri")})
        signal = lambda ime, *p: link_hub_streznik._ob_signalu_obvestila(  # noqa: E731
            None, "", "", "", ime, mock.Mock(unpack=lambda: p))
        signal("ActionInvoked", 41, "neznan")      # neznan gumb: nic; obvestilo je s tem porabljeno
        signal("ActionInvoked", 41, "sprosti")
        self.assertEqual(klici, [])
        # Oblacek obvestila izgine (NotificationClosed), obvestilo z gumbom pa ostane v pladnju: gumb mora delati.
        signal("NotificationClosed", 42, 1)
        signal("ActionInvoked", 42, "odpri")
        self.assertEqual(klici, ["odpri"])
        link_hub_streznik._zapomni_dejanja(43, {"sprosti": lambda: klici.append("sprosti")})
        signal("ActionInvoked", 43, "sprosti")
        signal("ActionInvoked", 43, "sprosti")
        self.assertEqual(klici, ["odpri", "sprosti"])
        # Dejanje, ki pade, ne podre glavne zanke.
        link_hub_streznik._zapomni_dejanja(44, {"x": lambda: 1 / 0})
        signal("ActionInvoked", 44, "x")
        # Spomin je omejen.
        for i in range(100, 100 + 3 * link_hub_streznik.NAJVEC_OBVESTIL_Z_GUMBI):
            link_hub_streznik._zapomni_dejanja(i, {"a": lambda: None})
        self.assertLessEqual(len(link_hub_streznik._dejanja), link_hub_streznik.NAJVEC_OBVESTIL_Z_GUMBI)

    @unittest.skipUnless(importlib.util.find_spec("gi"), "gumbi na obvestilu gredo po D-Bus (gi), ki ga tu ni")
    def test_narocilo_na_signal_drzi_povezavo_z_vodilom(self):
        """Gio.bus_get_sync vrne skupno povezavo, ki se zapre, ko jo spusti zadnji lastnik - z njo izgine narocilo na
        signal in gumb je mrtev (videno v Cinnamonu: pritisk je obvestilo zaprl, zgodilo pa se ni nic)."""
        vodilo = mock.Mock()
        with mock.patch.object(link_hub_streznik, "_dejanja_narocena", False), \
                mock.patch.object(link_hub_streznik, "_vodilo_dejanj", None):
            link_hub_streznik._naroci_dejanja(vodilo)
            self.assertIs(link_hub_streznik._vodilo_dejanj, vodilo)
            link_hub_streznik._naroci_dejanja(vodilo)
            self.assertEqual(vodilo.signal_subscribe.call_count, 1, "narocilo je eno na proces")
            self.assertEqual(vodilo.signal_subscribe.call_args[0][2], "ActionInvoked")

    def test_besedila(self):
        self.assertEqual(link_hub_streznik.besedilo_sprostitve("»Tablica« (192.168.0.87)", False),
                         ("Safeer Link: device released", "»Tablica« (192.168.0.87) is released. It can connect again."))
        self.assertEqual(link_hub_streznik.besedilo_odprtja_kode(False)[0], "Safeer Link: pairing by code is open")


class SredisceVZivo(unittest.TestCase):
    """Pravo sredisce na zanki. Zanka je sicer izvzeta - tu jo stejemo, da lahko napademo sami sebe."""

    @classmethod
    def setUpClass(cls):
        cls.mapa = tempfile.TemporaryDirectory()
        cls.popravki = [
            mock.patch.object(link_krog, "_mapa_nastavitev", return_value=cls.mapa.name),
            # Na razvojnem racunalniku ze tece sredisce na privzetih vratih: preizkus zazene svoje na drugih.
            mock.patch.object(link_hub_streznik.HubStreznik, "_ze_gosti_lokalno", staticmethod(lambda: False)),
            mock.patch.dict(os.environ, {"SAFEER_HUB_DRUGI": "1"}),
            mock.patch.object(link_hub_streznik, "_obvestilo", lambda *a, **k: None),
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
        cls.odtis = cls.streznik.odtis

    @classmethod
    def tearDownClass(cls):
        cls.streznik.ustavi()
        for p in reversed(cls.popravki):
            p.stop()
        cls.mapa.cleanup()

    def setUp(self):
        self.zapore = []
        self.streznik.ob_zapori = lambda *a: self.zapore.append(a)
        self.streznik.obramba.sprosti("127.0.0.1")
        with self.streznik.obramba._zaklep:
            self.streznik.obramba._viri.clear()

    def _zeton(self, zeton="ni-pravi"):
        return link_tls.zahteva(self.osnova + "/cast/ticket", {}, zeton, timeout=5.0, pripeti=self.odtis)[0]

    def test_prepoznava_sredisca_ni_sovrazna(self):
        for _ in range(12):
            self.assertTrue(link_hub.je_hub(self.osnova, odtis=self.odtis))
        self.assertEqual(self.zapore, [])
        self.assertFalse(self.streznik.obramba.zaprt("127.0.0.1"))

    def test_napacni_zetoni_zaprejo_vir_in_ta_ne_dobi_vec_niti_rokovanja(self):
        kode = []
        for _ in range(40):
            kode.append(self._zeton())
            if self.zapore:
                break
        # 20 (zavrnjen zeton) + 1 (povezava) na poskus: devetnajst jih dobi odgovor, dvajseta povezava je ze zaprta.
        self.assertEqual(kode, [401] * 19 + [0])
        self.assertEqual([(z[0], z[2]) for z in self.zapore], [("127.0.0.1", "brez_zaupanja")])
        # Zaprt vir: povezava se zapre pred rokovanjem TLS - ni odgovora, ni potrdila.
        self.assertEqual(self._zeton(), 0)
        self.assertEqual(link_tls.potrdilo_huba("wss://127.0.0.1:%d/cast/ws" % self.streznik.vrata, timeout=2.0), ("", ""))
        self.assertFalse(link_hub.je_hub(self.osnova, odtis=self.odtis))
        self.assertGreaterEqual(self.streznik.obramba.stanje()["zavrnjenih"], 3)
        # Uporabnik vir sprosti: sredisce spet odgovarja.
        self.assertTrue(self.streznik.obramba.sprosti("127.0.0.1"))
        self.assertEqual(self._zeton(), 401)

    def test_tipanje_vrat_brez_tls(self):
        """Pregledovalnik vrat: povezava brez rokovanja TLS. Vsaka steje 11; zapora ob sedemintrideseti."""
        import time
        for i in range(60):
            try:
                v = socket.create_connection(("127.0.0.1", self.streznik.vrata), timeout=2.0)
                v.sendall(b"GET / HTTP/1.0\r\n\r\n")
                v.close()
            except OSError:
                pass
            # Rokovanje pade v delovni niti streznika: pocakamo, da je presteto.
            for _ in range(300):
                if self.zapore:
                    break
                with self.streznik.obramba._zaklep:
                    v_ = self.streznik.obramba._viri.get("127.0.0.1")
                    presteto = sum(1 for d in v_.dogodki if d[2] == "rokovanje") if v_ else 0
                if presteto >= i + 1:
                    break
                time.sleep(0.01)
            if self.zapore:
                break
        self.assertEqual([(z[0], z[2]) for z in self.zapore], [("127.0.0.1", "rokovanje")])
        self.assertEqual(i + 1, 37)

    def test_clan_kroga_dela_naprej(self):
        """Veljaven podpis naredi vir zaupan: stotine povezav niso poplava."""
        clan = {"kljuc": link_krog.javni_kljuc_b64(), "ime": "Preizkus", "platforma": "linux"}
        lazni = mock.MagicMock()
        lazni.clan_za_id.return_value = clan
        lazni.json.return_value = {"v": 1, "clani": {}, "umiki": {}}
        naslov = "wss://127.0.0.1:%d%s" % (self.streznik.vrata, link_hub_streznik.POT_WS)
        with mock.patch.object(link_krog, "krog", return_value=lazni), \
                mock.patch.object(link_krog, "lahko_s_podpisom", return_value=True):
            vstopnica, _ = link_hub.vzemi_vstopnico_s_podpisom(naslov, "n-0123456789abcdef", self.odtis, "Preizkus")
        self.assertTrue(vstopnica, "prijava s podpisom mora uspeti")
        for _ in range(450):
            self.assertTrue(self.streznik.obramba.dovoli("127.0.0.1"))
        self.assertEqual(link_tls.zahteva(self.osnova + "/cast/health", timeout=5.0, pripeti=self.odtis)[0], 200)
        self.assertEqual(self.zapore, [])

    def test_zacetek_seznanitve_steje(self):
        """Vsak zacetek seznanitve uporabniku pokaze obvestilo s kodo: napadalec ga ne sme sproziti brez konca."""
        kode = []
        for i in range(30):
            koda, _, _ = link_tls.zahteva(self.osnova + "/cast/pair/start", {"device_id": "x-%d" % i, "name": "Napadalec"},
                                          timeout=5.0, pripeti=self.odtis)
            kode.append(koda)
            if self.zapore:
                break
        # Trije zacetki dobijo kodo (tri obvestila), cetrti vir zapre.
        self.assertEqual(kode, [200, 200, 200, 200])
        self.assertEqual(self.zapore[0][2], "zacetek_seznanitve")
        self.assertEqual(link_tls.zahteva(self.osnova + "/cast/pair/start", {"device_id": "x", "name": "N"},
                                          timeout=3.0, pripeti=self.odtis)[0], 0)


if __name__ == "__main__":
    unittest.main()
