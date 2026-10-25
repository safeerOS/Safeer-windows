"""Vrstni red virov (lastnik 25. 10. 2026 07:25): z vpisanim indeksatorjem gre Usenet, ki ga ima TorBox ze pripravljenega,
pred vse druge vire (placan, najboljsa kakovost in hitrost). Preverba prvih treh izdaj tece hkrati s preverbo ⚡, rok ~6 s.
Brez omrezja: klici storitev so nadomesceni."""
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import debrid, debrid_pravila as P, os_media, usenet_pravila as U

H1 = "2849211f150e966ef7924f43aec22727a644e10d"
KLJUC_TB = "0f0e0d0c-0b0a-0908-0706-050403020100"


def _sifriraj(s):
    return "enc:" + s[::-1]


def _desifriraj(s):
    return s[4:][::-1] if s.startswith("enc:") else ""


def _debrid(*kljuci):
    shramba = {"d": {}}
    d = debrid.Debrid(lambda: shramba["d"], lambda x: shramba.__setitem__("d", x), _sifriraj, _desifriraj)
    for p, k in kljuci:
        assert d.nastavi_kljuc(p, k)
    return d


def _tok_usenet(n, gb=2.0):
    return {"url": "usenet:%016x" % n, "naslov": "Film.%d.1080p" % n, "opis": "Film %d 1080p" % n, "gb": gb}


class UsenetTakoj(unittest.TestCase):
    def test_najboljsa_pripravljena_in_preklic_ostalih(self):
        d = _debrid((P.TORBOX, KLJUC_TB))
        prejeto = []

        def tok(id_toka, ime, indeks=None, samo_takoj=False, rok_cakanja=0.0, preklic=None):
            prejeto.append((id_toka, samo_takoj, preklic))
            if id_toka.endswith("1"):
                return debrid.Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.TORBOX)
            return debrid.Izid(url="https://cdn.tb/" + id_toka[-1], ponudnik=P.TORBOX)

        tokovi = [_tok_usenet(1), _tok_usenet(2), _tok_usenet(3), _tok_usenet(4)]
        with mock.patch.object(d, "usenet_tok", side_effect=tok):
            izid = d.usenet_takoj(tokovi, rok=2.0)
        self.assertEqual(izid[0], 1)
        self.assertEqual(izid[1].url, "https://cdn.tb/2")
        self.assertEqual(len(prejeto), U.TAKOJ_IZDAJ)                # prve tri izdaje, cetrte ne
        self.assertTrue(all(samo for _i, samo, _p in prejeto))
        self.assertTrue(prejeto[0][2].is_set())

    def test_rok_velja(self):
        d = _debrid((P.TORBOX, KLJUC_TB))
        sprosti = threading.Event()

        def tok(*a, **k):
            sprosti.wait(5)
            return debrid.Izid(url="https://cdn.tb/x", ponudnik=P.TORBOX)

        with mock.patch.object(d, "usenet_tok", side_effect=tok):
            zacetek = time.monotonic()
            self.assertIsNone(d.usenet_takoj([_tok_usenet(1)], rok=0.3))
            self.assertLess(time.monotonic() - zacetek, 2.0)
        sprosti.set()

    def test_nzb_se_ne_prenese_dvakrat(self):
        d = _debrid((P.TORBOX, KLJUC_TB))
        d._povezave_nzb["usenet:aaaa"] = "https://ix.example/getnzb/a.nzb?apikey=x"
        with mock.patch.object(debrid, "usenet_nzb", return_value=(b"<nzb/>", "")) as nzb, \
                mock.patch.object(debrid, "torbox_usenet", return_value=debrid.Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO)):
            d.usenet_tok("usenet:aaaa", "Film", samo_takoj=True)
            d.usenet_tok("usenet:aaaa", "Film", samo_takoj=False)
        self.assertEqual(nzb.call_count, 1)


class VrstniRedVirov(unittest.TestCase):
    """Lastnik 25. 10. 2026 07:25: z vpisanim indeksatorjem gre Usenet, ki ga ima TorBox pripravljenega, pred ⚡ in povezave."""

    def _center(self, td, tokovi):
        center = os_media.MediaCenter(td, roots=[], secret_encryptor=_sifriraj, secret_decryptor=_desifriraj)
        center._stremio_tokovi_vseh = lambda *a, **k: list(tokovi)
        center._zivi_naprej = lambda t: t
        item = {"id": "stremio:x:movie:tt0000001", "naslov": "Film", "vrsta": "film",
                "url": "stremio:https://d.primer|movie|tt0000001"}
        center._dynamic_items[item["id"]] = item
        center.debrid.nastavi_kljuc(P.TORBOX, KLJUC_TB)
        return center, item["id"]

    def _tokovi(self):
        return [{"url": "https://splet.primer/f.mp4", "vir": "Splet", "kakovost": "720p", "opis": "720p"},
                {"url": "", "torrent": True, "hash": H1, "indeks": 0, "ime": "f.mkv", "sledilniki": [], "vir": "T",
                 "kakovost": "1080p", "opis": "1080p"}]

    def test_usenet_pripravljen_pred_predpomnjenim(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, self._tokovi())
            center.debrid.nastavi_indeksator("https://ix.example", "0123456789abcdef")
            with mock.patch.object(center.debrid, "usenet_isci", return_value=[_tok_usenet(1)]), \
                    mock.patch.object(center.debrid, "usenet_takoj",
                                      return_value=(0, debrid.Izid(url="https://cdn.tb/u", ponudnik=P.TORBOX))), \
                    mock.patch.object(center.debrid, "predpomnjeni", return_value={H1}), \
                    mock.patch.object(center.debrid, "tok", side_effect=AssertionError("Usenet je pripravljen")):
                r = center.resolve(ident)
            self.assertEqual(r["url"], "https://cdn.tb/u")
            self.assertTrue(r["usenet"])
            self.assertEqual(r["razlicice"][1]["url"], "https://splet.primer/f.mp4")    # povezava ostane rezerva

    def test_usenet_ni_pripravljen_nato_predpomnjen(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, self._tokovi())
            center.debrid.nastavi_indeksator("https://ix.example", "0123456789abcdef")
            with mock.patch.object(center.debrid, "usenet_isci", return_value=[_tok_usenet(1)]), \
                    mock.patch.object(center.debrid, "usenet_takoj", return_value=None), \
                    mock.patch.object(center.debrid, "predpomnjeni", return_value={H1}), \
                    mock.patch.object(center.debrid, "usenet_tok", side_effect=AssertionError("⚡ pred Usenetom s cakanjem")), \
                    mock.patch.object(center.debrid, "tok", return_value=debrid.Izid(url="https://cdn.tb/t", ponudnik=P.TORBOX)):
                r = center.resolve(ident)
            self.assertEqual(r["url"], "https://cdn.tb/t")

    def test_brez_indeksatorja_ni_usenet_koraka(self):
        with tempfile.TemporaryDirectory() as td:
            center, ident = self._center(td, self._tokovi())
            with mock.patch.object(center.debrid, "usenet_takoj", side_effect=AssertionError("brez indeksatorja")), \
                    mock.patch.object(center.debrid, "predpomnjeni", return_value=set()):
                r = center.resolve(ident)
            self.assertEqual(r["url"], "https://splet.primer/f.mp4")


if __name__ == "__main__":
    unittest.main()
