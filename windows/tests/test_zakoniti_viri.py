import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.zakoniti_viri import ZakonitiViri
from core.os_media import MediaCenter, parse_payload
from core import media_servers


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

    def test_m3u_and_pls_user_radio_lists_are_parsed(self):
        pls = b"[playlist]\nNumberOfEntries=2\nFile1=https://radio.test/jazz.m3u8\nTitle1=Jazz One\nLength1=-1\nFile2=/pop.mp3\nTitle2=Pop Two\n"
        items = parse_payload(pls, "audio/x-scpls", "https://example.test/list.pls", "Moj seznam")
        self.assertEqual([item["naslov"] for item in items], ["Jazz One", "Pop Two"])
        self.assertEqual(items[0]["vrsta"], "radio")
        self.assertEqual(items[1]["url"], "https://example.test/pop.mp3")
        m3u = parse_payload(b"#EXTM3U\n#EXTINF:-1 group-title=Jazz,Jazz FM\nhttps://radio.test/aac\n",
                            "audio/x-mpegurl", "https://example.test/list.m3u", "Radio")
        self.assertEqual(m3u[0]["naslov"], "Jazz FM")

    def test_local_roots_scan_music_video_pictures_and_accept_unc_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cover.jpg").write_bytes(b"not-a-real-image")
            (root / "Song.mp3").write_bytes(b"not-a-real-audio-file")
            center = MediaCenter(directory + "/config", roots=[])
            result = center.add_local_root(directory)
            self.assertTrue(result["ok"])
            items = center.catalog()["vnosi"]
            self.assertEqual({item["vrsta"] for item in items}, {"slika", "glasba"})
            self.assertFalse(center.add_local_root(directory)["ok"])
            self.assertIn("NFS", center.add_local_root("nfs://server/share")["napaka"])

    def test_personal_server_credentials_are_encrypted_and_not_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            center = MediaCenter(directory, roots=[],
                                 secret_encryptor=lambda text: "protected:" + base64.b64encode(text.encode()).decode(),
                                 secret_decryptor=lambda text: base64.b64decode(text.removeprefix("protected:")).decode())
            with mock.patch("core.os_media.media_servers.authenticate", return_value={"token": "private-token", "user_id": "u1"}):
                result = center.add_server("jellyfin", "Domači", "https://media.example", "lastnik", "password")
            self.assertTrue(result["ok"])
            saved = json.loads(center.store_path.read_text())
            stored = saved["osebni_strezniki"][0]
            self.assertTrue(stored["secret_enc"].startswith("protected:"))
            self.assertNotIn("private-token", center.store_path.read_text())
            self.assertNotIn("password", center.store_path.read_text())
            self.assertNotIn("secret_enc", center.sources()[-1])
            self.assertEqual(center.export_json()["viri"], [])

    def test_jellyfin_catalog_maps_movie_music_and_uses_official_api(self):
        replies = [Response({"Items": [
            {"Id": "m1", "Name": "Film", "Type": "Movie", "RunTimeTicks": 36000000000},
            {"Id": "a1", "Name": "Song", "Type": "Audio", "Album": "Record", "AlbumArtist": "Artist"},
        ]})]
        urls = []
        def fake_request(url, headers=None, body=None):
            urls.append((url, headers or {}))
            return replies.pop(0).payload
        with mock.patch("core.media_servers._request", side_effect=fake_request):
            rows = media_servers.catalog("jellyfin", "https://media.example", {"id": "s1", "ime": "Domači", "user_id": "u1"}, "token")
        self.assertEqual([row["vrsta"] for row in rows], ["film", "glasba"])
        self.assertIn("/Users/u1/Items", urls[0][0])
        self.assertEqual(urls[0][1]["X-Emby-Token"], "token")
        self.assertIn("api_key=token", rows[0]["url"])

    def test_plex_reads_library_xml_and_creates_tokenized_stream(self):
        replies = [b'<MediaContainer><Directory key="1"/></MediaContainer>',
                   b'<MediaContainer><Video ratingKey="7" title="Open movie" type="movie"><Media><Part key="/library/parts/9/file.mp4"/></Media></Video></MediaContainer>']
        urls = []
        def fake_request(url, headers=None, body=None):
            urls.append(url)
            return replies.pop(0)
        with mock.patch("core.media_servers._request", side_effect=fake_request):
            rows = media_servers.catalog("plex", "https://plex.example", {"id": "p1", "ime": "Plex"}, "plex-token")
        self.assertEqual(rows[0]["vrsta"], "film")
        self.assertIn("/library/parts/9/file.mp4?X-Plex-Token=plex-token", rows[0]["url"])
        self.assertTrue(all("plex-token" not in url for url in urls))

    def test_navidrome_uses_subsonic_token_hash_and_stream_api(self):
        urls = []
        payload = json.dumps({"subsonic-response": {"randomSongs": {"song": [
            {"id": "song1", "title": "A Tune", "artist": "Artist", "album": "Album", "duration": 210}
        ]}}}).encode()
        with mock.patch("core.media_servers._request", side_effect=lambda url, **kwargs: (urls.append(url) or payload)):
            rows = media_servers.catalog("navidrome", "https://music.example", {
                "id": "n1", "ime": "Navidrome", "uporabnik": "lastnik"}, "private-password")
        self.assertEqual(rows[0]["vrsta"], "glasba")
        self.assertIn("/rest/stream.view", rows[0]["url"])
        self.assertIn("t=", urls[0])
        self.assertNotIn("private-password", urls[0])

    def test_soundcloud_uses_official_player_without_reading_the_page(self):
        with tempfile.TemporaryDirectory() as directory:
            center = MediaCenter(directory, roots=[])
            center._izmeri_ping = lambda _url: None
            center._download = mock.Mock(side_effect=AssertionError("SoundCloud page must not be fetched"))
            added = center.add_source("https://soundcloud.com/artist/public-track", "Public track")
            self.assertTrue(added["ok"])
            item = center.catalog(kind="glasba")["vnosi"][0]
            self.assertEqual(item["vrsta"], "glasba")
            self.assertTrue(item["url"].startswith("https://w.soundcloud.com/player/?"))
            center._download.assert_not_called()

    def test_bandcamp_requires_official_embedded_player_link(self):
        with tempfile.TemporaryDirectory() as directory:
            center = MediaCenter(directory, roots=[])
            center._izmeri_ping = lambda _url: None
            center._download = mock.Mock(side_effect=AssertionError("Bandcamp page must not be fetched"))
            added = center.add_source("https://artist.bandcamp.com/track/public-song", "Song")
            self.assertFalse(added["ok"])
            self.assertIn("EmbeddedPlayer", added["napaka"])
            center._download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
