"""Deljenje zaslona prek sredisca na racunalniku (core/link_hub_deljenje.Zasloni, poti v core/link_hub_streznik).

Izmerjeno 5. 10. 2026: sredisce racunalnika poti za zaslon ni imelo (404 »Ni te poti.«), zato racunalnik racunalniku
zaslona ni mogel pokazati, zaslon s telefona pa se je na racunalniku odprl kot stran z napako - racunalnik je stran
gledalca iskal samo pri svojem sredisci, deljenje pa je sprejelo telefonovo.

Najprej logika brez omrezja (ura in casovnik sta parametra), nato pravila sredisca in na koncu cela zica cez TLS:
posiljatelj je isti razred, kot ga uporabljata Safeer Control in Safeer OS (link_deljenje.DeljenjeZaslona), gledalec
bere tok MJPEG. Sredisce v teh preizkusih tece na prostih vratih z zacasnim potrdilom in laznim krogom zaupanja -
prave identitete racunalnika in vrat 8990 se ne dotakne.
"""
import io
import json
import ssl
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_datoteke, link_deljenje, link_hub_deljenje as D, link_hub_streznik as S, link_krog, link_tls


class LaznaPovezava:
    def __init__(self):
        self.poslano = []
        self.prislo = threading.Event()

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))
        self.prislo.set()
        return True

    def zapri(self, *_a, **_k):
        pass

    def zasloni(self, dejanje=None):
        return [s for s in self.poslano if s.get("type") == "share.screen"
                and (dejanje is None or s["payload"].get("action") == dejanje)]


def _prijava(id_naprave, ime):
    return json.dumps({"id": "r1", "type": "cast.register",
                       "payload": {"device_id": id_naprave, "name": ime, "role": "receiver", "capabilities": ["url", "screen"],
                                   "platform": "linux", "protocol": "1", "kind": "computer", "version": "2.1.55"}})


def _lazni_krog():
    krog = mock.MagicMock()
    krog.clan.return_value = None
    krog.clan_za_id.return_value = None
    krog.json.return_value = {"v": 1, "clani": {}, "umiki": {}}
    return mock.patch.object(link_krog, "krog", return_value=krog)


def _okvirji(*okvirji):
    return io.BytesIO(b"".join(len(o).to_bytes(4, "big") + o for o in okvirji))


class Zaloga(unittest.TestCase):
    def setUp(self):
        self.cas = 1_000_000.0
        self.nacrtovano = []
        self.koncani = []
        self.z = D.Zasloni(ura=lambda: self.cas, casovnik=lambda cez, klic: self.nacrtovano.append((cez, klic)))
        self.z.ob_koncu = self.koncani.append

    def _sprozi(self, cez):
        """Pozene (in odstrani) nacrtovane preverbe s tem rokom."""
        zdaj = [k for c, k in self.nacrtovano if c == cez]
        self.nacrtovano = [(c, k) for c, k in self.nacrtovano if c != cez]
        for klic in zdaj:
            klic()

    def test_zacetek_da_poti_in_tovor_kot_android(self):
        z, koda, kdo = self.z.zacni("pc1", "pc2")
        self.assertEqual((koda, kdo), ("", ""))
        self.assertEqual((len(z.id), len(z.kljuc)), (16, 32))
        self.assertEqual(z.pot_potiskanja(), "/cast/screen/%s?k=%s" % (z.id, z.kljuc))
        self.assertEqual(z.tovor_zacetka(), {"action": "start", "id": z.id, "path": "/cast/screen/%s/view?k=%s" % (z.id, z.kljuc)})
        self.assertEqual(z.tovor_konca(), {"action": "stop", "id": z.id})
        self.assertIs(self.z.najdi(z.id, z.kljuc), z)
        self.assertIsNone(self.z.najdi(z.id, "0" * 32))
        self.assertIsNone(self.z.najdi(z.id, ""))
        self.assertIsNone(self.z.najdi("drug", z.kljuc))

    def test_en_zaslon_na_posiljatelja(self):
        prvi = self.z.zacni("pc1", "pc2")[0]
        drugi = self.z.zacni("pc1", "tv")[0]
        self.assertEqual([(k.id, k.razlog) for k in self.koncani], [(prvi.id, D.KONEC_POSILJATELJ)])
        self.assertFalse(prvi.tece)
        self.assertTrue(drugi.tece)
        self.assertEqual(self.z.stevilo(), 1)

    def test_z_eno_napravo_deli_naenkrat_ena(self):
        self.z.zacni("pc1", "pc2")
        self.assertEqual(self.z.zacni("fon", "pc2"), (None, "naprava_zasedena", "pc1"))
        # Isti posiljatelj z istim ciljem znova: prejsnje deljenje se konca, novo zacne.
        self.assertIsNotNone(self.z.zacni("pc1", "pc2")[0])
        # Druga naprava je prosta tudi medtem.
        self.assertIsNotNone(self.z.zacni("fon", "tv")[0])

    def test_omejeno_stevilo_zaslonov(self):
        for i in range(D.NAJVEC_ZASLONOV):
            self.assertIsNotNone(self.z.zacni("p%d" % i, "c%d" % i)[0])
        self.assertEqual(self.z.zacni("se-en", "cilj"), (None, "prevec_zaslonov", ""))

    def test_okvirji_gredo_gledalcem_in_konec_toka_konca_deljenje(self):
        z = self.z.zacni("pc1", "pc2")[0]
        g, koda = self.z.dodaj_gledalca(z)
        self.assertEqual(koda, "")
        self.assertEqual(self.z.sprejmi(z, _okvirji(b"JPEG-1", b"JPEG-22").read), 2)
        self.assertEqual((g.naslednji(0), g.naslednji(0), g.naslednji(0)), (b"JPEG-1", b"JPEG-22", None))
        self.assertEqual((z.tece, z.razlog, z.zadnji, g.konec), (False, D.KONEC_POSILJATELJ, b"JPEG-22", True))
        self.assertEqual(self.koncani, [z])
        self.assertIsNone(self.z.najdi(z.id, z.kljuc), "koncanega deljenja ni vec")

    def test_pokvarjen_tok_konca_deljenje(self):
        for tok in (b"\x00\x00\x00\x00", (D.NAJVECJI_OKVIR + 1).to_bytes(4, "big") + b"x", b"\x00\x00", b"\x00\x00\x00\x09kratek"):
            z = self.z.zacni("pc1", "pc2")[0]
            self.assertEqual(self.z.sprejmi(z, io.BytesIO(tok).read), 0, tok)
            self.assertFalse(z.tece)

    def test_molk_posiljatelja_konca_deljenje(self):
        z = self.z.zacni("pc1", "pc2")[0]

        def beri(_n):
            raise TimeoutError("brez okvirja")
        self.assertEqual(self.z.sprejmi(z, beri), 0)
        self.assertEqual((z.tece, z.razlog), (False, D.KONEC_POSILJATELJ))

    def test_en_tok_na_deljenje(self):
        z = self.z.zacni("pc1", "pc2")[0]
        z.ima_tok = True
        self.assertEqual(self.z.sprejmi(z, _okvirji(b"x").read), -1)
        self.assertTrue(z.tece, "drugi tok deljenja ne sme koncati")

    def test_gledalec_ki_ne_dohaja_izgubi_starejse_okvirje(self):
        g = D.Gledalec()
        for okvir in (b"1", b"2", b"3", b"4"):
            g.ponudi(okvir)
        self.assertEqual((g.naslednji(0), g.naslednji(0), g.naslednji(0)), (b"3", b"4", None))
        self.assertEqual(D.VRSTA_GLEDALCA, 2)

    def test_nov_gledalec_takoj_dobi_zadnjo_sliko(self):
        z = self.z.zacni("pc1", "pc2")[0]
        z.zadnji = b"ZADNJA"
        g, _ = self.z.dodaj_gledalca(z)
        self.assertEqual(g.naslednji(0), b"ZADNJA")

    def test_omejeno_stevilo_gledalcev_in_koncano_deljenje(self):
        z = self.z.zacni("pc1", "pc2")[0]
        for _ in range(D.NAJVEC_GLEDALCEV):
            self.assertIsNotNone(self.z.dodaj_gledalca(z)[0])
        self.assertEqual(self.z.dodaj_gledalca(z), (None, "prevec_gledalcev"))
        self.z.koncaj(z.id)
        self.assertEqual(self.z.dodaj_gledalca(z), (None, "ni_zaslona"))

    def test_brez_gledalcev_se_deljenje_konca(self):
        z = self.z.zacni("pc1", "pc2")[0]
        z.ima_tok = True
        g, _ = self.z.dodaj_gledalca(z)
        self.z.odstrani_gledalca(z, g)
        self.assertIn(D.BREZ_GLEDALCEV_S, [c for c, _k in self.nacrtovano])
        self.assertTrue(z.tece, "takoj se ne konca - stran gledalca se lahko nalozi znova")
        self._sprozi(D.BREZ_GLEDALCEV_S)
        self.assertEqual((z.tece, z.razlog), (False, D.KONEC_BREZ_GLEDALCEV))
        self.assertEqual(self.koncani, [z])

    def test_gledalec_ki_se_vrne_deljenja_ne_konca(self):
        z = self.z.zacni("pc1", "pc2")[0]
        g, _ = self.z.dodaj_gledalca(z)
        self.z.odstrani_gledalca(z, g)
        self.cas += 3
        g2, _ = self.z.dodaj_gledalca(z)            # stran se je nalozila znova
        self._sprozi(D.BREZ_GLEDALCEV_S)
        self.assertTrue(z.tece)
        # Odide se enkrat in se vrne tik pred rokom; stara preverba ne sme veljati za novo odsotnost.
        self.z.odstrani_gledalca(z, g2)
        self.cas += 1
        self.z.dodaj_gledalca(z)
        self._sprozi(D.BREZ_GLEDALCEV_S)
        self.assertTrue(z.tece)

    def test_deljenje_brez_gledalca_od_zacetka_tece_naprej(self):
        """Cilj strani morda se ni odprl: dokler gledalca sploh ni bilo, sredisce deljenja zaradi tega ne konca."""
        z = self.z.zacni("pc1", "pc2")[0]
        z.ima_tok = True
        self._sprozi(D.BREZ_GLEDALCEV_S)
        self._sprozi(D.ROK_ZA_TOK_S)
        self.assertTrue(z.tece)

    def test_posiljatelj_ki_toka_ne_odpre_ne_drzi_cilja(self):
        z = self.z.zacni("pc1", "pc2")[0]
        self.assertEqual(self.z.zacni("fon", "pc2")[1], "naprava_zasedena")
        self._sprozi(D.ROK_ZA_TOK_S)
        self.assertEqual((z.tece, z.razlog), (False, D.KONEC_NI_TOKA))
        self.assertIsNotNone(self.z.zacni("fon", "pc2")[0], "cilj je spet prost")

    def test_prvi_razlog_velja_in_obvestilo_je_eno(self):
        z = self.z.zacni("pc1", "pc2")[0]
        self.assertIs(self.z.koncaj(z.id, D.KONEC_BREZ_GLEDALCEV), z)
        self.assertIsNone(self.z.koncaj(z.id, D.KONEC_USTAVLJENO))
        self.assertEqual(self.z.sprejmi(z, _okvirji(b"x").read), 0)
        self.assertEqual((z.razlog, self.koncani), (D.KONEC_BREZ_GLEDALCEV, [z]))

    def test_napaka_obvestila_ne_ustavi_konca(self):
        self.z.ob_koncu = mock.Mock(side_effect=RuntimeError("cilja ni"))
        z = self.z.zacni("pc1", "pc2")[0]
        self.assertIs(self.z.koncaj(z.id), z)
        self.assertEqual(self.z.stevilo(), 0)

    def test_koncaj_vse(self):
        a, b = self.z.zacni("pc1", "pc2")[0], self.z.zacni("fon", "tv")[0]
        self.z.koncaj_vse()
        self.assertEqual({(k.id, k.razlog) for k in self.koncani}, {(a.id, D.KONEC_SREDISCE), (b.id, D.KONEC_SREDISCE)})

    def test_tok_in_stran_gledalca(self):
        self.assertEqual(D.del_toka(b"JPEG"), b"--safeerokvir\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nJPEG\r\n")
        z = self.z.zacni("pc1", "pc2", 'Pisarna <script>alert(1)</script> & "co"')[0]
        stran = D.stran_gledalca(z)
        self.assertIn('src="/cast/screen/%s/stream?k=%s"' % (z.id, z.kljuc), stran)
        self.assertIn("/cast/screen/%s/state?k=%s" % (z.id, z.kljuc), stran)
        self.assertIn('id="zaslon"', stran, "okno gledalca v Safeer Controlu sliko poisce po tem id-ju")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp;", stran)
        self.assertNotIn("<script>alert(1)", stran)
        # Samo gledanje: stran ne poslje nazaj nobenega dotika ali tipke.
        self.assertNotIn("/input", stran)
        self.assertNotIn("POST", stran)


class PravilaSredisca(unittest.TestCase):
    def setUp(self):
        krog = _lazni_krog()
        krog.start()
        self.addCleanup(krog.stop)
        self.cas = 1_000_000.0
        self.hub = S.Hub(odtis="ab" * 32, nas_id="n-pc2", ura=lambda: self.cas)
        self.hub.zasloni = D.Zasloni(ura=lambda: self.cas, casovnik=lambda *_a: None)
        self.hub.zasloni.ob_koncu = self.hub._zaslon_koncan
        self.pc2, self.fon = LaznaPovezava(), LaznaPovezava()
        self.hub.obdelaj(self.pc2, _prijava("pc2", "Računalnik v dnevni"))
        self.hub.obdelaj(self.fon, _prijava("fon1", "Telefon"))
        self.hub._zetoni["zeton-pc1"] = ("pc1", "Računalnik v pisarni", self.cas)
        self.hub._zetoni["zeton-fon"] = ("fon1", "Telefon", self.cas)
        self.hub._zetoni["zeton-pc2"] = ("pc2", "Računalnik v dnevni", self.cas)

    def test_zacetek_obvesti_cilj_in_vrne_poti(self):
        koda, odgovor = self.hub.zacni_zaslon("zeton-pc1", "pc2")
        self.assertEqual(koda, 200, odgovor)
        self.assertEqual(set(odgovor), {"id", "push_path", "view_path"})
        self.assertTrue(odgovor["push_path"].startswith("/cast/screen/%s?k=" % odgovor["id"]))
        s = self.pc2.zasloni("start")[-1]
        self.assertEqual((s["sender"], s["sender_name"], s["target"]), ("pc1", "Računalnik v pisarni", "pc2"))
        self.assertEqual(s["payload"], {"action": "start", "id": odgovor["id"], "path": odgovor["view_path"]})
        self.assertTrue(s["id"].startswith("hub-"))
        self.assertFalse(self.fon.zasloni(), "druge naprave ne izvejo nicesar")

    def test_posiljatelj_je_lastnik_zetona(self):
        for zeton in ("", "neznan"):
            koda, odgovor = self.hub.zacni_zaslon(zeton, "pc2")
            self.assertEqual((koda, odgovor["koda"], odgovor["error_code"]), (401, "naprava_ni_seznanjena", "naprava_ni_seznanjena"))
        self.assertEqual(self.hub.koncaj_zaslon("neznan", "x")[0], 401)

    def test_napake_cilja(self):
        self.assertEqual(self.hub.zacni_zaslon("zeton-pc1", "")[1]["koda"], "manjka_target")
        self.assertEqual(self.hub.zacni_zaslon("zeton-fon", "fon1")[1]["koda"], "isti_naprava")
        self.assertEqual(self.hub.zacni_zaslon("zeton-pc1", "tablica9"), (404, D.napaka("Ciljna naprava ni povezana.", "naprava_ni_povezana")))
        self.assertEqual(self.hub.zasloni.stevilo(), 0)

    def test_napravi_pri_sosednjem_sredisci_zaslona_od_tu_ne_pokazemo(self):
        """Stran gledalca cilj isce pri svojem in pri posiljateljevem sredisci (pravilo 9) - pri tretjem je ne bi nasel."""
        self.hub.najdi("fon1").sosed = "hub-telefona"
        koda, odgovor = self.hub.zacni_zaslon("zeton-pc1", "fon1")
        self.assertEqual((koda, odgovor["koda"]), (409, "naprava_pri_drugem_srediscu"))
        self.assertIn("zaslona", odgovor["napaka"])
        self.assertFalse(self.fon.zasloni())

    def test_zasedena_naprava_pove_kdo_deli(self):
        self.assertEqual(self.hub.zacni_zaslon("zeton-pc1", "pc2")[0], 200)
        koda, odgovor = self.hub.zacni_zaslon("zeton-fon", "pc2")
        self.assertEqual(koda, 409)
        self.assertEqual((odgovor["koda"], odgovor["busy_by"], odgovor["busy_by_name"], odgovor["target"]),
                         ("naprava_zasedena", "pc1", "pc1", "pc2"))
        self.assertEqual(link_deljenje.napaka_huba(koda, odgovor)["zasedenaOd"], "pc1")
        self.assertEqual(len(self.pc2.zasloni("start")), 1)

    def test_cilja_ni_mogoce_obvestiti(self):
        self.pc2.poslji = lambda _b: False
        koda, odgovor = self.hub.zacni_zaslon("zeton-pc1", "pc2")
        self.assertEqual((koda, odgovor["koda"]), (502, "posredovanje_ni_uspelo"))
        self.assertEqual(self.hub.zasloni.stevilo(), 0, "posiljatelj ne sme deliti v prazno")

    def test_konec_obvesti_cilj(self):
        id_ = self.hub.zacni_zaslon("zeton-pc1", "pc2")[1]["id"]
        # Tretja naprava deljenja ne more ustaviti (odgovor je isti - nic ne izve).
        self.assertEqual(self.hub.koncaj_zaslon("zeton-fon", id_), (200, {"stopped": True}))
        self.assertFalse(self.pc2.zasloni("stop"))
        self.assertEqual(self.hub.koncaj_zaslon("zeton-pc1", id_), (200, {"stopped": True}))
        s = self.pc2.zasloni("stop")[-1]
        self.assertEqual((s["sender"], s["target"], s["payload"]), ("pc1", "pc2", {"action": "stop", "id": id_}))
        # Ze koncano ali neznano deljenje ni napaka: posiljatelj stop poslje tudi po zaprtem toku.
        self.assertEqual(self.hub.koncaj_zaslon("zeton-pc1", id_), (200, {"stopped": True}))
        self.assertEqual(len(self.pc2.zasloni("stop")), 1)

    def test_cilj_lahko_deljenje_konca(self):
        id_ = self.hub.zacni_zaslon("zeton-pc1", "pc2")[1]["id"]
        self.hub.koncaj_zaslon("zeton-pc2", id_)
        self.assertEqual(self.hub.zasloni.stevilo(), 0)

    def test_konec_iz_zaloge_obvesti_cilj(self):
        id_ = self.hub.zacni_zaslon("zeton-pc1", "pc2")[1]["id"]
        self.hub.zasloni.koncaj(id_, D.KONEC_BREZ_GLEDALCEV)
        self.assertEqual(self.pc2.zasloni("stop")[-1]["payload"], {"action": "stop", "id": id_})

    def test_besedilo_in_datoteka_ostaneta_kot_prej(self):
        self.assertIsNone(self.hub.cilj_deljenja("pc2", "pc1"))
        self.hub.najdi("pc2").sosed = "hub-x"
        self.assertIsNone(self.hub.cilj_deljenja("pc2", "pc1"), "besedilo gre tudi prek sosednjega sredisca")
        self.assertIn("datoteke", self.hub.cilj_deljenja("pc2", "pc1", datoteka=True)[1])
        self.assertIn("zaslona", self.hub.cilj_deljenja("pc2", "pc1", zaslon=True)[1])


class _Deljenje(link_deljenje.DeljenjeZaslona):
    """Posiljatelj brez zajema zaslona: vsak okvir je drugacen, da tok tece."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.poslanih = 0

    def _okvir(self):
        self.poslanih += 1
        return b"\xff\xd8JPEG-%06d\xff\xd9" % self.poslanih


class _Sredisce:
    """Sredisce na prostih vratih 127.0.0.1 z zacasnim potrdilom; brez mDNS, sosedov in prave identitete."""

    def __init__(self, test: unittest.TestCase, nas_id: str):
        mapa = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        test.addCleanup(mapa.cleanup)
        kljuc, potrdilo, self.odtis = link_datoteke.zagotovi_potrdilo(mapa.name)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(potrdilo, kljuc)
        self.hub = S.Hub(odtis=self.odtis, nas_id=nas_id)
        self.streznik = S._Streznik(("127.0.0.1", 0), S._Obravnava)
        self.streznik.socket = ctx.wrap_socket(self.streznik.socket, server_side=True, do_handshake_on_connect=False)
        self.streznik.hub = self.hub
        self.streznik.datoteke = lambda: None
        self.vrata = self.streznik.server_address[1]
        self.naslov = "wss://127.0.0.1:%d%s" % (self.vrata, S.POT_WS)
        self.osnova = "https://127.0.0.1:%d" % self.vrata
        threading.Thread(target=self.streznik.serve_forever, daemon=True).start()
        test.addCleanup(self.ustavi)

    def ustavi(self):
        self.hub.zasloni.koncaj_vse()
        self.streznik.shutdown()
        self.streznik.server_close()

    def naprava(self, id_naprave, ime):
        p = LaznaPovezava()
        self.hub.obdelaj(p, _prijava(id_naprave, ime))
        return p

    def zeton(self, id_naprave, ime):
        zeton = "zeton-" + id_naprave
        self.hub._zetoni[zeton] = (id_naprave, ime, time.time())
        return zeton


class _Gledalec:
    """Bere tok MJPEG s sredisca, kot ga bere <img> na strani gledalca."""

    def __init__(self, sredisce: _Sredisce, pot: str):
        self.povezava = link_tls._PripetaHttps("127.0.0.1", sredisce.vrata, sredisce.odtis, 5.0)
        self.povezava.request("GET", pot)
        self.odgovor = self.povezava.getresponse()

    def okvir(self):
        """Naslednji okvir ali None ob koncu toka."""
        vrstica = self.odgovor.readline()
        while vrstica in (b"\r\n", b"\n"):
            vrstica = self.odgovor.readline()
        if vrstica.strip() != b"--" + D.MEJA_TOKA.encode("ascii"):
            return None
        dolzina = 0
        while True:
            glava = self.odgovor.readline().strip()
            if not glava:
                break
            if glava.lower().startswith(b"content-length:"):
                dolzina = int(glava.split(b":", 1)[1])
        return self.odgovor.read(dolzina)

    def zapri(self):
        # Odgovor brez dolzine (Connection: close) si povezavo vzame: zapreti je treba NJEGA, sicer vticnik ostane odprt.
        for kaj in (self.odgovor, self.povezava):
            try:
                kaj.close()
            except Exception:
                pass


def _pocakaj(pogoj, najvec_s=6.0):
    konec = time.monotonic() + najvec_s
    while time.monotonic() < konec:
        if pogoj():
            return True
        time.sleep(0.02)
    return bool(pogoj())


class CelaZica(unittest.TestCase):
    """Racunalnik (pc1) deli zaslon z racunalnikom (pc2) prek sredisca pc2 - kot v Link Meshu (pravilo 9)."""

    def setUp(self):
        krog = _lazni_krog()
        krog.start()
        self.addCleanup(krog.stop)
        hitreje = mock.patch.object(link_deljenje, "RAZMIK_S", 0.02)
        hitreje.start()
        self.addCleanup(hitreje.stop)
        self.s = _Sredisce(self, "n-pc2")
        self.cilj = self.s.naprava("pc2", "Računalnik v dnevni")
        self.zeton = self.s.zeton("pc1", "Računalnik v pisarni")
        self.stanja = []

    def _deli(self, zeton=None):
        d = _Deljenje(self.s.naslov, zeton or self.zeton, self.s.odtis, "pc1", "pc2", "Računalnik v dnevni",
                      ob_spremembi=lambda st: self.stanja.append(dict(st)))
        d.zacni()
        self.addCleanup(d.ustavi)
        return d

    def _zacetek(self):
        self.assertTrue(_pocakaj(lambda: self.cilj.zasloni("start")), "cilj mora izvedeti za deljenje")
        return self.cilj.zasloni("start")[-1]["payload"]

    def test_zaslon_od_posiljatelja_do_gledalca_in_konec(self):
        d = self._deli()
        tovor = self._zacetek()
        self.assertTrue(_pocakaj(lambda: d.tece), self.stanja)
        # Stran gledalca, kot jo odpre ciljna naprava.
        p = link_tls._PripetaHttps("127.0.0.1", self.s.vrata, self.s.odtis, 5.0)
        p.request("GET", tovor["path"])
        o = p.getresponse()
        stran = o.read().decode("utf-8")
        p.close()
        self.assertEqual((o.status, o.getheader("Content-Type")), (200, "text/html; charset=utf-8"))
        self.assertIn("Računalnik v pisarni", stran)
        tok = stran.split('src="', 1)[1].split('"', 1)[0]
        stanje = tok.replace("/stream?", "/state?")
        self.assertEqual(link_tls.zahteva(self.s.osnova + stanje, None, pripeti=self.s.odtis)[0], 200)

        g = _Gledalec(self.s, tok)
        self.addCleanup(g.zapri)
        self.assertEqual(g.odgovor.status, 200)
        self.assertEqual(g.odgovor.getheader("Content-Type"), "multipart/x-mixed-replace; boundary=safeerokvir")
        okvirji = [g.okvir() for _ in range(3)]
        for okvir in okvirji:
            self.assertTrue(okvir and okvir.startswith(b"\xff\xd8JPEG-") and okvir.endswith(b"\xff\xd9"), okvir)
        self.assertEqual(len(set(okvirji)), 3)

        d.ustavi()
        self.assertTrue(_pocakaj(lambda: self.cilj.zasloni("stop")), "cilj mora izvedeti za konec")
        self.assertEqual(self.cilj.zasloni("stop")[-1]["payload"], {"action": "stop", "id": tovor["id"]})
        while g.okvir() is not None:      # tok gledalca se konca, ne obvisi
            pass
        self.assertTrue(_pocakaj(lambda: self.stanja and not self.stanja[-1]["tece"]))
        self.assertEqual((self.stanja[-1]["napaka"], self.stanja[-1]["koda"]), ("", ""))
        self.assertEqual(self.s.hub.zasloni.stevilo(), 0)
        # Po koncu: stran pove, da je deljenja konec; stanja in toka ni vec.
        p = link_tls._PripetaHttps("127.0.0.1", self.s.vrata, self.s.odtis, 5.0)
        p.request("GET", tovor["path"])
        o = p.getresponse()
        self.assertEqual(o.status, 404)
        self.assertIn("text/html", o.getheader("Content-Type"))
        o.read()
        p.close()
        koda, odgovor, _ = link_tls.zahteva(self.s.osnova + stanje, None, pripeti=self.s.odtis)
        self.assertEqual((koda, odgovor["koda"]), (404, "ni_zaslona"))

    def test_ko_cilj_neha_gledati_posiljatelj_izve_da_ni_napaka(self):
        with mock.patch.object(D, "BREZ_GLEDALCEV_S", 0.2):
            d = self._deli()
            tovor = self._zacetek()
            g = _Gledalec(self.s, tovor["path"].replace("/view?", "/stream?"))
            self.assertTrue(g.okvir())
            g.zapri()                                   # uporabnik je okno gledalca zaprl
            self.assertTrue(_pocakaj(lambda: self.stanja and not self.stanja[-1]["tece"] and not d.tece, 10.0), self.stanja)
        zadnje = self.stanja[-1]
        self.assertEqual(zadnje["koda"], "konec_pri_napravi", zadnje)
        self.assertEqual(zadnje["napaka"], link_deljenje.SPOROCILA_ZASLONA["konec_pri_napravi"])
        self.assertNotIn("padlo", zadnje["napaka"])
        self.assertTrue(_pocakaj(lambda: self.cilj.zasloni("stop")))
        self.assertEqual(self.s.hub.zasloni.stevilo(), 0)

    def test_zasedena_naprava(self):
        self._deli()
        self._zacetek()
        zeton_fon = self.s.zeton("fon1", "Telefon")
        koda, odgovor, _ = link_tls.zahteva(self.s.osnova + S.POT_ZASLON_START, {"device_id": "fon1", "target": "pc2"},
                                            zeton=zeton_fon, pripeti=self.s.odtis)
        self.assertEqual((koda, odgovor["koda"], odgovor["busy_by"]), (409, "naprava_zasedena", "pc1"))

    def test_okvirje_potiska_samo_naprava_ki_je_deljenje_zacela(self):
        koda, odgovor, _ = link_tls.zahteva(self.s.osnova + S.POT_ZASLON_START, {"target": "pc2"},
                                            zeton=self.zeton, pripeti=self.s.odtis)
        self.assertEqual(koda, 200, odgovor)
        pot = odgovor["push_path"]

        def potisni(pot_, zeton):
            p = link_tls._PripetaHttps("127.0.0.1", self.s.vrata, self.s.odtis, 5.0)
            try:
                p.request("POST", pot_, body=b"", headers={"X-Safeer-Token": zeton} if zeton else {})
                o = p.getresponse()
                return o.status, json.loads(o.read().decode("utf-8"))
            finally:
                p.close()

        self.assertEqual(potisni(pot, "")[0], 401)
        self.assertEqual(potisni(pot, "ni-zeton")[1]["koda"], "naprava_ni_seznanjena")
        koda, telo = potisni(pot, self.s.zeton("fon1", "Telefon"))
        self.assertEqual((koda, telo["koda"]), (403, "tuje_deljenje"))
        self.assertEqual(potisni(pot + "0", self.zeton)[1]["koda"], "ni_zaslona")
        self.assertEqual(potisni(pot.replace("?k=", "/input?k="), self.zeton)[0], 404, "dotika nazaj sredisce racunalnika ne posreduje")
        self.assertEqual(self.s.hub.zasloni.stevilo(), 1, "zavrnjeni poskusi deljenja ne koncajo")
        # Pravi lastnik, ki okvirjev ne poslje: po roku molka se deljenje konca z odgovorom.
        with mock.patch.object(D, "BREZ_OKVIRJA_S", 0.3):
            koda, telo = potisni(pot, self.zeton)
        self.assertEqual((koda, telo["koncano"], telo["razlog"], telo["okvirjev"]), (200, True, D.KONEC_POSILJATELJ, 0))
        self.assertEqual(self.s.hub.zasloni.stevilo(), 0)

    def test_poti_zaslona_niso_get_in_neznane_poti_ostanejo_neznane(self):
        for pot in (S.POT_ZASLON_START, S.POT_ZASLON_STOP):
            self.assertEqual(link_tls.zahteva(self.s.osnova + pot, None, pripeti=self.s.odtis)[0], 405, pot)
        koda, odgovor, _ = link_tls.zahteva(self.s.osnova + "/cast/screen/abc/karkoli?k=x", None, pripeti=self.s.odtis)
        self.assertEqual((koda, odgovor["code"]), (404, "ni_poti"))
        koda, odgovor, _ = link_tls.zahteva(self.s.osnova + "/cast/screen/abc/stream?k=x", None, pripeti=self.s.odtis)
        self.assertEqual((koda, odgovor["koda"]), (404, "ni_zaslona"))

    def test_stran_gledalca_najdemo_pri_sredisci_ki_je_deljenje_sprejelo(self):
        """Telefon deljenje zacne pri SVOJEM sredisci; racunalnik stran gledalca najprej isce pri svojem (404), nato
        pri telefonovem."""
        telefonovo = _Sredisce(self, "n-fon")
        telefonovo.naprava("pc2", "Računalnik v dnevni")
        koda, odgovor, _ = link_tls.zahteva(telefonovo.osnova + S.POT_ZASLON_START, {"target": "pc2"},
                                            zeton=telefonovo.zeton("fon1", "Telefon"), pripeti=telefonovo.odtis)
        self.assertEqual(koda, 200, odgovor)
        pot = odgovor["view_path"]
        nase, tuje = (self.s.naslov, self.s.odtis), (telefonovo.naslov, telefonovo.odtis)
        self.assertEqual(link_deljenje.gledalec_pri_srediscih([nase, tuje], pot), (telefonovo.osnova + pot, telefonovo.odtis))
        self.assertEqual(link_deljenje.gledalec_pri_srediscih([tuje, nase], pot), (telefonovo.osnova + pot, telefonovo.odtis))
        self.assertEqual(link_deljenje.gledalec_pri_srediscih([nase], pot), ("", ""))
        self.assertEqual(link_deljenje.gledalec_pri_srediscih([], pot), ("", ""))
        # Sredisce z drugim potrdilom, nedosegljivo sredisce in manjkajoc odtis ne ustavijo iskanja.
        prosta = _Sredisce(self, "n-x")
        prosta.ustavi()
        self.assertEqual(link_deljenje.gledalec_pri_srediscih(
            [(telefonovo.naslov, "00" * 32), (prosta.naslov, prosta.odtis), (telefonovo.naslov, ""), tuje], pot, timeout=1.0),
            (telefonovo.osnova + pot, telefonovo.odtis))


if __name__ == "__main__":
    unittest.main()
