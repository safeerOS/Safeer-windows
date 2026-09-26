"""Unit testi za Safeer OS Windows zaledje, Safeer Control in Google avtentikacijo."""

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from safeer_windows import control_backend, os_backend_win, policy
from core import link_hub, os_media, os_scit


class TestOsWindows(unittest.TestCase):
    def test_google_auth_urls_detected(self):
        auth_urls = [
            "https://accounts.google.com/signin/v2/identifier",
            "https://accounts.google.si/ServiceLogin",
            "https://mail.google.com/mail/u/0/#inbox",
            "https://accounts.youtube.com/accounts/SetSID",
            "https://myaccount.google.com/security",
            "https://www.google.com/signin",
            "https://www.google.si/servicelogin",
        ]
        for url in auth_urls:
            self.assertTrue(policy.is_google_auth_url(url), f"Moralo bi prepoznati kot Google auth: {url}")

    def test_non_auth_urls_not_flagged(self):
        regular_urls = [
            "https://www.google.com/search?q=test",
            "https://example.com/login",
            "https://github.com",
            "https://safeer.si",
        ]
        for url in regular_urls:
            self.assertFalse(policy.is_google_auth_url(url), f"Ne bi smelo prepoznati kot Google auth: {url}")

    def test_uporabniske_mape(self):
        mape = os_backend_win.uporabniske_mape()
        self.assertIsInstance(mape, list)
        self.assertTrue(len(mape) > 0)
        vrste = [m["vrsta"] for m in mape]
        self.assertIn("HOME", vrste)

    def test_vrsta_datoteke(self):
        self.assertEqual(os_backend_win.vrsta_datoteke("folder", je_mapa=True), "mapa")
        self.assertEqual(os_backend_win.vrsta_datoteke("slika.png"), "slika")
        self.assertEqual(os_backend_win.vrsta_datoteke("video.mp4"), "video")
        self.assertEqual(os_backend_win.vrsta_datoteke("pesem.mp3"), "zvok")
        self.assertEqual(os_backend_win.vrsta_datoteke("paket.zip"), "arhiv")
        self.assertEqual(os_backend_win.vrsta_datoteke("program.exe"), "program")
        self.assertEqual(os_backend_win.vrsta_datoteke("tekst.txt"), "dokument")
        self.assertEqual(os_backend_win.vrsta_datoteke("neznano.xyz"), "drugo")

    def test_preglej_mapo(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "podmapa"))
            with open(os.path.join(td, "dokument.txt"), "w") as f:
                f.write("test")
            vsebina = os_backend_win.preglej_mapo(td)
            self.assertEqual(len(vsebina["elementi"]), 2)
            imena = [e["ime"] for e in vsebina["elementi"]]
            self.assertIn("podmapa", imena)
            self.assertIn("dokument.txt", imena)

    def test_doloci_skupino(self):
        self.assertEqual(os_backend_win.doloci_skupino("Google Chrome", "chrome.lnk"), "splet")
        self.assertEqual(os_backend_win.doloci_skupino("Microsoft Word", "winword.lnk"), "pisarna")
        self.assertEqual(os_backend_win.doloci_skupino("VLC Media Player", "vlc.lnk"), "predstavnost")
        self.assertEqual(os_backend_win.doloci_skupino("Visual Studio Code", "code.lnk"), "programiranje")
        self.assertEqual(os_backend_win.doloci_skupino("Nadzorna plošča", "control.exe"), "sistem")

    def test_stanje_sistema(self):
        st = os_backend_win.stanje_sistema()
        self.assertIn("cpu", st)
        self.assertIn("ram", st)
        self.assertIn("ram_gb", st)
        self.assertIn("disk", st)

    def test_windows_nastavitve_uporabljajo_pogodbo_vmesnika(self):
        razpolozljivo = os_backend_win.razpolozljive_nastavitve()
        self.assertIsInstance(razpolozljivo["moduli"], list)
        self.assertIsInstance(razpolozljivo["orodja"], list)
        self.assertIn("display", razpolozljivo["moduli"])
        self.assertIn("omrezje", razpolozljivo["orodja"])

    def test_napajalni_ukazi_iz_vmesnika_so_preslikani_na_windows(self):
        primeri = {
            "zakleni": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "ponovni-zagon": ["shutdown.exe", "/r", "/t", "0"],
            "odjava": ["shutdown.exe", "/l"],
        }
        with mock.patch.object(os_backend_win.sys, "platform", "win32"), \
             mock.patch.object(os_backend_win.subprocess, "Popen") as popen:
            for dejanje, pricakovano in primeri.items():
                popen.reset_mock()
                self.assertTrue(os_backend_win.napajanje(dejanje))
                popen.assert_called_once_with(pricakovano)
            self.assertFalse(os_backend_win.napajanje("neznano-dejanje"))

    def test_windows_vmesnik_ne_uporablja_zastarele_trdo_zapisane_razlicice(self):
        koren = Path(__file__).resolve().parents[2]
        os_app = (koren / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        zaslon = (koren / "windows" / "safeer_windows" / "navidezni_zaslon.py").read_text(encoding="utf-8")
        self.assertIn('"razlicica": policy.APP_VERSION', os_app)
        self.assertIn('"version": policy.APP_VERSION', zaslon)
        self.assertNotIn('"razlicica": "0.5.0"', os_app)
        self.assertNotIn('"version": "0.5.0"', zaslon)

    def test_windows_besedila_in_prazna_stanja_so_varna(self):
        koren = Path(__file__).resolve().parents[2]
        skripta = (koren / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        self.assertIn('prilagodiPlatformo(z.namizje);', skripta)
        self.assertIn('nazajVMint: "Nazaj v Windows"', skripta)
        self.assertIn('S.zacetek.namizje === "windows"', skripta)
        os_app = (koren / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn('"naprave": [], "omrezja": [], "shranjene": []', os_app)
        self.assertIn('"izhodi": [], "vhodi": [], "programi": []', os_app)

    def test_link_in_control_sta_predstavljena_kot_del_safeer_os(self):
        koren = Path(__file__).resolve().parents[2]
        html = (koren / "assets" / "link" / "index.html").read_text(encoding="utf-8")
        skripta = (koren / "assets" / "link" / "link.js").read_text(encoding="utf-8")
        okno = (koren / "windows" / "safeer_windows" / "control_window.py").read_text(encoding="utf-8")

        self.assertIn('id="naslovAplikacije"', html)
        self.assertIn('id="podrocjeAplikacije"', html)
        self.assertIn('document.title = "Safeer OS · Naprave"', skripta)
        self.assertIn('besedilo("naslovAplikacije", "Safeer OS")', skripta)
        self.assertNotIn('naslov.textContent = "Safeer Control"', skripta)
        self.assertIn('self.setWindowTitle("Safeer OS · Naprave")', okno)

    def test_media_isti_vir_lahko_dodamo_samo_enkrat(self):
        payload = json.dumps({"items": [{"title": "Film", "url": "https://cdn.test/film-720p.mp4",
                                          "type": "movie", "year": 2025}]}).encode()
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            with mock.patch.object(center, "_download", return_value=(payload, "application/json", "https://api.test/catalog")):
                first = center.add_source("HTTPS://API.TEST/catalog/?utm_source=safeer", "Prvi vir")
                duplicate = center.add_source("https://api.test/catalog", "Isti vir")
            self.assertTrue(first["ok"])
            self.assertFalse(duplicate["ok"])
            self.assertEqual(duplicate["napaka"], "podvojen")
            self.assertEqual(len(center.sources()), 1)

    def test_media_zdruzi_enako_vsebino_in_izbere_najboljso(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            responses = {
                "https://a.test/catalog": json.dumps({"items": [{"title": "Moj film", "url": "https://a.test/film-720p.mp4", "type": "movie", "year": 2025}]}).encode(),
                "https://b.test/catalog": json.dumps({"items": [{"title": "Moj film 1080p", "url": "https://b.test/film-1080p.mp4", "type": "movie"}]}).encode(),
            }
            def download(url):
                return responses[url], "application/json", url
            with mock.patch.object(center, "_download", side_effect=download):
                self.assertTrue(center.add_source("https://a.test/catalog", "A")["ok"])
                self.assertTrue(center.add_source("https://b.test/catalog", "B")["ok"])
            catalog = center.catalog()
            self.assertEqual(len(catalog["vnosi"]), 1)
            item = catalog["vnosi"][0]
            self.assertEqual(item["kakovost"], "1080p")
            self.assertEqual(item["stevilo_razlicic"], 2)
            self.assertEqual(item["viri"], ["B", "A"])

    def test_media_razbere_api_m3u_in_spletno_aplikacijo(self):
        api = os_media.parse_payload(
            b'{"shows":[{"name":"Oddaja","type":"series","season":1,"episode":2,"streams":[{"url":"https://cdn.test/e2-1080p.mp4"}]}]}',
            "application/json", "https://api.test/catalog")
        m3u = os_media.parse_payload(
            b'#EXTM3U\n#EXTINF:-1 group-title="Music",Pesem\nhttps://cdn.test/song.mp3\n',
            "audio/x-mpegurl", "https://api.test/list.m3u")
        html = os_media.parse_payload(
            b'<script type="application/ld+json">{"name":"Film","contentUrl":"/film-4k.mp4","@type":"Movie"}</script>',
            "text/html", "https://app.test/watch")
        self.assertEqual(api[0]["vrsta"], "serija")
        self.assertEqual(api[0]["epizoda"], 2)
        self.assertEqual(m3u[0]["vrsta"], "glasba")
        self.assertEqual(html[0]["kakovost"], "4K")

    def test_media_razbere_in_podeduje_imdb_in_tmdb_id(self):
        payload = json.dumps({
            "results": [{
                "id": 27205,
                "media_type": "movie",
                "title": "Inception",
                "release_date": "2010-07-16",
                "poster_path": "/poster.jpg",
                "external_ids": {"imdb_id": "tt1375666"},
                "streams": [
                    {"url": "https://cdn-a.test/inception-720p.mp4", "quality": "720p"},
                    {"url": "https://cdn-b.test/inception-1080p.mp4", "quality": "1080p"},
                ],
            }]
        }).encode()
        items = os_media.parse_payload(payload, "application/json", "https://api.test/catalog")
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["imdb_id"] == "tt1375666" for item in items))
        self.assertTrue(all(item["tmdb_id"] == 27205 for item in items))
        self.assertTrue(all(item["leto"] == 2010 for item in items))
        self.assertTrue(all(item["slika"] == "https://image.tmdb.org/t/p/w500/poster.jpg" for item in items))

        endpoint_items = os_media.parse_payload(
            b'[{"title":"Fight Club","url":"https://cdn.test/fight.m3u8","quality":"Auto"}]',
            "application/json",
            "https://localhost/api/streams/movie/550",
        )
        self.assertEqual(endpoint_items[0]["tmdb_id"], 550)
        self.assertEqual(endpoint_items[0]["kakovost"], "1080p")

    def test_media_zdruzi_razlicne_naslove_po_zunanjem_id(self):
        english = os_media._item(
            "The Dark Knight", "https://a.test/dark-knight-720p.mp4", base="",
            source_id="a", source_name="A", kind="movie", year=2008,
            imdb_id="tt0468569", tmdb_id=155, quality="720p",
        )
        slovenian = os_media._item(
            "Vitez teme", "https://b.test/dark-knight-2160p.m3u8", base="",
            source_id="b", source_name="B", kind="movie", year=2008,
            imdb_id="tt0468569", quality="4K", description="Boljši opis",
        )
        merged = os_media.merge_duplicates([english, slovenian])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["imdb_id"], "tt0468569")
        self.assertEqual(merged[0]["tmdb_id"], 155)
        self.assertEqual(merged[0]["kakovost"], "4K")
        self.assertEqual(merged[0]["stevilo_razlicic"], 2)

    def test_media_ne_zdruzi_razlicnih_id_ali_epizod(self):
        first = os_media._item(
            "Enak naslov", "https://a.test/one.mp4", base="", source_id="a",
            source_name="A", kind="movie", year=2024, imdb_id="tt1234567",
        )
        second = os_media._item(
            "Enak naslov", "https://b.test/two.mp4", base="", source_id="b",
            source_name="B", kind="movie", year=2024, imdb_id="tt7654321",
        )
        episode_one = os_media._item(
            "Oddaja", "https://a.test/s1e1.mp4", base="", source_id="a",
            source_name="A", kind="series", imdb_id="tt9999999", season=1, episode=1,
        )
        episode_two = os_media._item(
            "Oddaja", "https://a.test/s1e2.mp4", base="", source_id="a",
            source_name="A", kind="series", imdb_id="tt9999999", season=1, episode=2,
        )
        merged = os_media.merge_duplicates([first, second, episode_one, episode_two])
        self.assertEqual(len(merged), 4)

    def test_media_isce_tudi_po_imdb_in_tmdb_id(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            payload = json.dumps([{
                "title": "Film", "url": "https://cdn.test/film.mp4",
                "imdb_id": "tt1234567", "tmdb_id": 98765,
            }])
            self.assertTrue(center.import_json(payload)["ok"])
            self.assertEqual(center.catalog("tt1234567")["skupaj"], 1)
            self.assertEqual(center.catalog("98765")["skupaj"], 1)

    def test_media_vmesnik_uporablja_vgrajeni_predvajalnik(self):
        koren = Path(__file__).resolve().parents[2]
        html = (koren / "assets" / "os" / "index.html").read_text(encoding="utf-8")
        app = (koren / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        player = (koren / "windows" / "safeer_windows" / "vlc_player.py").read_text(encoding="utf-8")
        self.assertIn('id="mediaDodajVir"', html)
        self.assertIn('id="mediaPredvajalnik"', html)
        self.assertIn("VlcPlayerWidget", app)
        self.assertIn("set_hwnd", player)
        self.assertIn("SAFEER OS · MEDIA", player)

    def test_media_viri_so_samo_v_nastavitvah_in_brez_iframe_predvajalnika(self):
        koren = Path(__file__).resolve().parents[2]
        html = (koren / "assets" / "os" / "index.html").read_text(encoding="utf-8")
        javascript = (koren / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        media_start = html.index('id="r-media"')
        settings_start = html.index('id="r-nastavitve"')
        source_form = html.index('id="mediaDodajVir"')
        self.assertLess(media_start, settings_start)
        self.assertGreater(source_form, settings_start)
        self.assertNotIn('id="mediaIframe"', html)
        self.assertNotIn('$("mediaIframe")', javascript)

    def test_safeer_os_uporablja_notranji_zasciteni_brskalnik(self):
        koren = Path(__file__).resolve().parents[2]
        app = (koren / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        launcher = (koren / "windows" / "safeer_os_windows.py").read_text(encoding="utf-8")
        self.assertIn("browser.BrowserWindow", app)
        self.assertIn("embedded=True", app)
        self.assertIn("self._odpri_notranji_splet(url, media=True)", app)
        self.assertNotIn("subprocess.Popen", app)
        for source in (app, launcher):
            self.assertNotIn("--disable-web-security", source)
            self.assertNotIn("--no-sandbox", source)

    def test_media_api_http_glave_se_ohranijo_za_libvlc(self):
        payload = json.dumps({
            "items": [{
                "title": "Film",
                "url": "https://cdn.test/film.m3u8",
                "headers": {"Referer": "https://app.test/", "User-Agent": "Safeer Test"},
            }]
        }).encode()
        item = os_media.parse_payload(payload, "application/json", "https://api.test/")[0]
        self.assertEqual(item["referer"], "https://app.test/")
        self.assertEqual(item["glave"]["User-Agent"], "Safeer Test")
        merged = os_media.merge_duplicates([item])[0]
        self.assertEqual(merged["razlicice"][0]["glave"]["Referer"], "https://app.test/")

        koren = Path(__file__).resolve().parents[2]
        player = (koren / "windows" / "safeer_windows" / "vlc_player.py").read_text(encoding="utf-8")
        self.assertIn(":http-referrer=", player)
        self.assertIn(":http-user-agent=", player)

    def test_media_samodejno_osvezi_samo_zastarele_vire(self):
        payload = b'{"items":[{"title":"Film","url":"https://cdn.test/film.mp4"}]}'
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            with mock.patch.object(center, "_download",
                                   return_value=(payload, "application/json", "https://api.test/catalog")) as download:
                self.assertTrue(center.add_source("https://api.test/catalog")["ok"])
                download.reset_mock()
                self.assertEqual(center.refresh_stale(max_age=3600)["osvezenih"], 0)
                download.assert_not_called()
                stored = center._load()
                stored["viri"][0]["posodobljeno"] = 0
                center._save(stored)
                self.assertEqual(center.refresh_stale(max_age=3600)["osvezenih"], 1)
                download.assert_called_once()

    # ------------------------------------------------------------------ Safeer Control testi
    def test_control_backend_identity(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            self.assertTrue(backend.device_id.endswith("-control"))
            self.assertTrue(backend.device_ime.startswith("Safeer Control"))

    def test_control_backend_stanje(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            st_os = backend.stanje_povezave()
            self.assertTrue(st_os["control"])
            self.assertEqual(st_os["stanje"], "nov")

            st_link = backend.stanje_linka()
            self.assertTrue(st_link["control"])
            self.assertEqual(st_link["id"], backend.device_id)
            self.assertTrue(st_link["brezPovezave"], "brezPovezave mora biti True, da stran prikaze gumb Nadaljuj brez povezave")
            self.assertFalse(st_link["brezPovezaveIzbrano"])

            backend.nadaljuj_brez_povezave()
            st_os_brez = backend.stanje_povezave()
            self.assertEqual(st_os_brez["stanje"], "brez")
            st_link_brez = backend.stanje_linka()
            self.assertTrue(st_link_brez["brezPovezave"])
            self.assertTrue(st_link_brez["brezPovezaveIzbrano"])

    def test_control_backend_settings(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            backend.nastavi_zaupanje(True)
            self.assertTrue(backend.nastavitve.get("zaupana"))
            backend.nadaljuj_brez_povezave()
            self.assertTrue(backend.nastavitve.get("brez_povezave"))

            # Ponovno nalozi
            backend2 = control_backend.SafeerControlBackend(config_pot=cfg)
            self.assertTrue(backend2.nastavitve.get("zaupana"))
            self.assertTrue(backend2.nastavitve.get("brez_povezave"))

    def test_control_backend_shared_folders(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            backend.dodaj_deljeno_mapo(td)
            self.assertIn(td, backend.deljene_mape())
            backend.odstrani_deljeno_mapo(0)
            self.assertEqual(len(backend.deljene_mape()), 0)

    def test_control_backend_devices_filtering(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            backend.naprave = [
                {"id": backend.device_id, "name": "Ta PC", "ta": True, "capabilities": ["files"]},
                {"id": "tv-1", "name": "Philips Android TV", "platform": "tv", "kind": "tv", "capabilities": ["apps", "remote"]},
                {"id": "phone-1", "name": "Samsung Telefon", "platform": "android", "kind": "phone", "capabilities": ["share"]},
            ]
            vse = backend.vse_naprave()
            self.assertEqual(len(vse), 3)
            ta_pc = next(n for n in vse if n["id"] == backend.device_id)
            self.assertTrue(ta_pc["ta"])

            s_programi = backend.naprave_s_programi()
            self.assertEqual(len(s_programi), 1)
            self.assertEqual(s_programi[0]["id"], "tv-1")

            # tv-1 ima capabilities brez files, phone-1 pa share (torej ni files). Dodajmo napravo s files:
            backend.naprave.append({"id": "pc-2", "name": "Linux PC", "platform": "linux", "kind": "desktop", "capabilities": ["files"]})
            s_datotekami2 = backend.naprave_s_datotekami()
            ids_dat = [d["id"] for d in s_datotekami2]
            self.assertIn("pc-2", ids_dat)
            self.assertNotIn(backend.device_id, ids_dat)

    def test_control_backend_datoteke_rpc(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            # Simuliraj ukaz_pocakaj
            def mock_ukaz(id_n, dejanje, parametri=None, cas=12.0):
                if dejanje == "files.list":
                    return {
                        "ok": True,
                        "data": {
                            "items": [
                                {"id": "share:0:video.mp4", "name": "video.mp4", "type": "video", "size": 1024},
                                {"id": "share:0:podmapa", "name": "podmapa", "type": "folder"}
                            ],
                            "folder": parametri.get("folder", "") if parametri else "",
                            "shared": True,
                            "server": {"base_url": "https://192.168.1.50:8992", "fp": "abc", "token": "xyz"}
                        }
                    }
                if dejanje == "files.open":
                    return {"ok": True, "message": "Datoteka se odpira"}
                return {"ok": False}

            backend.ukaz_pocakaj = mock_ukaz

            res = backend.datoteke_naprave("pc-2", "")
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["items"]), 2)
            self.assertTrue(res["shared"])
            self.assertEqual(res["server"]["token"], "xyz")

            res_odpri = backend.odpri_datoteko_naprave("pc-2", "share:0:video.mp4")
            self.assertTrue(res_odpri["ok"])

    def test_link_qr_svg_generation(self):
        svg = link_hub.qr_svg("safeer-link://join?a=192.168.0.135:8990")
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)

    def test_control_backend_stanje_linka_identity(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)
            st = backend.stanje_linka()
            self.assertEqual(st["idNaprave"], backend.device_id)
            self.assertEqual(st["imeNaprave"], backend.device_ime)
            self.assertEqual(st["id"], backend.device_id)
            self.assertEqual(st["naprava"], backend.device_ime)
            self.assertTrue(st["control"])

    def test_control_backend_cast_devices_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            dogodki = []
            backend.dodaj_poslusalca(lambda v, p: dogodki.append((v, p)))

            msg = {
                "type": "cast.devices",
                "devices": [
                    {
                        "id": "tv-1",
                        "name": "Philips Android TV",
                        "role": "receiver",
                        "capabilities": ["remote", "apps"],
                        "platform": "tv",
                        "kind": "screen",
                        "ip": "192.168.0.77",
                        "busy_by": "phone-1",
                        "busy_by_name": "Galaxy S25"
                    }
                ]
            }
            backend._na_sporocilo(msg)
            self.assertEqual(len(backend.naprave), 1)
            tv = backend.naprave[0]
            self.assertEqual(tv["naslov"], "192.168.0.77")
            self.assertEqual(tv["ip"], "192.168.0.77")
            self.assertEqual(tv["zasedenaOd"], "phone-1")
            self.assertEqual(tv["zasedenaOdIme"], "Galaxy S25")
            self.assertIn("remote", tv["zmoznosti"])

            vse = backend.vse_naprave()
            self.assertEqual(len(vse), 1)
            self.assertIn("remote", vse[0]["zmoznosti"])

    def test_control_backend_ukaz_and_result(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            # Ukaz z JSON nizom za parametre
            uspeh = backend.ukaz("tv-1", "key", json.dumps({"key": "up"}), "ref-123")
            self.assertTrue(uspeh)
            self.assertEqual(len(poslana), 1)
            u = poslana[0]
            self.assertEqual(u["type"], "control.command")
            self.assertEqual(u["target"], "tv-1")
            self.assertEqual(u["id"], "ref-123")
            self.assertEqual(u["payload"]["action"], "key")
            self.assertEqual(u["payload"]["params"], {"key": "up"})

            # Prejem control.result
            dogodki = []
            backend.dodaj_poslusalca(lambda v, p: dogodki.append((v, p)))
            res_msg = {
                "type": "control.result",
                "ref_id": "ref-123",
                "target": backend.device_id,
                "payload": {
                    "ok": True,
                    "message": "Key received",
                    "action": "key",
                    "data": {"volume": 25}
                }
            }
            backend._na_sporocilo(res_msg)
            self.assertTrue(any(v == "ukaz" for v, _ in dogodki))
            ukaz_dogodek = next(p for v, p in dogodki if v == "ukaz")
            self.assertEqual(ukaz_dogodek["ref"], "ref-123")
            self.assertEqual(ukaz_dogodek["ref_id"], "ref-123")
            self.assertTrue(ukaz_dogodek["ok"])
            self.assertEqual(ukaz_dogodek["data"], {"volume": 25})


class TestNavidezniZaslon(unittest.TestCase):
    def setUp(self):
        from safeer_windows.navidezni_zaslon import NavidezniZaslon
        self.zaslon = NavidezniZaslon()

    def tearDown(self):
        self.zaslon.ustavi_sejo()

    def test_inicializacija_in_geometrija(self):
        self.assertEqual(self.zaslon.sirina, 1920)
        self.assertEqual(self.zaslon.visina, 1080)
        self.assertEqual(self.zaslon.kazalec_x, 960)
        self.assertEqual(self.zaslon.kazalec_y, 540)
        self.assertEqual(self.zaslon.nacin, "namizje")

    def test_izolacija_tipk_in_dpad(self):
        # D-pad desno in dol
        self.assertEqual(self.zaslon.izbrani_indeks, 0)
        self.zaslon.obdelaj_tipko("right")
        self.assertEqual(self.zaslon.izbrani_indeks, 1)
        self.zaslon.obdelaj_tipko("down")
        self.assertEqual(self.zaslon.izbrani_indeks, 5)

        # OK sprozi program
        self.zaslon.obdelaj_tipko("ok")
        self.assertIn(self.zaslon.nacin, ("brskalnik", "program"))

        # Domov vrne na namizje
        self.zaslon.obdelaj_tipko("home")
        self.assertEqual(self.zaslon.nacin, "namizje")
        self.assertEqual(self.zaslon.izbrani_indeks, 0)

    def test_izolacija_miske_in_pomika(self):
        self.zaslon.obdelaj_misko("premik", 350, 450)
        self.assertEqual(self.zaslon.kazalec_x, 350)
        self.assertEqual(self.zaslon.kazalec_y, 450)

        self.zaslon.obdelaj_pomik("down")
        self.assertGreater(self.zaslon.scroll_odmik, 0)
        self.zaslon.obdelaj_pomik("top")
        self.assertEqual(self.zaslon.scroll_odmik, 0)

        # Vnos prek vmesnika NavidezniVnos
        self.assertTrue(self.zaslon.vnos.mozno)
        self.zaslon.vnos.izvedi({"vrsta": "tocka", "x": 500, "y": 600})
        self.assertEqual(self.zaslon.kazalec_x, 500)
        self.assertEqual(self.zaslon.kazalec_y, 600)

    def test_posnetek_zaslona(self):
        posnetek = self.zaslon.zajemi_posnetek()
        self.assertIsInstance(posnetek, dict)
        self.assertEqual(posnetek["width"], 1920)
        self.assertEqual(posnetek["height"], 1080)
        self.assertTrue(posnetek["image"].startswith("data:image/jpeg;base64,"))

        # Preveri, da je vsebina veljaven JPEG
        b64_podatki = posnetek["image"].split(",", 1)[1]
        raw_bajti = base64.b64decode(b64_podatki)
        self.assertTrue(raw_bajti.startswith(b"\xff\xd8"))

    def test_katalog_in_programi(self):
        kat = self.zaslon.katalog_aplikacij()
        self.assertIsInstance(kat, dict)
        self.assertIn("app_brskalnik", kat)
        self.assertEqual(kat["app_brskalnik"]["name"], "Brskalnik")

        seznam = self.zaslon.seznam_programov_za_daljinec(z_ikonami=True)
        self.assertIn("apps", seznam)
        self.assertIn("items", seznam)
        self.assertGreaterEqual(len(seznam["apps"]), 3)

    def test_pretocna_seja(self):
        seja = self.zaslon.zacni_sejo("tv-naprava")
        self.assertIsInstance(seja, dict)
        self.assertGreater(seja["port"], 0)
        self.assertTrue(bool(seja["token"]))
        self.assertTrue(bool(seja["fp"]))
        self.assertEqual(seja["codec"], "h264")
        self.assertEqual(seja["screen"], "virtual")
        self.assertEqual(seja["quality"], "najvisja")
        self.assertEqual(seja["fps"], 60)
        self.assertTrue(seja["secure"])

        stanje = self.zaslon.stanje_seje()
        self.assertTrue(stanje["tece"])
        self.assertEqual(stanje["vrata"], seja["port"])
        self.assertTrue(stanje["varno"])
        self.assertEqual(stanje["kakovost"], "najvisja")

        self.zaslon.ustavi_sejo()
        stanje_po = self.zaslon.stanje_seje()
        self.assertFalse(stanje_po["tece"])
        self.assertEqual(stanje_po["vrata"], 0)


class TestControlBackendDohodniNadzor(unittest.TestCase):
    def test_dohodni_ukaz_status_in_odziv(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            # Televizor poslje ukaz status
            cmd = {
                "id": "ukaz-status-1",
                "type": "control.command",
                "sender": "tv-1",
                "payload": {"action": "status", "params": {}}
            }
            backend._na_sporocilo(cmd)

            # Preveri odgovor control.result
            self.assertEqual(len(poslana), 1)
            res = poslana[0]
            self.assertEqual(res["type"], "control.result")
            self.assertEqual(res["target"], "tv-1")
            self.assertEqual(res["ref_id"], "ukaz-status-1")
            self.assertTrue(res["payload"]["ok"])
            self.assertEqual(res["payload"]["action"], "status")
            podatki = res["payload"]["data"]
            self.assertEqual(podatki["app"], "safeer-control-windows")
            self.assertEqual(podatki["screen"], "virtual")
            self.assertIn("key", podatki["actions"])
            self.assertIn("screenshot", podatki["actions"])

    def test_dohodni_ukaz_key_in_screenshot(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            # Tipka z daljinca
            cmd_key = {
                "id": "ukaz-key-1",
                "type": "control.command",
                "sender": "telefon-1",
                "payload": {"action": "key", "params": {"key": "right"}}
            }
            backend._na_sporocilo(cmd_key)
            self.assertEqual(backend.navidezni_zaslon.izbrani_indeks, 1)

            # Posnetek zaslona z daljinca
            cmd_ss = {
                "id": "ukaz-ss-1",
                "type": "control.command",
                "sender": "telefon-1",
                "payload": {"action": "screenshot", "params": {}}
            }
            backend._na_sporocilo(cmd_ss)
            self.assertEqual(len(poslana), 2)
            res_ss = poslana[1]
            self.assertEqual(res_ss["payload"]["action"], "screenshot")
            self.assertTrue(res_ss["payload"]["ok"])
            self.assertTrue(res_ss["payload"]["data"]["image"].startswith("data:image/jpeg;base64,"))

    def test_dohodni_ukaz_apps_in_open_url(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            # Zahteva po programih
            cmd_apps = {
                "id": "ukaz-apps-1",
                "type": "control.command",
                "sender": "tv-1",
                "payload": {"action": "apps.list", "params": {"limit": 10}}
            }
            backend._na_sporocilo(cmd_apps)
            self.assertEqual(len(poslana), 1)
            res_apps = poslana[0]
            self.assertTrue(res_apps["payload"]["ok"])
            self.assertIn("items", res_apps["payload"]["data"])
            self.assertIn("apps", res_apps["payload"]["data"])

            # Odpiranje URL na ločenem navideznem zaslonu
            cmd_url = {
                "id": "ukaz-url-1",
                "type": "control.command",
                "sender": "tv-1",
                "payload": {"action": "open_url", "params": {"url": "https://safeer.si"}}
            }
            backend._na_sporocilo(cmd_url)
            self.assertEqual(len(poslana), 2)
            self.assertEqual(backend.navidezni_zaslon.nacin, "brskalnik")
            self.assertEqual(backend.navidezni_zaslon.aktivni_url, "https://safeer.si")

    def test_dohodni_ukaz_volume(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            cmd_vol = {
                "id": "ukaz-vol-1",
                "type": "control.command",
                "sender": "tv-1",
                "payload": {"action": "volume", "params": {"level": 60}}
            }
            backend._na_sporocilo(cmd_vol)
            self.assertEqual(len(poslana), 1)
            res_vol = poslana[0]
            self.assertEqual(res_vol["payload"]["data"]["level"], 60)
            self.assertEqual(backend.navidezni_zaslon.glasnost, 60)

    def test_stanje_visoka_kakovost_in_varnost(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            stanje_p = backend.stanje_povezave()
            self.assertTrue(stanje_p.get("varno"))
            self.assertEqual(stanje_p.get("kakovost"), "najvisja")

            stanje_l = backend.stanje_linka()
            self.assertTrue(stanje_l.get("varno"))
            self.assertEqual(stanje_l.get("kakovost"), "najvisja")
            self.assertEqual(stanje_l.get("sifriranje"), "TLS 1.2+ (ECDHE/AEAD)")
            self.assertTrue(stanje_l.get("navidezni_zaslon"))

    def test_dohodni_ukaz_screen_start_privzeto_najvisja(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "link.json")
            backend = control_backend.SafeerControlBackend(config_pot=cfg)

            poslana = []
            class MockPovezava:
                tece = True
                def poslji(self, sporocilo):
                    poslana.append(sporocilo)
                    return True

            backend.povezava = MockPovezava()

            cmd_screen = {
                "id": "ukaz-scr-1",
                "type": "control.command",
                "sender": "tv-dnevna",
                "payload": {"action": "screen.start", "params": {}}
            }
            backend._na_sporocilo(cmd_screen)
            self.assertEqual(len(poslana), 1)
            res = poslana[0]
            self.assertTrue(res["payload"]["ok"])
            seja = res["payload"]["data"]
            self.assertEqual(seja["quality"], "najvisja")
            self.assertEqual(seja["fps"], 60)
            self.assertTrue(seja["secure"])
            self.assertEqual(seja["screen"], "virtual")

            backend.navidezni_zaslon.ustavi_sejo()

    def test_enotni_program_vstopna_tocka(self):
        pot = os.path.join(os.path.dirname(__file__), "..", "safeer_control_windows.py")
        self.assertTrue(os.path.exists(pot))
        with open(pot, "r", encoding="utf-8") as f:
            vsebina = f.read()
        self.assertIn("from safeer_windows.os_app import main", vsebina)
        self.assertIn("--control", vsebina)
        self.assertIn("--okno", vsebina)

    def test_media_center_import_and_export_json(self):
        with tempfile.TemporaryDirectory() as td:
            mc = os_media.MediaCenter(td, roots=[])
            izvoz = mc.export_json()
            self.assertEqual(izvoz.get("razlicica"), 1)
            self.assertEqual(izvoz.get("aplikacija"), "Safeer Media")
            self.assertIsInstance(izvoz.get("viri"), list)

            # Neveljaven JSON
            res_bad = mc.import_json("neveljaven { json")
            self.assertFalse(res_bad["ok"])
            self.assertIn("Neveljaven JSON", res_bad["napaka"])

            # Uvoz seznama medijskih vsebin
            primer_json = json.dumps([
                {
                    "title": "Sintel (Odprti film)",
                    "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
                    "type": "film",
                    "year": 2010
                },
                {
                    "title": "Big Buck Bunny",
                    "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
                    "type": "film",
                    "year": 2008
                }
            ])
            res_import = mc.import_json(primer_json, default_name="Moj testni vir")
            self.assertTrue(res_import["ok"])
            self.assertEqual(res_import["st_vnosov"], 2)
            self.assertEqual(res_import["vir"], "Moj testni vir")

            kat = mc.catalog()
            self.assertEqual(kat["skupaj"], 2)
            naslovi = [x["naslov"] for x in kat["vnosi"]]
            self.assertIn("Sintel (Odprti film)", naslovi)
            self.assertIn("Big Buck Bunny", naslovi)

    def test_media_center_import_full_export_structure(self):
        with tempfile.TemporaryDirectory() as td:
            mc = os_media.MediaCenter(td, roots=[])
            izvozen_paket = {
                "razlicica": 1,
                "viri": [
                    {
                        "id": "vir-test-1",
                        "url": "https://primer.si/vir1.json",
                        "ime": "Prvi vir",
                        "vnosi": [
                            {"naslov": "Film 1", "url": "https://primer.si/film1.mp4", "vrsta": "film"}
                        ]
                    }
                ]
            }
            res = mc.import_json(izvozen_paket)
            self.assertTrue(res["ok"])
            self.assertEqual(res["st_dodanih"], 1)

            kat = mc.catalog()
            self.assertEqual(kat["skupaj"], 1)
            self.assertEqual(kat["vnosi"][0]["naslov"], "Film 1")

    def test_os_scit_windows(self):
        # Preizkusimo delovanje Scita s simuliranim okoljem
        class MockShramba:
            def __init__(self):
                self._d = {}
            def get(self, k, privzeto=None):
                return self._d.get(k, privzeto)
            def dobi(self, k, privzeto=None):
                return self._d.get(k, privzeto)
            def nastavi(self, k, v):
                self._d[k] = v
            def set(self, k, v):
                self._d[k] = v

        shramba = MockShramba()
        scit = os_scit.Scit(shramba)
        stanje = scit.stanje()
        self.assertIsInstance(stanje, dict)
        self.assertIn("vklop", stanje)
        self.assertIn("mozno", stanje)
        self.assertIn("tece", stanje)
        self.assertIn("blokiranih", stanje)

        # Preizkus pomožnih funkcij
        self.assertTrue(os_scit.isti_gostitelj("https://example.com/a", "http://example.com/b"))
        self.assertFalse(os_scit.isti_gostitelj("https://example.com/a", "https://other.com/a"))

        with mock.patch("core.os_scit.sys.platform", "win32"):
            with mock.patch.dict("os.environ", {"LOCALAPPDATA": "/tmp/test_localappdata"}):
                mapa = os_scit.podatkovna_mapa()
                self.assertTrue(str(mapa).endswith("scit"))

    def test_control_backend_pairing_and_lokalna_koda(self):
        oddani = []
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "control.json")
            cb = control_backend.SafeerControlBackend(config_pot=cfg)
            cb.dodaj_poslusalca(lambda vrsta, podatki=None: oddani.append((vrsta, podatki)))

            # Lokalna koda mora imeti 6 stevilk
            self.assertTrue(cb.lokalna_koda.isdigit())
            self.assertEqual(len(cb.lokalna_koda), 6)

            # Stanje linka mora vsebovati lokalnaKoda
            stanje = cb.stanje_linka()
            self.assertIn("lokalnaKoda", stanje)
            self.assertEqual(stanje["lokalnaKoda"], cb.lokalna_koda)

            # Nova lokalna koda
            nova = cb.nova_lokalna_koda()
            self.assertEqual(len(nova), 6)
            self.assertEqual(cb.lokalna_koda, nova)

            # zacni_qr mora takoj oddati SVG QR in lokalnaKoda
            oddani.clear()
            cb.zacni_qr()
            vrste = [v[0] for v in oddani]
            self.assertIn("qr", vrste)
            self.assertIn("lokalnaKoda", vrste)
            qr_podatki = next(v[1] for v in oddani if v[0] == "qr")
            self.assertIn("svg", qr_podatki)
            self.assertIn("<svg", qr_podatki["svg"])

            # Preizkus potrditve z lokalno kodo
            oddani.clear()
            cb.potrdi_kodo(cb.lokalna_koda)
            vrste = [v[0] for v in oddani]
            self.assertIn("seznanitev", vrste)
            seznanitev_rez = next(v[1] for v in oddani if v[0] == "seznanitev")
            self.assertTrue(seznanitev_rez)

            # Preizkus povezi_naprave
            cb.nastavitve["brez_povezave"] = True
            cb.povezi_naprave()
            self.assertFalse(cb.nastavitve["brez_povezave"])

    def test_media_embed_vir_vidsrc_in_iframe_podpora(self):
        # 1. HTML z vdelanim iframe in povezavami
        html = '''<!DOCTYPE html><html><body><h1>Test Portal</h1>
        <iframe src="https://vidsrc.cc/v2/embed/tv/tt0944947/1/5" title="Igra prestolov S01E05"></iframe>
        <a href="https://vidsrc.cc/v2/embed/tv/tt0944947/1/1">Epizoda 1: Zima prihaja</a>
        <a href="https://vidsrc.cc/v2/embed/movie/tt1375666">Inception Film</a>
        </body></html>'''
        items = os_media.parse_payload(html.encode("utf-8"), "text/html", "https://portal.test/igra")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["naslov"], "Igra prestolov S01E05")
        self.assertEqual(items[0]["vrsta"], "serija")
        self.assertEqual(items[0]["sezona"], 1)
        self.assertEqual(items[0]["epizoda"], 5)
        self.assertEqual(items[1]["naslov"], "Epizoda 1: Zima prihaja")
        self.assertEqual(items[1]["vrsta"], "serija")
        self.assertEqual(items[2]["naslov"], "Inception Film")
        self.assertEqual(items[2]["vrsta"], "film")

        # 2. Dodajanje korenskega vira vidsrc.cc v MediaCenter (VidSrc Embed Engine)
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            with mock.patch.object(center, "_download", side_effect=Exception("HTTP Error 403: Forbidden")):
                rez = center.add_source("https://vidsrc.cc", "VidSrc")
                self.assertTrue(rez["ok"])
                self.assertGreater(rez["vir"]["stevilo"], 5)
                cat_filmi = center.catalog("", "film")
                cat_serije = center.catalog("", "serija")
                self.assertTrue(len(cat_filmi["vnosi"]) > 0)
                self.assertTrue(len(cat_serije["vnosi"]) > 0)
                # Preveri, da imajo filmi vrsto film in serije vrsto serija
                self.assertTrue(all(x["vrsta"] == "film" for x in cat_filmi["vnosi"]))
                self.assertTrue(all(x["vrsta"] == "serija" for x in cat_serije["vnosi"]))
                # Preveri, da imajo serije nastavljeno sezono in epizodo
                self.assertTrue(any(x["sezona"] == 1 and x["epizoda"] == 5 for x in cat_serije["vnosi"]))

        # 3. Dodajanje specifične povezave do serije
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            with mock.patch.object(center, "_download", side_effect=Exception("HTTP Error 403: Forbidden")):
                rez_tv = center.add_source("https://vidsrc.cc/v2/embed/tv/tt0944947/1/5", "GoT Epizoda")
                self.assertTrue(rez_tv["ok"])
                cat = center.catalog("", "vse")
                self.assertEqual(len(cat["vnosi"]), 1)
                item = cat["vnosi"][0]
                self.assertEqual(item["vrsta"], "serija")
                self.assertEqual(item["sezona"], 1)
                self.assertEqual(item["epizoda"], 5)
                self.assertIn("tt0944947", item["url"])

    def test_os_app_media_predvajaj_embed_is_not_native(self):
        # Preveri, da obravnava v os_app za embed vsebine določa native=False
        koren = Path(__file__).resolve().parent.parent.parent
        os_app_src = (koren / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn("is_embed = (", os_app_src)
        self.assertIn("native = self.media_player.available and is_direct_stream and not is_embed", os_app_src)
        self.assertIn('"vidsrc"', os_app_src)

        # Preveri prepoznavo embed vira v core/os_media.py
        item = os_media._item("tt1375666", "https://vidsrc.cc/v2/embed/movie/tt1375666",
                              base="", source_id="s1", source_name="VidSrc", kind="film")
        self.assertIsNotNone(item)
        self.assertEqual(item["naslov"], "Inception (Izvor)")
        self.assertEqual(item["vrsta"], "film")
        self.assertEqual(item["leto"], 2010)


if __name__ == "__main__":
    unittest.main()
