"""Knjiznica kroga na racunalniku (polica »Na tvojih napravah« v Medijskem centru): core/knjiznica_kroga.py in del v
MediaCenter (opis lastnega prenosa, zasebnost dodatka iz manifesta, predvajanje naravnost iz torrenta).
Brez omrezja, brez Linka in brez rqbit."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import knjiznica_kroga as kk, link_datoteke, media_servers, os_media, os_torrent, os_torrent_tok as tt  # noqa: E402

H1, H2, H3, H4 = "a" * 40, "b" * 40, "c" * 40, "d" * 40
KOREN, ZASEBEN, MRTEV = "https://dodatek.primer.si", "https://zaseben.primer.si", "https://mrtev.primer.si"
PLAKAT = "https://slike.primer.si/film.jpg"


class Opis(unittest.TestCase):
    def test_javni_film_dobi_naslov_plakat_in_oznako_izvirnika(self):
        o = kk.opis_vnosa({"id": "stremio:s1:movie:tt1", "naslov": " Film ena ", "slika": PLAKAT, "vrsta": "film"}, False)
        self.assertEqual(o, {"title": "Film ena", "poster": PLAKAT, "kind": "movie", "ref": "stremio:s1:movie:tt1", "private": False})

    def test_epizoda_dobi_sezono_in_epizodo_plakat_samo_https(self):
        o = kk.opis_vnosa({"naslov": "Serija", "vrsta": "serija", "sezona": 2, "epizoda": 5, "slika": "http://x/p.jpg"}, False)
        self.assertEqual((o["title"], o["kind"], o["poster"]), ("Serija S02E05", "series", ""))
        self.assertEqual(kk.opis_vnosa({"naslov": "Serija S02E05 Naslov", "vrsta": "serija", "sezona": 2, "epizoda": 5}, False)["title"],
                         "Serija S02E05 Naslov")

    def test_zaseben_ali_neznan_dodatek_ostane_brez_naslova(self):
        for zaseben in (True, None):
            self.assertEqual(kk.opis_vnosa({"naslov": "Naslov", "slika": PLAKAT}, zaseben), {"private": True})


class Zapisi(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.raba = os.path.join(self.mapa, "raba-gledanje.json")
        self.opisi = kk.pot_opisov(self.raba)

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)

    def _lokalni(self, na_disku=None):
        na_disku = na_disku or {}
        with mock.patch.object(link_datoteke, "ze_preneseno", lambda h, i, m=None: na_disku.get(h, ("", -1))):
            return kk.lokalni(self.raba, self.opisi)

    def test_opisi_gledanja_so_loceni_od_opisov_controla(self):
        self.assertEqual(os.path.basename(self.opisi), "opisi-gledanje.json")
        self.assertNotEqual(self.opisi, link_datoteke._pot_opisov(self.raba))

    def test_prenos_z_naslovom_je_na_polici_zaseben_in_brez_naslova_ne(self):
        for h in (H1, H2, H3):
            link_datoteke.zabelezi_rabo(h, self.raba)
        kk.zabelezi(H1, {"title": "Film ena", "poster": PLAKAT, "kind": "movie", "ref": "r1", "private": False}, 1, self.opisi)
        kk.zabelezi(H2, {"private": True}, 0, self.opisi)
        film = os.path.join(self.mapa, "Film.mkv")
        with open(film, "wb") as d:
            d.write(b"x" * 7)
        vnosi = self._lokalni({H1: (film, 1)})
        self.assertEqual(len(vnosi), 1)
        self.assertEqual({k: vnosi[0][k] for k in ("hash", "title", "poster", "kind", "ref", "file", "finished", "size")},
                         {"hash": H1, "title": "Film ena", "poster": PLAKAT, "kind": "movie", "ref": "r1", "file": 1,
                          "finished": True, "size": 7})
        self.assertNotIn("private", json.dumps(vnosi))
        # Zasebni zapis ne hrani ne naslova ne plakata.
        self.assertEqual(link_datoteke._beri_opise(self.opisi)[H2], {"private": True})

    def test_kar_je_enkrat_zasebno_ostane_zasebno(self):
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"private": True}, None, self.opisi)
        kk.zabelezi(H1, {"title": "Naslov", "poster": PLAKAT, "private": False}, 0, self.opisi)
        self.assertEqual(link_datoteke._beri_opise(self.opisi)[H1], {"private": True})
        self.assertEqual(self._lokalni(), [])

    def test_prenos_ki_se_se_prenasa_je_na_polici_brez_velikosti(self):
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"title": "Film", "private": False}, 2, self.opisi)
        v = self._lokalni()[0]
        self.assertEqual((v["finished"], v["size"], v["file"], v["magnet"]), (False, 0, 2, "magnet:?xt=urn:btih:" + H1))

    def test_opis_prenosa_ki_ga_ni_vec_med_zapisi_rabe_se_pobrise(self):
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"title": "Ostane", "private": False}, None, self.opisi)
        kk.zabelezi(H2, {"title": "Odstranjen", "private": False}, None, self.opisi)
        self.assertEqual([v["title"] for v in self._lokalni()], ["Ostane"])
        self.assertEqual(list(link_datoteke._beri_opise(self.opisi)), [H1])

    def test_odstranitev_lokalnega_prenosa_samo_iz_zapisa_rabe(self):
        class Motor:
            def __init__(self):
                self.torrenti, self.odstranjeni = {H1: 1, H2: 2}, []

            def tece(self):
                return True

            def seznam(self):
                return [{"id": t, "hash": h} for h, t in self.torrenti.items()]

            def odstrani(self, tid, z_datotekami=False):
                self.odstranjeni.append((tid, z_datotekami))
                return True
        m = Motor()
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"title": "Film", "private": False}, None, self.opisi)
        self.assertFalse(kk.odstrani_lokalnega(H2, m, self.raba))              # uporabnikov torrent: polica se ga ne dotika
        self.assertEqual(m.odstranjeni, [])
        self.assertTrue(kk.odstrani_lokalnega(H1, m, self.raba))
        self.assertEqual(m.odstranjeni, [(1, True)])                          # z datotekami
        self.assertEqual(link_datoteke._beri_rabo(self.raba), {})
        self.assertEqual(link_datoteke._beri_opise(self.opisi), {})

    def test_motor_ki_po_zagonu_torrenta_se_ne_nasteje_ne_pomeni_da_ga_ni(self):
        """Pocasen disk (v zivo na Windows): takoj po zagonu je seznam motorja prazen, torrent pa je v njegovi seji.
        Odstranitev pocaka; ce ga motor ne pokaze, zapis OSTANE (sicer bi datoteke ostale brez zapisa za vedno)."""
        stanje = os.path.join(self.mapa, "stanje")
        os.makedirs(stanje)
        with open(os.path.join(stanje, "session.json"), "w", encoding="utf-8") as d:
            json.dump({"torrents": {"1": {"info_hash": H1.upper(), "output_folder": self.mapa}}}, d)

        class Motor:
            mapa_stanja = stanje

            def __init__(self, pripravljen_po):
                self.klici, self.pripravljen_po, self.odstranjeni = 0, pripravljen_po, []

            def tece(self):
                return True

            def seznam(self):
                self.klici += 1
                return [{"id": 1, "hash": H1}] if self.klici > self.pripravljen_po else []

            def odstrani(self, tid, z_datotekami=False):
                self.odstranjeni.append((tid, z_datotekami))
                return True
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"title": "Film", "private": False}, None, self.opisi)
        self.assertTrue(link_datoteke.v_seji_motorja(Motor(0), H1))
        self.assertFalse(link_datoteke.v_seji_motorja(Motor(0), H2))
        m = Motor(3)                                                         # prve tri poizvedbe: prazen seznam
        self.assertTrue(kk.odstrani_lokalnega(H1, m, self.raba, spanec=lambda s: None))
        self.assertEqual(m.odstranjeni, [(1, True)])
        # Motor torrenta ne pokaze niti po cakanju: nic ne pozabimo.
        link_datoteke.zabelezi_rabo(H1, self.raba)
        kk.zabelezi(H1, {"title": "Film", "private": False}, None, self.opisi)
        nikoli = Motor(10 ** 9)
        with mock.patch.object(kk, "CAKANJE_MOTORJA_S", 0.0):
            self.assertFalse(kk.odstrani_lokalnega(H1, nikoli, self.raba, spanec=lambda s: None))
        self.assertEqual(nikoli.odstranjeni, [])
        self.assertIn(H1, link_datoteke._beri_rabo(self.raba))
        self.assertIn(H1, link_datoteke._beri_opise(self.opisi))
        # Samodejno ciscenje v istem primeru zapisa ne zavrze (sicer filma ne bi odstranilo nikoli).
        self.assertEqual(tt.pocisti(nikoli, self.raba, zdaj=10 ** 12), [])
        self.assertIn(H1, link_datoteke._beri_rabo(self.raba))
        self.assertEqual(link_datoteke.pocisti_neuporabljene(nikoli, self.raba, zdaj=10 ** 12), [])
        self.assertIn(H1, link_datoteke._beri_rabo(self.raba))


def _naprava(id_, ime, zmoznosti, vrsta="screen", platforma="phone", ta=False):
    return {"id": id_, "ime": ime, "zmoznosti": zmoznosti, "vrsta": vrsta, "platforma": platforma, "ta": ta}


TELEFON = _naprava("n-telefon", "Telefon", ["remote", "magnet", "torrent"])
TV_STAR = _naprava("n-tv", "TV", ["remote", "magnet"], platforma="tv")           # starejsi Safeer OS brez pomoci
RACUNALNIK = _naprava("n-pc-control", "Racunalnik", ["remote", "magnet"], "control", "windows")
TA = _naprava("n-jaz-control", "Ta racunalnik", ["remote", "magnet"], "control", "linux", ta=True)


class Polica(unittest.TestCase):
    def test_brez_dvojnikov_prednost_ta_racunalnik_nato_racunalniki_nato_naprave(self):
        vnos = lambda h, naslov, **k: dict({"id": 3, "magnet": "magnet:?xt=urn:btih:" + h, "title": naslov, "size": 5, "finished": True}, **k)
        p = kk.polica([{"hash": H1, "title": "Tukaj", "magnet": "magnet:?xt=urn:btih:" + H1, "finished": False, "size": 0}], [
            {"id": "n-telefon", "ime": "Telefon", "racunalnik": False, "ta": False, "items": [vnos(H1, "Na telefonu"), vnos(H2, "Dva na telefonu")]},
            {"id": "n-pc", "ime": "PC", "racunalnik": True, "ta": False, "items": [vnos(H2, "Dva na PC", kind="series", poster=PLAKAT, file=4)]},
        ])
        self.assertEqual([(v["kljuc"], v["naslov"], v["naprava"]["id"]) for v in p],
                         [(H1, "Tukaj", kk.TUKAJ), (H2, "Dva na PC", "n-pc")])
        self.assertEqual((p[0]["naprava"]["tukaj"], p[1]["naprava"]["tukaj"]), (True, False))
        self.assertEqual((p[1]["vrsta"], p[1]["slika"], p[1]["datoteka"], p[1]["id"], p[1]["koncano"], p[1]["velikost"]),
                         ("serija", PLAKAT, 4, 3, True, 5))

    def test_zasebnega_in_vnosa_brez_naslova_ni_na_polici(self):
        p = kk.polica([], [{"id": "n-pc", "ime": "PC", "racunalnik": True, "ta": False, "items": [
            {"id": 1, "magnet": "magnet:?xt=urn:btih:" + H1, "private": True},
            {"id": 2, "magnet": "magnet:?xt=urn:btih:" + H2, "name": "surovo.ime.torrenta.mkv"},
            {"id": 3, "magnet": "brez hasha", "title": "Brez hasha"},
            {"id": 4, "magnet": "magnet:?xt=urn:btih:" + H3, "title": "Film", "poster": "http://ni-https/p.jpg"}]}])
        self.assertEqual([(v["naslov"], v["slika"]) for v in p], [("Film", "")])
        self.assertNotIn("surovo", json.dumps(p))


class Krog(unittest.TestCase):
    """Knjiznica z nadomestnim Linkom."""

    def setUp(self):
        self.klici = []
        self.odgovori = {}
        self.k = kk.Knjiznica(lambda: [TELEFON, TV_STAR, RACUNALNIK, TA], self._ukaz, lokalni=lambda: [], spanec=lambda s: None)

    def _ukaz(self, id_, dejanje, parametri, cas):
        self.klici.append((id_, dejanje, dict(parametri)))
        o = self.odgovori.get((id_, dejanje))
        if isinstance(o, list):
            o = o.pop(0) if len(o) > 1 else o[0]
        return o if o is not None else {"ok": False, "koda": "neznano_dejanje"}

    @staticmethod
    def _seznam(*vnosi):
        return {"ok": True, "data": {"items": list(vnosi)}}

    @staticmethod
    def _vnos(h, naslov, tid=7, **k):
        return dict({"id": tid, "magnet": "magnet:?xt=urn:btih:%s&dn=surovo.ime" % h, "title": naslov, "size": 9, "finished": True, "file": 2}, **k)

    def test_vprasa_samo_naprave_ki_znajo_seznam_in_strani_ne_da_magneta(self):
        self.odgovori[("n-telefon", "magnet.list")] = self._seznam(self._vnos(H1, "Film na telefonu", poster=PLAKAT))
        self.odgovori[("n-jaz-control", "magnet.list")] = self._seznam(self._vnos(H2, "Film na tem racunalniku"))
        s = self.k.seznam()
        self.assertEqual(sorted(k[0] for k in self.klici), ["n-jaz-control", "n-pc-control", "n-telefon"])   # TV brez "torrent" ne
        self.assertEqual([(v["naslov"], v["naprava"]["ime"], v["naprava"]["tukaj"]) for v in s],
                         [("Film na tem racunalniku", "Ta racunalnik", True), ("Film na telefonu", "Telefon", False)])
        self.assertEqual(sorted(s[0]), ["kljuc", "koncano", "naprava", "naslov", "obdrzi", "slika", "velikost", "vrsta"])
        self.assertNotIn("magnet", json.dumps(s))
        self.assertNotIn("surovo", json.dumps(s))

    def test_naprava_ki_ne_odgovori_police_ne_zadrzi(self):
        def ukaz(id_, dejanje, parametri, cas):
            if id_ == "n-telefon":
                raise OSError("ni povezave")
            return self._seznam(self._vnos(H1, "Film")) if id_ == "n-pc-control" else {"ok": False, "koda": "cas"}
        k = kk.Knjiznica(lambda: [TELEFON, RACUNALNIK, TA], ukaz, lokalni=lambda: [])
        self.assertEqual([v["naslov"] for v in k.seznam()], ["Film"])

    def test_predvaja_naprava_ki_film_hrani_android_najprej_odgovori_pending(self):
        self.odgovori[("n-telefon", "magnet.list")] = self._seznam(self._vnos(H1, "Film", poster=PLAKAT, kind="series", ref="r9"))
        self.k.seznam()
        streznik = {"base_url": "https://192.168.0.9:8443/", "fp": "AA", "token": "zeton"}
        self.odgovori[("n-telefon", "magnet.stream")] = [
            {"ok": True, "data": {"pending": True}}, {"ok": False, "koda": "cas"},
            {"ok": True, "data": {"server": streznik, "path": "/magnet/skrivnost", "name": "f.mkv"}}]
        self.klici.clear()
        r = self.k.predvajaj(H1)
        self.assertEqual(len(self.klici), 3)
        self.assertEqual(self.klici[0], ("n-telefon", "magnet.stream", {"uri": "magnet:?xt=urn:btih:%s&dn=surovo.ime" % H1, "file": 2,
                                                                     "title": "Film", "poster": PLAKAT, "kind": "series", "ref": "r9"}))
        self.assertEqual((r["ok"], r["tok"]), (True, {"server": streznik, "path": "/magnet/skrivnost", "name": "f.mkv", "subs": []}))
        self.assertEqual((r["vnos"]["naslov"], r["vnos"]["naprava"]["id"], r["vnos"]["ref"]), ("Film", "n-telefon", "r9"))

    def test_napaka_pomocnika_je_kratka_koda_in_nic_se_ne_predvaja(self):
        self.odgovori[("n-telefon", "magnet.list")] = self._seznam(self._vnos(H1, "Film"))
        self.k.seznam()
        self.odgovori[("n-telefon", "magnet.stream")] = {"ok": False, "koda": "ni_prostora"}
        self.assertEqual(self.k.predvajaj(H1), {"ok": False, "koda": "ni_prostora"})
        self.odgovori[("n-telefon", "magnet.stream")] = {"ok": True, "data": {"server": "ni slovar", "path": "/x"}}
        self.assertEqual(self.k.predvajaj(H1), {"ok": False, "koda": "napaka"})
        self.assertEqual(self.k.predvajaj(H4), {"ok": False, "koda": "ni_prenosa"})

    def test_prenos_motorja_safeer_os_predvaja_klicatelj(self):
        k = kk.Knjiznica(lambda: [], lambda *a: self.fail("ne prek Linka"),
                         lokalni=lambda: [{"hash": H1, "title": "Moj film", "magnet": "magnet:?xt=urn:btih:" + H1, "file": 1, "ref": "r1"}])
        self.assertEqual(k.seznam()[0]["naprava"], {"id": kk.TUKAJ, "ime": "", "tukaj": True})
        r = k.predvajaj(H1.upper())
        self.assertEqual((r["ok"], r["tukaj"]["kljuc"], r["tukaj"]["datoteka"], r["tukaj"]["ref"]), (True, H1, 1, "r1"))

    def test_odstrani_z_naprave_ki_ga_hrani(self):
        self.odgovori[("n-pc-control", "magnet.list")] = self._seznam(self._vnos(H1, "Film", tid=12))
        self.k.seznam()
        self.odgovori[("n-pc-control", "magnet.remove")] = {"ok": True}
        self.assertTrue(self.k.odstrani(H1))
        self.assertEqual(self.klici[-1], ("n-pc-control", "magnet.remove", {"id": 12}))
        self.assertIsNone(self.k.vnos(H1))
        self.assertFalse(self.k.odstrani(H1))
        odstranjeni = []
        k = kk.Knjiznica(lambda: [], self._ukaz,
                         lokalni=lambda: [{"hash": H2, "title": "Moj", "magnet": "magnet:?xt=urn:btih:" + H2}])
        k.seznam()
        self.assertTrue(k.odstrani(H2, lambda v: odstranjeni.append(v["kljuc"]) or True))
        self.assertEqual(odstranjeni, [H2])


class Pretok(unittest.TestCase):
    """Tok torrenta z druge naprave gre skozi lokalni pretok (pripet odtis, zeton) - samo pot toka, samo doma."""

    STREZNIK = {"base_url": "https://192.168.0.9:8443/", "fp": "AA:BB", "token": "zeton"}

    def test_vir_toka_sprejme_samo_pot_toka_na_domacem_naslovu(self):
        from core import link_pretok
        v = link_pretok.vir_toka(self.STREZNIK, "/magnet/Skrivnost_12-ab", "video/x-matroska")
        self.assertEqual((v.base_url, v.odtis, v.zeton, v.pot, v.mime), ("https://192.168.0.9:8443", "AA:BB", "zeton", "/magnet/Skrivnost_12-ab", "video/x-matroska"))
        self.assertEqual(link_pretok.vir_toka(self.STREZNIK, "/m/abcdefgh12345678/Film%20ena.mkv").pot, "/m/abcdefgh12345678/Film%20ena.mkv")
        self.assertIsNotNone(link_pretok.vir_toka(self.STREZNIK, "/m/abcdefgh12345678/Film..2020.mkv"))
        for slaba in ("/d/disk:%2Fetc%2Fpasswd", "/m/abcdefgh/../../d/x", "/m/abcdefgh12345678/..", "/m/kratka/x.mkv", "/magnet/abcdefgh12345678?t=1", "magnet/abcdefgh12345678", ""):
            self.assertIsNone(link_pretok.vir_toka(self.STREZNIK, slaba), slaba)
        self.assertIsNone(link_pretok.vir_toka(dict(self.STREZNIK, base_url="https://8.8.8.8:443"), "/magnet/abcdefgh12345678"))
        self.assertIsNone(link_pretok.vir_toka(dict(self.STREZNIK, base_url="http://192.168.0.9:8080"), "/magnet/abcdefgh12345678"))
        self.assertIsNone(link_pretok.vir_toka(dict(self.STREZNIK, token=""), "/magnet/abcdefgh12345678"))

    def test_datoteke_naprav_gredo_po_starem(self):
        from core import link_pretok
        self.assertEqual(link_pretok.vir_iz_streznika(self.STREZNIK, "disk:/film.mkv").pot, "")


class MedijskiCenter(unittest.TestCase):
    """Safeer OS si ob predvajanju filma iz torrenta zapomni opis; zasebnost pove manifest dodatka."""

    ODGOVORI = {
        KOREN + "/manifest.json": {"id": "si.test", "name": "Test", "resources": ["catalog", "stream"], "types": ["movie"], "catalogs": []},
        ZASEBEN + "/manifest.json": {"id": "si.zaseben", "name": "Zaseben", "resources": ["stream"], "types": ["movie"], "catalogs": [],
                                    "behaviorHints": {"adult": True}},
        KOREN + "/stream/movie/tt0000001.json": {"streams": [{"name": "T", "title": "Film 1080p \U0001F464 120", "infoHash": H1, "fileIdx": 1}]},
        KOREN + "/stream/movie/tt0000002.json": {"streams": []},
        ZASEBEN + "/stream/movie/tt0000002.json": {"streams": [{"name": "Z", "infoHash": H2}]},
        ZASEBEN + "/stream/movie/tt0000001.json": {"streams": []},
        KOREN + "/stream/movie/tt0000003.json": {"streams": []},
        ZASEBEN + "/stream/movie/tt0000003.json": {"streams": []},
        MRTEV + "/stream/movie/tt0000003.json": {"streams": [{"name": "M", "infoHash": H3}]},
        MRTEV + "/stream/movie/tt0000001.json": {"streams": []},
        MRTEV + "/stream/movie/tt0000002.json": {"streams": []},
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raba = os.path.join(self.tmp, "raba-gledanje.json")
        self.mc = os_media.MediaCenter(self.tmp, roots=[], secret_encryptor=lambda s: s, secret_decryptor=lambda s: s)
        data = self.mc._load()
        data["osebni_strezniki"] = [{"id": "s%d" % i, "vrsta": "streznik", "ponudnik": "stremio", "ime": "Dodatek %d" % i, "url": k + "/manifest.json"}
                                    for i, k in enumerate((KOREN, ZASEBEN, MRTEV))]
        self.mc._save(data)

        def zahteva(url, headers=None, body=None, raw=None):
            if url not in self.ODGOVORI:
                raise OSError("HTTP 500 " + url)
            return json.dumps(self.ODGOVORI[url]).encode()

        def pripravi(hash_, indeks=None, ime="", sledilniki=()):
            self.pripravljeni.append((hash_, indeks))
            return {"url": "http://127.0.0.1:5555/t/x/Film.mkv", "ime": "Film.mkv", "indeks": 1 if indeks is None else indeks,
                    "velikost": 1, "podnapisi": [], "zacasen": self.zacasen}
        self.pripravljeni, self.zacasen = [], True
        self.popravki = [mock.patch.object(media_servers, "_request", zahteva),
                         mock.patch.dict(os_media.TMDB_TO_IMDB, {"11": "tt0000001", "12": "tt0000002", "13": "tt0000003"}),
                         mock.patch.object(tt, "podprto", lambda: True), mock.patch.object(tt, "pripravi", pripravi),
                         mock.patch.object(tt, "pot_rabe", lambda: self.raba)]
        for p in self.popravki:
            p.start()

    def tearDown(self):
        for p in self.popravki:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _opisi(self):
        return link_datoteke._beri_opise(kk.pot_opisov(self.raba))

    def test_manifest_pove_ali_je_dodatek_zaseben(self):
        self.assertFalse(media_servers.stremio_je_zaseben(self.ODGOVORI[KOREN + "/manifest.json"]))
        self.assertTrue(media_servers.stremio_je_zaseben(self.ODGOVORI[ZASEBEN + "/manifest.json"]))
        self.assertEqual([self.mc._koren_zaseben(k) for k in (KOREN + "/manifest.json", ZASEBEN, MRTEV, "")], [False, True, None, None])

    def test_film_iz_javnega_dodatka_si_zapomni_z_naslovom_in_plakatom(self):
        it = self.mc.movie_item(11, "Film ena")
        r = self.mc.resolve(it["id"])
        self.assertEqual(r["url"], "http://127.0.0.1:5555/t/x/Film.mkv")
        o = self._opisi()[H1]
        self.assertEqual((o["title"], o["kind"], o["ref"], o["private"], o["file"]), ("Film ena", "movie", it["id"], False, 1))

    def test_film_ki_ga_ponudi_zaseben_dodatek_ostane_brez_naslova(self):
        it = self.mc.movie_item(12, "Zasebni naslov")
        self.assertNotIn("napaka_koda", self.mc.resolve(it["id"]))
        self.assertEqual(self._opisi()[H2], {"private": True})
        with open(kk.pot_opisov(self.raba), encoding="utf-8") as d:
            self.assertNotIn("Zasebni naslov", d.read())

    def test_kadar_manifesta_ni_mogoce_prebrati_velja_kot_zaseben(self):
        it = self.mc.movie_item(13, "Neznano")
        self.assertNotIn("napaka_koda", self.mc.resolve(it["id"]))
        self.assertEqual(self._opisi()[H3], {"private": True})

    def test_naslov_iz_kataloga_zasebnega_dodatka_je_zaseben_tudi_ce_tok_da_javni(self):
        self.mc._tokovi_odgovor.dodatki_torrentov = {H4: KOREN}
        self.mc._zabelezi_knjiznico({"id": "x", "naslov": "Iz zasebnega kataloga", "stremio": {"koren": ZASEBEN}}, H4, 0)
        self.assertEqual(self._opisi()[H4], {"private": True})
        # Naslov iz javnega kataloga (TMDB), ki ga ponudi javni dodatek: drugi dodatki na kartici ne odlocajo.
        self.mc._tokovi_odgovor.dodatki_torrentov = {H1: KOREN}
        self.mc._zabelezi_knjiznico({"id": "y", "naslov": "Javni", "tmdb_id": 5, "stremio": {"koren": ZASEBEN}}, H1, 0)
        self.assertEqual(self._opisi()[H1]["title"], "Javni")

    def test_uporabnikovega_torrenta_in_filma_z_diska_ne_belezi(self):
        self.zacasen = False
        self.mc.resolve(self.mc.movie_item(11, "Film ena")["id"])
        self.assertEqual(self._opisi(), {})

    def test_vnos_police_se_predvaja_naravnost_iz_torrenta_in_nadaljuje_pod_izvirno_oznako(self):
        item = self.mc.knjiznica_vnos({"kljuc": H1.upper(), "naslov": "Film ena", "slika": PLAKAT, "vrsta": "film", "datoteka": 3, "ref": "stremio:s0:movie:tt1"})
        self.assertEqual(item["id"], "stremio:s0:movie:tt1")
        r = self.mc.resolve("knjiznica:" + H1)
        self.assertEqual(self.pripravljeni, [(H1, 3)])                       # brez vprasanja dodatku
        self.assertEqual((r["id"], r["url"], r["naslov"], r["vrsta"]), ("stremio:s0:movie:tt1", "http://127.0.0.1:5555/t/x/Film.mkv", "Film ena", "film"))
        self.assertEqual(self._opisi(), {})                                  # predvajanje s police opisa ne spreminja
        brez = self.mc.knjiznica_vnos({"kljuc": H2, "naslov": "Brez oznake", "vrsta": "serija"})
        self.assertEqual((brez["id"], brez["vrsta"]), ("knjiznica:" + H2, "serija"))
        self.mc.resolve("knjiznica:" + H2)
        self.assertEqual(self.pripravljeni[-1], (H2, None))

    def test_odprte_podrobnosti_torrenta_ne_zacnejo_prenasati(self):
        """Do 3. 10. 2026 je ze klik na kartico (podrobnosti) zacel prenos torrenta; zdaj sele Predvajaj."""
        it = self.mc.movie_item(11, "Film ena")
        with mock.patch.object(self.mc, "_tmdb", lambda *a, **k: {}), \
                mock.patch.object(self.mc, "_watch_providers", lambda *a, **k: {}), \
                mock.patch.object(self.mc, "watch_country_settings", lambda *a, **k: {"drzava": "SI", "ime_drzave": "Slovenija"}):
            d = self.mc.details(it["id"])
        self.assertEqual(self.pripravljeni, [])
        self.assertEqual(self._opisi(), {})
        self.assertNotIn("napaka_koda", d)
        self.assertEqual(d.get("naslov"), "Film ena")
        self.assertEqual(self.mc.resolve(it["id"])["url"], "http://127.0.0.1:5555/t/x/Film.mkv")   # Predvajaj: zdaj ja
        self.assertEqual(self.pripravljeni, [(H1, 1)])

    def test_napaka_motorja_je_kratka_koda(self):
        self.mc.knjiznica_vnos({"kljuc": H1, "naslov": "Film", "vrsta": "film"})

        def ni_prostora(*a, **k):
            raise os_torrent.NapakaTorrenta("ni_prostora")
        with mock.patch.object(tt, "pripravi", ni_prostora):
            self.assertEqual(self.mc.resolve("knjiznica:" + H1)["napaka_koda"], "ni_prostora")


class Stran(unittest.TestCase):
    """Stran Medijskega centra ima polico in njena besedila v vseh jezikih (Linux in Windows: assets/os)."""

    KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _beri(self, ime):
        with open(os.path.join(self.KOREN, "assets", "os", ime), encoding="utf-8") as d:
            return d.read()

    def test_polica_je_na_strani_in_klice_most(self):
        self.assertIn('id="mediaKnjiznica"', self._beri("index.html"))
        koda = self._beri("os.js")
        for klic in ('klic("mediaKnjiznica")', 'klic("mediaKnjiznicaPredvajaj"', 'klic("mediaKnjiznicaOdstrani"'):
            self.assertIn(klic, koda)

    def test_besedila_police_v_vseh_jezikih(self):
        import re
        kljuci = set(re.findall(r'\bt\("(knjiznica[A-Za-z0-9_]+)"', self._beri("os.js")))
        self.assertGreaterEqual(len(kljuci), 8)
        besedila = self._beri("besedila.js")
        for jezik in ("sl", "en", "de", "es", "fr", "it"):
            bloki = "\n".join(re.findall(r"Object\.assign\(BESEDILA_OS\.%s, \{(.*?)\}\);" % jezik, besedila, re.S))
            for kljuc in kljuci:
                self.assertIn('"%s":' % kljuc, bloki, "%s manjka v %s" % (kljuc, jezik))


if __name__ == "__main__":
    unittest.main()
