"""Podnapisi ob videu (core/podnapisi.py): kateri sodijo k videu, jezik iz imena, pretvorba v WebVTT
in polje `subtitles` v seznamu deljene mape."""
import os
import shutil
import sys
import tempfile
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

from core import podnapisi as pn  # noqa: E402
from core.link_datoteke import DeljeneMape  # noqa: E402


class Ujemanje(unittest.TestCase):
    def test_jezik_iz_imena(self):
        self.assertEqual(pn.jezik("Film.mkv", "Film.en.srt"), ("en", ""))
        self.assertEqual(pn.jezik("Film.mkv", "Film.slv.forced.srt"), ("sl", "forced"))
        self.assertEqual(pn.jezik("Film.mkv", "Subs/2_English.srt"), ("en", ""))
        self.assertEqual(pn.jezik("Film.mkv", "Film.srt"), ("", ""))

    def test_kateri_sodijo_k_videu(self):
        kandidati = ["Film.en.srt", "Drugi.srt", "Subs/Film.sl.srt", "Subs/Film/3_Slovenian.srt",
                     "Extras/Film.srt", "Film.nfo", "Film.ass"]
        self.assertEqual(pn.ujemajoci("Film.mkv", kandidati, samo_en_video=False),
                         ["Film.ass", "Film.en.srt", "Subs/Film.sl.srt", "Subs/Film/3_Slovenian.srt"])
        # En sam video v mapi: vsi podnapisi so njegovi (a ne iz nepovezanih podmap).
        self.assertIn("Drugi.srt", pn.ujemajoci("Film.mkv", kandidati, samo_en_video=True))
        self.assertNotIn("Extras/Film.srt", pn.ujemajoci("Film.mkv", kandidati, samo_en_video=True))


class Vtt(unittest.TestCase):
    def test_srt(self):
        srt = "1\r\n00:00:01,500 --> 00:00:03,000\r\n<font color=red>Živjo</font> <i>svet</i>\r\n\r\n2\r\n00:00:04,000 --> 00:00:05,250\r\nDrugi\r\n"
        vtt = pn.srt_v_vtt(srt.encode("utf-8"))
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:01.500 --> 00:00:03.000\nŽivjo <i>svet</i>\n", vtt)
        self.assertIn("00:00:04.000 --> 00:00:05.250\nDrugi", vtt)
        # Windows-1250 (stari slovenski podnapisi)
        self.assertIn("Čas je za žgance, šef.", pn.srt_v_vtt("1\n00:00:01,000 --> 00:00:02,000\nČas je za žgance, šef.\n".encode("cp1250")))

    def test_srt_popravimo_kot_vlc(self):
        # Big Buck Bunny.en.srt: presledek za številko in CRLF - GStreamer in ExoPlayer ga sicer ne prebereta.
        raw = b"1 \r\n00:00:02,000 --> 00:00:05,000\r\nBig Buck Bunny\r\n\r\n1 \r\n00:00:45.5 --> 00:00:59,000\r\nHello\r\n\r\n"
        self.assertEqual(pn.srt_pocisti(raw), "1\n00:00:02,000 --> 00:00:05,000\nBig Buck Bunny\n\n"
                                              "2\n00:00:45,500 --> 00:00:59,000\nHello\n")
        d = tempfile.mkdtemp()
        try:
            izvor = os.path.join(d, "f.srt")
            with open(izvor, "wb") as f:
                f.write("1\n00:00:01,000 --> 00:00:02,000\nŠola\n".encode("cp1250"))
            uri = pn.pripravi("file://" + izvor, "f.srt", mapa=os.path.join(d, "c"))
            self.assertTrue(uri.startswith("file://" + d))
            with open(uri[7:], encoding="utf-8", newline="") as f:
                vsebina = f.read()
            self.assertIn("Šola\r\n", vsebina)             # CRLF: tako ga prepozna GStreamer
            self.assertEqual(pn.pripravi("https://tuj.example/x.srt", "x.srt"), "https://tuj.example/x.srt")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_ass(self):
        ass = ("[Script Info]\nTitle: x\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
               "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}Prva{\\i0}\\Nvrstica, z vejico\n")
        vtt = pn.ass_v_vtt(ass.encode())
        self.assertIn("00:00:01.000 --> 00:00:02.500\nPrva\nvrstica, z vejico\n", vtt)


class Mapa(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        for ime in ("Film.mkv", "Film.en.srt", "Film.sl.srt", "Drugi.mp4", "Drugi.srt", ".skrit.srt"):
            with open(os.path.join(self.d, ime), "wb") as d:
                d.write(b"1\n00:00:01,000 --> 00:00:02,000\nx\n")
        os.mkdir(os.path.join(self.d, "Subs"))
        with open(os.path.join(self.d, "Subs", "Film.hr.srt"), "wb") as d:
            d.write(b"x")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_seznam_pripne_podnapise(self):
        m = DeljeneMape([self.d])
        vnosi = m.dodaj_podnapise(m.seznam("share:0:"))
        film = next(v for v in vnosi if v["name"] == "Film.mkv")
        self.assertEqual([(p["name"], p["lang"]) for p in film["subtitles"]],
                         [("Film.en.srt", "en"), ("Film.sl.srt", "sl"), ("Film.hr.srt", "hr")])
        self.assertEqual(film["subtitles"][0]["id"], "share:0:Film.en.srt")
        self.assertIsNotNone(m.razresi(film["subtitles"][2]["id"]))
        drugi = next(v for v in vnosi if v["name"] == "Drugi.mp4")
        self.assertEqual([p["name"] for p in drugi["subtitles"]], ["Drugi.srt"])
        self.assertNotIn("subtitles", next(v for v in vnosi if v["name"] == "Film.en.srt"))


if __name__ == "__main__":
    unittest.main()
