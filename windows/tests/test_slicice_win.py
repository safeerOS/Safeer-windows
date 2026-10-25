"""Pomanjsane slicice v Datotekah namizja (lastnik, 25. 10. 2026): ta racunalnik in naprave v Safeer Linku.

Preverja ciste funkcije (kljuc predpomnilnika po napravi + poti + casu spremembe, ciscenje, varen streznik),
izdelavo slicice slike s tega racunalnika in celo pot do naprave: streznik datotek (core/link_datoteke, nova pot
/thumb/<id>) -> odjemalec slicice_win z zetonom in pripetim potrdilom.
"""
import io
import os
import sys
import tempfile
import threading
import time
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from safeer_windows import slicice_win as sw  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def _jpeg(pot, barva=(200, 80, 40), velikost=(1200, 800)):
    Image.new("RGB", velikost, barva).save(pot, "JPEG", quality=80)


class CisteFunkcije(unittest.TestCase):
    def test_vrsta(self):
        self.assertEqual(sw.vrsta_po_imenu("IMG_1.JPG"), "slika")
        self.assertEqual(sw.vrsta_po_imenu("film.mkv"), "video")
        self.assertEqual(sw.vrsta_po_imenu("porocilo.pdf"), "")
        self.assertEqual(sw.vrsta_vnosa({"vrsta": "slika", "pot": "x"}), "slika")
        self.assertEqual(sw.vrsta_vnosa({"type": "image", "id": "media:image:1"}), "slika")
        self.assertEqual(sw.vrsta_vnosa({"mime": "video/mp4", "id": "x"}), "video")
        self.assertEqual(sw.vrsta_vnosa({"mapa": True, "vrsta": "slika"}), "")

    def test_kljuc_po_napravi_poti_in_casu(self):
        a = sw.kljuc("ta", "C:\\a.jpg", 100, 5)
        self.assertEqual(a, sw.kljuc("ta", "C:\\a.jpg", 100.4, 5))       # cele sekunde
        self.assertNotEqual(a, sw.kljuc("ta", "C:\\a.jpg", 101, 5))      # spremenjena datoteka -> nova slicica
        self.assertNotEqual(a, sw.kljuc("ta", "C:\\a.jpg", 100, 6))
        self.assertNotEqual(a, sw.kljuc("n-telefon", "C:\\a.jpg", 100, 5))  # druga naprava, ista oznaka
        self.assertTrue(a.endswith(".jpg") and len(a) == 44)

    def test_ciscenje_najstarejsa_raba_prva(self):
        d = [("a", 100, 3.0), ("b", 100, 1.0), ("c", 100, 2.0)]
        self.assertEqual(sw.za_brisanje(d, 150), ["b", "c"])
        self.assertEqual(sw.za_brisanje(d, 300), [])

    def test_samo_https_s_pripetim_potrdilom(self):
        self.assertIsNone(sw.varen_streznik({"base_url": "http://192.168.0.5:5000", "fp": "ab"}))
        self.assertIsNone(sw.varen_streznik({"base_url": "https://192.168.0.5:5000", "fp": ""}))
        self.assertIsNone(sw.varen_streznik({"base_url": "https://192.168.0.5:5000/drugam", "fp": "ab"}))
        self.assertIsNone(sw.varen_streznik("https://x"))
        s = sw.varen_streznik({"base_url": "https://192.168.0.5:5000/", "fp": "ab", "token": "z"})
        self.assertEqual(s, {"base_url": "https://192.168.0.5:5000", "fp": "ab", "token": "z"})


@unittest.skipIf(Image is None, "brez Pillow")
class Izdelava(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self._prej = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = os.path.join(self.mapa, "lad")

    def tearDown(self):
        if self._prej is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._prej

    def test_slika_tega_racunalnika_in_predpomnilnik(self):
        pot = os.path.join(self.mapa, "foto.jpg")
        _jpeg(pot)
        s = sw.naredi_lokalno(pot)
        self.assertTrue(s.startswith(sw.mapa()) and os.path.isfile(s))
        with Image.open(s) as im:
            self.assertLessEqual(max(im.size), sw.ROB)
        self.assertEqual(sw.naredi_lokalno(pot), s)                      # drugic iz predpomnilnika
        self.assertEqual(sw.naredi_lokalno(os.path.join(self.mapa, "ni.jpg")), "")
        self.assertEqual(sw.naredi_lokalno(os.path.join(self.mapa, "x.pdf")), "")

    def test_vrsta_v_ozadju_sporoci_vsako_slicico(self):
        poti = []
        for i in range(3):
            p = os.path.join(self.mapa, "f%d.jpg" % i)
            _jpeg(p, (i * 60, 100, 200))
            poti.append(p)
        prisle, dogodek = [], threading.Event()

        def ob(d):
            prisle.append(d)
            if len(prisle) == 3:
                dogodek.set()
        v = sw.Slicice(ob)
        r = v.zahtevaj("ta", [{"pot": p, "vrsta": "slika"} for p in poti] + [{"pot": "x.pdf", "vrsta": "dokument"}])
        self.assertEqual((r["slicice"], r["v_delu"]), ({}, 3))
        self.assertTrue(dogodek.wait(20))
        self.assertEqual(sorted(d["id"] for d in prisle), sorted(poti))
        # Ko so narejene, pridejo takoj (iz predpomnilnika), brez dela v ozadju.
        r2 = v.zahtevaj("ta", [{"pot": p, "vrsta": "slika"} for p in poti])
        self.assertEqual((len(r2["slicice"]), r2["v_delu"]), (3, 0))
        v.ustavi()

    def test_slicica_z_naprave_prek_streznika_datotek(self):
        from core import link_datoteke
        deljena = os.path.join(self.mapa, "deljeno")
        os.makedirs(deljena)
        _jpeg(os.path.join(deljena, "dopust.jpg"), velikost=(2000, 1500))
        d = link_datoteke.Datoteke(poti=[deljena], tls_mapa=os.path.join(self.mapa, "tls"))
        try:
            o = d.seznam("share:0:", "n-telefon")
            vnos = next(v for v in o["items"] if v["name"] == "dopust.jpg")
            self.assertIn("modified", vnos)                              # ms, kot Android (datum na drugi napravi)
            streznik = dict(o["server"], base_url="https://127.0.0.1:%d" % d.streznik.vrata)
            s = sw.naredi_z_naprave("n-telefon", vnos["id"], vnos["modified"], vnos["size"], streznik)
            self.assertTrue(os.path.isfile(s))
            with Image.open(s) as im:
                self.assertLessEqual(max(im.size), link_datoteke.SLICICA_ROB)
            # Napacen zeton: streznik zavrne, slicice ni (in ni zapisana v predpomnilnik).
            napacen = dict(streznik, token="napacen")
            self.assertEqual(sw.naredi_z_naprave("n-drug", vnos["id"], vnos["modified"], vnos["size"], napacen), "")
            # Napacno potrdilo (drug odtis): povezava se ne vzpostavi.
            tuj = dict(streznik, fp="00" * 32)
            self.assertEqual(sw.naredi_z_naprave("n-tretji", vnos["id"], vnos["modified"], vnos["size"], tuj), "")
            # Oznaka zunaj deljene mape: 404.
            sw._mrtvi.clear()
            self.assertEqual(sw.naredi_z_naprave("n-telefon", "share:0:../tls/kljuc.pem", 1, 1, streznik), "")
        finally:
            d.ustavi()


@unittest.skipIf(Image is None, "brez Pillow")
class StreznikSlicic(unittest.TestCase):
    def test_brez_zetona_401(self):
        import http.client
        import ssl
        from core import link_datoteke
        mapa = tempfile.mkdtemp()
        _jpeg(os.path.join(mapa, "a.jpg"))
        d = link_datoteke.Datoteke(poti=[mapa], tls_mapa=os.path.join(mapa, ".tls"))
        try:
            d.seznam("share:0:", "n-x")
            k = ssl.create_default_context()
            k.check_hostname = False
            k.verify_mode = ssl.CERT_NONE
            c = http.client.HTTPSConnection("127.0.0.1", d.streznik.vrata, context=k, timeout=5)
            c.request("GET", "/thumb/share%3A0%3Aa.jpg")
            self.assertEqual(c.getresponse().status, 401)
        finally:
            d.ustavi()


if __name__ == "__main__":
    unittest.main()
