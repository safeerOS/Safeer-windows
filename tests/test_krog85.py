"""Krog 85 na racunalniku (skupno za Linux in Windows): »Obdrži« za prenose na polici »Na tvojih napravah«, podnapisi iz
torrenta pri filmu, ki ga pretaka druga naprava, in Moji viri, enaki na vseh napravah v Safeer Linku.
Brez omrezja, brez Linka in brez rqbit."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import knjiznica_kroga as kk, link_datoteke, media_servers, os_media, os_torrent_tok as tt, viri_sink  # noqa: E402

A, B, C = "a" * 40, "b" * 40, "c" * 40
URA = 1_000_000.0


class _Prenosi:
    """Nadomestek motorja torrentov: seznam z hashi, odstranjevanje se belezi."""

    def __init__(self, hashi):
        self.vsi = [{"id": i + 1, "hash": h, "ime": "Film %d" % i, "lastna": False, "skupaj": 10, "preneseno": 10,
                     "koncano": True, "datoteke": [{"i": 0, "ime": "f.mkv", "vrsta": "video", "vkljucena": True}]}
                    for i, h in enumerate(hashi)]
        self.odstranjeni = []

    def tece(self):
        return True

    def seznam(self):
        return list(self.vsi)

    def magnet(self, tid):
        return "magnet:?xt=urn:btih:" + next(t["hash"] for t in self.vsi if t["id"] == tid)

    def odstrani(self, tid, z_datotekami=False):
        self.odstranjeni.append(tid)
        self.vsi = [t for t in self.vsi if t["id"] != tid]
        return True


class Obdrzi(unittest.TestCase):
    """Prenos, ki ga uporabnik oznaci z »Obdrži«, ne potece po 48 urah in ne gre niti ob pomanjkanju prostora."""

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-obdrzi-")
        self.raba = os.path.join(self.mapa, "raba-naprave.json")
        self.opisi = link_datoteke._pot_opisov(self.raba)
        self.d = link_datoteke.Datoteke([], tls_mapa=os.path.join(self.mapa, "tls"))
        self.addCleanup(self.d.ustavi)
        self.addCleanup(shutil.rmtree, self.mapa, True)

    def test_obdrzan_prenos_za_naprave_ne_potece(self):
        t = _Prenosi([A, B])
        for h in (A, B):
            link_datoteke.zabelezi_rabo(h, self.raba, URA - 100 * 3600)
        self.assertTrue(link_datoteke.nastavi_obdrzi(self.opisi, A, True))
        self.assertEqual(link_datoteke.obdrzani(self.opisi), {A})
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.raba, URA), [B])
        # Tudi ob pomanjkanju prostora ostane - odstrani ga samo uporabnik.
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.raba, URA, dovolj=lambda: False), [])
        self.assertEqual([x["hash"] for x in t.vsi], [A])
        self.assertIn(A, link_datoteke._beri_rabo(self.raba))                       # zapis rabe ostane
        # Ne vec obdrzan: spet velja rok.
        self.assertTrue(link_datoteke.nastavi_obdrzi(self.opisi, A, False))
        self.assertEqual(link_datoteke.pocisti_neuporabljene(t, self.raba, URA), [A])
        self.assertFalse(link_datoteke.nastavi_obdrzi(self.opisi, "ni hash", True))

    def test_magnet_list_pove_in_magnet_keep_nastavi(self):
        t = _Prenosi([A])
        link_datoteke.zabelezi_opis(A, {"title": "Film", "private": False}, "tel-1", self.raba)
        self.assertIs(self.d.prenosi_za_naprave(t, self.raba, "tel-1")["items"][0]["keep"], False)
        self.assertTrue(self.d.obdrzi_prenos(1, True, t, self.raba, "tv-2"))        # javen prenos: katera koli naprava
        v = self.d.prenosi_za_naprave(t, self.raba, "tel-1")["items"][0]
        self.assertEqual((v["keep"], v["title"]), (True, "Film"))                    # opis ostane
        # Nov opis (film prosi se druga naprava) oznake ne izbrise.
        link_datoteke.zabelezi_opis(A, {"title": "Film", "private": False}, "tv-2", self.raba)
        self.assertTrue(self.d.prenosi_za_naprave(t, self.raba, "tv-2")["items"][0]["keep"])
        self.assertTrue(self.d.obdrzi_prenos(1, False, t, self.raba, "tv-2"))
        self.assertFalse(self.d.prenosi_za_naprave(t, self.raba, "tv-2")["items"][0]["keep"])
        self.assertFalse(self.d.obdrzi_prenos(9, True, t, self.raba, "tv-2"))       # neznan prenos

    def test_zasebnega_obdrzi_samo_naprava_ki_ga_je_prosila(self):
        t = _Prenosi([A])
        link_datoteke.zabelezi_opis(A, {"private": True}, "tel-1", self.raba)
        self.assertFalse(self.d.obdrzi_prenos(1, True, t, self.raba, "tv-2"))
        self.assertFalse(self.d.obdrzi_prenos(1, True, t, self.raba, ""))
        self.assertTrue(self.d.obdrzi_prenos(1, True, t, self.raba, "tel-1"))
        v = self.d.prenosi_za_naprave(t, self.raba, "tel-1")["items"][0]
        self.assertEqual((v["keep"], v.get("private")), (True, True))
        # Zasebnost ostane, oznaka tudi, ko ga prosi se kdo.
        link_datoteke.zabelezi_opis(A, {"title": "X", "private": False}, "tv-2", self.raba)
        o = link_datoteke._beri_opise(self.opisi)[A]
        self.assertEqual((o.get("private"), o.get("keep"), "title" in o), (True, True, False))

    def test_prenos_safeer_os_obdrzi_safeer_os(self):
        klici = []
        self.d.gledanje = lambda: [{"hash": B, "title": "Na racunalniku", "magnet": "magnet:?xt=urn:btih:" + B, "file": 0,
                                    "finished": True, "size": 5, "name": "f.mkv", "keep": True}]
        t = _Prenosi([])
        # Brez funkcije za »Obdrži« (starejsi Safeer OS) polja ni - naprava moznosti ne ponudi.
        self.assertNotIn("keep", self.d.prenosi_za_naprave(t, self.raba, "tel-1")["items"][0])
        self.assertFalse(self.d.obdrzi_prenos(link_datoteke.oznaka_gledanja(B), True, t, self.raba))
        self.d.obdrzi_gledanje = lambda h, drzi: klici.append((h, drzi)) or True
        self.assertIs(self.d.prenosi_za_naprave(t, self.raba, "tel-1")["items"][0]["keep"], True)
        self.assertTrue(self.d.obdrzi_prenos(link_datoteke.oznaka_gledanja(B), False, t, self.raba))
        self.assertEqual(klici, [(B, False)])
        self.assertFalse(self.d.obdrzi_prenos(link_datoteke.oznaka_gledanja(C), True, t, self.raba))

    def test_prenos_zaradi_gledanja_obdrzan_ne_potece(self):
        raba = os.path.join(self.mapa, "raba-gledanje.json")
        opisi = kk.pot_opisov(raba)
        t = _Prenosi([A, B])
        for h in (A, B):
            link_datoteke.zabelezi_rabo(h, raba, URA - 100 * 3600)
            kk.zabelezi(h, {"title": "Film " + h[0], "private": False}, 0, opisi)
        self.assertTrue(kk.nastavi_obdrzi(A, True, opisi))
        self.assertEqual(tt.pocisti(t, raba, URA), [B])
        self.assertEqual(tt.pocisti(t, raba, URA, dovolj=lambda: False), [])
        with mock.patch.object(link_datoteke, "ze_preneseno", lambda h, i, m=None: ("", -1)):
            self.assertEqual([(v["hash"], v["keep"]) for v in kk.lokalni(raba, opisi)], [(A, True)])
        # Nov opis istega filma (predvajanje naslednji vecer) oznake ne izbrise.
        kk.zabelezi(A, {"title": "Film a", "private": False}, 0, opisi)
        self.assertTrue(link_datoteke._beri_opise(opisi)[A]["keep"])
        self.assertTrue(kk.nastavi_obdrzi(A, False, opisi))
        self.assertEqual(tt.pocisti(t, raba, URA), [A])
        # Torrent, ki ga v motorju ni vec, ne ostane v zapisu samo zato, ker je bil obdrzan.
        link_datoteke.zabelezi_rabo(C, raba, URA)
        kk.nastavi_obdrzi(C, True, opisi)
        tt.pocisti(t, raba, URA)
        self.assertNotIn(C, link_datoteke._beri_rabo(raba))

    def test_polica_ponudi_obdrzi_samo_pri_napravi_ki_ga_pozna(self):
        klici = []
        odgovori = {("n-nov", "magnet.list"): {"ok": True, "data": {"items": [
                        {"id": 4, "magnet": "magnet:?xt=urn:btih:" + A, "title": "Nov", "finished": True, "keep": False}]}},
                    ("n-star", "magnet.list"): {"ok": True, "data": {"items": [
                        {"id": 5, "magnet": "magnet:?xt=urn:btih:" + B, "title": "Star", "finished": True}]}},
                    ("n-nov", "magnet.keep"): {"ok": True}}

        def ukaz(id_, dejanje, parametri, cas):
            klici.append((id_, dejanje, dict(parametri)))
            return odgovori.get((id_, dejanje), {"ok": False})
        naprave = [{"id": "n-nov", "ime": "Nov", "zmoznosti": ["remote", "torrent"]}, {"id": "n-star", "ime": "Star", "zmoznosti": ["remote", "torrent"]}]
        tukaj = [{"hash": C, "title": "Tukaj", "magnet": "magnet:?xt=urn:btih:" + C, "file": 0, "keep": True}]
        k = kk.Knjiznica(lambda: naprave, ukaz, lokalni=lambda: tukaj)
        self.assertEqual({v["naslov"]: v["obdrzi"] for v in k.seznam()}, {"Tukaj": True, "Nov": False, "Star": None})
        klici.clear()
        self.assertFalse(k.obdrzi(B, True))                                          # starejsa naprava: ukaza ne posljemo
        self.assertEqual(klici, [])
        self.assertTrue(k.obdrzi(A, True))
        self.assertEqual(klici, [("n-nov", "magnet.keep", {"id": 4, "keep": True})])
        self.assertTrue(k.vnos(A)["obdrzi"])
        nastavljeni = []
        self.assertTrue(k.obdrzi(C, False, lambda h, drzi: nastavljeni.append((h, drzi)) or True))
        self.assertEqual(nastavljeni, [(C, False)])
        self.assertFalse(k.obdrzi("f" * 40, True))


class _TorrentiSPodnapisi:
    def zazeni(self):
        pass

    def preberi(self, uri):
        return {"hash": A, "ime": "Film", "uri": uri, "datoteke": [
            {"i": 0, "ime": "Film/film.mkv", "velikost": 9000, "vrsta": "video"},
            {"i": 1, "ime": "Film/film.en.srt", "velikost": 90, "vrsta": "podnapisi"},
            {"i": 2, "ime": "Film/Subs/film.sl.srt", "velikost": 90, "vrsta": "podnapisi"}]}

    def dodaj(self, uri, izbrane):
        return 3

    def tok(self, tid, i):
        return "http://127.0.0.1:5555/t/skrito%d/%s" % (i, ["film.mkv", "film.en.srt", "film.sl.srt"][i])

    def podnapisi_za(self, tid, i):
        return [(1, "Film/film.en.srt"), (2, "Film/Subs/film.sl.srt")]

    def tece(self):
        return True

    def seznam(self):
        return []


class Podnapisi(unittest.TestCase):
    """Naprava, ki film samo gleda, dobi tudi podnapise iz istega torrenta (`subs` v odgovoru `magnet.stream`)."""

    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-podnapisi-")
        self.d = link_datoteke.Datoteke([], tls_mapa=os.path.join(self.mapa, "tls"))
        self.addCleanup(self.d.ustavi)
        self.addCleanup(shutil.rmtree, self.mapa, True)

    def test_racunalnik_ponudi_podnapise_iz_torrenta(self):
        o = self.d.tok_torrenta("magnet:?xt=urn:btih:" + A, "tv-1", torrenti=_TorrentiSPodnapisi(), zmogljivost=lambda m, v: "")
        self.assertEqual([p["name"] for p in o["subs"]], ["film.en.srt", "film.sl.srt"])
        for p in o["subs"]:
            self.assertRegex(p["path"], r"^/m/[A-Za-z0-9_\-]{8,}/film\.(en|sl)\.srt$")
            self.assertEqual(self.d.streznik.lokalni_tok(p["path"].split("/")[2])[:len("http://127.0.0.1:5555/t/skrito")],
                             "http://127.0.0.1:5555/t/skrito")
        self.assertNotEqual(o["subs"][0]["path"], o["path"])

    def test_film_z_diska_ponudi_podnapise_ob_datoteki(self):
        film = os.path.join(self.mapa, "Film")
        os.makedirs(os.path.join(film, "Subs"))
        for ime in ("film.mkv", "film.sl.srt", os.path.join("Subs", "film.en.srt"), "opombe.txt"):
            with open(os.path.join(film, ime), "wb") as f:
                f.write(b"x" * 10)
        with mock.patch.object(link_datoteke, "ze_preneseno", lambda h, i, m=None: (os.path.join(film, "film.mkv"), 0)):
            o = self.d.tok_torrenta("magnet:?xt=urn:btih:" + A, "tv-1", mape_stanja=[], pot_rabe=os.path.join(self.mapa, "r.json"))
        self.assertTrue(o["local"])
        self.assertEqual(sorted(p["name"] for p in o["subs"]), ["film.en.srt", "film.sl.srt"])
        for p in o["subs"]:
            self.assertTrue(self.d.streznik.lokalni_tok(p["path"].split("/")[2]).startswith("file://"))

    def test_knjiznica_podnapise_poda_predvajalniku_skozi_lokalni_pretok(self):
        streznik = {"base_url": "https://192.168.0.9:8443/", "fp": "AA" * 32, "token": "zeton"}
        odgovor = {"ok": True, "data": {"server": streznik, "path": "/magnet/abcdef0123456789", "name": "Film.2020.mkv", "subs": [
            {"path": "/magnet/1111111111111111", "name": "Film.2020.sl.srt"},
            {"path": "/m/2222222222222222/Film.2020.en.forced.srt", "name": "Subs/Film.2020.en.forced.srt"},
            {"path": "/d/tuja-datoteka", "name": "zunaj.srt"},                      # ni pot toka: odpade
            {"path": "/magnet/3333333333333333", "name": "namesti.exe"},            # ni podnapis: odpade
            "smeti", {"name": "brez-poti.srt"}]}}
        naprave = [{"id": "n-tel", "ime": "Telefon", "zmoznosti": ["remote", "torrent"]}]
        seznam = {"ok": True, "data": {"items": [{"id": 4, "magnet": "magnet:?xt=urn:btih:" + A, "title": "Film", "finished": True}]}}
        k = kk.Knjiznica(lambda: naprave, lambda id_, dejanje, p, cas: seznam if dejanje == "magnet.list" else odgovor, lokalni=lambda: [])
        k.seznam()
        tok = k.predvajaj(A)["tok"]
        self.assertEqual(len(tok["subs"]), 4)                                       # samo slovarji s potjo
        dodani = []
        izid = kk.podnapisi_toka(tok, dodaj=lambda vir: dodani.append(vir) or "http://127.0.0.1:1/m/%d" % len(dodani))
        self.assertEqual([(ime, jezik, oznaka) for _, ime, jezik, oznaka in izid],
                         [("Film.2020.sl.srt", "sl", ""), ("Film.2020.en.forced.srt", "en", "forced")])
        self.assertEqual([v.pot for v in dodani], ["/magnet/1111111111111111", "/m/2222222222222222/Film.2020.en.forced.srt"])
        self.assertEqual({(v.base_url, v.zeton) for v in dodani}, {("https://192.168.0.9:8443", "zeton")})
        self.assertEqual(kk.podnapisi_toka({"server": streznik, "path": "/magnet/abcdef0123456789", "name": "f.mkv"}), [])


MANIFESTI = {
    "https://javen.primer.si": {"id": "si.javen", "name": "Javni dodatek", "resources": ["stream"], "types": ["movie"], "catalogs": []},
    "https://zaseben.primer.si": {"id": "si.zaseben", "name": "Zaseben", "resources": ["stream"], "types": ["movie"], "catalogs": [],
                                  "behaviorHints": {"adult": True}},
    "https://katalog.primer.si": {"id": "si.katalog", "name": "Samo katalog", "resources": ["catalog"], "types": ["movie"], "catalogs": []},
}


class Viri(unittest.TestCase):
    """Moji viri so enaki na vseh napravah v Linku: racunalnik jih pove (brez zasebnih) in prevzame, kar zna predvajati."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="safeer-viri-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mc = os_media.MediaCenter(self.tmp, roots=[], secret_encryptor=lambda s: s, secret_decryptor=lambda s: s)
        self.ura = [1_790_000_000_000]
        self.predvajljivi = {"https://podkast.primer.si/feed.xml"}

        def manifest(url):
            koren = viri_sink.stremio_osnova(url)
            if koren not in MANIFESTI:
                raise OSError("ni dosegljiv")
            return MANIFESTI[koren]

        def preveri(base):
            return "" if "stream" in manifest(base)["resources"] else "Samo seznam naslovov."

        def osvezi(source_id):
            with self.mc._lock:
                data = self.mc._load()
                vir = next(v for v in data["viri"] if v["id"] == source_id)
                ok = vir["url"] in self.predvajljivi
                vir.update({"stevilo": 3 if ok else 0, "napaka": "" if ok else "ni predvajljivo"})
                self.mc._save(data)
            return {"ok": ok, "napaka": "" if ok else "ni predvajljivo", "vir": {k: v for k, v in vir.items() if k != "vnosi"}}
        self.popravki = [mock.patch.object(media_servers, "stremio_manifest", manifest),
                         mock.patch.object(media_servers, "stremio_preveri", preveri),
                         mock.patch.object(media_servers, "authenticate", lambda *a, **k: {}),
                         mock.patch.object(self.mc, "refresh_source", osvezi),
                         mock.patch.object(self.mc, "_izmeri_ping", lambda url: None),
                         mock.patch.object(self.mc, "_zdaj_ms", lambda: self.ura[0])]
        for p in self.popravki:
            p.start()
            self.addCleanup(p.stop)

    def _viri(self):
        return {(v["tip"], v["naslov"]): v["cas"] for v in self.mc.viri_izvoz()["sources"]}

    def test_cista_pravila(self):
        self.assertEqual(viri_sink.stremio_osnova("stremio://d.primer.si/x/manifest.json"), "https://d.primer.si/x")
        self.assertEqual(viri_sink.stremio_naslov("https://d.primer.si/x/"), "https://d.primer.si/x/manifest.json")
        self.assertEqual(viri_sink.istovetnost("stremio", "https://D.primer.si/manifest.json"), viri_sink.istovetnost("stremio", "https://d.primer.si"))
        self.assertEqual(viri_sink.istovetnost("podkast", "https://p.si/f.xml"), viri_sink.istovetnost("url", "https://p.si/f.xml"))
        self.assertNotEqual(viri_sink.istovetnost("stremio", "https://p.si"), viri_sink.istovetnost("url", "https://p.si"))
        self.assertTrue(viri_sink.vir_prevzamemo(False, None, 0))                   # dodan pred usklajevanjem, tu nikoli izbrisan
        self.assertFalse(viri_sink.vir_prevzamemo(False, 5, 5))                     # tu izbrisan hkrati ali pozneje
        self.assertTrue(viri_sink.vir_prevzamemo(False, 5, 6))
        self.assertFalse(viri_sink.vir_prevzamemo(True, None, 6))
        self.assertTrue(viri_sink.izbris_vira_velja(5, 6))
        self.assertFalse(viri_sink.izbris_vira_velja(6, 6))
        self.assertFalse(viri_sink.izbris_vira_velja(0, 0))
        self.assertEqual(viri_sink.nov_cas(10, 20, 30), 31)
        self.assertEqual(viri_sink.cas_izbrisa({"podkast|https://p.si/f.xml": 7, "url|https://p.si/f.xml": 9, "x": "y"}, "tok", "https://p.si/f.xml"), 9)
        self.assertIsNone(viri_sink.cas_izbrisa({}, "tok", "https://p.si/f.xml"))
        self.assertIsNone(viri_sink.cist_vir({"tip": "kodi", "ime": "", "naslov": "https://x.si"}))
        self.assertIsNone(viri_sink.cist_vir({"tip": "splet", "ime": "", "naslov": "file:///etc/passwd"}))
        self.assertIsNone(viri_sink.cist_vir({"tip": "splet", "ime": "a\nb", "naslov": "https://x.si"}))
        self.assertEqual(viri_sink.cist_vir({"tip": "tok-hls-video", "ime": "TV", "naslov": "https://x.si/a.m3u8", "cas": "x", "se": 1}),
                         {"tip": "tok-hls-video", "ime": "TV", "naslov": "https://x.si/a.m3u8", "cas": 0})
        self.assertEqual(viri_sink.cisti_izbrisi({"stremio|https://a.si/manifest.json": 5, "kodi|x": 5, "url|https://b.si": -1, 3: 4}),
                         {"stremio|https://a.si/manifest.json": 5})

    def test_izvoz_brez_zasebnih_in_neznanih_dodatkov(self):
        self.assertTrue(self.mc.add_server("stremio", "", "https://javen.primer.si/manifest.json", "", "")["ok"])
        self.assertTrue(self.mc.add_server("stremio", "", "https://zaseben.primer.si/manifest.json", "", "")["ok"])
        # Dodatek iz casa pred usklajevanjem (brez oznake) in zdaj nedosegljiv: ne vemo, ali je zaseben - ne gre ven.
        with self.mc._lock:
            data = self.mc._load()
            data["osebni_strezniki"].append({"id": "star", "vrsta": "streznik", "ponudnik": "stremio", "ime": "Star", "url": "https://mrtev.primer.si"})
            data["osebni_strezniki"].append({"id": "jf", "vrsta": "streznik", "ponudnik": "jellyfin", "ime": "Doma", "url": "https://jf.primer.si"})
            self.mc._save(data)
        with mock.patch.object(self.mc, "_spoznaj_dodatke", lambda idji: None):
            self.assertEqual(self._viri(), {("stremio", "https://javen.primer.si/manifest.json"): self.ura[0]})
            kazalo = self.mc.seznami_izvoz({})
        self.assertEqual([v["naslov"] for v in kazalo["sources"]], ["https://javen.primer.si/manifest.json"])
        self.assertEqual(kazalo["sources_deleted"], {})
        self.assertNotIn("zaseben", json.dumps(kazalo))
        self.assertNotIn("jf.primer", json.dumps(kazalo))                           # prijave v streznike ne potujejo

    def test_naslov_dodan_na_racunalniku_gre_napravam_kot_url(self):
        self.assertTrue(self.mc.add_source("https://podkast.primer.si/feed.xml", "Podkast")["ok"])
        self.assertFalse(self.mc.add_source("https://stran.primer.si/", "Stran")["ok"])      # ni predvajljiv: ni dodan
        self.assertEqual(self._viri(), {("url", "https://podkast.primer.si/feed.xml"): self.ura[0]})
        # Izvoz za Safeer Control (Linux) je zapisan in enak.
        with open(os.path.join(self.tmp, "viri_za_naprave.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), self.mc.viri_izvoz())

    def test_prevzame_dodatek_z_naprave_zasebnega_in_nepredvajljivega_ne(self):
        kazalo = {"sources": [
            {"tip": "stremio", "ime": "javen.primer.si", "naslov": "https://javen.primer.si/manifest.json", "cas": 500},
            {"tip": "stremio", "ime": "z", "naslov": "https://zaseben.primer.si/manifest.json", "cas": 500},     # starejsa naprava ga ponudi
            {"tip": "stremio", "ime": "k", "naslov": "https://katalog.primer.si/manifest.json", "cas": 500},     # brez tokov: racunalnik ga ne zna
            {"tip": "stremio", "ime": "m", "naslov": "https://mrtev.primer.si/manifest.json", "cas": 500},
            {"tip": "podkast", "ime": "Moj podkast", "naslov": "https://podkast.primer.si/feed.xml", "cas": 0},
            {"tip": "splet", "ime": "Stran", "naslov": "https://stran.primer.si/", "cas": 7},
            {"tip": "peertube", "ime": "pt", "naslov": "peertube.primer.si", "cas": 7},
            {"tip": "api", "ime": "api", "naslov": "https://api.primer.si|x", "cas": 7}], "sources_deleted": {}}
        osvezitve = []
        self.mc.ob_virih = lambda: osvezitve.append(1)
        self.assertTrue(self.mc.viri_uskladi(kazalo))
        self.assertEqual(osvezitve, [1])
        data = self.mc._load()
        self.assertEqual([(s["ime"], s["zaseben"], s["dodan"], s["link_naslov"]) for s in data["osebni_strezniki"]],
                         [("Javni dodatek", False, 500, "https://javen.primer.si/manifest.json")])
        self.assertEqual([(v["url"], v["link_tip"], v["dodan"]) for v in data["viri"]], [("https://podkast.primer.si/feed.xml", "podkast", 1)])
        # Naprava dobi svoje vire nazaj z istim kljucem (ne podvoji jih).
        self.assertEqual(self._viri(), {("stremio", "https://javen.primer.si/manifest.json"): 500,
                                        ("podkast", "https://podkast.primer.si/feed.xml"): 1})
        # Drugi krog: nic novega, zavrnjenih ne preverja znova (ne sprasuje omrezja ob vsakem usklajevanju).
        with mock.patch.object(self.mc, "_prevzemi_vir", lambda v: self.fail("ne znova: " + v["naslov"])):
            self.assertFalse(self.mc.viri_uskladi(kazalo))
        # Nedosegljiv dodatek poskusimo spet po 10 minutah, zavrnjenega po enem dnevu.
        klici = []
        with mock.patch.object(self.mc, "_prevzemi_vir", lambda v: klici.append(v["naslov"]) or (False, viri_sink.ZAVRNJEN_VELJA_MS)):
            self.ura[0] += viri_sink.NEDOSEGLJIV_VELJA_MS + 1
            self.mc.viri_uskladi(kazalo)
            self.assertEqual(klici, ["https://mrtev.primer.si/manifest.json"])
            self.ura[0] += viri_sink.ZAVRNJEN_VELJA_MS + 1
            self.mc.viri_uskladi(kazalo)
            self.assertEqual(len(klici), 4)
        # Spletne strani (na Androidu bliznjica v brskalnik), streznika PeerTube in vira API racunalnik ne prevzema.
        self.assertFalse(any("stran.primer" in k or "peertube" in k or "api.primer" in k for k in klici))

    def test_izbris_gre_v_obe_smeri(self):
        self.mc.add_server("stremio", "", "https://javen.primer.si", "", "")
        self.mc.add_source("https://podkast.primer.si/feed.xml", "Podkast")
        dodan = self.ura[0]
        # Izbris na napravi, starejsi od dodajanja tukaj, ne velja; novejsi velja - tudi ce ima naprava za vir svojo vrsto.
        self.assertFalse(self.mc.viri_uskladi({"sources_deleted": {"stremio|https://javen.primer.si/manifest.json": dodan - 5,
                                                                    "podkast|https://podkast.primer.si/feed.xml": dodan}}))
        self.assertEqual(len(self._viri()), 2)
        self.assertTrue(self.mc.viri_uskladi({"sources_deleted": {"stremio|https://javen.primer.si/manifest.json": dodan + 5,
                                                                   "podkast|https://podkast.primer.si/feed.xml": dodan + 6,
                                                                   "tok|https://neznan.primer.si/a.mp3": 9}}))
        self.assertEqual(self._viri(), {})
        izbrisani = self.mc.viri_izvoz()["sources_deleted"]
        self.assertEqual(izbrisani, {"stremio|https://javen.primer.si/manifest.json": dodan + 5,
                                     "podkast|https://podkast.primer.si/feed.xml": dodan + 6, "tok|https://neznan.primer.si/a.mp3": 9})
        # Izbrisan vir se z naprave, ki ga se ima (dodan prej), ne vrne; dodan pozneje se.
        self.assertFalse(self.mc.viri_uskladi({"sources": [{"tip": "stremio", "ime": "", "naslov": "https://javen.primer.si/manifest.json", "cas": dodan}]}))
        self.assertTrue(self.mc.viri_uskladi({"sources": [{"tip": "stremio", "ime": "", "naslov": "https://javen.primer.si/manifest.json", "cas": dodan + 9}]}))
        self.assertEqual(self._viri(), {("stremio", "https://javen.primer.si/manifest.json"): dodan + 9})
        self.assertNotIn("stremio|https://javen.primer.si/manifest.json", self.mc.viri_izvoz()["sources_deleted"])
        # Izbris tukaj: druge naprave ga dobijo s casom, ki ni starejsi od dodajanja (ure naprav niso enake).
        self.ura[0] = 5
        vir = self.mc._load()["osebni_strezniki"][0]
        self.assertTrue(self.mc.remove_source(vir["id"]))
        self.assertEqual(self.mc.viri_izvoz()["sources_deleted"]["stremio|https://javen.primer.si/manifest.json"], dodan + 10)
        # Uporabnik ga doda znova: izbris je pozabljen, cas dodajanja je po izbrisu.
        self.mc.add_server("stremio", "", "https://javen.primer.si", "", "")
        self.assertNotIn("stremio|https://javen.primer.si/manifest.json", self.mc.viri_izvoz()["sources_deleted"])
        self.assertEqual(self._viri(), {("stremio", "https://javen.primer.si/manifest.json"): dodan + 11})

    def test_usklajevanje_seznamov_prevzame_tudi_vire_iz_istega_kazala(self):
        vprasanja = []

        def vprasaj(parametri):
            vprasanja.append(dict(parametri or {}))
            return {"lists": [], "deleted": {}, "sources": [{"tip": "stremio", "ime": "", "naslov": "https://javen.primer.si/manifest.json", "cas": 3}],
                    "sources_deleted": {}} if not parametri else None
        self.assertTrue(self.mc.seznami_uskladi(vprasaj))
        self.assertEqual(vprasanja, [{}])                                           # eno vprasanje za sezname in vire
        self.assertEqual(list(self._viri()), [("stremio", "https://javen.primer.si/manifest.json")])
        # Naprava brez virov (starejsa razlicica ali racunalnik brez njih): nic se ne zgodi.
        self.assertFalse(self.mc.seznami_uskladi(lambda p: {"lists": [], "deleted": {}} if not p else None))
        self.assertFalse(self.mc.seznami_uskladi(lambda p: None))


class Stran(unittest.TestCase):
    """Stran Medijskega centra (Linux in Windows: assets/os): »Obdrži« na polici in osvezitev po usklajenih virih."""

    KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _beri(self, ime):
        with open(os.path.join(self.KOREN, "assets", "os", ime), encoding="utf-8") as d:
            return d.read()

    def test_obdrzi_je_na_polici_in_besedila_v_vseh_jezikih(self):
        import re
        koda = self._beri("os.js")
        self.assertIn('klic("mediaKnjiznicaObdrzi", [x.kljuc, novo])', koda)
        self.assertIn("x.obdrzi === true || x.obdrzi === false", koda)             # naprava, ki ne zna, moznosti nima
        self.assertIn('"mediaViriUsklajeni"', koda)
        kljuci = ("knjiznicaObdrzi", "knjiznicaNeObdrzi", "knjiznicaObdrzano", "knjiznicaNiVecObdrzano",
                  "knjiznicaObdrziNiUspelo", "knjiznicaObdrzanoOznaka")
        for kljuc in kljuci:
            self.assertIn('"%s"' % kljuc, koda)
        besedila = self._beri("besedila.js")
        for jezik in ("sl", "en", "de", "es", "fr", "it"):
            bloki = "\n".join(re.findall(r"Object\.assign\(BESEDILA_OS\.%s, \{(.*?)\}\);" % jezik, besedila, re.S))
            for kljuc in kljuci:
                self.assertIn('"%s":' % kljuc, bloki, "%s manjka v %s" % (kljuc, jezik))


if __name__ == "__main__":
    unittest.main()
