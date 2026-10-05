"""Deljenje prek Huba na racunalniku: besedilo in datoteka med napravami (core/link_hub_deljenje.py).

Najprej logika brez omrezja (zaloga datotek, pravila Huba), nato cela zica: pravi Hub cez TLS, posiljatelj z istima
funkcijama, kot ju uporablja Safeer Control (link_deljenje.poslji_besedilo / poslji_datoteko), in cilj, ki datoteko
prevzame (link_deljenje.prevzemi_datoteko). Do 0.4.46 je Hub na racunalniku na ti poti odgovoril 404 in 501.
"""
import hashlib
import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_deljenje, link_hub, link_hub_deljenje, link_hub_streznik, link_krog


class LaznaPovezava:
    def __init__(self):
        self.poslano = []

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))
        return True

    def zapri(self, *_a, **_k):
        pass


def _prijava(id_naprave, ime):
    return json.dumps({"id": "r1", "type": "cast.register",
                       "payload": {"device_id": id_naprave, "name": ime, "role": "receiver", "capabilities": ["url"],
                                   "platform": "tv", "protocol": "1", "kind": "tv", "version": "2.1.169"}})


class Zaloga(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cas = 1_000_000.0
        self.prosto = 50 * 1024 ** 3
        self.z = link_hub_deljenje.Deljenje(mapa=lambda: os.path.join(self.tmp.name, "deljenje"),
                                            ura=lambda: self.cas, prosto=lambda _m: self.prosto)

    def _sprejmi(self, vsebina=b"vsebina datoteke", ime="Račun 2026.pdf", cilj="tv1", sha=None, dolzina=None):
        return self.z.sprejmi(io.BytesIO(vsebina), len(vsebina) if dolzina is None else dolzina, ime, cilj, "fon1",
                              hashlib.sha256(vsebina).hexdigest() if sha is None else sha)

    def test_sprejem_prevzem_in_izbris(self):
        koda, odgovor, d = self._sprejmi()
        self.assertEqual(koda, 200)
        self.assertEqual((odgovor["name"], odgovor["size"], odgovor["for_host"]), ("Račun 2026.pdf", 16, False))
        self.assertEqual(odgovor["sha256"], hashlib.sha256(b"vsebina datoteke").hexdigest())
        self.assertTrue(os.path.isfile(d.pot))
        if os.name != "nt":      # dovoljenja POSIX; na Windows datoteke v profilu varuje ACL uporabnika
            self.assertEqual(stat.S_IMODE(os.stat(d.pot).st_mode), 0o600, "datoteko sme brati samo uporabnik")
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(d.pot)).st_mode), 0o700)
        self.assertEqual(d.tovor(), {"id": d.id, "name": "Račun 2026.pdf", "size": 16, "path": "/cast/file/%s?k=%s" % (d.id, d.kljuc),
                                     "sha256": d.sha256, "for_host": False})
        self.assertIsNone(self.z.najdi(d.id, "napacen"))
        self.assertIsNone(self.z.najdi("drug-id", d.kljuc))
        self.assertIs(self.z.najdi(d.id, d.kljuc), d)
        self.assertTrue(self.z.zacni_prevzem())
        self.z.koncaj_prevzem(d, cela=False)
        self.assertTrue(os.path.isfile(d.pot), "prekinjen prevzem datoteke ne izbrise")
        self.assertTrue(self.z.zacni_prevzem())
        self.z.koncaj_prevzem(d, cela=True)
        self.assertFalse(os.path.exists(d.pot))
        self.assertIsNone(self.z.najdi(d.id, d.kljuc))

    def test_dve_datoteki_z_istim_imenom(self):
        a, b = self._sprejmi()[2], self._sprejmi(b"druga")[2]
        self.assertNotEqual(a.pot, b.pot)
        self.assertEqual((a.ime, b.ime), ("Račun 2026.pdf", "Račun 2026.pdf"), "prejemnik dobi izvirno ime")

    def test_napacen_odtis_in_okrnjena_datoteka(self):
        koda, odgovor, d = self._sprejmi(sha="0" * 64)
        self.assertEqual((koda, odgovor["koda"], d), (400, "napacen_odtis", None))
        koda, odgovor, d = self._sprejmi(dolzina=999)
        self.assertEqual((koda, odgovor["koda"], d), (400, "ni_cela", None))
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "deljenje")), [], "zavrnjena datoteka ne ostane na disku")

    def test_brez_odtisa_je_dovoljeno(self):
        self.assertEqual(self._sprejmi(sha="")[0], 200)

    def test_meje(self):
        self.assertEqual(self.z.preveri("a.txt", "tv1", link_hub_deljenje.NAJVECJA_DATOTEKA + 1)[0], 413)
        self.assertEqual(self.z.preveri("", "tv1", 5)[0], 400)
        self.assertEqual(self.z.preveri("a.txt", "", 5)[0], 400)
        self.assertEqual(self.z.preveri("a.txt", "tv1", -1)[0], 400)
        self.prosto = 100 * 1024 * 1024
        koda, odgovor = self.z.preveri("a.txt", "tv1", 5)
        self.assertEqual((koda, odgovor["koda"], odgovor["error_code"]), (507, "ni_prostora", "ni_prostora"))

    def test_omejeno_stevilo_hkratnih_prenosov(self):
        for _ in range(link_hub_deljenje.NAJVEC_PRENOSOV):
            self.assertTrue(self.z.zacni_prevzem())
        self.assertFalse(self.z.zacni_prevzem())
        koda, odgovor, d = self._sprejmi()
        self.assertEqual((koda, odgovor["koda"], d), (503, "prevec_prenosov", None))

    def test_neprevzeta_datoteka_po_eni_uri_izgine(self):
        d = self._sprejmi()[2]
        self.cas += link_hub_deljenje.DATOTEKA_VELJA_S - 5
        self.z.pocisti()
        self.assertTrue(os.path.isfile(d.pot))
        self.cas += 10
        self.z.pocisti()
        self.assertFalse(os.path.exists(d.pot))
        self.assertEqual(self.z.stevilo(), 0)

    def test_ostanki_prejsnjega_zagona_se_pobrisejo(self):
        mapa = os.path.join(self.tmp.name, "deljenje")
        os.makedirs(mapa)
        with open(os.path.join(mapa, "abc123-stara.bin"), "wb") as f:
            f.write(b"x")
        d = self._sprejmi()[2]
        self.assertEqual(os.listdir(mapa), [os.path.basename(d.pot)])

    def test_izprazni_ob_ustavitvi(self):
        d = self._sprejmi()[2]
        self.z.izprazni()
        self.assertFalse(os.path.exists(d.pot))

    def test_varno_ime(self):
        v = link_hub_deljenje.varno_ime
        self.assertEqual(v("../../etc/passwd"), "passwd")
        self.assertEqual(v("C:\\Users\\a\\slika.png"), "slika.png")
        self.assertEqual(v(".skrita"), "skrita")
        self.assertEqual(v("ime\x00z\nnicem.txt"), "imeznicem.txt")
        self.assertEqual(v("Počitnice 2026.mp4"), "Počitnice 2026.mp4")
        self.assertEqual(v(""), "")
        self.assertEqual(len(v("a" * 500 + ".txt")), link_hub_deljenje.NAJVEC_IMENA_DATOTEKE)
        self.assertEqual(self._sprejmi(ime="../../x")[2].ime, "x")
        self.assertEqual(self._sprejmi(ime="///")[0], 400)


class PravilaHuba(unittest.TestCase):
    def setUp(self):
        self.cas = 1_000_000.0
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik", ura=lambda: self.cas)
        self.tv, self.fon = LaznaPovezava(), LaznaPovezava()
        self.hub.obdelaj(self.tv, _prijava("tv1", "Televizor"))
        self.hub.obdelaj(self.fon, _prijava("fon1", "Telefon"))
        self.hub._zetoni["zeton-fon"] = ("fon1", "Telefon", self.cas)

    def test_besedilo_pride_do_cilja_s_posiljateljem(self):
        koda, odgovor = self.hub.deli_besedilo("zeton-fon", "tv1", "Živjo, televizor")
        self.assertEqual((koda, odgovor), (200, {"sent": True}))
        s = [x for x in self.tv.poslano if x.get("type") == "share.text"][-1]
        self.assertEqual((s["sender"], s["sender_name"], s["target"], s["payload"]), ("fon1", "Telefon", "tv1", {"text": "Živjo, televizor"}))
        self.assertTrue(s["id"].startswith("hub-"))
        self.assertFalse([x for x in self.fon.poslano if x.get("type") == "share.text"], "posiljatelj ne dobi kopije")

    def test_posiljatelj_je_lastnik_zetona(self):
        koda, odgovor = self.hub.deli_besedilo("neznan", "tv1", "x")
        self.assertEqual((koda, odgovor["koda"], odgovor["error_code"]), (401, "naprava_ni_seznanjena", "naprava_ni_seznanjena"))
        self.assertEqual(self.hub.deli_besedilo("", "tv1", "x")[0], 401)

    def test_napake_cilja_in_besedila(self):
        self.assertEqual(self.hub.deli_besedilo("zeton-fon", "", "x")[1]["koda"], "manjka_target")
        self.assertEqual(self.hub.deli_besedilo("zeton-fon", "tv1", "   ")[1]["koda"], "prazno_besedilo")
        self.assertEqual(self.hub.deli_besedilo("zeton-fon", "fon1", "x")[1]["koda"], "isti_naprava")
        koda, odgovor = self.hub.deli_besedilo("zeton-fon", "tablica9", "x")
        self.assertEqual((koda, odgovor["koda"]), (404, "naprava_ni_povezana"))

    def test_besedilo_je_omejeno(self):
        self.hub.deli_besedilo("zeton-fon", "tv1", "a" * 50_000)
        s = [x for x in self.tv.poslano if x.get("type") == "share.text"][-1]
        self.assertEqual(len(s["payload"]["text"]), link_hub_deljenje.NAJVEC_BESEDILA)

    def test_ime_iz_zetona_ce_posiljatelj_ni_povezan(self):
        self.hub._zetoni["zeton-ura"] = ("ura1", "Ura", self.cas)
        self.assertEqual(self.hub.deli_besedilo("zeton-ura", "tv1", "x")[0], 200)
        self.assertEqual([x for x in self.tv.poslano if x.get("type") == "share.text"][-1]["sender_name"], "Ura")

    def test_datoteke_ne_posljemo_napravi_pri_drugem_srediscu(self):
        self.assertIsNone(self.hub.cilj_deljenja("tv1", "fon1", datoteka=True))
        self.hub.najdi("tv1").sosed = "hub-dnevna"
        self.assertEqual(self.hub.cilj_deljenja("tv1", "fon1", datoteka=True)[2], "naprava_pri_drugem_srediscu")
        self.assertIsNone(self.hub.cilj_deljenja("tv1", "fon1"), "besedilo gre tudi prek sosednjega sredisca")


class DeljenjeVZivo(unittest.TestCase):
    """Cela zica cez TLS: Safeer Control kot posiljatelj, druga naprava kot cilj."""

    A, B = "n-aaaaaaaaaaaaaaaa", "n-bbbbbbbbbbbbbbbb"

    @classmethod
    def setUpClass(cls):
        cls.streznik = link_hub_streznik.HubStreznik()
        if not cls.streznik.zazeni():
            raise unittest.SkipTest("huba ni bilo mogoce zagnati")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.streznik.hub.deljenje = link_hub_deljenje.Deljenje(mapa=lambda: os.path.join(cls.tmp.name, "zaloga"))
        cls.naslov = "wss://127.0.0.1:%d%s" % (cls.streznik.vrata, link_hub_streznik.POT_WS)
        cls.odtis = cls.streznik.odtis
        cls.clan = {"kljuc": link_krog.javni_kljuc_b64(), "ime": "Preizkus", "platforma": "linux"}

    @classmethod
    def tearDownClass(cls):
        cls.streznik.ustavi()
        cls.tmp.cleanup()

    def _s_krogom(self):
        lazni = mock.MagicMock()
        lazni.clan_za_id.return_value = self.clan
        lazni.json.return_value = {"v": 1, "clani": {}, "umiki": {}}
        return mock.patch.object(link_krog, "krog", return_value=lazni)

    def _cilj(self, prejeto, dogodek, tip):
        p = link_hub.Povezava(self.naslov, "", self.B, "Tablica", odtis=self.odtis)
        p.v_krog = True
        p.ob_sporocilu = lambda s: (prejeto.append(s), dogodek.set()) if s.get("type") == tip else None
        return p

    def test_besedilo_in_datoteka_od_posiljatelja_do_cilja(self):
        with self._s_krogom(), mock.patch.object(link_krog, "lahko_s_podpisom", return_value=True), \
                mock.patch.object(link_krog, "sprejmi", return_value=True):
            seja = link_hub.seja_s_podpisom(self.naslov, self.A, self.odtis, "Racunalnik")
            self.assertTrue(seja, "naprava v krogu dobi sejni zeton za HTTP")

            # Cilj ni povezan: posiljatelj dobi jasno napako, ne 404 »ni te poti«.
            ok, n = link_deljenje.poslji_besedilo(self.naslov, seja, self.odtis, self.A, self.B, "Živjo")
            self.assertEqual((ok, n["koda"]), (False, "naprava_ni_povezana"))

            besedila, datoteke, prislo_b, prisla_d = [], [], threading.Event(), threading.Event()
            p = self._cilj(besedila, prislo_b, "share.text")
            izvirni = p.ob_sporocilu
            p.ob_sporocilu = lambda s: (izvirni(s), (datoteke.append(s), prisla_d.set()) if s.get("type") == "share.file" else None)
            self.assertTrue(p.poveži())
            try:
                time.sleep(0.5)
                # ---- besedilo
                ok, n = link_deljenje.poslji_besedilo(self.naslov, seja, self.odtis, self.A, self.B, "Živjo, tablica")
                self.assertTrue(ok, n)
                self.assertTrue(prislo_b.wait(5), "besedilo mora priti do cilja")
                self.assertEqual((besedila[-1]["sender"], besedila[-1]["payload"]), (self.A, {"text": "Živjo, tablica"}))
                ok, n = link_deljenje.poslji_besedilo(self.naslov, "napacen-zeton", self.odtis, self.A, self.B, "x")
                self.assertEqual((ok, n["koda"]), (False, "naprava_ni_seznanjena"))

                # ---- datoteka: oddaja, obvestilo cilju, prevzem
                vsebina = os.urandom(300_000) + "čšž".encode("utf-8")
                pot = os.path.join(self.tmp.name, "Počitnice 2026.bin")
                with open(pot, "wb") as f:
                    f.write(vsebina)
                odstotki = []
                ok, n = link_deljenje.poslji_datoteko(self.naslov, seja, self.odtis, self.A, self.B, pot, napredek=odstotki.append)
                self.assertTrue(ok, n)
                self.assertEqual(odstotki[-1], 100)
                self.assertTrue(prisla_d.wait(5), "cilj mora izvedeti za datoteko")
                tovor = datoteke[-1]["payload"]
                self.assertEqual((datoteke[-1]["sender"], tovor["name"], tovor["size"], tovor["for_host"]),
                                 (self.A, "Počitnice 2026.bin", len(vsebina), False))
                self.assertEqual(tovor["sha256"], hashlib.sha256(vsebina).hexdigest())
                self.assertTrue(tovor["path"].startswith("/cast/file/"))
                mapa = os.path.join(self.tmp.name, "prejeto")
                os.makedirs(mapa)
                # Napacen kljuc ne da nicesar.
                cilj, razlog = link_deljenje.prevzemi_datoteko(self.naslov, self.odtis, tovor["path"][:-4] + "0000",
                                                               tovor["name"], tovor["sha256"], mapa=mapa)
                self.assertIsNone(cilj, razlog)
                cilj, razlog = link_deljenje.prevzemi_datoteko(self.naslov, self.odtis, tovor["path"], tovor["name"],
                                                               tovor["sha256"], mapa=mapa)
                self.assertTrue(cilj, razlog)
                with open(cilj, "rb") as f:
                    self.assertEqual(f.read(), vsebina)
                self.assertEqual(os.path.basename(cilj), "Počitnice 2026.bin")
                # Prevzeta datoteka na Hubu ne ostane; drugi prevzem ne dobi nicesar.
                self.assertEqual(os.listdir(os.path.join(self.tmp.name, "zaloga")), [])
                cilj2, _ = link_deljenje.prevzemi_datoteko(self.naslov, self.odtis, tovor["path"], tovor["name"],
                                                           tovor["sha256"], mapa=mapa)
                self.assertIsNone(cilj2)

                # ---- brez veljavnega zetona datoteke ne sprejme (in odjemalec dobi razlog, ne prekinjene povezave)
                ok, n = link_deljenje.poslji_datoteko(self.naslov, "napacen-zeton", self.odtis, self.A, self.B, pot)
                self.assertEqual((ok, n["koda"]), (False, "naprava_ni_seznanjena"))
                self.assertEqual(os.listdir(os.path.join(self.tmp.name, "zaloga")), [])
                # Vecje telo, kot ga sredisce se zavrze: povezavo zapre sredi posiljanja; posiljatelj ne sme obviseti
                # in mora dobiti neuspeh (z razlogom, ce je odgovor se prisel, sicer »posiljanje ni uspelo«).
                velika = os.path.join(self.tmp.name, "velika.bin")
                with open(velika, "wb") as f:
                    f.write(os.urandom(3 * 1024 * 1024))
                with mock.patch.object(link_hub_streznik, "NAJVEC_ZAVRZENEGA", 64 * 1024):
                    ok, n = link_deljenje.poslji_datoteko(self.naslov, "napacen-zeton", self.odtis, self.A, self.B, velika)
                self.assertFalse(ok)
                self.assertIn(n["koda"], ("naprava_ni_seznanjena", "posiljanje_ni_uspelo"))
                self.assertEqual(os.listdir(os.path.join(self.tmp.name, "zaloga")), [])
            finally:
                p.zapri()

    def test_get_na_poti_deljenja_pove_da_pot_obstaja(self):
        osnova = link_hub._osnova(self.naslov)
        for pot in (link_hub_streznik.POT_BESEDILO, link_hub_streznik.POT_ODDAJA):
            koda, _odgovor = link_hub._zahteva(osnova + pot, None, odtis=self.odtis)
            self.assertEqual(koda, 405, pot)


if __name__ == "__main__":
    unittest.main()
