"""magnet.stream: racunalnik prenasa torrent, televizor dobi samo tok (core/link_datoteke.py; ukaz: windows/safeer_windows/control_backend.py)."""
import http.client
import http.server
import os
import shutil
import ssl
import sys
import tempfile
import threading
import time
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

from core import link_datoteke, os_torrent  # noqa: E402

VSEBINA = bytes(range(256)) * 64  # 16384 B
MAGNET = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=Film"


class _Lokalni(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def do_HEAD(self):
        self._p(True)

    def do_GET(self):
        self._p(False)

    def _p(self, glava):
        a, b = 0, len(VSEBINA) - 1
        r = self.headers.get("Range")
        if r:
            x, y = r[6:].split("-")
            a = int(x)
            b = int(y) if y else b
        self.send_response(206 if r else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(b - a + 1))
        if r:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(VSEBINA)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if not glava:
            self.wfile.write(VSEBINA[a:b + 1])


class _Torrenti:
    """Namesto rqbit: datoteke magneta in lokalni tok."""

    def __init__(self, vrata):
        self.vrata = vrata
        self.dodane = []

    def zazeni(self):
        pass

    def preberi(self, uri):
        return {"hash": "a" * 40, "ime": "Film", "uri": uri, "datoteke": [
            {"i": 0, "ime": "Film/vzorec.mp4", "velikost": 100, "vrsta": "video", "predvajljivo": True},
            {"i": 1, "ime": "Film/film.mkv", "velikost": 9000, "vrsta": "video", "predvajljivo": True},
            {"i": 2, "ime": "Film/namesti.exe", "velikost": 99999, "vrsta": "nevarno", "predvajljivo": False}]}

    def dodaj(self, uri, izbrane):
        self.dodane.append(list(izbrane))
        return 7

    def tok(self, tid, i):
        return "http://127.0.0.1:%d/t/skrito/film.mkv" % self.vrata

    def tece(self):
        return True

    def seznam(self):
        return [{"id": 7, "ime": "Film", "skupaj": 9100, "preneseno": 4550, "koncano": False, "hitrost_mibs": 1.5,
                 "datoteke": [{"i": 1, "ime": "Film/film.mkv", "vrsta": "video", "vkljucena": True},
                              {"i": 0, "ime": "Film/vzorec.mp4", "vrsta": "video", "vkljucena": False}]}]

    def magnet(self, tid):
        return MAGNET

    def odstrani(self, tid, z_datotekami=False):
        self.odstranjen = (tid, z_datotekami)
        return tid == 7


class TokTorrenta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapa = tempfile.mkdtemp(prefix="safeer-tok-")
        cls.lokalni = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Lokalni)
        threading.Thread(target=cls.lokalni.serve_forever, daemon=True).start()
        cls.d = link_datoteke.Datoteke([], tls_mapa=os.path.join(cls.mapa, "tls"))

    @classmethod
    def tearDownClass(cls):
        cls.d.ustavi()
        cls.lokalni.shutdown()
        shutil.rmtree(cls.mapa, ignore_errors=True)

    def _zahteva(self, pot, glave=None, metoda="GET"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        p = http.client.HTTPSConnection("127.0.0.1", self.d.streznik.vrata, context=ctx, timeout=5)
        p.request(metoda, pot, headers=glave or {})
        o = p.getresponse()
        telo = o.read()
        p.close()
        return o.status, dict((k.lower(), v) for k, v in o.getheaders()), telo

    def test_tok_prek_racunalnika(self):
        t = _Torrenti(self.lokalni.server_address[1])
        o = self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=lambda m, v: "")
        self.assertEqual(t.dodane, [[1]])  # najvecji video, ne vzorec in nikoli program
        self.assertEqual((o["file"], o["name"]), (1, "film.mkv"))
        self.assertTrue(o["path"].startswith("/m/") and o["path"].endswith("/film.mkv"))
        self.assertTrue(o["server"]["base_url"].startswith("https://"))
        z = {"X-Safeer-Token": o["server"]["token"]}
        st, gl, telo = self._zahteva(o["path"], z)
        self.assertEqual((st, telo), (200, VSEBINA))
        st, gl, telo = self._zahteva(o["path"], {**z, "Range": "bytes=100-199"})
        self.assertEqual((st, telo, gl["content-range"]), (206, VSEBINA[100:200], "bytes 100-199/16384"))
        st, gl, telo = self._zahteva(o["path"], z, "HEAD")
        self.assertEqual((st, gl["content-length"], telo), (200, "16384", b""))
        # brez zetona, z napacnim ali z izmisljeno skrivnostjo nic
        self.assertEqual(self._zahteva(o["path"])[0], 401)
        self.assertEqual(self._zahteva(o["path"], {"X-Safeer-Token": "x"})[0], 401)
        self.assertEqual(self._zahteva("/m/izmisljeno/film.mkv", z)[0], 404)
        # izbrana datoteka; program ne
        self.assertEqual(self.d.tok_torrenta(MAGNET, "tv-1", datoteka=0, torrenti=t, zmogljivost=lambda m, v: "")["file"], 0)
        with self.assertRaises(os_torrent.NapakaTorrenta):
            self.d.tok_torrenta(MAGNET, "tv-1", datoteka=2, torrenti=t, zmogljivost=lambda m, v: "")
        with self.assertRaises(os_torrent.NapakaTorrenta):
            self.d.tok_torrenta("https://primer.si/x", "tv-1", torrenti=t)

    def test_prenosi_in_odstranitev(self):
        t = _Torrenti(self.lokalni.server_address[1])
        o = self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=lambda m, v: "")
        self.assertEqual(self.d.prenosi_za_naprave(t)["items"], [{"id": 7, "name": "Film", "size": 9100, "done": 4550,
                         "finished": False, "speed_mibs": 1.5, "magnet": MAGNET, "file": 1}])
        self.assertTrue(self.d.odstrani_prenos(7, t))
        self.assertEqual(t.odstranjen, (7, True))  # z datotekami: na racunalniku ne ostane nic
        z = {"X-Safeer-Token": o["server"]["token"]}
        self.assertEqual(self._zahteva(o["path"], z)[0], 404)  # odstranjen tok ni vec dosegljiv
        self.assertFalse(self.d.odstrani_prenos(8, t))

    def test_knjiznica_kroga_naslov_plakat_in_zasebno(self):
        t = _Torrenti(self.lokalni.server_address[1])
        raba = os.path.join(self.mapa, "knjiznica", "raba.json")
        prosto = lambda m, v: ""  # noqa: E731
        # Starejsa naprava ne pove nicesar: vnos kot do zdaj (brez naslova).
        self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=prosto, pot_rabe=raba)
        self.assertNotIn("title", self.d.prenosi_za_naprave(t, raba, "tel-2")["items"][0])
        # Naprava pove naslov in plakat: dobijo ju vse naprave v krogu.
        opis = link_datoteke.opis_iz_parametrov({"title": " Sintel ", "poster": "https://slike.primer/s.jpg", "kind": "movie",
                                                 "ref": "stremio|movie|tt1|https://d.primer", "uri": MAGNET})
        self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=prosto, pot_rabe=raba, opis_naprave=opis)
        vnos = self.d.prenosi_za_naprave(t, raba, "tel-2")["items"][0]
        self.assertEqual((vnos["title"], vnos["poster"], vnos["kind"], vnos["ref"]),
                         ("Sintel", "https://slike.primer/s.jpg", "movie", "stremio|movie|tt1|https://d.primer"))
        self.assertNotIn("private", vnos)
        # Plakat s tujega protokola in neznana vrsta odpadeta; brez naslova ni opisa.
        o = link_datoteke.opis_iz_parametrov({"title": "X", "poster": "http://192.168.0.2/p.jpg", "kind": "karkoli"})
        self.assertEqual((o["poster"], o["kind"]), ("", ""))
        self.assertIsNone(link_datoteke.opis_iz_parametrov({"poster": "https://x/p.jpg"}))
        # Zaseben prenos: vidi ga samo naprava, ki ga je prosila - brez naslova in plakata, tudi ce sta bila prej znana.
        zasebno = link_datoteke.opis_iz_parametrov({"private": True, "title": "ne sme na racunalnik"})
        self.assertEqual(zasebno, {"private": True})
        self.d.tok_torrenta(MAGNET, "tablica-3", torrenti=t, zmogljivost=prosto, pot_rabe=raba, opis_naprave=zasebno)
        self.assertEqual(self.d.prenosi_za_naprave(t, raba, "tel-2")["items"], [])
        self.assertEqual(self.d.prenosi_za_naprave(t, raba)["items"], [])
        moj = self.d.prenosi_za_naprave(t, raba, "tablica-3")["items"][0]
        self.assertTrue(moj["private"])
        self.assertNotIn("title", moj)
        # Kar je enkrat zasebno, ostane zasebno, tudi ce ga druga naprava prosi z javnim opisom.
        self.d.tok_torrenta(MAGNET, "tel-2", torrenti=t, zmogljivost=prosto, pot_rabe=raba, opis_naprave=opis)
        self.assertTrue(self.d.prenosi_za_naprave(t, raba, "tel-2")["items"][0]["private"])
        self.assertEqual(self.d.prenosi_za_naprave(t, raba, "tv-9")["items"], [])
        # Ko prenosa ni vec, tudi opis ne ostane.
        t.seznam = lambda: []
        self.d.prenosi_za_naprave(t, raba, "tel-2")
        self.assertEqual(link_datoteke._beri_opise(link_datoteke._pot_opisov(raba)), {})

    def test_kar_je_prenesel_safeer_os_vidijo_in_odstranijo_tudi_naprave(self):
        """Ena naprava hrani, vse predvajajo: film, ki ga je Safeer OS zaradi gledanja prenesel sam in je v celoti na
        disku, je v `magnet.list` z naslovom in plakatom; `magnet.remove` z njegovo (negativno) oznako ga odstrani."""
        h1, h2 = "1" * 40, "2" * 40
        t = _Torrenti(self.lokalni.server_address[1])
        t.seznam = lambda: []
        odstranjeni = []
        d = link_datoteke.Datoteke([], tls_mapa=os.path.join(self.mapa, "tls"))
        self.addCleanup(d.ustavi)
        self.assertEqual(d.prenosi_za_naprave(t)["items"], [])                 # brez Safeer OS: po starem
        self.assertFalse(d.odstrani_prenos(-5, t))
        d.gledanje = lambda: [
            {"hash": h1, "title": "Film na racunalniku", "poster": "https://slike.primer.si/p.jpg", "kind": "movie", "ref": "r1",
             "magnet": "magnet:?xt=urn:btih:" + h1, "file": 2, "finished": True, "size": 700, "name": "Film.mkv"},
            {"hash": h2, "title": "Se se prenasa", "magnet": "magnet:?xt=urn:btih:" + h2, "file": 0, "finished": False, "size": 0, "name": ""}]
        d.odstrani_gledanje = lambda h: odstranjeni.append(h) or True
        vnosi = d.prenosi_za_naprave(t, id_naprave="tv-1")["items"]
        self.assertEqual(len(vnosi), 1)                                        # nedokoncanega Control ne ponuja
        v = vnosi[0]
        self.assertEqual({k: v[k] for k in ("title", "poster", "kind", "ref", "file", "finished", "size", "done", "name")},
                         {"title": "Film na racunalniku", "poster": "https://slike.primer.si/p.jpg", "kind": "movie", "ref": "r1",
                          "file": 2, "finished": True, "size": 700, "done": 700, "name": "Film.mkv"})
        self.assertLess(v["id"], 0)                                            # ne more trciti z oznako motorja za naprave
        self.assertEqual(v["id"], link_datoteke.oznaka_gledanja(h1))
        self.assertFalse(d.odstrani_prenos(link_datoteke.oznaka_gledanja(h2) - 1, t))   # neznana oznaka: nic
        self.assertEqual(odstranjeni, [])
        self.assertTrue(d.odstrani_prenos(v["id"], t))
        self.assertEqual(odstranjeni, [h1])
        self.assertFalse(hasattr(t, "odstranjen"))                            # motorja za naprave se ne dotakne

    def test_film_safeer_os_ki_ga_gleda_naprava_ne_potece(self):
        h = "3" * 40
        raba_naprave = os.path.join(self.mapa, "krog", "raba-naprave.json")
        raba_gledanja = os.path.join(self.mapa, "krog", "raba-gledanje.json")
        link_datoteke.zabelezi_rabo(h, raba_gledanja, zdaj=1000.0)
        link_datoteke._osvezi_rabo_gledanja(h, raba_naprave)
        self.assertGreater(link_datoteke._beri_rabo(raba_gledanja)[h], 1000.0)
        link_datoteke._osvezi_rabo_gledanja("4" * 40, raba_naprave)             # ni prenos Safeer OS: nic ne zapise
        self.assertNotIn("4" * 40, link_datoteke._beri_rabo(raba_gledanja))

    def test_ne_preobremeni_racunalnika(self):
        t = _Torrenti(self.lokalni.server_address[1])
        for razlog in ("preobremenjen", "malo_pomnilnika", "ni_prostora"):
            with self.assertRaises(os_torrent.NapakaTorrenta) as e:
                self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=lambda m, v, r=razlog: r)
            self.assertEqual(str(e.exception), razlog)
        self.assertEqual(t.dodane, [])  # nic ni zacelo prenasati
        vprasano = []
        self.d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=lambda m, v: vprasano.append(v) or "")
        self.assertEqual(vprasano, [9000])  # disk se preveri za velikost izbrane datoteke
        # Pretakanje torrenta ne gleda obremenitve procesorja (racunalnik lahko medtem prevaja), disk pa vedno.
        self.assertEqual(link_datoteke.zmogljivost_za_tok(self.mapa, 10 ** 18), "ni_prostora")
        self.assertEqual(link_datoteke.prosta_zmogljivost(self.mapa, 10 ** 18, procesor=False), "ni_prostora")

    def test_samo_lokalni_tokovi(self):
        with self.assertRaises(ValueError):
            self.d.streznik.dodaj_tok("http://10.0.0.5:8000/x.mp4")
        with self.assertRaises(ValueError):
            self.d.streznik.dodaj_tok("file:///etc/passwd")

    # Ukaz magnet.stream in stanje za Windows Control: windows/tests/test_magnet_windows.py (LinkTokTorrenta).


if __name__ == "__main__":
    unittest.main()


def _benc(v):
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, bytes):
        return b"%d:%s" % (len(v), v)
    if isinstance(v, str):
        return _benc(v.encode())
    if isinstance(v, list):
        return b"l" + b"".join(_benc(x) for x in v) + b"e"
    return b"d" + b"".join(_benc(k) + _benc(v[k]) for k in sorted(v)) + b"e"


class Nadzornik(unittest.TestCase):
    """Ista vsebina se ne prenasa dvakrat: kar je na racunalniku ze v celoti, gre z diska."""

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-nadzornik-")
        self.stanje = os.path.join(self.mapa, "stanje")
        self.izhod = os.path.join(self.mapa, "Prejemi", "Film")
        os.makedirs(self.stanje)
        os.makedirs(self.izhod)
        self.hash = "b" * 40
        # dve datoteki: vzorec (10 B) in film (5000 B); kos 1024 B -> 5 kosov
        with open(os.path.join(self.izhod, "vzorec.mp4"), "wb") as d:
            d.write(b"v" * 10)
        with open(os.path.join(self.izhod, "film.mkv"), "wb") as d:
            d.write(VSEBINA[:5000])
        info = {"name": "Film", "piece length": 1024, "pieces": b"x" * 100,
                "files": [{"length": 10, "path": ["vzorec.mp4"]}, {"length": 5000, "path": ["film.mkv"]}]}
        with open(os.path.join(self.stanje, self.hash + ".torrent"), "wb") as d:
            d.write(_benc({"info": info}))
        with open(os.path.join(self.stanje, "session.json"), "w") as d:
            d.write('{"torrents": {"0": {"info_hash": "%s", "output_folder": "%s"}}}' % (self.hash, self.izhod))
        self.d = link_datoteke.Datoteke([], tls_mapa=os.path.join(self.mapa, "tls"))

    def tearDown(self):
        self.d.ustavi()
        shutil.rmtree(self.mapa, ignore_errors=True)

    def _bitv(self, b):
        with open(os.path.join(self.stanje, self.hash + ".bitv"), "wb") as d:
            d.write(bytes(b))

    def test_samo_v_celoti_preneseno(self):
        self._bitv([0b11110000])     # zadnji kos manjka: film ni koncan, ceprav ima pravo velikost
        self.assertEqual(link_datoteke.ze_preneseno(self.hash, None, [self.stanje]), ("", -1))
        self._bitv([0b11111000])
        pot, i = link_datoteke.ze_preneseno(self.hash, None, [self.stanje])
        self.assertEqual((os.path.basename(pot), i), ("film.mkv", 1))   # najvecji video
        self.assertEqual(link_datoteke.ze_preneseno("c" * 40, None, [self.stanje]), ("", -1))
        self.assertEqual(link_datoteke.ze_preneseno("../x", None, [self.stanje]), ("", -1))

    def test_tok_z_diska_brez_torrenta(self):
        self._bitv([0b11111000])

        class Ne:
            def __getattr__(self, ime):
                raise AssertionError("torrent se ne sme zagnati: " + ime)

        o = self.d.tok_torrenta("magnet:?xt=urn:btih:" + self.hash, "tv-1", torrenti=Ne(), mape_stanja=[self.stanje])
        self.assertTrue(o["local"])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        p = http.client.HTTPSConnection("127.0.0.1", self.d.streznik.vrata, context=ctx, timeout=5)
        p.request("GET", o["path"], headers={"X-Safeer-Token": o["server"]["token"], "Range": "bytes=0-99"})
        r = p.getresponse()
        self.assertEqual((r.status, r.read()), (206, VSEBINA[:100]))
        p.close()


class _Prenosi:
    """Nadomestek rqbit za ciscenje: seznam torrentov z hashi, odstranjevanje se belezi."""

    def __init__(self, hashi, lastni=()):
        self.vsi = [{"id": i + 1, "hash": h, "ime": "Film %d" % i, "lastna": h in lastni, "datoteke": []} for i, h in enumerate(hashi)]
        self.odstranjeni = []
        self.tece_ = True

    def tece(self):
        return self.tece_

    def seznam(self):
        return list(self.vsi)

    def magnet(self, tid):
        return "magnet:?xt=urn:btih:" + next(t["hash"] for t in self.vsi if t["id"] == tid)

    def odstrani(self, tid, z_datotekami=False):
        self.odstranjeni.append((tid, z_datotekami))
        self.vsi = [t for t in self.vsi if t["id"] != tid]
        return True


class SamodejnoCiscenje(unittest.TestCase):
    """Torrent za naprave, ki ga 48 h nihce ni predvajal, racunalnik odstrani sam (lastnik, 3. 10. 2026)."""

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-raba-")
        self.pot = os.path.join(self.mapa, "raba-naprave.json")
        self.a, self.b, self.c = "a" * 40, "b" * 40, "c" * 40
        self.ura = 1_000_000.0

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)

    def test_po_48_urah_brez_predvajanja(self):
        t = _Prenosi([self.a, self.b, self.c])
        link_datoteke.zabelezi_rabo(self.a, self.pot, self.ura - 49 * 3600)
        link_datoteke.zabelezi_rabo(self.b, self.pot, self.ura - 47 * 3600)
        # c je iz casa pred to razlicico (brez zapisa): rok mu tece od prvega pregleda, ne izgine takoj.
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura), [self.a])
        self.assertEqual(t.odstranjeni, [(1, True)])       # z datotekami
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura + 2 * 3600), [self.b])
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura + 47 * 3600), [])
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura + 49 * 3600), [self.c])
        self.assertEqual(t.vsi, [])

    def test_ponovno_predvajanje_podaljsa_rok(self):
        t = _Prenosi([self.a])
        link_datoteke.zabelezi_rabo(self.a, self.pot, self.ura - 47 * 3600)
        link_datoteke.zabelezi_rabo(self.a, self.pot, self.ura)            # naslednji vecer nadaljuje film
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura + 47 * 3600), [])
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura + 49 * 3600), [self.a])

    def test_uporabnikovih_datotek_in_ugasnjenega_rqbita_se_ne_dotika(self):
        t = _Prenosi([self.a, self.b], lastni=[self.a])
        link_datoteke.zabelezi_rabo(self.a, self.pot, self.ura - 100 * 3600)
        link_datoteke.zabelezi_rabo(self.b, self.pot, self.ura - 100 * 3600)
        t.tece_ = False
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura), [])
        t.tece_ = True
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura), [self.b])   # a deli uporabnik sam

    def test_ob_pomanjkanju_prostora_najstarejsi_prvi(self):
        t = _Prenosi([self.a, self.b, self.c])
        link_datoteke.zabelezi_rabo(self.a, self.pot, self.ura - 20 * 3600)
        link_datoteke.zabelezi_rabo(self.b, self.pot, self.ura - 30 * 3600)
        link_datoteke.zabelezi_rabo(self.c, self.pot, self.ura - 1 * 3600)      # ta se predvaja: ostane
        prosto = {"n": 0}

        def dovolj():
            return len(t.odstranjeni) >= prosto["n"]
        prosto["n"] = 1
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura, dovolj=dovolj), [self.b])
        prosto["n"] = 5      # prostora ni dovolj niti brez vseh: film v teku in zahtevani ostaneta
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.pot, self.ura, dovolj=dovolj, obdrzi=self.c), [self.a])
        self.assertEqual([x["hash"] for x in t.vsi], [self.c])

    def test_tok_naredi_prostor_za_nov_film(self):
        d = link_datoteke.Datoteke([], tls_mapa=os.path.join(self.mapa, "tls"))
        try:
            t = _Torrenti(1)
            t.vsi = [{"id": 3, "hash": self.b, "lastna": False}]
            t.odstranjeni = []
            t.seznam = lambda: list(t.vsi)

            def odstrani(tid, z_datotekami=False):
                t.odstranjeni.append(tid)
                t.vsi = []
                return True
            t.odstrani = odstrani
            link_datoteke.zabelezi_rabo(self.b, self.pot, time.time() - 10 * 3600)
            o = d.tok_torrenta(MAGNET, "tv-1", torrenti=t, pot_rabe=self.pot,
                               zmogljivost=lambda m, v: "" if t.odstranjeni else "ni_prostora")
            self.assertEqual((t.odstranjeni, o["file"]), ([3], 1))
            # Brez podane poti (preizkusi z nadomestkom) se nic ne belezi in nic ne odstrani.
            t.vsi = [{"id": 4, "hash": self.c, "lastna": False}]
            with self.assertRaises(os_torrent.NapakaTorrenta):
                d.tok_torrenta(MAGNET, "tv-1", torrenti=t, zmogljivost=lambda m, v: "ni_prostora")
            self.assertEqual(t.odstranjeni, [3])
        finally:
            d.ustavi()
