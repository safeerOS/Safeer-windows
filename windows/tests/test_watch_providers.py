import unittest
import json
import urllib.parse
from unittest import mock

from core import watch_providers
from core.os_media import MediaCenter, TMDB_IMAGE


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit=-1): return self.payload[:limit]


class TestWatchCountry(unittest.TestCase):
    def test_locale_region_and_language_fallbacks(self):
        self.assertEqual(watch_providers.country_from_locale("de_DE.UTF-8"), "DE")
        self.assertEqual(watch_providers.country_from_locale("sl"), "SI")
        self.assertEqual(watch_providers.detect_country("fr", platform_name="posix",
                                                        locale_values=["C", "de_DE.UTF-8"]), "DE")
        self.assertEqual(watch_providers.detect_country("fr", platform_name="posix",
                                                        locale_values=["C", ""]), "FR")
        self.assertEqual(watch_providers.detect_country("xx", platform_name="posix",
                                                        locale_values=["C", ""]), "US")

    def test_windows_geo_id_precedes_locale(self):
        class Kernel:
            def GetUserGeoID(self, geo_class):
                self.geo_class = geo_class
                return 123

            def GetGeoInfoW(self, geo_id, geo_type, buffer, size, flags):
                buffer.value = "DE"
                return 2

        class FakeCtypes:
            def __init__(self):
                self.kernel = Kernel()

            def WinDLL(self, name, use_last_error=True):
                return self.kernel

            @staticmethod
            def create_unicode_buffer(size):
                import ctypes
                return ctypes.create_unicode_buffer(size)

        fake = FakeCtypes()
        self.assertEqual(watch_providers.detect_country("sl", platform_name="nt", ctypes_module=fake,
                                                        locale_values=["sl_SI"]), "DE")
        self.assertEqual(fake.kernel.geo_class, 16)

    def test_regions_selected_country_and_automatic_default(self):
        center = MediaCenter("/tmp/safeer-test-watch")
        center.watch_regions = lambda language="sl": {"regions": [
            {"code": "SI", "native_name": "Slovenija", "english_name": "Slovenia"},
            {"code": "DE", "native_name": "Deutschland", "english_name": "Germany"},
        ]}
        with mock.patch("core.os_media.watch_providers.detect_country", return_value="SI"):
            automatic = center.watch_country_settings("auto", "sl")
            selected = center.watch_country_settings("DE", "de")
        self.assertEqual((automatic["izbrana"], automatic["drzava"]), ("auto", "SI"))
        self.assertEqual(automatic["ime_drzave"], "Slovenija")
        self.assertEqual((selected["izbrana"], selected["drzava"], selected["ime_drzave"]),
                         ("DE", "DE", "Deutschland"))


class TestMediaWhereToWatch(unittest.TestCase):
    def setUp(self):
        self.center = MediaCenter("/tmp/safeer-test-watch")
        self.center.resolve = lambda _item_id: {
            "id": "catalog:gladiator", "tmdb_id": 98, "vrsta": "film", "naslov": "Gladiator"
        }
        self.center._tmdb_cache.clear()
        self.urlopen = mock.patch("core.os_media.urllib.request.urlopen", side_effect=self._fake_network)
        self.urlopen.start()
        self.addCleanup(self.urlopen.stop)

    def _fake_network(self, request, timeout=10):
        path = urllib.parse.urlsplit(request.full_url).path
        if path.endswith("/watch/providers/regions"):
            return FakeResponse({"results": [
                {"iso_3166_1": "SI", "native_name": "Slovenija", "english_name": "Slovenia"},
                {"iso_3166_1": "DE", "native_name": "Deutschland", "english_name": "Germany"},
            ]})
        if path == "/3/movie/98":
            return FakeResponse({"overview": "A Roman general.", "vote_average": 8.2, "seasons": []})
        if path == "/3/movie/98/watch/providers":
            return FakeResponse({"results": {
                "SI": {"link": "https://www.themoviedb.org/movie/98/watch?locale=SI",
                       "flatrate": [{"provider_name": "SkyShowtime", "logo_path": "/sky.png"}],
                       "rent": [{"provider_name": "Apple TV Store", "logo_path": "/apple.png"}]},
                "DE": {"link": "https://www.themoviedb.org/movie/98/watch?locale=DE",
                       "flatrate": [{"provider_name": "Netflix", "logo_path": "/netflix.png"}],
                       "buy": [{"provider_name": "Amazon Video", "logo_path": "/amazon.png"},
                               {"provider_name": "Regional Store", "logo_path": "/regional.png"}]},
            }})
        if path == "/3/tv/1399":
            return FakeResponse({"overview": "A fantasy drama.", "seasons": []})
        if path == "/3/tv/1399/watch/providers":
            return FakeResponse({"results": {
                "SI": {"link": "https://www.themoviedb.org/tv/1399/watch?locale=SI",
                       "flatrate": [{"provider_name": "HBO Max", "logo_path": "/hbo.png"}]},
                "DE": {"link": "https://www.themoviedb.org/tv/1399/watch?locale=DE",
                       "flatrate": [{"provider_name": "HBO Max", "logo_path": "/hbo.png"}]},
            }})
        raise AssertionError(path)

    def test_details_groups_logos_links_and_country(self):
        sl = self.center.details("catalog:gladiator", "SI", "sl")
        de = self.center.details("catalog:gladiator", "DE", "de")
        self.assertEqual(sl["kje_gledati"]["drzava"], "SI")
        self.assertEqual(de["kje_gledati"]["drzava"], "DE")
        self.assertEqual(sl["kje_gledati"]["skupine"][0]["ponudniki"][0]["ime"], "SkyShowtime")
        german_provider = de["kje_gledati"]["skupine"][0]["ponudniki"][0]
        self.assertEqual(german_provider["ime"], "Netflix")
        self.assertEqual(german_provider["logo"], TMDB_IMAGE + "/w92/netflix.png")
        self.assertEqual(german_provider["povezava"], "https://www.netflix.com/search?q=Gladiator")
        self.assertEqual(de["kje_gledati"]["skupine"][1]["ponudniki"][0]["povezava"],
                         "https://www.primevideo.com/search?phrase=Gladiator")
        self.assertEqual(de["kje_gledati"]["skupine"][1]["ponudniki"][1]["povezava"],
                         "https://www.themoviedb.org/movie/98/watch?locale=DE")

    def test_tv_details_use_the_requested_region(self):
        self.center.resolve = lambda _item_id: {
            "id": "catalog:got", "tmdb_id": 1399, "vrsta": "serija", "naslov": "Igra prestolov"
        }
        result = self.center.details("catalog:got", "SI", "sl")
        self.assertEqual(result["media_type"], "tv")
        self.assertEqual(result["kje_gledati"]["drzava"], "SI")
        self.assertEqual(result["kje_gledati"]["skupine"][0]["ponudniki"][0]["ime"], "HBO Max")

    def test_missing_provider_data_and_api_failure_do_not_break_details(self):
        with mock.patch("core.os_media.urllib.request.urlopen", side_effect=lambda request, timeout=10:
                        FakeResponse({"overview": "Still returned", "seasons": []})
                        if urllib.parse.urlsplit(request.full_url).path == "/3/movie/98"
                        else FakeResponse({"results": {}})):
            self.center._tmdb_cache.clear()
            self.center.watch_regions = lambda language="sl": {"regions": [
                {"code": "SI", "native_name": "Slovenija", "english_name": "Slovenia"},
                {"code": "DE", "native_name": "Deutschland", "english_name": "Germany"},
            ]}
            data = self.center.details("catalog:gladiator", "DE", "de")
        self.assertEqual(data["opis"], "Still returned")
        self.assertEqual(data["kje_gledati"]["skupine"], [])
        self.assertEqual(data["kje_gledati"]["ime_drzave"], "Deutschland")

        self.center.watch_regions = lambda language="sl": {"regions": []}
        self.center._tmdb_cache.clear()
        with mock.patch("core.os_media.urllib.request.urlopen", side_effect=OSError("offline")):
            self.center.resolve = lambda _item_id: {
                "id": "catalog:gladiator", "tmdb_id": 98, "vrsta": "film", "naslov": "Gladiator"
            }
            data = self.center.details("catalog:gladiator", "SI", "sl")
        self.assertTrue(data)
        self.assertEqual(data["kje_gledati"]["skupine"], [])


if __name__ == "__main__":
    unittest.main()
