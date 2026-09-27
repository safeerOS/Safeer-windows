"""Medijski center: katalog se prikaze takoj iz predpomnilnika, sveze podatke dobi v ozadju."""
import tempfile
import threading
import time
import unittest

from core import os_media


class PredpomnilnikKatalogaTest(unittest.TestCase):
    def _center(self, td, vnosi):
        center = os_media.MediaCenter(td, roots=[])
        klici = []

        def katalog(query="", kind="vse", genre="", page=1, **_moznosti):
            klici.append((query, kind, genre, page))
            return {"vnosi": list(vnosi), "viri": [], "skupaj": len(vnosi), "stran": page, "skupaj_strani": 1, "mape": []}

        center.catalog = katalog
        return center, klici

    def test_drugic_iz_predpomnilnika_tudi_po_ponovnem_zagonu(self):
        with tempfile.TemporaryDirectory() as td:
            center, klici = self._center(td, [{"id": "a", "naslov": "Film A", "vrsta": "film"}])
            prvi = center.catalog_hitro("", "film")
            self.assertFalse(prvi["iz_predpomnilnika"])
            center._shrani_predpomnilnik_zdaj()
            # "Ponovni zagon": nov objekt, podatki z diska, brez cakanja na omrezje.
            nov, klici2 = self._center(td, [{"id": "a", "naslov": "Film A", "vrsta": "film"}])
            drugi = nov.catalog_hitro("", "film")
            self.assertTrue(drugi["iz_predpomnilnika"])
            self.assertEqual([v["id"] for v in drugi["vnosi"]], ["a"])
            self.assertFalse(drugi["osvezujem"])  # svez pogled: ni odvecnega osvezevanja
            self.assertEqual(klici2, [])
            self.assertIn("a", nov._dynamic_items)  # klik na kartico iz predpomnilnika deluje

    def test_star_pogled_takoj_nato_osvezitev_v_ozadju(self):
        with tempfile.TemporaryDirectory() as td:
            center, _ = self._center(td, [{"id": "a", "naslov": "A", "vrsta": "film"}])
            center.catalog_hitro("", "film")
            center.ozastari_predpomnilnik()
            center.catalog = lambda *a, **k: {"vnosi": [{"id": "b", "naslov": "B", "vrsta": "film"}], "skupaj_strani": 1}
            dobljeno, konec = [], threading.Event()
            rez = center.catalog_hitro("", "film", ob_osvezitvi=lambda kljuc, r: (dobljeno.append(r), konec.set()))
            self.assertEqual([v["id"] for v in rez["vnosi"]], ["a"])  # takoj stari pogled
            self.assertTrue(rez["osvezujem"])
            self.assertTrue(konec.wait(5))
            self.assertEqual([v["id"] for v in dobljeno[0]["vnosi"]], ["b"])
            self.assertEqual(dobljeno[0]["kljuc"], rez["kljuc"])

    def test_prazen_odgovor_ne_prepise_dobrega_pogleda(self):
        with tempfile.TemporaryDirectory() as td:
            center, _ = self._center(td, [{"id": "a", "naslov": "A", "vrsta": "film"}])
            center.catalog_hitro("", "film")
            center.ozastari_predpomnilnik()
            center.catalog = lambda *a, **k: {"vnosi": [], "skupaj_strani": 1}
            center.catalog_hitro("", "film", ob_osvezitvi=lambda *a: self.fail("ni spremembe"))
            for _ in range(50):
                if not center._osvezujem:
                    break
                time.sleep(0.05)
            self.assertEqual([v["id"] for v in center.catalog_hitro("", "film")["vnosi"]], ["a"])

    def test_odstranjen_vir_pocisti_predpomnilnik(self):
        with tempfile.TemporaryDirectory() as td:
            center, _ = self._center(td, [{"id": "a", "naslov": "A", "vrsta": "film"}])
            center.catalog_hitro("", "film")
            center._save({"viri": [{"id": "v1", "url": "https://primer.si/a.m3u", "vnosi": []}]})
            self.assertTrue(center.remove_source("v1"))
            self.assertEqual(center._nalozi_predpomnilnik()["katalog"], {})


if __name__ == "__main__":
    unittest.main()


class NepredvajljiviViriTest(unittest.TestCase):
    def test_torrent_in_arhiv_nista_v_katalogu(self):
        self.assertFalse(os_media.je_predvajljiv_naslov("https://x.si/film.torrent"))
        self.assertFalse(os_media.je_predvajljiv_naslov("https://x.si/paket.ZIP"))
        self.assertFalse(os_media.je_predvajljiv_naslov("magnet:?xt=urn:btih:abc"))
        self.assertTrue(os_media.je_predvajljiv_naslov("https://x.si/tok.m3u8"))
        self.assertIsNone(os_media._item("Film", "https://x.si/film.torrent", base="", source_id="s", source_name="S"))

    def test_vir_brez_predvajljive_vsebine_ni_dodan_in_uporabnik_izve_zakaj(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._izmeri_ping = lambda url: None
            center.refresh_source = lambda sid: {"ok": False, "napaka": "Vira ni bilo mogoče prebrati.", "vir": {"stevilo": 0}}
            rez = center.add_source("https://primer.si/samo-torrenti.xml")
            self.assertFalse(rez["ok"])
            self.assertTrue(rez["nepredvajljiv"])
            self.assertIn("nismo dodali", rez["sporocilo"])
            self.assertEqual(center.sources(), [])

    def test_prazen_vir_ni_prikazan(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._save({"viri": [{"id": "a", "url": "https://a.si", "stevilo": 0, "napaka": "x", "vnosi": []},
                                   {"id": "b", "url": "https://b.si", "stevilo": 3, "vnosi": []}]})
            self.assertEqual([v["id"] for v in center.vidni_viri()], ["b"])


class StremioPreveriTest(unittest.TestCase):
    def test_samo_torrenti_zavrnjen_katalog_brez_tokov_zavrnjen(self):
        from core import media_servers as ms
        import json as _json
        odgovori = {}
        stari = ms._request
        ms._request = lambda url, *a, **k: _json.dumps(odgovori[url.split("://", 1)[1].split("/", 1)[1]])
        try:
            odgovori.update({
                "manifest.json": {"id": "d", "resources": ["catalog", "stream"], "catalogs": [{"type": "movie", "id": "top"}]},
                "catalog/movie/top.json": {"metas": [{"id": "tt1"}]},
                "stream/movie/tt1.json": {"streams": [{"infoHash": "abc"}]},
            })
            self.assertIn("torrent", ms.stremio_preveri("https://dodatek.si/manifest.json"))
            odgovori["stream/movie/tt1.json"] = {"streams": [{"url": "https://cdn.si/f.mp4"}]}
            self.assertEqual(ms.stremio_preveri("https://dodatek.si/manifest.json"), "")
            odgovori["manifest.json"] = {"id": "d", "resources": ["catalog"], "catalogs": []}
            self.assertIn("brez predvajalnih", ms.stremio_preveri("https://dodatek.si/manifest.json"))
        finally:
            ms._request = stari


class RazvrscanjeInFiltriTest(unittest.TestCase):
    VNOSI = [
        {"id": "1", "naslov": "Zebra", "leto": 1999, "vir_id": "a", "razlicice": [{"vir_id": "a", "vir": "A", "url": "https://a/1"}]},
        {"id": "2", "naslov": "Ananas", "leto": 0, "datum": "2021-05-01", "vir_id": "b",
         "razlicice": [{"vir_id": "b", "vir": "B", "url": "https://b/2"}, {"vir_id": "a", "vir": "A", "url": "https://a/2"}]},
        {"id": "3", "naslov": "Čebula", "leto": 0, "vir_id": "b", "razlicice": [{"vir_id": "b", "vir": "B", "url": "https://b/3"}]},
    ]

    def test_po_letu_brez_letnice_na_konec(self):
        r = os_media.MediaCenter._razvrsti_vnose(list(self.VNOSI), "novo")
        self.assertEqual([x["id"] for x in r], ["2", "1", "3"])
        r = os_media.MediaCenter._razvrsti_vnose(list(self.VNOSI), "staro")
        self.assertEqual([x["id"] for x in r], ["1", "2", "3"])

    def test_po_abecedi_s_sumniki(self):
        r = os_media.MediaCenter._razvrsti_vnose(list(self.VNOSI), "az")
        self.assertEqual([x["naslov"] for x in r], ["Ananas", "Čebula", "Zebra"])

    def test_izklopljen_vir_skrije_samo_njegove_kartice(self):
        r = os_media.MediaCenter._filtriraj_vire(list(self.VNOSI), {"b"})
        self.assertEqual([x["id"] for x in r], ["1", "2"])
        self.assertEqual(r[1]["url"], "https://a/2")
        self.assertEqual(r[1]["stevilo_razlicic"], 1)

    def test_samo_lokalno_brez_spletnih_katalogov(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._tmdb_catalog = lambda *a, **k: self.fail("samo lokalno ne sme klicati spleta")
            center._local_items = lambda: [{"id": "L", "naslov": "Moj posnetek", "vrsta": "video", "url": "file:///x.mp4",
                                            "vir_id": "lokalno", "vir": "Ta računalnik"}]
            r = center.catalog_hitro("", "vse", samo_lokalno=True)
            self.assertEqual([x["naslov"] for x in r["vnosi"]], ["Moj posnetek"])


class JavnaLastTest(unittest.TestCase):
    def test_samo_pd_mp4_brez_sumljivih_naslovov(self):
        from core import zakoniti_viri as z
        docs = [
            {"identifier": "his_girl_friday", "title": "His Girl Friday", "year": "1940", "format": ["h.264", "Ogg Video"]},
            {"identifier": "film-drip-torrent", "title": "Film 2020 DRip Mp3 Torrent", "format": ["h.264"]},
            {"identifier": "samo_ogg", "title": "Samo Ogg", "format": ["Ogg Video"]},
        ]
        v = z.ZakonitiViri()
        v._json = lambda url: {"response": {"docs": docs}}
        r = v.javna_last()
        self.assertEqual([x["archive_id"] for x in r], ["his_girl_friday"])
        self.assertEqual(r[0]["leto"], 1940)
        self.assertEqual(r[0]["vrsta"], "film")


class PriporocenoTest(unittest.TestCase):
    def test_privzeto_najprej_priljubljeno_iz_najboljsih_virov(self):
        with tempfile.TemporaryDirectory() as td:
            center = os_media.MediaCenter(td, roots=[])
            center._local_items = lambda: [{"id": "l", "naslov": "Aaa domaci", "vrsta": "film", "url": "file:///a.mp4"}]
            center._ima_embed_vir = lambda data=None: True
            center._embed_viri = lambda data: []
            center._tmdb_catalog = lambda *a, **k: ([{"naslov": "Zzz uspesnica", "vrsta": "film", "url": "https://t/1", "leto": 2024},
                                                     {"naslov": "Mmm druga", "vrsta": "film", "url": "https://t/2", "leto": 2023}], 1)
            center._zakoniti_viri.get = lambda *a, **k: [{"naslov": "Bbb javna last", "vrsta": "film", "url": "https://a/1",
                                                          "vir_id": "archive-javna-last"}]
            center._personal_items = lambda q: []
            r = center.catalog("", "film")
            self.assertEqual([x["naslov"] for x in r["vnosi"]], ["Zzz uspesnica", "Mmm druga", "Bbb javna last", "Aaa domaci"])


class PeerTubeFilterTest(unittest.TestCase):
    def test_piratske_nalozbe_in_blokirani_strezniki_izloceni(self):
        from core import zakoniti_viri as z
        v = z.ZakonitiViri()
        ok = {"name": "What is PeerTube?", "uuid": "u1"}
        self.assertIsNotNone(v._peertube_video(ok, "framatube.org", "x"))
        self.assertIsNone(v._peertube_video(ok, "peertube.uno", "x"))
        for naslov in ("Snowden (Film Completo Italiano in streaming)", "Inside Job (documentario completo in streaming ITA)",
                       "cats - the living tombstone 10 hours [LCrCCgjdKx8]", "Neki film 2020 WEBRip"):
            self.assertIsNone(v._peertube_video({"name": naslov, "uuid": "u2"}, "tilvids.com", "x"), naslov)
