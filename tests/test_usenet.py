"""Usenet prek TorBoxa na namizju (core/usenet_pravila.py, core/debrid.py) - enako kot Android (UsenetPravilaTest.kt)."""
import json
import unittest
from unittest import mock

from core import debrid, debrid_pravila as P, usenet_pravila as U

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel>
<item><title>Film.2010.1080p.BluRay.x264</title><link>https://ix.example/getnzb/a?apikey=SKRIVNO</link>
<enclosure url="https://ix.example/getnzb/a.nzb?apikey=SKRIVNO" length="5000" type="application/x-nzb"/>
<newznab:attr name="size" value="8589934592"/></item>
<item><title>Film.2010.1080p.BluRay.x264</title><enclosure url="https://ix.example/getnzb/b.nzb" length="1"/>
<newznab:attr name="size" value="8589934592"/></item>
<item><title>Brez povezave</title></item>
<item><title>Http drugam</title><enclosure url="http://drug.example/c.nzb"/></item>
<item><title>Film.2010.2160p</title><enclosure url="https://ix.example/getnzb/d.nzb" length="123"/></item>
</channel></rss>"""


class Pravila(unittest.TestCase):
    def test_osnova(self):
        self.assertEqual(U.osnova(" https://api.ix.example/api?t=caps "), "https://api.ix.example")
        self.assertEqual(U.osnova("https://ix.example/newznab/api/"), "https://ix.example/newznab")
        self.assertEqual(U.osnova("http://192.168.0.5:5076/api"), "http://192.168.0.5:5076")
        self.assertEqual(U.osnova("http://nzbhydra.local"), "http://nzbhydra.local")
        for slab in ("http://ix.example/api", "ftp://ix.example", "https://user:pass@ix.example", "",
                     "https://ix.example/a b", "http://8.8.8.8/api"):
            self.assertIsNone(U.osnova(slab), slab)
        # Lastnik 25. 10. 2026 (kot Android): gola domena dobi https:// sama.
        self.assertEqual(U.osnova(" nzbfinder.ws "), "https://nzbfinder.ws")
        self.assertEqual(U.osnova("ix.example/api?"), "https://ix.example")
        self.assertEqual(U.osnova("nzbfinder.ws:8443"), "https://nzbfinder.ws:8443")
        self.assertEqual(U.osnova("localhost:5076"), "https://localhost:5076")
        self.assertEqual(U.osnova("192.168.1.10:5076"), "https://192.168.1.10:5076")
        self.assertEqual(U.osnova("[::1]:5076"), "https://[::1]:5076")
        self.assertEqual(U.osnova("abc123.example"), "https://abc123.example")      # kratko heks ime s piko ostane

    def test_kljuc_v_polju_za_naslov(self):
        """Grokov pregled 31, H1 (Android bed1134): gola domena je vsak vnos brez sheme spremenila v https://<vnos> - kljuc
        API v polju za naslov bi postal gostitelj in sel necifriran v DNS. Gostitelj mora biti ime s piko brez kljuca."""
        heks32, uuid = "0123456789abcdef0123456789abcdef", "abcdef01-2345-6789-abcd-ef0123456789"
        rd = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJKLMNOPQRST"
        for slab in (heks32, uuid, "https://" + heks32, rd, heks32 + ":443", heks32 + ".ws", "https://%s.example" % uuid,
                     "nzbfinder", "http//nzbfinder.ws", "https:/nzbfinder.ws", "https://nas:5076", "https://x.example:99999",
                     "https://x.example:abc", "jaz:geslo@x.example", "https://x..example"):
            self.assertIsNone(U.osnova(slab), slab)
        for kljuc in (" %s " % heks32, uuid, "https://%s/api" % heks32, rd, heks32 + ".home", "aB3dE5gH7jK9mN1pQ3sT"):
            self.assertTrue(U.naslov_je_kljuc(kljuc), kljuc)
        for ime in ("nzbfinder.ws", "nzbfinder", "https://api.nzbgeek.info/api?", "http://192.168.1.20:5076", "localhost:5076",
                    "", "abc123.example"):
            self.assertFalse(U.naslov_je_kljuc(ime), ime)

    def test_kljuc(self):
        self.assertEqual(U.ocisti_kljuc(" 0123456789abcdef0123456789abcdef "), "0123456789abcdef0123456789abcdef")
        for slab in ("kratek", "z presledkom 12345", "ključčšž12345", "a" * 129, None):
            self.assertIsNone(U.ocisti_kljuc(slab))

    def test_naslov_iskanja(self):
        self.assertEqual(U.naslov_iskanja("https://ix.example", "k1234567", "tt1375666"),
                         "https://ix.example/api?apikey=k1234567&imdbid=1375666&limit=100&extended=1&t=movie")
        self.assertTrue(U.naslov_iskanja("https://ix.example", "k1234567", "tt0108778:1:2").endswith("&t=tvsearch&season=1&ep=2"))
        for ident in ("tmdb:1396", "kitsu:1:2", "tt", "tt0108778:1", "tt0108778:a:1", "tt0108778:1:0", ""):
            self.assertIsNone(U.naslov_iskanja("https://ix.example", "k1234567", ident), ident)
            self.assertFalse(U.iscemo(ident))

    def test_napaka(self):
        self.assertEqual(U.napaka('<error code="100" description="x"/>'), P.NAPAKA_KLJUC)
        self.assertEqual(U.napaka('<error code="501"/>'), P.NAPAKA_MEJA)
        self.assertEqual(U.napaka('<error code="900"/>'), U.NAPAKA_INDEKSATOR)
        self.assertIsNone(U.napaka(RSS))

    def test_zadetki(self):
        z = U.zadetki(RSS, "https://ix.example")
        self.assertEqual([x.naslov for x in z], ["Film.2010.1080p.BluRay.x264", "Film.2010.2160p"])
        self.assertEqual(z[0].velikost, 8589934592)
        self.assertEqual(z[1].velikost, 123)                    # enclosure length, ko ni newznab:attr
        self.assertEqual(U.opis(z[0]), "Film.2010.1080p.BluRay.x264\n💾 8.0 GB")

    def test_zadetki_xxe_in_smeti(self):
        xxe = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>'
        self.assertEqual(U.zadetki(xxe, "https://ix.example"), [])
        self.assertEqual(U.zadetki("<html>ni rss", "https://ix.example"), [])
        self.assertEqual(U.zadetki("", "https://ix.example"), [])

    def test_http_samo_isti_gostitelj_v_domacem_omrezju(self):
        rss = '<rss><channel><item><title>A</title><enclosure url="http://192.168.0.5:5076/getnzb/1"/></item></channel></rss>'
        self.assertEqual(len(U.zadetki(rss, "http://192.168.0.5:5076")), 1)
        self.assertEqual(U.zadetki(rss, "https://ix.example"), [])

    def test_id_toka_brez_kljuca(self):
        i = U.id_toka("https://ix.example/getnzb/a.nzb?apikey=SKRIVNO")
        self.assertTrue(i.startswith("usenet:") and len(i) == len("usenet:") + 16)
        self.assertNotIn("SKRIVNO", i)
        self.assertTrue(U.je_usenet(i))

    def test_samodejno(self):
        self.assertEqual(U.za_samodejno([60.0, 8.0, 0.0, 4.0]), [1, 2])
        self.assertEqual(U.za_samodejno([]), [])

    def test_je_nzb(self):
        self.assertTrue(U.je_nzb('<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">'))
        self.assertFalse(U.je_nzb("<!DOCTYPE html><html>"))
        self.assertFalse(U.je_nzb('<error code="100"/>'))

    def test_ni_predpomnjeno(self):
        self.assertTrue(U.ni_predpomnjeno(True, P.NAPAKA_STREZNIK))
        self.assertFalse(U.ni_predpomnjeno(True, P.NAPAKA_KLJUC))
        self.assertFalse(U.ni_predpomnjeno(False, P.NAPAKA_STREZNIK))

    def test_vecdelni_obrazec(self):
        t = U.vecdelni_obrazec([("name", "Ime\r\n--mejaX\r\nvrinjeno"), ("add_only_if_cached", "false")],
                               ("file", "safeer.nzb", b"<nzb/>"), "mejaX")
        self.assertEqual(t.count(b"--mejaX\r\n"), 3)            # dve polji + datoteka; vrinjena meja odstranjena
        self.assertIn(b'name="name"\r\n\r\nIme vrinjeno\r\n', t)
        self.assertTrue(t.endswith(b"\r\n--mejaX--\r\n"))
        with self.assertRaises(ValueError):
            U.vecdelni_obrazec([], ("file", "a", b""), "slaba meja\r\n")


def _debrid(stanje):
    return debrid.Debrid(lambda: json.loads(json.dumps(stanje)), lambda d: (stanje.clear(), stanje.update(d)),
                         lambda s: "enc:" + s, lambda s: s[4:] if s.startswith("enc:") else (_ for _ in ()).throw(ValueError()))


class Shramba(unittest.TestCase):
    def test_indeksator_samo_sifriran_in_most(self):
        st = {}
        d = _debrid(st)
        self.assertFalse(d.nastavi_indeksator("http://ix.example", "0123456789abcdef"))
        self.assertTrue(d.nastavi_indeksator("https://ix.example/api", "0123456789abcdef"))
        self.assertEqual(st["usenet"], {"url": "enc:https://ix.example", "kljuc": "enc:0123456789abcdef"})
        self.assertEqual(d.indeksator(), ("https://ix.example", "0123456789abcdef"))
        s = debrid.most(d, [])
        self.assertEqual(s["usenet"], {"gostitelj": "ix.example", "torbox": False, "torbox_pro": None, "stanje": "nepreverjen"})
        self.assertNotIn("0123456789abcdef", json.dumps(s))
        self.assertFalse(d.usenet_na_voljo())                   # brez kljuca TorBox ne
        d.nastavi_kljuc(P.TORBOX, "t" * 32)
        self.assertTrue(d.usenet_na_voljo())
        d.nastavi_aktivno(None)                                 # »Brez debrida«
        self.assertFalse(d.usenet_na_voljo())
        debrid.most(d, ["pozabi_usenet"])
        self.assertIsNone(d.indeksator())
        self.assertFalse(debrid.most(d, ["usenet", "https://ix.example", "x"])["ok"])

    def test_iskanje_in_tok(self):
        st = {}
        d = _debrid(st)
        d.nastavi_kljuc(P.TORBOX, "t" * 32)
        d.nastavi_indeksator("https://ix.example", "0123456789abcdef")
        z = [U.Zadetek("Film.1080p", "https://ix.example/getnzb/a.nzb?apikey=0123456789abcdef", 2 * 1073741824)]
        with mock.patch.object(debrid, "usenet_isci", return_value=z) as isci:
            tokovi = d.usenet_isci("tt1375666")
        isci.assert_called_once()
        self.assertEqual(isci.call_args[0], ("https://ix.example", "0123456789abcdef", "tt1375666"))
        self.assertEqual(len(tokovi), 1)
        self.assertNotIn("0123456789abcdef", json.dumps(tokovi))
        with mock.patch.object(debrid, "usenet_nzb", return_value=(b"<nzb/>", "")) as nzb, \
                mock.patch.object(debrid, "torbox_usenet", return_value=debrid.Izid(url="https://cdn.example/f", ponudnik=P.TORBOX)) as tb:
            izid = d.usenet_tok(tokovi[0]["url"], "Film.1080p")
        nzb.assert_called_once_with(z[0].povezava)
        self.assertEqual(tb.call_args[0][0], "t" * 32)
        self.assertEqual(izid.url, "https://cdn.example/f")
        # NZB od indeksatorja in povezava TorBoxa potrdita oba kljuca (stanje sledi uporabi).
        self.assertEqual((d.stanje_kljuca(P.INDEKSATOR), d.stanje_kljuca(P.TORBOX)), (P.STANJE_VELJA, P.STANJE_VELJA))
        self.assertEqual(d.usenet_tok("usenet:neznan", "x").napaka, U.NAPAKA_INDEKSATOR)

    def test_torbox_usenet_pot(self):
        odgovori = [
            debrid.Odgovor(200, json.dumps({"success": True, "data": {"usenetdownload_id": 7}})),
            debrid.Odgovor(200, json.dumps({"success": True, "data": {"download_state": "downloading", "files": []}})),
            debrid.Odgovor(200, json.dumps({"success": True, "data": {"download_state": "completed", "download_finished": True,
                                                                         "download_present": True,
                                                                         "files": [{"id": 3, "short_name": "f.mkv", "size": 9}]}})),
            debrid.Odgovor(200, json.dumps({"success": True, "data": "https://cdn.example/x.mkv"})),
        ]
        klici = []
        with mock.patch.object(debrid, "klic", side_effect=lambda *a, **k: (klici.append((a, k)), odgovori.pop(0))[1]):
            izid = debrid.torbox_usenet("t" * 32, b"<nzb/>", "Film 1080p", None, False, cakaj=lambda s: None)
        self.assertEqual(izid.url, "https://cdn.example/x.mkv")
        self.assertIn("multipart/form-data; boundary=", klici[0][1]["telo"][1])
        self.assertIn("token=", klici[3][0][0])
        self.assertIsNone(klici[3][0][1])                       # requestdl brez glave (kljuc je token)

    def test_torbox_usenet_ni_predpomnjeno(self):
        o = debrid.Odgovor(200, json.dumps({"success": False, "error": "NOT_CACHED", "detail": "x"}))
        with mock.patch.object(debrid, "klic", return_value=o):
            izid = debrid.torbox_usenet("t" * 32, b"<nzb/>", "Film", None, True, cakaj=lambda s: None)
        self.assertEqual(izid.napaka, P.NAPAKA_NI_PREDPOMNJENO)


if __name__ == "__main__":
    unittest.main()
