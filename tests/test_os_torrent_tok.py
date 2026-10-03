"""Film iz torrenta (tok `infoHash` dodatka) v Medijskem centru na racunalniku: core/os_torrent_tok.py, tokovi
dodatka z vsem za motor (media_servers.stremio_tokovi), izbira po sejalcih (tok_izbira) in MediaCenter.resolve.
Brez omrezja in brez rqbit (motor je lazen)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import link_datoteke, media_servers, os_media, os_torrent, os_torrent_tok as tt, tok_izbira  # noqa: E402

H1, H2, H3 = "a" * 40, "b" * 40, "c" * 40
KOREN = "https://dodatek.primer.si"


class _Motor:
    """Namesto rqbit: en torrent z vzorcem, filmom, podnapisi in programom."""

    def __init__(self, mapa):
        self.mapa_prenosov = mapa
        self.torrenti = {}            # hash -> id
        self.dodane = []
        self.odstranjeni = []
        self.lastni = set()
        self.zadnji_uri = ""

    def zazeni(self):
        pass

    def tece(self):
        return True

    def preberi(self, uri):
        self.zadnji_uri = uri
        h = os_torrent.razcleni_magnet(uri)["hash"]
        if h == H3:
            raise os_torrent.NapakaTorrenta("ni_metapodatkov")
        return {"hash": h, "ime": "Film", "uri": uri, "datoteke": [
            {"i": 0, "ime": "Film/vzorec.mp4", "velikost": 100, "vrsta": "video"},
            {"i": 1, "ime": "Film/Film.S01E02.mkv", "velikost": 5000, "vrsta": "video"},
            {"i": 2, "ime": "Film/Film.S01E01.mkv", "velikost": 9000, "vrsta": "video"},
            {"i": 3, "ime": "Film/Film.S01E02.sl.srt", "velikost": 10, "vrsta": "podnapisi"},
            {"i": 4, "ime": "Film/namesti.exe", "velikost": 99999, "vrsta": "nevarno"}]}

    def dodaj(self, uri, izbrane):
        h = os_torrent.razcleni_magnet(uri)["hash"]
        self.torrenti.setdefault(h, len(self.torrenti) + 1)
        self.dodane.append((h, list(izbrane)))
        return self.torrenti[h]

    def tok(self, tid, i):
        return "http://127.0.0.1:5555/t/skrito%d/%d.mkv" % (tid, i)

    def podnapisi_za(self, tid, i):
        return [(3, "Film/Film.S01E02.sl.srt")] if i == 1 else []

    def seznam(self):
        return [{"id": tid, "hash": h, "ime": "Film", "lastna": h in self.lastni} for h, tid in self.torrenti.items()]

    def magnet(self, tid):
        return ""

    def odstrani(self, tid, z_datotekami=False):
        h = next(h for h, t in self.torrenti.items() if t == tid)
        self.torrenti.pop(h)
        self.odstranjeni.append((h, z_datotekami))
        return True


class Tok(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.raba = os.path.join(self.mapa, "raba.json")
        self.m = _Motor(self.mapa)
        self.prosto = lambda mapa, potrebno: ""

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)

    def _pripravi(self, h=H1, **k):
        k.setdefault("zmogljivost", self.prosto)
        return tt.pripravi(h, torrenti=self.m, mape_stanja=[], pot=self.raba, **k)

    def test_magnet_iz_podatkov_dodatka(self):
        self.assertEqual(tt.magnet("ni hash"), "")
        uri = tt.magnet(H1.upper(), "Film (2020).mkv", ["udp://tracker.primer.si:1337/announce"])
        self.assertTrue(uri.startswith("magnet:?xt=urn:btih:" + H1 + "&dn=Film%20%282020%29.mkv&tr=udp%3A%2F%2F"))
        self.assertIsNotNone(os_torrent.razcleni_magnet(uri))

    def test_izbere_datoteko_dodatka_sicer_ime_sicer_najvecji_video(self):
        self.assertEqual(self._pripravi(indeks=1)["indeks"], 1)
        self.assertEqual(self._pripravi(ime="Film.S01E02.mkv")["indeks"], 1)
        self.assertEqual(self._pripravi()["indeks"], 2)                    # najvecji video
        self.assertEqual(self._pripravi(indeks=4)["indeks"], 2)            # programa nikoli, raje najvecji video
        self.assertEqual(self.m.dodane[0], (H1, [1]))

    def test_tok_in_podnapisi_iz_istega_torrenta(self):
        tok = self._pripravi(indeks=1)
        self.assertEqual(tok["url"], "http://127.0.0.1:5555/t/skrito1/1.mkv")
        self.assertEqual(tok["podnapisi"], [{"uri": "http://127.0.0.1:5555/t/skrito1/3.mkv", "ime": "Film.S01E02.sl.srt",
                                             "jezik": "sl", "oznaka": ""}])
        self.assertEqual(tok["velikost"], 5000)

    def test_napake_so_kratke_kode(self):
        for slab in ("", "abc", "z" * 40):
            with self.assertRaises(os_torrent.NapakaTorrenta) as e:
                self._pripravi(slab)
            self.assertEqual(str(e.exception), "ni_magnet")
        with self.assertRaises(os_torrent.NapakaTorrenta) as e:
            self._pripravi(zmogljivost=lambda mapa, potrebno: "ni_prostora")
        self.assertEqual(str(e.exception), "ni_prostora")
        self.assertEqual(self.m.dodane, [])                                # brez prostora se prenos ne zacne

    def test_po_48_urah_brez_gledanja_se_odstrani_samo(self):
        self._pripravi(H1)
        self._pripravi(H2)
        zdaj = time.time()
        link_datoteke._pisi_rabo(self.raba, {H1: zdaj - 49 * 3600, H2: zdaj - 3600})
        self.assertEqual(tt.pocisti(self.m, self.raba), [H1])
        self.assertEqual(self.m.odstranjeni, [(H1, True)])
        self.assertEqual(set(link_datoteke._beri_rabo(self.raba)), {H2})
        # Ponovno gledanje rok podaljsa.
        self._pripravi(H2)
        self.assertGreater(link_datoteke._beri_rabo(self.raba)[H2], zdaj - 60)

    def test_uporabnikovega_torrenta_se_ciscenje_ne_dotakne(self):
        self.m.torrenti[H2] = 9                    # uporabnik ga je dodal sam (Magnet povezave): ni v zapisu rabe
        self._pripravi(H2)                         # zdaj ga gleda se iz Medijskega centra
        self.assertNotIn(H2, link_datoteke._beri_rabo(self.raba))
        self._pripravi(H1)
        link_datoteke._pisi_rabo(self.raba, {H1: time.time() - 49 * 3600})
        self.assertEqual(tt.pocisti(self.m, self.raba), [H1])
        self.assertIn(H2, self.m.torrenti)
        # Prenos zaradi gledanja, ki ga uporabnik potem doda sam, ostane.
        self._pripravi(H1)
        tt.obdrzi(H1, self.raba)
        link_datoteke._pisi_rabo(self.raba, dict(link_datoteke._beri_rabo(self.raba)))
        self.assertEqual(tt.pocisti(self.m, self.raba, zdaj=time.time() + 100 * 3600), [])
        self.assertIn(H1, self.m.torrenti)

    def test_brez_prostora_najprej_odstrani_negledano(self):
        self._pripravi(H1)
        link_datoteke._pisi_rabo(self.raba, {H1: time.time() - 7 * 3600})     # 7 ur: ni vec "v teku", a mlajse od 48 h
        stanje = {"prosto": False}

        def zmogljivost(mapa, potrebno):
            return "" if stanje["prosto"] or H1 not in self.m.torrenti else "ni_prostora"

        tok = self._pripravi(H2, zmogljivost=zmogljivost)
        self.assertEqual(self.m.odstranjeni, [(H1, True)])
        self.assertTrue(tok["url"])

    def test_ze_preneseno_gre_z_diska(self):
        pot = os.path.join(self.mapa, "Film.S01E02.mkv")
        with open(pot, "wb") as d:
            d.write(b"x" * 10)
        with mock.patch.object(link_datoteke, "ze_preneseno", lambda h, i, m=None: (pot, 1)):
            tok = self._pripravi(indeks=1)
            self.assertEqual((tok["pot"], tok["indeks"], tok["velikost"]), (pot, 1, 10))
            self.assertTrue(tok["url"].startswith("file://"))
            self.assertEqual(self.m.dodane, [])
            # Paket brez indeksa: najvecji video na disku ni nujno zahtevana epizoda -> ne ugibamo, vprasamo motor.
            self.assertEqual(self._pripravi(ime="Film.S01E01.mkv")["indeks"], 2)


class Izbira(unittest.TestCase):
    def test_sejalci_kot_na_androidu(self):
        self.assertEqual(tok_izbira.sejalci("Film 1080p \U0001F464 123 \U0001F4BE 2 GB"), 123)
        self.assertEqual(tok_izbira.sejalci("Seeders: 7"), 7)
        self.assertEqual(tok_izbira.sejalci("Film 1080p WEB"), -1)
        z = tok_izbira.Zmoznosti()
        tokovi = ["1080p \U0001F464 0", "720p \U0001F464 300", "1080p \U0001F464 3", "1080p \U0001F464 250"]
        self.assertEqual(tok_izbira.uredi(tokovi, lambda t: t, z), ["1080p \U0001F464 250", "720p \U0001F464 300",
                                                                   "1080p \U0001F464 3", "1080p \U0001F464 0"])


class MedijskiCenter(unittest.TestCase):
    ODGOVORI = {
        KOREN + "/manifest.json": {"id": "si.test", "name": "Test", "resources": ["catalog", "stream"], "types": ["movie"], "catalogs": []},
        KOREN + "/stream/movie/tt0000001.json": {"streams": [
            {"name": "T\n4k", "title": "Film 2160p \U0001F464 0", "infoHash": H3.upper(), "fileIdx": 0},
            {"name": "T\n1080p", "title": "Film 1080p \U0001F464 120\nvec", "infoHash": H1, "fileIdx": 1,
             "behaviorHints": {"filename": "Film.S01E02.mkv"}, "sources": ["tracker:udp://t.primer.si:1/announce", "dht:" + H1]},
            {"name": "pokvarjen", "infoHash": "abc"}]},
        KOREN + "/stream/movie/tt0000002.json": {"streams": [
            {"name": "HD", "url": "https://cdn.primer.si/f.mp4"}, {"name": "T", "infoHash": H1}]},
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mc = os_media.MediaCenter(self.tmp, roots=[], secret_encryptor=lambda s: s, secret_decryptor=lambda s: s)
        data = self.mc._load()
        data["osebni_strezniki"] = [{"id": "s1", "vrsta": "streznik", "ponudnik": "stremio", "ime": "Dodatek", "url": KOREN + "/manifest.json"}]
        self.mc._save(data)

        def zahteva(url, headers=None, body=None, raw=None):
            if url not in self.ODGOVORI:
                raise OSError("HTTP 404 " + url)
            return json.dumps(self.ODGOVORI[url]).encode()
        self.popravki = [mock.patch.object(media_servers, "_request", zahteva),
                         mock.patch.dict(os_media.TMDB_TO_IMDB, {"11": "tt0000001", "12": "tt0000002"}),
                         mock.patch.object(tt, "podprto", lambda: True)]
        for p in self.popravki:
            p.start()

    def tearDown(self):
        for p in self.popravki:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tok_dodatka_nosi_vse_za_motor(self):
        t = media_servers.stremio_tokovi(KOREN, "movie", "tt0000001")
        self.assertEqual((t[1]["hash"], t[1]["indeks"], t[1]["ime"], t[1]["sledilniki"]),
                         (H1, 1, "Film.S01E02.mkv", ["udp://t.primer.si:1/announce"]))
        self.assertEqual((t[1]["vir"], t[1]["kakovost"]), ("T", "Film 1080p \U0001F464 120"))
        self.assertEqual(t[0]["hash"], H3)                                   # velike crke -> male
        self.assertEqual(t[2], {"url": "", "torrent": True})                 # neveljaven hash: brez podatkov za motor

    def test_film_samo_s_torrenti_se_predvaja(self):
        klici = []

        def pripravi(hash_, indeks=None, ime="", sledilniki=()):
            klici.append((hash_, indeks, ime, list(sledilniki)))
            return {"url": "http://127.0.0.1:5555/t/x/Film.mkv", "ime": "Film.mkv", "indeks": indeks, "velikost": 1,
                    "podnapisi": [{"uri": "http://127.0.0.1:5555/t/y/Film.sl.srt", "ime": "Film.sl.srt", "jezik": "sl", "oznaka": ""}]}

        obvestila = []
        self.mc.ob_pripravi_torrenta = obvestila.append
        it = self.mc.movie_item(11, "Film ena")
        with mock.patch.object(tt, "pripravi", pripravi):
            r = self.mc.resolve(it["id"])
        # Dobro podprt torrent 1080p pred 4K brez sejalcev (ta bi cakal v nedogled).
        self.assertEqual(klici, [(H1, 1, "Film.S01E02.mkv", ["udp://t.primer.si:1/announce"])])
        self.assertEqual((r["url"], r["torrent"], r["razlicice"][0]["vir"]), ("http://127.0.0.1:5555/t/x/Film.mkv", True, "T"))
        self.assertEqual(r["podnapisi"][0]["jezik"], "sl")
        self.assertNotIn("napaka_koda", r)
        self.assertEqual(len(obvestila), 1)
        self.assertFalse(self.mc.znano_ni_na_voljo(it))

    def test_neposredni_tok_ima_prednost(self):
        it = self.mc.movie_item(12, "Film dva")
        with mock.patch.object(tt, "pripravi", lambda *a, **k: self.fail("torrenta ne sme zaceti")):
            self.assertEqual(self.mc.resolve(it["id"])["url"], "https://cdn.primer.si/f.mp4")

    def test_ce_prvi_torrent_ne_gre_poskusi_naslednjega_in_naslova_ne_skrije(self):
        def pripravi(hash_, indeks=None, ime="", sledilniki=()):
            if hash_ == H1:
                raise os_torrent.NapakaTorrenta("ni_metapodatkov")
            return {"url": "http://127.0.0.1:5555/t/z/F.mkv", "ime": "F.mkv", "indeks": 0, "velikost": 1, "podnapisi": []}

        it = self.mc.movie_item(11, "Film ena")
        with mock.patch.object(tt, "pripravi", pripravi):
            self.assertEqual(self.mc.resolve(it["id"])["url"], "http://127.0.0.1:5555/t/z/F.mkv")

        def ni_prostora(*a, **k):
            raise os_torrent.NapakaTorrenta("ni_prostora")

        with mock.patch.object(tt, "pripravi", ni_prostora):
            r = self.mc.resolve(it["id"])
        self.assertEqual(r["napaka_koda"], "ni_prostora")
        self.assertFalse(self.mc.znano_ni_na_voljo(it))                      # napaka ni "noben vir tega ne predvaja"

    def test_kjer_motorja_ni_ostane_po_starem(self):
        it = self.mc.movie_item(11, "Film ena")
        with mock.patch.object(tt, "podprto", lambda: False):
            self.assertFalse(os_media.MediaCenter._predvajljivi(media_servers.stremio_tokovi(KOREN, "movie", "tt0000001")))
            self.assertEqual(self.mc.resolve(it["id"])["napaka_koda"], "ni_toka")
        self.assertTrue(os_media.MediaCenter._predvajljivi(media_servers.stremio_tokovi(KOREN, "movie", "tt0000001")))


if __name__ == "__main__":
    unittest.main()
