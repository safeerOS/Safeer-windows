import io
import json
import tempfile
import unittest
from unittest import mock

from core.zakoniti_viri import ZakonitiViri
from core.os_media import MediaCenter


class Response:
    status = 200

    def __init__(self, value):
        self.payload = json.dumps(value).encode()

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit=-1): return self.payload[:limit]


class TestZakonitiViri(unittest.TestCase):
    def test_peertube_sections_live_and_hls_resolution(self):
        calls = []
        def open_request(request, timeout):
            calls.append(request.full_url)
            if "/api/v1/videos/live-id" in request.full_url:
                return Response({"isLive": True, "streamingPlaylists": [{"playlistUrl": "https://cdn.test/live.m3u8"}]})
            return Response({"data": [{"uuid": "live-id", "name": "Live feed", "isLive": True,
                                      "thumbnailPath": "/thumb.jpg", "duration": 0}]})
        api = ZakonitiViri(opener=open_request)
        items = api._peer_rows("tilvids.com", "/api/v1/videos?sort=-trending", "Trending")
        self.assertEqual(items[0]["vrsta"], "tv-v-zivo")
        self.assertEqual(items[0]["slika"], "https://tilvids.com/thumb.jpg")
        resolved = api.resolve_video(items[0])
        self.assertEqual(resolved["url"], "https://cdn.test/live.m3u8")
        self.assertTrue(resolved["v_zivo"])
        self.assertTrue(all("timeout" not in url for url in calls))

    def test_radio_metadata_requires_https_and_keeps_codec(self):
        row = {"stationuuid": "s1", "name": "Jazz FM", "url_resolved": "https://radio.test/live.m3u8",
               "codec": "AAC", "bitrate": 128, "country": "Slovenia", "countrycode": "SI",
               "tags": "jazz", "lastcheckok": 1}
        station = ZakonitiViri._station(row, "Jazz")
        self.assertEqual((station["codec"], station["bitrate"], station["skupina"]), ("AAC", 128, "Jazz"))
        row["url_resolved"] = "http://radio.test/live.mp3"
        self.assertIsNone(ZakonitiViri._station(row, "Jazz"))

    def test_api_error_falls_back_to_previous_cache(self):
        now = [1000]
        response = [Response({"data": [{"uuid": "v1", "name": "Cached video"}]})]
        def open_request(request, timeout):
            if response:
                return response.pop()
            raise OSError("unavailable")
        api = ZakonitiViri(opener=open_request, clock=lambda: now[0])
        first = api._peer_rows("tilvids.com", "/api/v1/videos?sort=-views", "Popular")
        now[0] += 60
        again = api._peer_rows("tilvids.com", "/api/v1/videos?sort=-views", "Popular")
        self.assertEqual(first, again)

    def test_media_center_merges_public_catalog_and_resolves_direct_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            center = MediaCenter(directory, roots=[])
            center._zakoniti_viri.get = mock.Mock(return_value=[{
                "id": "radio:r1", "naslov": "Radio One", "vrsta": "radio",
                "url": "https://radio.test/listen.m3u8", "codec": "AAC", "bitrate": 96,
                "skupina": "Slovenija", "vir": "Radio Browser"}])
            found = center.catalog(kind="radio")["vnosi"]
            self.assertEqual(found[0]["codec"], "AAC")
            self.assertEqual(center.resolve(found[0]["id"])["url"], found[0]["url"])


if __name__ == "__main__":
    unittest.main()
