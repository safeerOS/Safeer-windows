"""Uvoz seznamov predvajanja (YouTube, Spotify): prepoznava povezav, razclenjevanje in shramba v Medijskem centru."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core import os_media, uvoz_seznama as u  # noqa: E402


LOCKUP = {"lockupViewModel": {
    "contentId": "abcDEF12345", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
    "contentImage": {"thumbnailViewModel": {"overlays": [{"x": {"icon": {"sources": [{"clientResource": {"imageName": "MUSIC"}}]}}}]}},
    "metadata": {"lockupMetadataViewModel": {
        "title": {"content": "Siddharta - Ledena (Official Video)"},
        "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [{"text": {"content": "SiddhartaVEVO"}}]}]}}}}}}
STARI = {"playlistVideoRenderer": {"videoId": "zzz99988877", "title": {"runs": [{"text": "Predavanje 1"}]},
                                   "shortBylineText": {"runs": [{"text": "Univerza"}]}}}
STRAN = {"contents": [{"a": [LOCKUP, STARI]}, {"playlistMetadataRenderer": {"title": "Moj seznam"}},
                      {"continuationCommand": {"token": "ZETON", "request": "CONTINUATION_REQUEST_TYPE_BROWSE"}}]}
SPOTIFY = ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": {
    "type": "playlist", "name": "Top", "coverArt": {"sources": [{"url": "https://i.scdn.co/image/x"}]},
    "trackList": [{"title": "Pesem", "subtitle": "Izvajalec A", "duration": 201500}, {"title": "", "subtitle": "x"}]}}}}}}) + "</script></html>")


class UvozSeznamaTest(unittest.TestCase):
    def test_prepozna_povezave(self):
        self.assertEqual(u.youtube_id("https://www.youtube.com/playlist?list=PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i"), "PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i")
        self.assertEqual(u.youtube_id("https://music.youtube.com/watch?v=abc&list=PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i"), "PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i")
        # Posamezen posnetek, zasebni "Vsecki" (LL) in tuja stran niso seznam.
        self.assertEqual(u.youtube_id("https://www.youtube.com/watch?v=abc"), "")
        self.assertEqual(u.youtube_id("https://www.youtube.com/playlist?list=LL"), "")
        self.assertEqual(u.youtube_id("https://primer.si/playlist?list=PL4fGSI1pDJn6puJdseH2Rt9sMvt9E2M4i"), "")
        self.assertEqual(u.spotify_id("https://open.spotify.com/intl-de/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x"), ("playlist", "37i9dQZF1DXcBWIGoYBM5M"))
        self.assertEqual(u.spotify_id("spotify:album:4aawyAB9vmqN3uQ7FjRGTy"), ("album", "4aawyAB9vmqN3uQ7FjRGTy"))
        self.assertIsNone(u.spotify_id("https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl"))
        self.assertEqual(u.povezava_iz("Poslusaj: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M."),
                         "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

    def test_razcleni_youtube_obe_obliki(self):
        html = "<script>var ytInitialData = " + json.dumps(STRAN) + ";</script>"
        stran = u.iz_youtube(u.json_za(html, "ytInitialData"))
        self.assertEqual(stran["ime"], "Moj seznam")
        self.assertEqual(stran["nadaljevanje"], "ZETON")
        self.assertEqual([v["id"] for v in stran["vnosi"]], ["abcDEF12345", "zzz99988877"])
        self.assertTrue(stran["vnosi"][0]["glasba"])
        s = u._youtube_skladba(stran["vnosi"][0])
        self.assertEqual((s["izvajalec"], s["naslov"], s["youtube"]), ("Siddharta", "Ledena (Official Video)", "abcDEF12345"))
        self.assertEqual(u._youtube_skladba(stran["vnosi"][1])["izvajalec"], "Univerza")

    def test_razcleni_spotify(self):
        izid = u.iz_spotify(SPOTIFY)
        self.assertEqual(izid["ime"], "Top")
        self.assertEqual(izid["skladbe"], [{"naslov": "Pesem", "izvajalec": "Izvajalec A", "youtube": "",
                                           "slika": "https://i.scdn.co/image/x", "sekund": 201}])

    def test_izbira_posnetka_po_dolzini(self):
        z = [("uradni", 315), ("besedilo", 297), ("koncert", 600)]
        self.assertEqual(u.izberi_zadetek(z, 297), "besedilo")
        self.assertEqual(u.izberi_zadetek(z, 0), "uradni")
        self.assertEqual(u.izberi_zadetek(z, 100), "uradni")            # nic blizu: prvi zadetek
        # Zamenjava zavrnjenega: samo posnetek z ujemajoco dolzino, sicer raje nic.
        self.assertEqual(u.izberi_zadetek(z + [("drugi", 299)], 297, ("besedilo",)), "drugi")
        self.assertEqual(u.izberi_zadetek(z, 297, ("besedilo",)), "")

    def test_shramba_seznamov(self):
        with tempfile.TemporaryDirectory() as mapa:
            m = os_media.MediaCenter(mapa, roots=[])
            self.assertEqual(m.uvozi_seznam("https://www.youtube.com/watch?v=abc"), {"napaka": "ni_seznam"})
            uvoz = {"ime": "Top", "vir": "Spotify", "skladbe": [
                {"naslov": "Pesem", "izvajalec": "A", "youtube": "", "slika": "", "sekund": 200},
                {"naslov": "Druga", "izvajalec": "B", "youtube": "yt222222222", "slika": "s", "sekund": 0}]}
            with mock.patch.object(u, "uvozi", return_value=uvoz):
                self.assertEqual(m.uvozi_seznam("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
                                 {"ime": "Top", "stevilo": 2, "vir": "Spotify"})
            with mock.patch.object(u, "uvozi", return_value=None):
                self.assertEqual(m.uvozi_seznam("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"), {"napaka": "ni_uspel"})
            self.assertEqual(m.seznami(), [{"ime": "Top", "vir": "Spotify", "stevilo": 2, "slika": "s"}])
            vnosi = m.seznam("Top")["vnosi"]
            self.assertEqual([v["vrsta"] for v in vnosi], ["glasba", "glasba"])
            self.assertEqual(vnosi[1]["youtube"], "yt222222222")
            # Skladba brez posnetka: poiscemo ga ob predvajanju in si ga zapomnimo.
            with mock.patch.object(u, "najdi", return_value="yt111111111") as najdi:
                razresen = m.resolve(vnosi[0]["id"])
                self.assertEqual(razresen["youtube"], "yt111111111")
                self.assertEqual(razresen["id"], vnosi[0]["id"])
                najdi.assert_called_once()
            with mock.patch.object(u, "najdi", side_effect=AssertionError("ze shranjeno")):
                self.assertEqual(m.resolve(vnosi[0]["id"])["youtube"], "yt111111111")
            # Zamenjava (lastnik ne dovoli vgradnje): novega isce brez zavrnjenega.
            with mock.patch.object(u, "najdi", return_value="yt333333333") as najdi:
                self.assertEqual(m.seznam_posnetek(vnosi[0]["id"], zamenjaj=True)["youtube"], "yt333333333")
                self.assertEqual(najdi.call_args[0][3], ("yt111111111",))
            # Svoj seznam: skladba z uvozenega seznama in skladba iz kataloga z neposrednim naslovom.
            self.assertEqual(m.dodaj_na_seznam("Moj", vnosi[1]["id"]), {"ok": True, "ime": "Moj"})
            self.assertEqual(m.dodaj_na_seznam("Moj", vnosi[1]["id"]), {"ze": True, "ime": "Moj"})
            m._dynamic_items["jamendo:1"] = {"id": "jamendo:1", "naslov": "Prosta", "izvajalec": "C", "vrsta": "glasba",
                                             "url": "https://primer.si/a.mp3", "slika": ""}
            m._dynamic_items["film:1"] = {"id": "film:1", "naslov": "Film", "vrsta": "film", "url": "https://primer.si/f.mp4"}
            self.assertEqual(m.dodaj_na_seznam("Moj", "jamendo:1"), {"ok": True, "ime": "Moj"})
            self.assertEqual(m.dodaj_na_seznam("Moj", "film:1"), {"napaka": "ni_mogoce"})
            self.assertEqual(m.dodaj_na_seznam(" ", "jamendo:1"), {"napaka": "ime"})
            moj = m.seznam("Moj")["vnosi"]
            self.assertEqual([(v["naslov"], v["youtube"], v["url"]) for v in moj],
                             [("Druga", "yt222222222", "https://www.youtube.com/watch?v=yt222222222"), ("Prosta", "", "https://primer.si/a.mp3")])
            # Skladba z neposrednim naslovom ne isce posnetka.
            with mock.patch.object(u, "najdi", side_effect=AssertionError("ne isci")):
                self.assertEqual(m.resolve(moj[1]["id"])["url"], "https://primer.si/a.mp3")
            self.assertEqual([x["ime"] for x in m.seznami()], ["Moj", "Top"])
            self.assertTrue(m.odstrani_s_seznama("Moj", moj[0]["id"]))
            self.assertTrue(m.odstrani_s_seznama("Moj", moj[1]["id"]))
            self.assertEqual([x["ime"] for x in m.seznami()], ["Top"])          # prazen seznam izgine
            self.assertTrue(m.odstrani_seznam("Top"))
            self.assertFalse(m.odstrani_seznam("Top"))
            self.assertEqual(m.seznami(), [])


class SamoPredvajljivoTest(unittest.TestCase):
    """Obvestil dodatkov (donacije, Discord, "No streams found") ni nikjer; brez toka ni strani, film izgine iz kataloga."""

    TOKOVI = {"streams": [
        {"name": "🌟 Donation needed", "title": "Click here to donate to hdhub", "externalUrl": "https://ko-fi.com/hdhub"},
        {"name": "💬 Join the Discord server", "title": "Get latest updates", "externalUrl": "https://discord.gg/abc"},
        {"name": "❌ No streams found", "title": "No streams found for this title on hdhub", "externalUrl": "https://hdhub.example"},
        {"name": "Join our Discord", "url": "https://discord.gg/xyz"},
        {"name": "Support us", "title": "Donate to keep the project alive", "url": "https://hdhub.example/donate"}]}

    def test_obvestila_niso_tokovi(self):
        from core import media_servers
        with mock.patch.object(media_servers, "_request", return_value=json.dumps(self.TOKOVI)):
            self.assertEqual(media_servers.stremio_tokovi("https://d.example", "movie", "tt1"), [])
        pravi = {"streams": self.TOKOVI["streams"] + [
            {"name": "HDHub 1080p", "title": "Film.2020.1080p.mkv", "url": "https://cdn.example/f.mkv"},
            {"name": "Donation.2019.720p", "title": "Donation.2019.720p.mp4", "url": "https://cdn.example/x", "behaviorHints": {"filename": "Donation.2019.720p.mp4"}}]}
        with mock.patch.object(media_servers, "_request", return_value=json.dumps(pravi)):
            self.assertEqual([t["url"] for t in media_servers.stremio_tokovi("https://d.example", "movie", "tt1")],
                             ["https://cdn.example/f.mkv", "https://cdn.example/x"])

    def test_tokove_vprasamo_vse_dodatke(self):
        """Katalog (Cinemeta) pozna naslov, tok ima drug dodatek: film se predvaja, ne izgine."""
        from core import media_servers
        with tempfile.TemporaryDirectory() as mapa:
            m = os_media.MediaCenter(mapa, roots=[])
            film = {"id": "stremio:kat:movie:tt2", "naslov": "Film", "vrsta": "film", "url": "stremio:https://katalog.example|movie|tt2", "tmdb_id": 5}
            m._dynamic_items[film["id"]] = film

            def zahteva(url, *a, **k):
                if url.startswith("https://tokovi.example/stream/movie/tt2"):
                    return json.dumps({"streams": [{"name": "HD", "title": "Film.1080p.mkv", "url": "https://cdn.example/film.mkv"}]})
                if url.startswith("https://katalog.example/stream/"):
                    return json.dumps(self.TOKOVI)
                raise OSError(url)

            with mock.patch.object(m, "_stremio_strezniki", return_value=[{"url": "https://katalog.example/manifest.json"}, {"url": "https://tokovi.example/manifest.json"}]), \
                    mock.patch.object(media_servers, "_request", side_effect=zahteva):
                izid = m.resolve(film["id"])
            self.assertEqual(izid.get("url"), "https://cdn.example/film.mkv")
            self.assertFalse(m.znano_ni_na_voljo(film))

    def test_brez_toka_ni_strani_in_film_izgine(self):
        from core import media_servers
        with tempfile.TemporaryDirectory() as mapa:
            m = os_media.MediaCenter(mapa, roots=[])
            film = {"id": "stremio:s1:movie:tt1", "naslov": "Film", "vrsta": "film", "url": "stremio:https://d.example|movie|tt1",
                    "tmdb_id": 42, "imdb_id": "tt1"}
            m._dynamic_items[film["id"]] = film
            with mock.patch.object(media_servers, "_request", return_value=json.dumps(self.TOKOVI)):
                izid = m.resolve(film["id"])
            self.assertEqual(izid.get("napaka_koda"), "ni_toka")
            self.assertNotIn("stran", izid)
            self.assertNotIn("ko-fi", json.dumps(izid))
            katalog = {"vnosi": [{"id": "tmdb:42", "vrsta": "film", "tmdb_id": 42}, {"id": "tmdb:43", "vrsta": "film", "tmdb_id": 43},
                                 {"id": "tmdb:s42", "vrsta": "serija", "tmdb_id": 42}]}
            self.assertEqual([v["id"] for v in m.brez_nerazpolozljivih(katalog)["vnosi"]], ["tmdb:43", "tmdb:s42"])
            # Po preteku veljavnosti se film spet pokaze (dodatki dobivajo nove vsebine).
            m._ni_na_voljo["film:42"] -= m.NI_NA_VOLJO_VELJA + 1
            self.assertEqual(len(m.brez_nerazpolozljivih(katalog)["vnosi"]), 3)
            # Epizode ne skrivamo (ostale so morda na voljo).
            m.oznaci_ni_na_voljo({"vrsta": "serija", "tmdb_id": 7})
            self.assertFalse(m.znano_ni_na_voljo({"vrsta": "serija", "tmdb_id": 7}))


if __name__ == "__main__":
    unittest.main()
