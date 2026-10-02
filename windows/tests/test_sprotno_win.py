"""Windows kot pomocnik sprotnega pretvarjanja (core/link_sprotno.py + control_backend video.stream + ffmpeg_win)."""
import http.client
import http.server
import os
import ssl
import stat
import sys
import tempfile
import threading
import unittest
import zipfile
import hashlib
import io

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from core import link_datoteke, link_sprotno  # noqa: E402

try:
    from safeer_windows import control_backend, ffmpeg_win  # noqa: E402
except Exception as e:  # pragma: no cover - na sistemu brez Qt
    control_backend = None
    NAPAKA = e

IZVIRNIK = bytes(range(256)) * 64


class _Vir(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Content-Length", str(len(IZVIRNIK)))
        self.end_headers()
        self.wfile.write(IZVIRNIK)


LAZNI_FFMPEG = """#!/bin/sh
vhod=""; izhod=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-i" ]; then shift; vhod="$1"; fi
  izhod="$1"; shift
done
python3 - "$vhod" "$izhod" <<'EOF'
import sys, urllib.request
vse = urllib.request.urlopen(sys.argv[1], timeout=10).read()
open(sys.argv[2], "wb").write(vse)
EOF
"""


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
@unittest.skipIf(os.name == "nt", "lazni ffmpeg je lupinska skripta")
class SprotnoWinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapa = tempfile.mkdtemp()
        cls.ffmpeg = os.path.join(cls.mapa, "ffmpeg")
        with open(cls.ffmpeg, "w", encoding="utf-8") as d:
            d.write(LAZNI_FFMPEG)
        os.chmod(cls.ffmpeg, os.stat(cls.ffmpeg).st_mode | stat.S_IEXEC)
        cls.vir = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Vir)
        threading.Thread(target=cls.vir.serve_forever, daemon=True).start()
        cls.sprotno = link_sprotno.Sprotno(mapa=os.path.join(cls.mapa, "pretok"), ffmpeg=cls.ffmpeg,
                                           vaapi=lambda: None, strojni=lambda: None)

    @classmethod
    def tearDownClass(cls):
        cls.vir.shutdown()

    def _zaledje(self, profil):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.nastavitve = {"dovoljenja_naprav": {"tv-1": profil}}
        b.naprave = [{"id": "tv-1", "naprava": "tv-1"}]
        b._opozorjena_dovoljenja = set()
        b.shrani_nastavitve = lambda: True
        b._oddaj_dogodek = lambda *a, **k: None
        b.navidezni_zaslon = type("Z", (), {"tls_mapa": tempfile.mkdtemp()})()
        b._sprotno = lambda: self.sprotno
        return b

    def test_video_stream_prek_zaledja(self):
        b = self._zaledje("zaslon")
        # Solidarnost: tudi naprava s profilom "zaslon" sme prositi za moc racunalnika, ne pa za datoteke.
        self.assertTrue(b._dejanje_dovoljeno("tv-1", "video.stream"))
        self.assertTrue(b._dejanje_dovoljeno("tv-1", "host.info"))
        self.assertFalse(b._dejanje_dovoljeno("tv-1", "files.list"))
        b.nastavitve["dovoljenja_naprav"]["tv-1"] = "vprasaj"
        self.assertFalse(b._dejanje_dovoljeno("tv-1", "video.stream"))
        url = "http://127.0.0.1:%d/film.mkv" % self.vir.server_address[1]
        o = b._pretok("video.stream", {"url": url, "name": "Film.mkv", "duration_ms": 1000, "size": len(IZVIRNIK)}, "tv-1")
        self.assertTrue(o["ok"], o)
        d = o["data"]
        self.assertTrue(d["url"].startswith("https://") and "/live/" in d["url"])
        # Tok bere naprava z zetonom prek streznika datotek (samo /live/, brez deljenih map)
        s = b._sprotni_streznik()
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        p = http.client.HTTPSConnection("127.0.0.1", s.vrata, context=ctx, timeout=10)
        p.request("GET", "/live/" + d["id"], headers={"X-Safeer-Token": d["token"]})
        r = p.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.read(), IZVIRNIK)
        p.close()
        self.assertTrue(b._pretok("video.stream_status", {"id": d["id"]}, "tv-1")["data"]["done"])
        self.assertTrue(b._pretok("video.stream_stop", {"id": d["id"]}, "tv-1")["ok"])
        self.assertEqual(b._pretok("video.stream_stop", {"id": d["id"]}, "tv-1")["code"], "ni_opravila")
        self.assertEqual(b._pretok("video.stream", {"url": "ftp://x", "name": "a"}, "tv-1")["code"], "napacna_zahteva")

    def test_ffmpeg_win_paket(self):
        """Paket se sprejme samo s pravo SHA-256 in vsemi datotekami; pot_ffmpeg pozna le cel paket prave izdaje."""
        with tempfile.TemporaryDirectory() as m:
            os.environ["LOCALAPPDATA"] = m
            try:
                self.assertEqual(ffmpeg_win.pot_ffmpeg(), "")
                b = io.BytesIO()
                with zipfile.ZipFile(b, "w") as zf:
                    for ime in ffmpeg_win.OBVEZNO:
                        zf.writestr(ime, b"x")
                    zf.writestr("../zlo.txt", b"ne")
                podatki = b.getvalue()
                # napacna vsota -> zavrnjen
                stari = ffmpeg_win.SHA256
                sporocila = []
                pravi_urlopen = ffmpeg_win.urllib.request.urlopen
                ffmpeg_win.urllib.request.urlopen = lambda *a, **k: io.BytesIO(podatki)
                self.assertEqual(ffmpeg_win.prenesi(sporocila.append), "")
                self.assertTrue(any("SHA-256" in s for s in sporocila))
                ffmpeg_win.SHA256 = hashlib.sha256(podatki).hexdigest()
                try:
                    pot = ffmpeg_win.prenesi(sporocila.append)
                    self.assertTrue(pot.endswith(os.path.join("ffmpeg", "bin", "ffmpeg.exe")), pot)
                    self.assertEqual(ffmpeg_win.pot_ffmpeg(), pot)
                    self.assertFalse(os.path.exists(os.path.join(m, "zlo.txt")))
                    self.assertFalse(os.path.exists(os.path.join(m, "SafeerOS", "zlo.txt")))
                finally:
                    ffmpeg_win.SHA256 = stari
                    ffmpeg_win.urllib.request.urlopen = pravi_urlopen
                self.assertEqual(ffmpeg_win.pot_ffmpeg(), "")      # druga izdaja -> paket ne velja
            finally:
                os.environ.pop("LOCALAPPDATA", None)


if __name__ == "__main__":
    unittest.main()
