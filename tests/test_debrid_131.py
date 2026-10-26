"""Naloga 131: debrid storitve (TorBox, Real-Debrid, AllDebrid) in serije iz katalogov z lastnimi id-ji - kot Safeer OS
za Android (naloge 119, 128, 130). Brez omrezja: odjemalci storitev in dodatki so nadomesceni."""
import tempfile
import unittest
from unittest import mock

from core import debrid, debrid_pravila as P, media_servers, os_media

H1 = "2849211f150e966ef7924f43aec22727a644e10d"
H2 = "9f23769f0000000000000000000000000000abcd"
#: Izmisljen; prejsnji (0f0e0d0c-…-050403020100, 17 nicel od 32 znakov) je vzorec (P.je_vzorec_kljuca).
KLJUC_TB = "7c1e9a4b-2f6d-4e8a-b3c5-9d0f1a2e6b74"
KLJUC_RD = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOP"


def _sifriraj(s):
    return "enc:" + s[::-1]


def _desifriraj(s):
    return s[4:][::-1] if s.startswith("enc:") else ""


def _debrid(nastavitve=None):
    shramba = {"d": dict(nastavitve or {})}
    return debrid.Debrid(lambda: shramba["d"], lambda d: shramba.__setitem__("d", d), _sifriraj, _desifriraj), shramba


class Pravila(unittest.TestCase):
    def test_vrstni_red_in_aktivna(self):
        self.assertEqual(P.vrstni_red(set(), None), [])
        self.assertEqual(P.vrstni_red({P.ALLDEBRID, P.TORBOX}, None), [P.TORBOX, P.ALLDEBRID])
        self.assertEqual(P.vrstni_red({P.TORBOX, P.REAL_DEBRID}, P.REAL_DEBRID), [P.REAL_DEBRID, P.TORBOX])
        self.assertEqual(P.aktivna({P.TORBOX}, None, False), P.TORBOX)
        self.assertIsNone(P.aktivna(set(), P.TORBOX, False))
        self.assertIsNone(P.aktivna({P.TORBOX}, None, True))          # »Brez debrida«
        self.assertEqual(P.aktivna({P.TORBOX}, P.ALLDEBRID, False), P.TORBOX)   # izbrana brez kljuca ne velja

    def test_kljuc(self):
        self.assertEqual(P.ocisti_kljuc(" %s\n" % KLJUC_RD), KLJUC_RD)
        self.assertIsNone(P.ocisti_kljuc("abc"))
        self.assertIsNone(P.ocisti_kljuc("https://real-debrid.com/apitoken"))
        self.assertIsNone(P.ocisti_kljuc("kljuc s presledki in vec besedami"))

    def test_napake(self):
        self.assertEqual(P.razlog_za_uporabnika([P.NAPAKA_NI_PREDPOMNJENO, P.NAPAKA_KLJUC]), P.NAPAKA_KLJUC)
        self.assertEqual(P.razlog_za_uporabnika([]), P.NAPAKA_STREZNIK)
        self.assertEqual(P.rd_vrsta_napake(403, 37), P.NAPAKA_STREZNIK)     # koda pred HTTP
        self.assertEqual(P.rd_vrsta_napake(401, None), P.NAPAKA_KLJUC)
        self.assertEqual(P.ad_vrsta_napake(200, "AUTH_BAD_APIKEY"), P.NAPAKA_KLJUC)
        self.assertEqual(P.torbox_vrsta_napake(429, None), P.NAPAKA_MEJA)
        self.assertTrue(P.poskusi_s_cakanjem(False, [P.NAPAKA_NI_PREDPOMNJENO]))
        self.assertFalse(P.poskusi_s_cakanjem(True, [P.NAPAKA_NI_PREDPOMNJENO]))
        self.assertFalse(P.poskusi_s_cakanjem(False, [P.NAPAKA_NI_PREDPOMNJENO, P.NAPAKA_KLJUC]))

    def test_hashi_in_oznaka(self):
        self.assertEqual(P.hashi_za_preverbo([H1.upper(), None, "kratek", H1, " %s " % H2, "z" * 40]), [H1, H2])
        self.assertEqual(len(P.hashi_za_preverbo([str(i).zfill(40) for i in range(150)])), 100)
        self.assertEqual(P.predpomnjeni([H1.upper(), "drug"], [H1, H2]), {H1})
        self.assertEqual(P.predpomnjeni_naprej(["a", H1, None, H2], {H1, H2}), [1, 3, 0, 2])
        self.assertEqual(P.samodejni_torrent(P.TORBOX, [None, H2, H1], {H1, H2}), 1)
        self.assertEqual(P.samodejni_torrent(None, [H1], {H1}), -1)
        self.assertEqual(P.samodejni_torrent(P.TORBOX, [H1], set()), -1)

    def test_datoteka(self):
        d = [P.Datoteka(0, "sample.mkv", 10), P.Datoteka(1, "film.mkv", 1000), P.Datoteka(2, "info.nfo", 5)]
        self.assertEqual(P.izberi_datoteko(d, 0).ime, "sample.mkv")        # dodatek pove indeks
        self.assertEqual(P.izberi_datoteko(d, 2).ime, "film.mkv")          # indeks ni predvajljiv -> najvecja
        self.assertEqual(P.izberi_datoteko(d, None).ime, "film.mkv")
        self.assertIsNone(P.izberi_datoteko([P.Datoteka(0, "a.txt", 1)], None))

    def test_najhitrejsa(self):
        hitra = P.Meritev(P.TORBOX, 80, 3_000_000, 1000)       # 24 Mb/s
        pocasna = P.Meritev(P.REAL_DEBRID, 20, 1_000_000, 1000)
        podobna = P.Meritev(P.ALLDEBRID, 30, 2_800_000, 1000)  # 22,4 Mb/s - manj kot 15 % razlike
        self.assertEqual(hitra.bitov_na_sekundo, 24_000_000)
        self.assertEqual(P.najhitrejsa([pocasna, hitra]), P.TORBOX)
        self.assertEqual(P.najhitrejsa([hitra, podobna, pocasna]), P.ALLDEBRID)
        self.assertEqual(P.najhitrejsa([P.Meritev(P.TORBOX, 5, 0, 1000), pocasna]), P.REAL_DEBRID)
        self.assertIsNone(P.najhitrejsa([]))
        self.assertEqual(P.opis_meritve(hitra), "24 Mb/s · 80 ms")
        self.assertEqual(P.opis_meritve(pocasna), "8.0 Mb/s · 20 ms")

    def test_magnet(self):
        m = P.magnet(H1.upper(), "Film 2010.mkv", ["udp://sledilnik:1337"])
        self.assertTrue(m.startswith("magnet:?xt=urn:btih:" + H1))
        self.assertIn("&dn=Film%202010.mkv", m)
        self.assertIn("&tr=udp%3A%2F%2Fsledilnik%3A1337", m)


class Storitev(unittest.TestCase):
    def test_kljuc_samo_sifriran_in_nikoli_v_stanju(self):
        d, shramba = _debrid()
        self.assertFalse(d.nastavi_kljuc(P.TORBOX, "ni kljuc"))
        self.assertTrue(d.nastavi_kljuc(P.TORBOX, KLJUC_TB))
        self.assertNotIn(KLJUC_TB, str(shramba["d"]))
        self.assertEqual(d.kljuc(P.TORBOX), KLJUC_TB)
        stanje = debrid.most(d, [])
        self.assertNotIn(KLJUC_TB, str(stanje))
        self.assertEqual(stanje["aktivna"], P.TORBOX)
        self.assertTrue(stanje["samo_takoj"])
        self.assertEqual([x["kljuc"] for x in stanje["storitve"]], [True, False, False])

    def test_most_izbira_in_pozabi(self):
        d, _ = _debrid()
        # Preverba ob vnosu (TorBox user/me) brez omrezja: preizkus nikoli ne klice prave storitve.
        with mock.patch.object(debrid, "torbox_preveri", return_value=(P.PREVERBA_VELJAVEN, P.TORBOX_PRO)):
            self.assertTrue(debrid.most(d, ["kljuc", P.TORBOX, KLJUC_TB])["ok"])
        self.assertEqual(debrid.most(d, ["aktivna", ""])["aktivna"], "")       # Brez debrida
        self.assertEqual(debrid.most(d, ["aktivna", P.TORBOX])["aktivna"], P.TORBOX)
        self.assertFalse(debrid.most(d, ["samo_takoj", False])["samo_takoj"])
        self.assertFalse(debrid.most(d, ["kljuc", P.REAL_DEBRID, "x"])["ok"])
        self.assertEqual(debrid.most(d, ["pozabi", P.TORBOX])["aktivna"], "")

    def test_ena_storitev(self):
        d, _ = _debrid()
        d.nastavi_kljuc(P.TORBOX, KLJUC_TB)
        with mock.patch.object(debrid, "torbox_tok", return_value=debrid.Izid(url="https://cdn.tb/f", ponudnik=P.TORBOX)) as tb:
            izid = d.tok(H1, 0)
        self.assertEqual((izid.url, izid.ponudnik), ("https://cdn.tb/f", P.TORBOX))
        self.assertTrue(tb.call_args[0][4])           # samo predpomnjeno

    def test_vec_storitev_zmaga_najhitrejsa(self):
        d, shramba = _debrid()
        d.nastavi_kljuc(P.TORBOX, KLJUC_TB)
        d.nastavi_kljuc(P.REAL_DEBRID, KLJUC_RD)
        meritve = {"https://cdn.tb/f": P.Meritev(P.TORBOX, 90, 1_000_000, 1000),
                   "https://cdn.rd/f": P.Meritev(P.REAL_DEBRID, 30, 3_000_000, 1000)}
        with mock.patch.object(debrid, "torbox_tok", return_value=debrid.Izid(url="https://cdn.tb/f", ponudnik=P.TORBOX)), \
                mock.patch.object(debrid, "rd_tok", return_value=debrid.Izid(url="https://cdn.rd/f", ponudnik=P.REAL_DEBRID)), \
                mock.patch.object(debrid, "izmeri", side_effect=lambda p, u: meritve[u]):
            izid = d.tok(H1, None)
        self.assertEqual(izid.ponudnik, P.REAL_DEBRID)
        self.assertEqual(sorted(shramba["d"]["meritve"]), [P.REAL_DEBRID, P.TORBOX])
        self.assertEqual(d.stanje()["storitve"][1]["meritev"], "24 Mb/s · 30 ms")

    def test_neuspeh_brez_povezave(self):
        d, _ = _debrid()
        d.nastavi_kljuc(P.TORBOX, KLJUC_TB)
        with mock.patch.object(debrid, "torbox_tok", return_value=debrid.Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.TORBOX)):
            izid = d.tok(H1, None)
        self.assertIsNone(izid.url)
        self.assertEqual(izid.napaka, P.NAPAKA_NI_PREDPOMNJENO)

    def test_brez_kljuca_ni_preverbe(self):
        d, _ = _debrid()
        with mock.patch.object(debrid, "torbox_predpomnjeni", side_effect=AssertionError("brez kljuca ni klica")):
            self.assertEqual(d.predpomnjeni([H1]), set())
            self.assertEqual(d.tok(H1).napaka, P.NAPAKA_KLJUC)


def _tok_url(url, opis="1080p"):
    return {"url": url, "vir": "Splet", "kakovost": opis, "opis": opis}


def _torrent(h, opis="1080p"):
    return {"url": "", "torrent": True, "hash": h, "indeks": 0, "ime": "film.mkv", "sledilniki": [], "vir": "Torrentio",
            "kakovost": opis, "opis": opis}


class Predvajanje(unittest.TestCase):
    """resolve(): z vpisanim kljucem gre pripravljen torrent prek debrida pred povezavami; ob napaki nikoli na torrent."""

    def _center(self, td, tokovi):
        center = os_media.MediaCenter(td, roots=[], secret_encryptor=_sifriraj, secret_decryptor=_desifriraj)
        center._stremio_tokovi_vseh = lambda *a, **k: list(tokovi)
        center._zivi_naprej = lambda t: t
        item = {"id": "stremio:x:movie:tt0000001", "naslov": "Film", "vrsta": "film", "url": "stremio:https://d.primer|movie|tt0000001"}
        center._dynamic_items[item["id"]] = item
        return center, item["id"]

    def test_pripravljen_torrent_pred_povezavo(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, [_tok_url("https://splet.primer/f.mp4"), _torrent(H2), _torrent(H1)])
            center.debrid.nastavi_kljuc(P.TORBOX, KLJUC_TB)
            with mock.patch.object(center.debrid, "predpomnjeni", return_value={H1}), \
                    mock.patch.object(center.debrid, "tok", return_value=debrid.Izid(url="https://cdn.tb/f", ponudnik=P.TORBOX)) as tok:
                r = center.resolve(ident)
            self.assertEqual(r["url"], "https://cdn.tb/f")
            self.assertEqual(tok.call_args[0][0], H1)
            self.assertEqual(r["razlicice"][0]["vir"], "⚡ TorBox")
            self.assertEqual(r["razlicice"][1]["url"], "https://splet.primer/f.mp4")   # povezava ostane rezerva

    def test_brez_kljuca_ostane_kot_prej(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, [_tok_url("https://splet.primer/f.mp4"), _torrent(H1)])
            with mock.patch.object(center.debrid, "tok", side_effect=AssertionError("brez kljuca ni debrida")):
                r = center.resolve(ident)
            self.assertEqual(r["url"], "https://splet.primer/f.mp4")

    def test_napaka_debrida_nikoli_na_neposreden_torrent(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, [_torrent(H1)])
            center.debrid.nastavi_kljuc(P.TORBOX, KLJUC_TB)
            with mock.patch.object(center.debrid, "predpomnjeni", return_value=set()), \
                    mock.patch.object(center.debrid, "tok", return_value=debrid.Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO)), \
                    mock.patch.object(center, "_razresi_torrent", side_effect=AssertionError("ne na neposreden torrent")):
                r = center.resolve(ident)
            self.assertEqual(r["napaka_koda"], "debrid_ni_predpomnjeno")
            self.assertFalse(r.get("url", "").startswith("magnet:"))

    def test_brez_debrida_izbira_uporabnika(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, [_tok_url("https://splet.primer/f.mp4"), _torrent(H1)])
            center.debrid.nastavi_kljuc(P.TORBOX, KLJUC_TB)
            center.debrid.nastavi_aktivno(None)
            with mock.patch.object(center.debrid, "tok", side_effect=AssertionError("Brez debrida")):
                self.assertEqual(center.resolve(ident)["url"], "https://splet.primer/f.mp4")


TMDB = "https://katalog.primer"
TORRENTI = "https://torrenti.primer"


class Serije(unittest.TestCase):
    def test_id_epizode_po_imdb(self):
        self.assertEqual(media_servers.stremio_imdb_iz_meta({"imdb_id": "tt0903747"}, "tmdb:1396"), "tt0903747")
        self.assertEqual(media_servers.stremio_imdb_iz_meta({}, "tt7631058"), "tt7631058")
        self.assertEqual(media_servers.stremio_imdb_iz_meta({"imdb_id": None}, "tmdb:1396"), "")
        self.assertEqual(media_servers.stremio_id_epizode_imdb("tt0903747", "tmdb:1396:1:2", 1, 2), "tt0903747:1:2")
        self.assertEqual(media_servers.stremio_id_epizode_imdb("tt0903747", "tt0903747:1:2", 1, 2), "")
        self.assertEqual(media_servers.stremio_id_epizode_imdb("tt0903747", "x", 0, 1), "")
        self.assertEqual(media_servers.stremio_id_epizode_imdb("", "x", 1, 1), "")

    def test_je_epizoda(self):
        self.assertTrue(media_servers.stremio_je_epizoda("tt0903747:1:2"))
        self.assertTrue(media_servers.stremio_je_epizoda("tmdb:1396:1:2"))
        self.assertFalse(media_servers.stremio_je_epizoda("tmdb:1396"))      # serija iz kataloga z lastnimi id-ji
        self.assertFalse(media_servers.stremio_je_epizoda("tt0903747"))
        self.assertFalse(media_servers.stremio_je_epizoda(""))

    def test_daje_meta_serij(self):
        self.assertTrue(media_servers.stremio_daje_meta_serij({"resources": ["meta"], "types": ["series"], "idPrefixes": ["tt"]}, "tt1"))
        self.assertFalse(media_servers.stremio_daje_meta_serij({"resources": ["stream"], "types": ["series"]}, "tt1"))
        self.assertFalse(media_servers.stremio_daje_meta_serij({"resources": [{"name": "meta", "types": ["movie"]}]}, "tt1"))
        self.assertFalse(media_servers.stremio_daje_meta_serij({"resources": ["meta"], "idPrefixes": ["tmdb:"]}, "tt1"))

    def _zahteve(self, odgovori):
        import json

        def zahteva(url, *a, **k):
            for kos, telo in odgovori.items():
                if kos in url:
                    return json.dumps(telo).encode()
            raise OSError("ni odgovora: " + url)
        return zahteva

    def test_tokovi_serije_z_lastnimi_idji_vprasajo_se_po_imdb(self):
        """Serija iz kataloga s tmdb: id-ji - Torrentio (pozna samo IMDb) dobi tt...:1:1 (prej ga ni nikoli)."""
        meta = {"meta": {"imdb_id": "tt7631058", "videos": [{"id": "tmdb:84773:1:1", "season": 1, "episode": 1}]}}
        vprasani = []

        def tokovi(k, tip, ident):
            vprasani.append((k, ident))
            return [_torrent(H1)] if (k, ident) == (TORRENTI, "tt7631058:1:1") else []
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._stremio_strezniki = lambda: [{"url": TMDB, "ponudnik": "stremio"}, {"url": TORRENTI, "ponudnik": "stremio"}]
            center.zasebni_koreni = lambda: set()
            with mock.patch.object(media_servers, "_request", self._zahteve({"/meta/series/tmdb%3A84773.json": meta})), \
                    mock.patch.object(media_servers, "stremio_tokovi", tokovi):
                t = center._stremio_tokovi_vseh(TMDB, "series", "tmdb:84773")
        self.assertIn((TORRENTI, "tt7631058:1:1"), vprasani)
        self.assertEqual([x["hash"] for x in t], [H1])

    def test_dodatek_brez_epizod_prva_epizoda_po_imdb_drugje(self):
        """Dodatek kartice epizod ne da (Breaking Bad iz iskanja): prva epizoda po IMDb pri drugem dodatku z meta."""
        vprasani = []
        zahteve = self._zahteve({"/meta/series/tt0903747.json": {"meta": {"videos": [{"id": "tt0903747:1:1", "season": 1, "episode": 1}]}}})

        def zahteva(url, *a, **k):
            if url.startswith(TMDB):
                raise OSError("dodatek kartice nima metapodatkov")
            return zahteve(url)
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._stremio_strezniki = lambda: [{"url": TMDB, "ponudnik": "stremio"}, {"url": TORRENTI, "ponudnik": "stremio"}]
            center.zasebni_koreni = lambda: set()
            with mock.patch.object(media_servers, "_request", zahteva), \
                    mock.patch.object(media_servers, "stremio_manifest", lambda u, sveze=False: {"resources": ["meta", "stream"], "types": ["series"], "idPrefixes": ["tt"]}), \
                    mock.patch.object(media_servers, "stremio_tokovi", lambda k, tip, i: vprasani.append(i) or []):
                center._stremio_tokovi_vseh(TMDB, "series", "tt0903747")
        self.assertEqual(set(vprasani), {"tt0903747:1:1"})

    def test_poskusne_epizode_z_imdb(self):
        meta = {"meta": {"imdb_id": "tt7631058", "videos": [{"id": "tmdb:1:1:1", "season": 1, "episode": 1},
                                                            {"id": "tmdb:1:2:1", "season": 2, "episode": 1},
                                                            {"id": "tmdb:1:2:8", "season": 2, "episode": 8}]}}
        with mock.patch.object(media_servers, "_request", self._zahteve({"/meta/series/": meta})):
            self.assertEqual(media_servers.stremio_poskusne_epizode_z_imdb(TMDB, "tmdb:1"),
                             [("tmdb:1:1:1", "tt7631058:1:1"), ("tmdb:1:2:1", "tt7631058:2:1"), ("tmdb:1:2:8", "tt7631058:2:8")])


if __name__ == "__main__":
    unittest.main()
