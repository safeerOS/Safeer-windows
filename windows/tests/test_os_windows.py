"""Unit testi za Safeer OS Windows zaledje, Safeer Control in Google avtentikacijo."""

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


if __name__ == "__main__":
    unittest.main()
