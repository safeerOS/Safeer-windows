"""Ostrina in en kazalec v gledalcu oddaljenega zaslona na Windows (lastnik, 25. 10. 2026, 09:01-09:13).

Prej: slika 1920x1080 se je v okno (testni PC 1440x900, 100 %) risala pomanjsana z najblizjim sosedom - izpadel je
vsak cetrti stolpec in vrstica besedila; nad sliko kazalca v sliki je bil se lokalni kazalec. Preverjamo ciste
funkcije (oddaljeni_zaslon_prikaz), pikselsko tocen prikaz 1:1 tudi pri 125 % in pot slike dekoder -> pretvorba
(Lanczos) -> platno z laznim izvorom (PyAV, ce je na voljo)."""
import ctypes
import json
import os
import sys
import threading
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from safeer_windows import oddaljeni_zaslon_prikaz as p  # noqa: E402


class Mere(unittest.TestCase):
    def test_slika_gre_v_platno_ostane_1_1(self):
        self.assertEqual(p.velikost_slike((1920, 1080), (1920, 1040)), (1848, 1040))
        self.assertEqual(p.velikost_slike((1920, 1080), (1920, 1080)), (1920, 1080))
        self.assertEqual(p.velikost_slike((1280, 720), (1920, 1080)), (1280, 720))      # nikoli povecano
        self.assertEqual(p.velikost_slike((1920, 1080), (1440, 795)), (1413, 795))     # testni PC, okno cez zaslon
        self.assertEqual(p.velikost_slike((1920, 1080), (1440, 795), "1:1"), (1920, 1080))

    def test_polozaj_na_sredini_in_premik_za_misko(self):
        self.assertEqual(p.polozaj_slike((1413, 795), (1440, 795)), (13, 0))
        self.assertEqual(p.polozaj_slike((1920, 1080), (1440, 795), (0, 0)), (0, 0))
        self.assertEqual(p.polozaj_slike((1920, 1080), (1440, 795), (1439, 794)), (-480, -285))

    def test_tocka_v_izvor(self):
        self.assertEqual(p.v_izvor((13, 0), (13, 0), (1413, 795), (1920, 1080)), (0, 0))
        self.assertEqual(p.v_izvor((13 + 1412, 794), (13, 0), (1413, 795), (1920, 1080)), (1918, 1078))
        self.assertIsNone(p.v_izvor((5, 5), (13, 0), (1413, 795), (1920, 1080)))       # crn rob
        self.assertEqual(p.v_izvor((100, 50), (-480, -285), (1920, 1080), (1920, 1080)), (580, 335))  # 1:1

    def test_fizicne_pike(self):
        self.assertEqual(p.fizicno(1152, 1.25), 1440)
        self.assertEqual(p.VISINA_VRSTICE % 4, 0)                    # platno na celi piki pri 125/150/175 %
        for dpr in (1.0, 1.25, 1.5, 1.75, 2.0):
            self.assertEqual(p.VISINA_VRSTICE * dpr, int(p.VISINA_VRSTICE * dpr))


class ZahtevaSeje(unittest.TestCase):
    def test_pogled_dpi_in_merilo(self):
        v = p.pogled_za_izvor((1441, 795), 1.25)
        self.assertEqual((v["w"], v["h"], v["dpi"], v["scale"], v["kind"], v["touch"]),
                         (1440, 794, 120, 1.25, "racunalnik", False))
        self.assertAlmostEqual(v["density"], 0.75)

    def test_zahteva_kot_android(self):
        z = p.zahteva_seje("najvisja", "desktop", (1440, 795), 1.0, "ethernet")
        self.assertEqual(z["quality"], "najvisja")
        self.assertEqual(z["net"], "ethernet")
        self.assertEqual(z["caps"], ["handoff", "rtt", "gop", "kazalec", "izvorna", "brezizgubno", "profil"])
        self.assertEqual(z["codecs"], ["h264"])
        self.assertEqual(z["screen"], "desktop")
        self.assertNotIn("handoff", z)
        self.assertTrue(p.zahteva_seje("najvisja", "desktop", (1440, 795), 1.0, predano=True)["handoff"])
        self.assertNotIn("net", p.zahteva_seje("najvisja", "apps", (1440, 795), 1.0))
        izvor = (KOREN / "windows" / "safeer_windows" / "oddaljeni_zaslon.py").read_text(encoding="utf-8")
        self.assertIn('prikaz.zahteva_seje("najvisja", self.zaslon_cilj, platno, dpr,', izvor)
        self.assertIn("predano=predano)", izvor)

    def test_vmesnik_omrezja(self):
        self.assertEqual(ctypes.sizeof(p._VrsticaVmesnika), 1352)          # MIB_IF_ROW2
        self.assertEqual(p._VrsticaVmesnika.ReceiveLinkSpeed.offset, 1200)
        self.assertEqual(p._VrsticaVmesnika.Type.offset, 1128)
        self.assertEqual((p.vrsta_vmesnika(6, 14), p.vrsta_vmesnika(71, 9), p.vrsta_vmesnika(24, 0)),
                         ("ethernet", "wifi", ""))
        self.assertEqual(p.gostitelj("https://192.168.0.5:8990/x"), "192.168.0.5")
        self.assertEqual(p.gostitelj("192.168.0.5:8990"), "192.168.0.5")
        self.assertEqual(p.gostitelj("[fe80::1]:5"), "fe80::1")
        if sys.platform != "win32":
            self.assertEqual(p.omrezje_do("192.168.0.5"), {})


class Kazalec(unittest.TestCase):
    def test_oblike(self):
        self.assertIsNone(p.oblika_kazalca({"kazalec": [1, 2]}))           # samo polozaj (povecava televizorja)
        self.assertEqual(p.oblika_kazalca({"oblika": "besedilo", "viden": True}), "IBeamCursor")
        self.assertEqual(p.oblika_kazalca({"oblika": "nekaj", "viden": True}), "ArrowCursor")
        self.assertEqual(p.oblika_kazalca({"oblika": "roka", "viden": False}), "BlankCursor")
        try:
            from PySide6.QtCore import Qt
        except ImportError:
            return
        for ime in set(p.OBLIKE_KAZALCA.values()) | {"BlankCursor"}:
            self.assertTrue(hasattr(Qt.CursorShape, ime), ime)

    def test_privzeto_en_kazalec(self):
        izvor = (KOREN / "windows" / "safeer_windows" / "oddaljeni_zaslon.py").read_text(encoding="utf-8")
        self.assertIn("self.setCursor(Qt.CursorShape.BlankCursor)", izvor)     # kazalec je ze v sliki izvora
        self.assertNotIn("SmoothPixmapTransform, False)\n        p.drawImage(self._cilj", izvor)


class Vrstica(unittest.TestCase):
    def test_lan_neposredno(self):
        v = p.vrstica_podatkov("sl", "192.168.0.10", False, {"vrsta": "ethernet", "hitrost_bps": 1_000_000_000},
                               (1920, 1080), (1920, 1080), 59.6, 14.2, 3.4)
        self.assertEqual(v, "LAN · kabel 1 Gb/s · neposredno · 1920×1080 1:1 · 60 fps · 14 Mb/s · zamik 3 ms")
        v = p.vrstica_podatkov("en", "93.184.216.34", True, {}, (1920, 1080), (1413, 795), 30, 4.25)
        self.assertEqual(v, "internet · via relay · 1920×1080 · scaled to 1413×795 · 30 fps · 4,2 Mb/s")
        self.assertEqual(p.hitrost_povezave(2_500_000_000), "2,5 Gb/s")
        self.assertEqual(p.hitrost_povezave(100_000_000), "100 Mb/s")
        for j in ("sl", "en", "de", "es", "fr", "it"):
            self.assertEqual(set(p.BESEDILA[j]), set(p.BESEDILA["sl"]), j)

    def test_odmev_in_percentil(self):
        o = p.odmev_rtt({"n": 7, "t": 123.5, "z": 4}, {"r": 1, "b": 2, "fps": 60.0, "pot": None})
        self.assertEqual(o, {"vrsta": "rtt", "n": 7, "t": 123.5, "r": 1, "b": 2, "fps": 60.0})
        self.assertIsNone(p.odmev_rtt({"n": True}, {}))
        self.assertIsNone(p.odmev_rtt({"n": 1.5}, {}))
        self.assertEqual((p.percentil([5, 1, 3, 2, 4], 50), p.percentil(range(1, 101), 95)), (3.0, 95.0))
        self.assertIsNone(p.percentil([], 50))


def _qt():
    # QApplication (ne QGuiApplication): drugi preizkusi v istem procesu ustvarjajo okna QWidget.
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        raise unittest.SkipTest("PySide6 ni na voljo")
    return QApplication.instance() or QApplication([])


class PikselskoTocno(unittest.TestCase):
    def test_1_1_pri_125_odstotkih(self):
        """Isti racun kot _Slika.paintGL: slika fizicne velikosti na celi piki -> vsaka pika enaka izvoru."""
        _qt()
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QImage, QPainter
        izvor = QImage(301, 157, QImage.Format.Format_ARGB32)
        for y in range(izvor.height()):
            for x in range(izvor.width()):
                izvor.setPixelColor(x, y, QColor((x * 7) % 256, (y * 13) % 256, ((x ^ y) * 5) % 256))
        for dpr in (1.0, 1.25, 1.5):
            platno = QImage(400, 200, QImage.Format.Format_ARGB32)
            platno.fill(QColor("#05070b"))
            platno.setDevicePixelRatio(dpr)
            kot = p.polozaj_slike((izvor.width(), izvor.height()), (400, 200))
            r = QPainter(platno)
            r.drawImage(QRectF(kot[0] / dpr, kot[1] / dpr, izvor.width() / dpr, izvor.height() / dpr), izvor)
            r.end()
            razlike = sum(1 for y in range(izvor.height()) for x in range(izvor.width())
                          if platno.pixel(kot[0] + x, kot[1] + y) != izvor.pixel(x, y))
            self.assertEqual(razlike, 0, dpr)


class PotSlike(unittest.TestCase):
    """Lazen izvor: glava, slike H.264 in ping; gledalec vrne odmev in pripravi sliko v velikosti platna."""

    def setUp(self):
        try:
            import av  # noqa: F401
        except ImportError:
            self.skipTest("PyAV ni na voljo")
        _qt()

    def _tok(self, sirina=640, visina=360, slik=6):
        import av
        import io
        izhod = io.BytesIO()
        kontejner = av.open(izhod, "w", format="h264")
        tok = kontejner.add_stream("libx264", rate=30)
        tok.width, tok.height, tok.pix_fmt = sirina, visina, "yuv420p"
        tok.options = {"qp": "16", "tune": "zerolatency"}
        paketi = []
        for i in range(slik):
            okvir = av.VideoFrame(sirina, visina, "yuv420p")
            for ravnina in okvir.planes:
                ravnina.update(bytes([(i * 30 + 16) % 256]) * ravnina.buffer_size)
            paketi += [bytes(x) for x in tok.encode(okvir)]
        paketi += [bytes(x) for x in tok.encode(None)]
        kontejner.close()
        return paketi

    def test_pomanjsano_v_niti_in_odmev(self):
        from safeer_windows import oddaljeni_zaslon as oz
        paketi = self._tok()
        poslano, slike, konec = [], [], threading.Event()

        class Povezava:
            def __init__(self, _seja):
                pass

            def povezi(self):
                return {"v": 2, "w": 640, "h": 360, "kodek": "h264", "rtt": True}

            def okvirji(self):
                yield oz.OKVIR_OBVESTILO, json.dumps({"rtt": {"n": 1, "t": 10.0, "z": 5}}).encode()
                for x in paketi:
                    yield oz.OKVIR_SLIKA, x
                konec.wait(5)

            def poslji(self, d):
                poslano.append(d)

            def zapri(self):
                konec.set()

        signali = oz._TokSignali()
        prejeto = threading.Event()

        def ob_sliki(s):
            slike.append((s.width(), s.height()))
            nit.prikaz_prost.set()
            if len(slike) >= 2:
                prejeto.set()
        signali.slika.connect(ob_sliki, oz.Qt.ConnectionType.DirectConnection)
        prej = oz.PovezavaGledalca
        oz.PovezavaGledalca = Povezava
        try:
            nit = oz._DekodirnaNit(oz.Seja("192.168.0.5", 1, "ab", "z"), signali, "preizkus")
            nit.cilj = (320, 180)
            nit.start()
            self.assertTrue(prejeto.wait(20))
        finally:
            nit.ustavi()
            oz.PovezavaGledalca = prej
        self.assertIn((320, 180), slike)
        odmev = next(d for d in poslano if d.get("vrsta") == "rtt")
        self.assertEqual((odmev["n"], odmev["t"], odmev["pot"]), (1, 10.0, "neposredno"))
        self.assertEqual(nit.stevci.rtt, [5.0])


if __name__ == "__main__":
    unittest.main()
