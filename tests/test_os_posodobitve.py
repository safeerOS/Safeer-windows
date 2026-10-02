"""Posodobitve s safeer.si: primerjava razlicic, izbira datoteke po nacinu namestitve, prenos s SHA-256, AppImage zamenjava."""
import hashlib
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import os_posodobitve as op  # noqa: E402

MANIFEST = {
    "android": {"si.safeer.phone": {"razlicica": "0.5.28", "koda": 53, "url": "https://safeer.si/os/a.apk", "sha256": "0" * 64, "velikost": 5}},
    "linux": {"safeer-os": {"razlicica": "0.4.23", "deb": {"url": "https://safeer.si/os/safeer-os_0.4.23_all.deb", "sha256": "a" * 64, "velikost": 1},
                            "tema_deb": {"url": "https://safeer.si/os/safeer-os-tema_0.4.23_all.deb", "sha256": "b" * 64, "velikost": 1},
                            "flatpak": {"url": "https://safeer.si/os/Safeer-OS-0.4.23-x86_64.flatpak", "sha256": "c" * 64, "velikost": 1},
                            "appimage": {"url": "https://github.com/x/Safeer-OS-0.4.23-x86_64.AppImage", "sha256": "d" * 64, "velikost": 1}},
              "safeer-control": {"razlicica": "2.1.21", "deb": {"url": "https://safeer.si/os/safeer-control_2.1.21_all.deb", "sha256": "e" * 64, "velikost": 1}}},
    "windows": {"safeer-os": {"razlicica": "1.0.18", "url": "https://github.com/x/SafeerOS-Windows-1.0.18.exe", "sha256": "f" * 64, "velikost": 1},
                "novo": {"sl": "Posodobitve z enim pritiskom.", "en": "One-press updates."}},
    "stran": "https://safeer.si/os/",
}


class Razlicice(unittest.TestCase):
    def test_novejsa(self):
        self.assertTrue(op.novejsa("0.4.23", "0.4.22"))
        self.assertTrue(op.novejsa("0.5.0", "0.4.99"))
        self.assertTrue(op.novejsa("1.0.18", "1.0.9"))
        self.assertFalse(op.novejsa("0.4.22", "0.4.22"))
        self.assertFalse(op.novejsa("0.4.21", "0.4.22"))
        self.assertFalse(op.novejsa("", "0.4.22"))

    def test_preveri_linux_deb(self):
        i = op.preveri("linux", {"safeer-os": "0.4.22", "safeer-control": "2.1.21"}, MANIFEST, nacin="deb")
        self.assertEqual([n["kljuc"] for n in i["nove"]], ["safeer-os"])
        n = i["nove"][0]
        self.assertEqual((n["ime"], n["nasa"], n["razlicica"], n["datoteka"]["url"].rsplit("/", 1)[1]), ("Safeer OS", "0.4.22", "0.4.23", "safeer-os_0.4.23_all.deb"))
        self.assertEqual(n["tema"]["url"].rsplit("/", 1)[1], "safeer-os-tema_0.4.23_all.deb")
        self.assertEqual(op.opis(i), "Safeer OS 0.4.23")

    def test_preveri_flatpak_appimage_windows(self):
        f = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="flatpak")["nove"][0]
        self.assertTrue(f["datoteka"]["url"].endswith(".flatpak") and "tema" not in f)
        a = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="appimage")["nove"][0]
        self.assertTrue(a["datoteka"]["url"].endswith(".AppImage"))
        w = op.preveri("windows", {"safeer-os": "1.0.17"}, MANIFEST, nacin="windows")
        self.assertEqual((w["nove"][0]["razlicica"], w["nove"][0]["datoteka"]["url"].rsplit("/", 1)[1]), ("1.0.18", "SafeerOS-Windows-1.0.18.exe"))
        self.assertEqual((w["novo"]["sl"], w["novo"]["en"]), ("Posodobitve z enim pritiskom.", "One-press updates."))
        self.assertEqual(op.preveri("windows", {"safeer-os": "1.0.18"}, MANIFEST, nacin="windows")["nove"], [])
        self.assertEqual(op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="deb")["novo"], {})
        # neznan nacin: nova razlicica brez datoteke (vmesnik odpre stran)
        n = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="neznano")["nove"][0]
        self.assertIsNone(n["datoteka"])


class Prenos(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.vsebina = os.urandom(200_000)
        with open(os.path.join(self.mapa, "paket.deb"), "wb") as f:
            f.write(self.vsebina)
        mapa = self.mapa

        class Streznik(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=mapa, **k)

            def log_message(self, *a):
                pass
        self.s = socketserver.TCPServer(("127.0.0.1", 0), Streznik)
        self.vrata = self.s.server_address[1]
        threading.Thread(target=self.s.serve_forever, daemon=True).start()

    def tearDown(self):
        self.s.shutdown()
        self.s.server_close()

    def test_prenos_sha_in_napredek(self):
        cilj = os.path.join(self.mapa, "dol", "paket.deb")
        napredki = []
        pot = op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, hashlib.sha256(self.vsebina).hexdigest(), len(self.vsebina),
                         napredek=lambda a, b: napredki.append((a, b)))
        self.assertEqual(pot, cilj)
        with open(cilj, "rb") as f:
            self.assertEqual(f.read(), self.vsebina)
        self.assertEqual(napredki[-1], (len(self.vsebina), len(self.vsebina)))
        self.assertFalse(os.path.exists(cilj + ".del"))

    def test_napacna_vsota_zavrze(self):
        cilj = os.path.join(self.mapa, "dol", "paket2.deb")
        with self.assertRaises(ValueError):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, "0" * 64)
        self.assertFalse(os.path.exists(cilj))
        self.assertFalse(os.path.exists(cilj + ".del"))

    def test_prekinitev(self):
        cilj = os.path.join(self.mapa, "dol", "paket3.deb")
        with self.assertRaises(InterruptedError):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, "", prekini=lambda: True)

    def test_appimage_zamenja_samega_sebe(self):
        star = os.path.join(self.mapa, "Safeer-OS-0.4.22-x86_64.AppImage")
        nov = os.path.join(self.mapa, "dol", "Safeer-OS-0.4.23-x86_64.AppImage")
        os.makedirs(os.path.dirname(nov))
        open(star, "wb").write(b"star")
        open(nov, "wb").write(b"nov")
        os.environ["APPIMAGE"] = star
        try:
            r = op.namesti_linux("appimage", [nov])
        finally:
            del os.environ["APPIMAGE"]
        self.assertEqual(r.returncode, 0)
        # ista pot kot prej (bliznjice ostanejo), vsebina nova, izvedljiva
        self.assertTrue(os.access(star, os.X_OK))
        with open(star, "rb") as f:
            self.assertEqual(f.read(), b"nov")
        self.assertFalse(os.path.exists(nov))

    def test_posodabljanje_stanje(self):
        p = op.Posodabljanje()
        self.assertFalse(p.tece())
        konec = threading.Event()

        def delo(x):
            x.odstotek = 50
            konec.wait(5)
        self.assertTrue(p.zacni(delo))
        self.assertFalse(p.zacni(delo))
        self.assertTrue(p.stanje()["tece"])
        konec.set()
        p.nit.join(5)
        self.assertEqual(p.stanje()["faza"], "koncano")

        def pade(x):
            raise ValueError("ni")
        p.zacni(pade)
        p.nit.join(5)
        self.assertEqual((p.faza, p.sporocilo), ("napaka", "ni"))


if __name__ == "__main__":
    unittest.main()
