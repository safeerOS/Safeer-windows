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

        def katalog(query="", kind="vse", genre="", page=1):
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
