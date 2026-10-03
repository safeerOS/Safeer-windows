"""Magnet povezave (core/os_torrent.py): razčlenitev, varne datoteke, preverjen prenos programa,
geslo za API in lokalni tok z Range - z lažnim rqbitom (brez omrežja)."""
import base64
import hashlib
import http.server
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

from core import os_torrent as ot  # noqa: E402

HASH = "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
MAGNET = "magnet:?xt=urn:btih:%s&dn=Big+Buck+Bunny" % HASH


class Magnet(unittest.TestCase):
    def test_razclenitev(self):
        m = ot.razcleni_magnet(MAGNET)
        self.assertEqual((m["hash"], m["ime"], m["sledilniki"]), (HASH, "Big Buck Bunny", []))
        b32 = base64.b32encode(bytes.fromhex(HASH)).decode()
        self.assertEqual(ot.razcleni_magnet("magnet:?xt=urn:btih:" + b32)["hash"], HASH)
        for slab in ("", "http://x", "magnet:?xt=urn:btih:123", "magnet:?dn=x", MAGNET + "\nX", "magnet:?xt=urn:btih:" + "a" * 40 + "&x=" + "y" * 9000):
            self.assertIsNone(ot.razcleni_magnet(slab), slab[:40])

    def test_sledilniki_samo_ce_jih_ni(self):
        z = ot.z_sledilniki(MAGNET)
        self.assertEqual(len(ot.razcleni_magnet(z)["sledilniki"]), len(ot.SLEDILNIKI))
        s_svojim = MAGNET + "&tr=udp%3A%2F%2Fmoj.si%3A1%2Fannounce"
        self.assertEqual(ot.razcleni_magnet(ot.z_sledilniki(s_svojim))["sledilniki"], ["udp://moj.si:1/announce"])

    def test_tuja_povezava_ne_usmerja_v_domace_omrezje(self):
        zla = (MAGNET + "&tr=http%3A%2F%2F192.168.1.1%2Fcgi-bin%2Freboot&tr=http%3A%2F%2Flocalhost%3A8080%2Fx"
               "&tr=udp%3A%2F%2F10.0.0.1%3A6969&tr=http%3A%2F%2Frouter.lan%2F&tr=udp%3A%2F%2F%5B%3A%3A1%5D%3A1"
               "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&x.pe=192.168.1.5%3A445&ws=http%3A%2F%2F10.0.0.2%2F")
        m = ot.razcleni_magnet(zla)
        self.assertEqual(m["sledilniki"], ["udp://tracker.opentrackr.org:1337/announce"])
        self.assertNotIn("x.pe", m["uri"])
        self.assertNotIn("ws=", m["uri"])
        self.assertNotIn("192.168", ot.z_sledilniki(zla))

    def test_nevarne_datoteke(self):
        d = ot.razvrsti_datoteke([
            {"name": "Film.mkv", "length": 10}, {"name": "Film.srt", "length": 1},
            {"name": "Film.mkv.exe", "length": 5}, {"name": "navodila.txt", "length": 1},
            {"name": "skripta", "length": 1, "attributes": {"executable": True}},
            {"name": "pad", "length": 1, "attributes": {"padding": True}}])
        po_imenu = {x["ime"]: x for x in d}
        self.assertTrue(po_imenu["Film.mkv"]["predvajljivo"] and po_imenu["Film.mkv"]["izbrana"])
        self.assertTrue(po_imenu["Film.srt"]["izbrana"] and not po_imenu["Film.srt"]["predvajljivo"])
        self.assertEqual(po_imenu["Film.mkv.exe"]["vrsta"], "nevarno")
        self.assertFalse(po_imenu["Film.mkv.exe"]["izbrana"])
        self.assertEqual(po_imenu["skripta"]["vrsta"], "nevarno")
        self.assertNotIn("pad", po_imenu)
        self.assertTrue(ot.sumljiv(d))


class Program(unittest.TestCase):
    def test_prenos_samo_s_pravim_sha256(self):
        mapa = tempfile.mkdtemp()
        vsebina = b"rqbit" * 100
        paket = {ot.platforma() or "linux-x86_64": ("rqbit-linux-amd64", hashlib.sha256(vsebina).hexdigest(), len(vsebina))}

        class Odgovor(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        try:
            with mock.patch.object(ot, "RQBIT_PAKETI", paket), mock.patch.object(ot, "platforma", lambda: list(paket)[0]), \
                    mock.patch.object(ot, "mapa_programa", lambda: mapa):
                pot = ot.prenesi_program(odpri=lambda *_a, **_k: Odgovor(vsebina))
                self.assertTrue(os.path.isfile(pot) and os.access(pot, os.X_OK))
                self.assertTrue(ot.program_na_voljo())
                os.remove(pot)
                with self.assertRaises(RuntimeError):
                    ot.prenesi_program(odpri=lambda *_a, **_k: Odgovor(b"zlonamerno" + vsebina[10:]))
                self.assertFalse(os.path.exists(pot) or os.path.exists(pot + ".part"))
        finally:
            shutil.rmtree(mapa, ignore_errors=True)


class LazniRqbit(http.server.BaseHTTPRequestHandler):
    """Dovolj rqbitovega API-ja za preizkus: zahteva geslo, list_only, dodaj, podrobnosti, tok z Range."""
    protocol_version = "HTTP/1.1"
    PODATKI = bytes(range(256)) * 400
    DATOTEKE = [{"name": "Big Buck Bunny.en.srt", "length": 140}, {"name": "Big Buck Bunny.mp4", "length": len(PODATKI)},
                {"name": "virus.exe", "length": 10}]
    zahteve = []

    def log_message(self, *a):
        pass

    def _odgovor(self, koda, telo=b"", vrsta="application/json", glave=None):
        self.send_response(koda)
        self.send_header("Content-Type", vrsta)
        self.send_header("Content-Length", str(len(telo)))
        for k, v in (glave or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(telo)

    def _avtoriziran(self):
        return self.headers.get("Authorization") == "Basic " + base64.b64encode(("safeer:" + self.server.geslo).encode()).decode()

    def do_GET(self):
        if not self._avtoriziran():
            return self._odgovor(401)
        LazniRqbit.zahteve.append(("GET", self.path))
        if self.path == "/torrents":
            ts = [{"id": 0, "info_hash": HASH, "name": "Big Buck Bunny"}] if self.server.dodan else []
            return self._odgovor(200, json.dumps({"torrents": ts}).encode())
        if self.path == "/torrents/0":
            f = [dict(d, included=i in self.server.vkljucene) for i, d in enumerate(self.DATOTEKE)]
            return self._odgovor(200, json.dumps({"info_hash": HASH, "name": "Big Buck Bunny", "files": f}).encode())
        if self.path == "/torrents/0/stream/1":
            if getattr(self.server, "pripravlja", 0) > 0:
                # rqbit med pripravo torrenta: 500 z opisom stanja (izmerjeno na Windows, 3. 10. 2026).
                self.server.pripravlja -= 1
                return self._odgovor(500, json.dumps({"error_kind": "internal_error", "status": 500, "human_readable":
                                                      "with_storage_and_file: invalid state: initializing"}).encode())
            if getattr(self.server, "pokvarjen", False):
                return self._odgovor(500, b'{"human_readable":"disk error"}')
            p = self.PODATKI
            r = self.headers.get("Range")
            if r:
                a, b = r[6:].split("-")
                a, b = int(a), int(b) if b else len(p) - 1
                return self._odgovor(206, p[a:b + 1], "application/octet-stream",
                                     {"Content-Range": "bytes %d-%d/%d" % (a, b, len(p)), "Accept-Ranges": "bytes"})
            return self._odgovor(200, p, "application/octet-stream", {"Accept-Ranges": "bytes"})
        return self._odgovor(404)

    do_HEAD = do_GET

    def do_POST(self):
        if not self._avtoriziran():
            return self._odgovor(401)
        telo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        LazniRqbit.zahteve.append(("POST", self.path, telo))
        if self.path.startswith("/torrents?"):
            f = [dict(d, included=True) for d in self.DATOTEKE]
            if "list_only=true" in self.path:
                return self._odgovor(200, json.dumps({"id": None, "details": {"info_hash": HASH, "name": "Big Buck Bunny", "files": f},
                                                      "seen_peers": ["203.0.113.7:6881", "[2001:db8::1]:6881", "ni naslov"]}).encode())
            self.server.vkljucene = set(int(x) for x in self.path.split("only_files=")[1].split("&")[0].split(","))
            self.server.dodan = True
            return self._odgovor(200, json.dumps({"id": 0, "details": {"info_hash": HASH, "files": f}}).encode())
        if self.path.endswith("/update_only_files"):
            self.server.vkljucene = set(json.loads(telo)["only_files"])
        return self._odgovor(200, b"{}")


class Motor(unittest.TestCase):
    def setUp(self):
        self.s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LazniRqbit)
        self.s.geslo = "skrivno"
        self.s.vkljucene = set()
        self.s.dodan = False
        threading.Thread(target=self.s.serve_forever, daemon=True).start()
        self.mapa = tempfile.mkdtemp()
        self.t = ot.Torrenti(mapa_prenosov_=self.mapa, mapa_stanja_=os.path.join(self.mapa, "st"),
                             nastavitve=os.path.join(self.mapa, "n.json"))
        self.t.vrata, self.t._geslo = self.s.server_address[1], "skrivno"
        self.t.tece = lambda: True
        self.t.zazeni = lambda: None
        LazniRqbit.zahteve = []

    def tearDown(self):
        self.t._streznik and self.t._streznik.shutdown()
        self.s.shutdown()
        shutil.rmtree(self.mapa, ignore_errors=True)

    def test_brez_gesla_ni_dostopa(self):
        self.t._geslo = "napacno"
        with self.assertRaises(ot.NapakaTorrenta):
            self.t.preberi(MAGNET)

    def test_preberi_dodaj_in_tok(self):
        opis = self.t.preberi(MAGNET)
        self.assertTrue(opis["sumljiv"])
        self.assertEqual([d["ime"] for d in opis["datoteke"] if d["izbrana"]], ["Big Buck Bunny.en.srt", "Big Buck Bunny.mp4"])
        # Nevarne datoteke tudi ob izrecni izbiri ne prenesemo.
        tid = self.t.dodaj(MAGNET, [1, 2])
        self.assertEqual(tid, 0)
        dodaj = [z for z in LazniRqbit.zahteve if z[0] == "POST" and "only_files=" in z[1]]
        self.assertIn("only_files=0,1&", dodaj[-1][1] + "&")       # video + njegovi podnapisi, program ne
        self.assertIn(b"tr=", dodaj[-1][2])              # dodani sledilniki za hitrejše iskanje
        # Ponovno dodajanje istega magneta ne naredi novega torrenta, ampak doda datoteke.
        self.assertEqual(self.t.dodaj(MAGNET, [0]), 0)
        self.assertEqual(self.s.vkljucene, {0, 1})
        url = self.t.tok(0, 1)
        self.assertTrue(url.startswith("http://127.0.0.1:%d/t/" % self.t.vrata_toka))
        self.assertNotIn("skrivno", url)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=100-199"}), timeout=10) as r:
            self.assertEqual((r.status, r.read()), (206, LazniRqbit.PODATKI[100:200]))
            self.assertEqual(r.headers["Content-Type"], "video/mp4")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url.rsplit("/", 2)[0] + "/" + "0" * 32 + "/x.mp4", timeout=10)
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(ot.NapakaTorrenta):
            self.t.tok(0, 2)                             # program se ne predvaja nikoli

    def test_vsak_motor_dobi_svoja_vrata(self):
        # Zasedena privzeta vrata (drug motor ze tece): dobimo druga prosta, ne napake ob zagonu.
        zasedena = socket.socket(socket.AF_INET6 if socket.has_ipv6 else socket.AF_INET, socket.SOCK_STREAM)
        zasedena.bind(("::" if socket.has_ipv6 else "0.0.0.0", 0))
        zasedena.listen(1)
        vrata = zasedena.getsockname()[1]
        try:
            with mock.patch.object(ot, "VRATA_TORRENTA", vrata):
                druga = ot._vrata_za_torrent()
                self.assertNotIn(druga, (0, vrata))
        finally:
            zasedena.close()
        with mock.patch.object(ot, "VRATA_TORRENTA", vrata):
            self.assertEqual(ot._vrata_za_torrent(), vrata)      # prosta privzeta vrata ostanejo privzeta

    def test_motor_za_naprave_ima_svoj_dht(self):
        # Windows (v zivo, 3. 10. 2026): vsi rqbit istega uporabnika si delijo shranjeno stanje DHT - drugi motor se je
        # ugasnil ob zagonu. Motor, ki pretaka napravam, zato tece s stikalom --disable-dht-persistence.
        import inspect
        from core import link_datoteke
        self.assertFalse(ot.Torrenti(self.mapa, self.mapa).svoj_dht)
        self.assertTrue(ot.Torrenti(self.mapa, self.mapa, svoj_dht=True).svoj_dht)
        self.assertIn('["--disable-dht-persistence"] if self.svoj_dht else []', inspect.getsource(ot.Torrenti.zazeni))
        self.assertIn("svoj_dht=True", inspect.getsource(link_datoteke.torrenti_za_naprave))
        # ... in poslusa na sosednjih vratih (na Windows rqbit vrata deli, preverjanje zasedenosti tam ne zadosca).
        self.assertIn("_vrata_za_torrent(VRATA_TORRENTA + 1 if self.svoj_dht else VRATA_TORRENTA)", inspect.getsource(ot.Torrenti.zazeni))
        with mock.patch.object(ot, "_vrata_zasedena", lambda v: False):
            self.assertEqual((ot._vrata_za_torrent(), ot._vrata_za_torrent(ot.VRATA_TORRENTA + 1)), (ot.VRATA_TORRENTA, ot.VRATA_TORRENTA + 1))

    def test_vrata_so_prosta_samo_ce_so_prosta_na_ipv4_in_ipv6_tcp_in_udp(self):
        # Windows (v zivo, 3. 10. 2026): prvi motor poslusa na 0.0.0.0, preverjanje samo [::] je vrata razglasilo za
        # prosta in drugi motor se je ugasnil ob zagonu. Vsaka druzina in protokol posebej.
        for druzina, naslov, vrsta in ((socket.AF_INET, "0.0.0.0", socket.SOCK_STREAM), (socket.AF_INET, "0.0.0.0", socket.SOCK_DGRAM)):
            s = socket.socket(druzina, vrsta)
            s.bind((naslov, 0))
            if vrsta == socket.SOCK_STREAM:
                s.listen(1)
            vrata = s.getsockname()[1]
            try:
                self.assertTrue(ot._vrata_zasedena(vrata), (druzina, vrsta))
                with mock.patch.object(ot, "VRATA_TORRENTA", vrata):
                    self.assertNotIn(ot._vrata_za_torrent(), (0, vrata))
            finally:
                s.close()
            self.assertFalse(ot._vrata_zasedena(vrata))
        if socket.has_ipv6:
            try:
                s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                s.bind(("::", 0))
            except OSError:
                return                                       # brez IPv6 na tem racunalniku
            s.listen(1)
            try:
                self.assertTrue(ot._vrata_zasedena(s.getsockname()[1]))
            finally:
                s.close()

    def test_dodajanje_brez_ponovnega_branja_in_z_najdenimi_viri(self):
        self.t.preberi(MAGNET)
        self.t.dodaj(MAGNET, [1])
        branja = [z for z in LazniRqbit.zahteve if z[0] == "POST" and "list_only=true" in z[1]]
        self.assertEqual(len(branja), 1)                 # dodajanje metapodatkov ne isce se enkrat
        dodaj = [z for z in LazniRqbit.zahteve if z[0] == "POST" and "only_files=" in z[1]][-1][1]
        self.assertTrue(dodaj.endswith("&initial_peers=203.0.113.7:6881"), dodaj)   # samo veljavni naslovi IPv4
        # Po izteku roka se torrent, ki ga motor (se) nima, prebere znova.
        self.s.dodan = False
        with mock.patch.object(ot, "PREBRANO_VELJA_S", -1.0):
            self.t.dodaj(MAGNET, [1])
        self.assertEqual(len([z for z in LazniRqbit.zahteve if z[0] == "POST" and "list_only=true" in z[1]]), 2)

    def test_znan_torrent_se_ne_isce_znova(self):
        self.t.dodaj(MAGNET, [1])
        LazniRqbit.zahteve = []
        with mock.patch.object(ot, "PREBRANO_VELJA_S", -1.0):      # tudi brez spomina: motor torrent ze ima
            opis = self.t.preberi(MAGNET)
            self.assertEqual(self.t.dodaj(MAGNET, [0]), 0)
        self.assertEqual([d["ime"] for d in opis["datoteke"]][:2], ["Big Buck Bunny.en.srt", "Big Buck Bunny.mp4"])
        self.assertEqual([z for z in LazniRqbit.zahteve if z[0] == "POST" and "list_only=true" in z[1]], [])

    def test_tok_pocaka_da_je_torrent_pripravljen(self):
        self.t.dodaj(MAGNET, [1])
        url = self.t.tok(0, 1)
        ot.PRIPRAVA_TOKA_RAZMIK_S = 0.01
        self.s.pripravlja = 3            # rqbit trikrat odgovori 500 "initializing", nato tok
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-99"}), timeout=10) as r:
            self.assertEqual((r.status, r.read()), (206, LazniRqbit.PODATKI[:100]))
        self.assertEqual(self.s.pripravlja, 0)
        # Druga napaka (ne priprava) gre naprej takoj in z izvirnim opisom - ne cakamo 45 s.
        self.s.pokvarjen = True
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=10)
        self.assertEqual((e.exception.code, e.exception.read()), (500, b'{"human_readable":"disk error"}'))
        # Priprava, ki se ne konca, po roku vrne napako (ne visi v nedogled).
        self.s.pokvarjen = False
        self.s.pripravlja = 10 ** 6
        ot.PRIPRAVA_TOKA_S = 0.2
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(url, timeout=10)
            self.assertEqual(e.exception.code, 500)
        finally:
            ot.PRIPRAVA_TOKA_S = 45.0
            ot.PRIPRAVA_TOKA_RAZMIK_S = 0.3

    def test_podnapisi_iz_istega_torrenta(self):
        self.s.dodan = True
        self.assertEqual(self.t.podnapisi_za(0, 1), [(0, "Big Buck Bunny.en.srt")])
        url = self.t.tok(0, 0)                            # podnapise sme predvajalnik prebrati
        self.assertIn("/t/", url)

    def test_morda_program_samo_s_potrditvijo(self):
        # Prepoznava programov se lahko zmoti: po izrecni potrditvi uporabnika datoteko prenesemo,
        # predvajamo pa je nikoli.
        self.assertEqual(self.t.dodaj(MAGNET, [1, 2], potrjene_nevarne=[2]), 0)
        dodaj = [z for z in LazniRqbit.zahteve if z[0] == "POST" and "only_files=" in z[1]]
        self.assertIn("only_files=0,1,2&", dodaj[-1][1] + "&")   # 0 = podnapisi k videu
        with self.assertRaises(ot.NapakaTorrenta):
            self.t.tok(0, 2)

    def test_lastnih_datotek_ne_brisemo(self):
        self.assertTrue(self.t._v_prenosih(os.path.join(self.mapa, "Film")))
        self.assertTrue(self.t._v_prenosih("Film"))                  # relativno na mapo prenosov
        for tuja in ("/home/uporabnik/Glasba", os.path.join(self.mapa, "..", "x"), ""):
            self.assertFalse(self.t._v_prenosih(tuja), tuja)
        with mock.patch.object(self.t, "_json", return_value={"output_folder": "/home/uporabnik/Moje"}):
            self.assertFalse(self.t.odstrani(0, z_datotekami=True))
        self.assertFalse(any("/delete" in z[1] for z in LazniRqbit.zahteve))

    def test_deli_naprej_se_zapomni(self):
        self.t.deli_naprej(HASH.upper(), True)
        t2 = ot.Torrenti(mapa_prenosov_=self.mapa, mapa_stanja_=os.path.join(self.mapa, "st"),
                         nastavitve=os.path.join(self.mapa, "n.json"))
        self.assertIn(HASH, t2._deli_naprej)
        t2.deli_naprej(HASH, False)
        self.assertNotIn(HASH, ot.Torrenti(nastavitve=os.path.join(self.mapa, "n.json"))._deli_naprej)


if __name__ == "__main__":
    unittest.main()
