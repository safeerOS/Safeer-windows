"""Unit testi za Safeer OS Windows zaledje, Safeer Control in Google avtentikacijo."""

import base64
import json
import os
import tempfile
import unittest

from safeer_windows import control_backend, os_backend_win, policy
from core import link_hub


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

            s_datotekami = backend.naprave_s_datotekami()
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
        self.assertGreaterEqual(len(seznam["apps"]), len(PRIVZETI_PROGRAMI if "PRIVZETI_PROGRAMI" in dir() else [1,2,3]))

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


if __name__ == "__main__":
    unittest.main()

