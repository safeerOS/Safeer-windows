"""Grokov pregled Android 2.1.231 (25. 10. 2026), prenesen na namizje: cakanje pri prvi storitvi z »ni predpomnjeno«,
pospravljanje nepredpomnjenih torrentov tega poskusa v `finally` (ura streznika - glava Date), preklic pred vsakim
klicem, ki v racunu kaj ustvari, meja odgovora 8 MiB. Brez omrezja: klici storitev so nadomesceni."""
import io
import json
import threading
import time
import unittest
from unittest import mock

from core import debrid, debrid_pravila as P

H1 = "2849211f150e966ef7924f43aec22727a644e10d"
KLJUC_TB = "0f0e0d0c-0b0a-0908-0706-050403020100"
KLJUC_RD = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOP"
KLJUC_AD = "abcdefghijklmnopqrstuvwxyz012345"
DATUM = 1792890125000            # glava Date odgovora na dodajanje (ura streznika)


def _sifriraj(s):
    return "enc:" + s[::-1]


def _desifriraj(s):
    return s[4:][::-1] if s.startswith("enc:") else ""


def _debrid(*kljuci, samo_takoj=True):
    shramba = {"d": {"samo_takoj": samo_takoj}}
    d = debrid.Debrid(lambda: shramba["d"], lambda x: shramba.__setitem__("d", x), _sifriraj, _desifriraj)
    for p, k in kljuci:
        assert d.nastavi_kljuc(p, k)
    return d


def _o(koda, telo, datum=0):
    return debrid.Odgovor(koda, json.dumps(telo), datum)


class Streznik:
    """Nadomestek klic(): odgovor po (metoda, del naslova); zapise vse klice."""

    def __init__(self, odgovori):
        self.odgovori = odgovori          # seznam (metoda, del_naslova, Odgovor ali izjema)
        self.klici = []

    def __call__(self, naslov, kljuc, metoda="GET", obrazec=None, rok=20.0, telo=None):
        self.klici.append((metoda, naslov, rok))
        for i, (m, del_, odg) in enumerate(self.odgovori):
            if m == metoda and del_ in naslov:
                self.odgovori.pop(i)
                if isinstance(odg, Exception):
                    raise odg
                return odg
        raise AssertionError("nepricakovan klic %s %s" % (metoda, naslov))

    def bilo(self, metoda, del_):
        return any(m == metoda and del_ in n for m, n, _r in self.klici)


class CakalnaStoritev(unittest.TestCase):
    def test_caka_prva_z_ni_predpomnjeno_ce_prednostna_pade(self):
        """Prej: TorBox (prednostna) pade na roku, RD rece »ni predpomnjeno« - razlog je bil »streznik«, cakanja ni bilo."""
        d = _debrid((P.TORBOX, KLJUC_TB), (P.REAL_DEBRID, KLJUC_RD), samo_takoj=False)
        klici = []

        def poskus(p, h, indeks, mag, samo, preklic=None):
            klici.append((p, samo))
            if samo:
                return debrid.Izid(napaka=P.NAPAKA_STREZNIK if p == P.TORBOX else P.NAPAKA_NI_PREDPOMNJENO, ponudnik=p)
            return debrid.Izid(url="https://cdn.rd/f", ponudnik=p)

        with mock.patch.object(d, "_poskus", side_effect=poskus):
            izid = d.tok(H1)
        self.assertEqual((izid.url, izid.ponudnik), ("https://cdn.rd/f", P.REAL_DEBRID))
        self.assertIn((P.REAL_DEBRID, False), klici)
        self.assertNotIn((P.TORBOX, False), klici)

    def test_samo_takoj_razlog_ni_predpomnjeno_kljuc_drugih_ga_ne_preglasi(self):
        d = _debrid((P.TORBOX, KLJUC_TB), (P.REAL_DEBRID, KLJUC_RD), samo_takoj=True)

        def poskus(p, h, indeks, mag, samo, preklic=None):
            self.assertTrue(samo, "pri »samo takoj« ni cakanja")
            return debrid.Izid(napaka=P.NAPAKA_KLJUC if p == P.TORBOX else P.NAPAKA_NI_PREDPOMNJENO, ponudnik=p)

        with mock.patch.object(d, "_poskus", side_effect=poskus):
            izid = d.tok(H1)
        self.assertEqual((izid.napaka, izid.ponudnik), (P.NAPAKA_NI_PREDPOMNJENO, P.REAL_DEBRID))

    def test_rok_vzporednega_kroga_velja_in_preklice_zamudnika(self):
        """Prej je `with ThreadPoolExecutor` cakal na vse niti (rok ni veljal), zamudnik je nadaljeval v racunu."""
        d = _debrid((P.TORBOX, KLJUC_TB), (P.REAL_DEBRID, KLJUC_RD))
        sprosti, prejet = threading.Event(), {}

        def poskus(p, h, indeks, mag, samo, preklic=None):
            if p == P.TORBOX:
                return debrid.Izid(url="https://cdn.tb/f", ponudnik=p)
            prejet["preklic"] = preklic
            sprosti.wait(5)
            return debrid.Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=p)

        with mock.patch.object(P, "VZPOREDNO_ROK_S", 0.3), mock.patch.object(d, "_poskus", side_effect=poskus):
            zacetek = time.monotonic()
            izid = d.tok(H1)
            trajalo = time.monotonic() - zacetek
        sprosti.set()
        self.assertEqual(izid.url, "https://cdn.tb/f")
        self.assertLess(trajalo, 2.0)
        self.assertTrue(prejet["preklic"].is_set())


class RealDebridPospravljanje(unittest.TestCase):
    def test_napaka_omrezja_po_dodajanju_pospravi_v_finally(self):
        s = Streznik([
            ("POST", "/torrents/addMagnet", _o(201, {"id": "T1"}, DATUM)),
            ("GET", "/torrents/info/T1", OSError("omrezje")),
            ("GET", "/torrents/info/T1", _o(200, {"added": "2026-10-25T01:02:04.000Z"})),
            ("DELETE", "/torrents/delete/T1", _o(204, {})),
        ])
        with mock.patch.object(debrid, "klic", side_effect=s):
            izid = debrid.rd_tok(KLJUC_RD, "magnet:?xt=urn:btih:" + H1, None, True, cakaj=lambda x: None)
        self.assertEqual(izid.napaka, P.NAPAKA_STREZNIK)
        self.assertTrue(s.bilo("DELETE", "/torrents/delete/T1"))
        self.assertLessEqual(max(r for m, n, r in s.klici if "delete" in n), debrid.POSPRAVI_ROK_S)

    def test_ne_izbrise_torrenta_ki_je_bil_v_racunu_ze_prej(self):
        """addMagnet za isti hash lahko vrne obstojeci torrent (dodan minuto prej, npr. na TV) - tega ne brisemo."""
        s = Streznik([
            ("POST", "/torrents/addMagnet", _o(201, {"id": "T2"}, DATUM)),
            ("GET", "/torrents/info/T2", _o(200, {"files": [{"id": 1, "path": "/f.mkv", "bytes": 9}], "status": "waiting_files_selection"})),
            ("POST", "/torrents/selectFiles/T2", _o(204, {})),
            ("GET", "/torrents/info/T2", _o(200, {"status": "downloading"})),
            ("GET", "/torrents/info/T2", _o(200, {"status": "downloading"})),
            ("GET", "/torrents/info/T2", _o(200, {"status": "downloading"})),
            ("GET", "/torrents/info/T2", _o(200, {"status": "downloading"})),
            ("GET", "/torrents/info/T2", _o(200, {"status": "downloading"})),
            ("GET", "/torrents/info/T2", _o(200, {"added": "2026-10-25T01:01:00.000Z"})),
        ])
        with mock.patch.object(debrid, "klic", side_effect=s):
            izid = debrid.rd_tok(KLJUC_RD, "magnet:?xt=urn:btih:" + H1, None, True, cakaj=lambda x: None)
        self.assertEqual(izid.napaka, P.NAPAKA_NI_PREDPOMNJENO)
        self.assertFalse(s.bilo("DELETE", "/torrents/delete/"))

    def test_preklic_pred_dodajanjem(self):
        preklic = threading.Event()
        preklic.set()
        with mock.patch.object(debrid, "klic", side_effect=AssertionError("preklican poskus ne klice storitve")):
            izid = debrid.rd_tok(KLJUC_RD, "magnet:?xt=urn:btih:" + H1, None, True, preklic=preklic)
        self.assertEqual(izid.napaka, P.NAPAKA_STREZNIK)

    def test_preklic_po_dodajanju_ne_izbere_in_pospravi(self):
        preklic = threading.Event()
        s = Streznik([
            ("POST", "/torrents/addMagnet", _o(201, {"id": "T3"}, DATUM)),
            ("GET", "/torrents/info/T3", _o(200, {"files": [{"id": 1, "path": "/f.mkv", "bytes": 9}]})),
            ("GET", "/torrents/info/T3", _o(200, {"added": "2026-10-25T01:02:05.000Z"})),
            ("DELETE", "/torrents/delete/T3", _o(204, {})),
        ])

        def klic(*a, **k):
            o = s(*a, **k)
            if "/torrents/info/T3" in a[0] and len(s.klici) == 2:
                preklic.set()               # rok vzporednega kroga je potekel, medtem ko je nit cakala na odgovor
            return o

        with mock.patch.object(debrid, "klic", side_effect=klic):
            debrid.rd_tok(KLJUC_RD, "magnet:?xt=urn:btih:" + H1, None, True, preklic=preklic)
        self.assertFalse(s.bilo("POST", "/torrents/selectFiles/"))
        self.assertTrue(s.bilo("DELETE", "/torrents/delete/T3"))

    def test_cakan_torrent_ne_izbrise_poskus_samo_takoj(self):
        debrid.CAKANI.oznaci(P.REAL_DEBRID, "T4")
        s = Streznik([("POST", "/torrents/addMagnet", _o(201, {"id": "T4"}, DATUM)),
                      ("GET", "/torrents/info/T4", OSError("omrezje"))])
        with mock.patch.object(debrid, "klic", side_effect=s):
            debrid.rd_tok(KLJUC_RD, "magnet:?xt=urn:btih:" + H1, None, True, cakaj=lambda x: None)
        self.assertFalse(s.bilo("DELETE", "/torrents/delete/"))


class AllDebridPospravljanje(unittest.TestCase):
    def _nalozi(self, mid, ready):
        return ("POST", "/magnet/upload", _o(200, {"status": "success", "data": {"magnets": [{"id": mid, "ready": ready}]}}, DATUM))

    def test_ni_pripravljen_izbrise_samo_svojega(self):
        s = Streznik([self._nalozi(11, False),
                      ("POST", "/magnet/status", _o(200, {"status": "success", "data": {"magnets": {"uploadDate": 1792890124}}})),
                      ("POST", "/magnet/delete", _o(200, {"status": "success"}))])
        with mock.patch.object(debrid, "klic", side_effect=s):
            izid = debrid.ad_tok(KLJUC_AD, H1, None, True)
        self.assertEqual(izid.napaka, P.NAPAKA_NI_PREDPOMNJENO)
        self.assertTrue(s.bilo("POST", "/magnet/delete"))

    def test_star_magnet_ostane(self):
        s = Streznik([self._nalozi(12, False),
                      ("POST", "/magnet/status", _o(200, {"status": "success", "data": {"magnets": [{"uploadDate": 1792880000}]}}))])
        with mock.patch.object(debrid, "klic", side_effect=s):
            debrid.ad_tok(KLJUC_AD, H1, None, True)
        self.assertFalse(s.bilo("POST", "/magnet/delete"))

    def test_brez_glave_date_ne_brisemo(self):
        s = Streznik([("POST", "/magnet/upload", _o(200, {"status": "success", "data": {"magnets": [{"id": 13, "ready": False}]}})),
                      ("POST", "/magnet/status", _o(200, {"status": "success", "data": {"magnets": {"uploadDate": 1792890124}}}))])
        with mock.patch.object(debrid, "klic", side_effect=s):
            debrid.ad_tok(KLJUC_AD, H1, None, True)
        self.assertFalse(s.bilo("POST", "/magnet/delete"))


class TorBoxPreklic(unittest.TestCase):
    def test_preklican_ne_doda_in_ne_steje_v_mejo(self):
        preklic = threading.Event()
        casi = []
        s = Streznik([("GET", "/checkcached", _o(200, {"success": True, "data": {}}))])

        def klic(*a, **k):
            o = s(*a, **k)
            preklic.set()
            return o

        with mock.patch.object(debrid, "klic", side_effect=klic):
            izid = debrid.torbox_tok(KLJUC_TB, H1, None, "magnet:?xt=urn:btih:" + H1, False, casi, preklic=preklic)
        self.assertEqual(izid.napaka, P.NAPAKA_STREZNIK)
        self.assertEqual(casi, [])
        self.assertFalse(s.bilo("POST", "/createtorrent"))


class MejaOdgovora(unittest.TestCase):
    class _Odg(io.BytesIO):
        def __init__(self, podatki, dolzina=None):
            super().__init__(podatki)
            self.headers = {"Content-Length": str(dolzina)} if dolzina is not None else {}

    def test_meja_8_mib(self):
        self.assertEqual(P.NAJVEC_ODGOVORA, 8 * 1024 * 1024)
        self.assertEqual(debrid._beri_omejeno(self._Odg(b"x" * 100), 100), b"x" * 100)
        with self.assertRaises(OSError):
            debrid._beri_omejeno(self._Odg(b"x" * 101), 100)
        with self.assertRaises(OSError):
            debrid._beri_omejeno(self._Odg(b"", dolzina=101), 100)      # Content-Length vec od meje: ne beremo

    def test_glava_date(self):
        self.assertEqual(debrid._datum_ms({"Date": "Sun, 25 Oct 2026 01:02:05 GMT"}), DATUM)
        self.assertEqual(debrid._datum_ms({}), 0)
        self.assertEqual(debrid._datum_ms({"Date": "ni datum"}), 0)


if __name__ == "__main__":
    unittest.main()
