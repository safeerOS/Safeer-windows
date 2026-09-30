"""Stremio dodatki v Medijskem centru: tokovi z glavami in podnapisi, epizode/filmi iz TMDB kataloga prek
uporabnikovih dodatkov, resolve z vdelanimi viri in tokovi dodatka (brez omrezja: _request je lazen)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import media_servers, os_media  # noqa: E402

KOREN = "https://dodatek.primer.si"
ODGOVORI = {
    KOREN + "/manifest.json": {"id": "si.test", "name": "Test", "resources": ["catalog", "stream"], "types": ["movie", "series"], "catalogs": []},
    KOREN + "/stream/movie/tt0000001.json": {"streams": [
        {"name": "HD", "title": "1080p", "url": "https://cdn.primer.si/f.m3u8",
         "behaviorHints": {"proxyHeaders": {"request": {"Referer": "https://primer.si/", "X-Zlo": "a\nb"}}},
         "subtitles": [{"url": "https://cdn.primer.si/sl.srt", "lang": "slv"}, {"url": "ftp://x/y.srt", "lang": "en"}]},
        {"name": "T", "infoHash": "abc"}]},
    KOREN + "/stream/series/tt0000002:2:3.json": {"streams": [{"name": "Ep", "url": "https://cdn.primer.si/s2e3.mp4"}]},
}


def _lazni_request(url, headers=None, body=None, raw=None):
    if url not in ODGOVORI:
        raise OSError("HTTP 404 " + url)
    return json.dumps(ODGOVORI[url]).encode()


class StremioMedijskiCenter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mc = os_media.MediaCenter(self.tmp, roots=[], secret_encryptor=lambda s: s, secret_decryptor=lambda s: s)
        data = self.mc._load()
        data["osebni_strezniki"] = [{"id": "streznik-1", "vrsta": "streznik", "ponudnik": "stremio", "ime": "Moj dodatek", "url": KOREN + "/manifest.json"}]
        self.mc._save(data)
        self.p = mock.patch.object(media_servers, "_request", _lazni_request); self.p.start()
        self.p2 = mock.patch.dict(os_media.TMDB_TO_IMDB, {"11": "tt0000001", "22": "tt0000002"}); self.p2.start()

    def tearDown(self):
        self.p.stop(); self.p2.stop()

    def test_tokovi_glave_podnapisi(self):
        t = media_servers.stremio_tokovi(KOREN, "movie", "tt0000001")
        self.assertEqual(t[0]["url"], "https://cdn.primer.si/f.m3u8")
        self.assertEqual(t[0]["glave"], {"Referer": "https://primer.si/"})          # glava z novo vrstico odpade
        self.assertEqual(t[0]["podnapisi"], [{"uri": "https://cdn.primer.si/sl.srt", "jezik": "slv"}])  # ftp odpade
        self.assertTrue(t[1].get("torrent"))

    def test_film_iz_tmdb_prek_dodatka(self):
        it = self.mc.movie_item(11, "Film ena")
        self.assertIsNotNone(it)
        self.assertEqual(it["url"], "stremio:%s|movie|tt0000001" % KOREN)
        r = self.mc.resolve(it["id"])
        self.assertEqual(r["url"], "https://cdn.primer.si/f.m3u8")
        self.assertEqual(r["glave"], {"Referer": "https://primer.si/"})
        self.assertEqual(r["podnapisi"][0]["uri"], "https://cdn.primer.si/sl.srt")
        self.assertEqual(r["razlicice"][0]["vir"], "HD")

    def test_epizoda_iz_tmdb_prek_dodatka(self):
        it = self.mc.episode_item(22, 2, 3, "Tretja")
        self.assertEqual(it["url"], "stremio:%s|series|tt0000002:2:3" % KOREN)
        self.assertEqual((it["sezona"], it["epizoda"]), (2, 3))
        r = self.mc.resolve(it["id"])
        self.assertEqual(r["url"], "https://cdn.primer.si/s2e3.mp4")

    def test_brez_imdb_ni_vnosa(self):
        self.assertIsNone(self.mc.movie_item(999, "Neznan"))

    def test_dodatek_kot_dodatna_razlicica(self):
        item = {"id": "x", "naslov": "Film ena", "vrsta": "film", "url": "https://vdelava.primer.si/e/1",
                "razlicice": [{"url": "https://vdelava.primer.si/e/1", "vir": "Vdelava"}, {"url": "stremio:%s|movie|tt0000001" % KOREN, "vir": "Moj dodatek"}]}
        self.mc._dynamic_items["x"] = item
        r = self.mc.resolve("x")
        self.assertEqual(r["url"], "https://vdelava.primer.si/e/1")
        self.assertEqual([v["url"] for v in r["razlicice"]], ["https://vdelava.primer.si/e/1", "https://cdn.primer.si/f.m3u8"])


if __name__ == "__main__":
    unittest.main()
