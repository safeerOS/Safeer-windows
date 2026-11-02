"""secrets.sync na namizju - isti scenariji kot Androidov tests/UskladitevKljucevPravilaTest.kt (veja
zaganjalnik-beta-k42): tri naprave, izbris in ponoven vnos, hkratni spremembi, uvoz s casom 1, neberljiva vrednost
brez groba, zavrnjeni zapisi, ozji krog, povabilo brez vrednosti, pregledi U1-U3, Grok 15 N3/N4/N9/N10, Grok 33 F1/F2
in pregled 96 V1."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import uskladitev_kljucev_pravila as P  # noqa: E402
from core.uskladitev_kljucev_pravila import Meta, Zapis  # noqa: E402

PONUDNIKI = {"torbox", "realdebrid", "alldebrid"}


def VSE(_k, v):
    return v != "slab"


def VSI(_izvor):
    return True


TB = P.kljuc_debrid("torbox")
DOD = P.kljuc_dodatka("0123456789abcdef")
URA = 1_000_000


class Naprava:
    """Simulacija naprave: stanje (meta + vrednosti) in prejem po pravilih."""

    def __init__(self, ident):
        self.id = ident
        self.meta = {}
        self.vrednosti = {}

    @staticmethod
    def odtis(v):
        return "o" + v

    def spremeni(self, k, v, ura):
        if v is None:
            self.vrednosti.pop(k, None)
        else:
            self.vrednosti[k] = v
        self.meta.update(P.lokalne_spremembe(self.meta, {a: self.odtis(b) for a, b in self.vrednosti.items()},
                                             set(), self.id, ura, False))

    def odstrani(self, k, v_krog, ura):
        self.meta = dict(P.po_odstranitvi(self.meta, k, v_krog))
        self.spremeni(k, None, ura)

    def stanje(self):
        return P.za_poslati(self.meta, self.vrednosti, self.id)

    def prejmi(self, zapisi, ura, od):
        u = P.za_uporabo(self.meta, zapisi, ura, PONUDNIKI, VSE,
                         lambda izvor: izvor != self.id and P.izvor_posiljatelja(izvor, od))
        for x in u:
            if x.izbrisan:
                self.vrednosti.pop(x.kljuc, None)
            else:
                self.vrednosti[x.kljuc] = x.vrednost
            self.meta[x.kljuc] = Meta(x.cas, x.izvor, x.izbrisan, "" if x.izbrisan else self.odtis(x.vrednost))
        lastne = P.lokalne_spremembe(self.meta, {a: self.odtis(b) for a, b in self.vrednosti.items()}, set(),
                                     self.id, ura, False)
        assert not lastne, "prejem je ustvaril lastno spremembo: %r" % lastne
        return len(u)


class Kljuci(unittest.TestCase):
    def test_veljavni_kljuci(self):
        self.assertTrue(P.veljaven_kljuc(TB, PONUDNIKI))
        self.assertFalse(P.veljaven_kljuc(P.kljuc_debrid("x"), PONUDNIKI))
        self.assertTrue(P.veljaven_kljuc(DOD, PONUDNIKI))
        self.assertFalse(P.veljaven_kljuc("dodatek:abc", PONUDNIKI))
        self.assertTrue(P.veljaven_kljuc(P.KLJUC_USENET, PONUDNIKI))
        self.assertTrue(P.veljaven_kljuc(P.KLJUC_USENET_PONUDNIK, PONUDNIKI))
        self.assertFalse(P.veljaven_kljuc("geslo", PONUDNIKI))
        # Namizje zaupanja zaslona in virov IPTV (se) ne usklajuje: zapis se prezre.
        self.assertFalse(P.veljaven_kljuc("zaupanje:n-aaaaaaaaaaaaaaaa", PONUDNIKI))
        self.assertFalse(P.veljaven_kljuc("iptv:0123456789abcdef", PONUDNIKI))

    def test_novejsi(self):
        self.assertTrue(P.novejsi(5, "a", False, Meta(4, "z", False, "")))
        self.assertFalse(P.novejsi(3, "z", False, Meta(4, "a", False, "")))
        self.assertTrue(P.novejsi(4, "b", False, Meta(4, "a", False, "")))
        self.assertTrue(P.novejsi(4, "a", True, Meta(4, "a", False, "")))
        self.assertFalse(P.novejsi(4, "a", False, Meta(4, "a", False, "x")), "idempotentno")
        self.assertTrue(P.novejsi(1, "a", False, None))

    def test_lokalne_spremembe(self):
        m0 = P.lokalne_spremembe({}, {TB: "h1"}, set(), "tel", 1000, uvoz=True)
        self.assertEqual(m0[TB], Meta(P.CAS_UVOZA, "tel", False, "h1"))
        m1 = P.lokalne_spremembe(m0, {TB: "h2"}, set(), "tel", 2000, False)
        self.assertEqual(m1[TB], Meta(2000, "tel", False, "h2"))
        m2 = P.lokalne_spremembe({TB: Meta(5000, "tv", False, "h2")}, {}, set(), "tel", 3000, False)
        self.assertEqual(m2[TB], Meta(5001, "tel", True, ""), "izbris: cas nikoli starejsi od prejsnjega")
        self.assertEqual(P.lokalne_spremembe({TB: Meta(5, "a", False, "h")}, {}, {TB}, "tel", 9, False), {})
        self.assertEqual(P.lokalne_spremembe({TB: Meta(5, "a", False, "h")}, {TB: "h"}, set(), "tel", 9, False), {})
        self.assertEqual(P.lokalne_spremembe({TB: Meta(9, "a", True, "")}, {TB: "h"}, set(), "tel", 10, False)[TB],
                         Meta(10, "tel", False, "h"))


class Prejem(unittest.TestCase):
    def test_veljavnost(self):
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 5, "a", True, "x"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 5, "a", False, ""), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 5, "a", False, "slab"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, URA + P.NAJVEC_NAPREJ_MS + 1, "a", False, "k"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 0, "a", False, "k"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 5, "a\u0001", False, "k"), URA, PONUDNIKI, VSE))
        self.assertTrue(P.veljaven_zapis(Zapis(TB, URA + 5 * 60_000, "a", False, "k"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, URA + 300 * 24 * 3600 * 1000, "a", False, "k"), URA, PONUDNIKI, VSE))
        self.assertFalse(P.veljaven_zapis(Zapis(TB, 5, "a", False, "k\x07"), URA, PONUDNIKI, VSE))
        self.assertTrue(P.veljaven_zapis(Zapis(TB, 5, "a", False, "vrstica\nvrstica"), URA, PONUDNIKI, VSE))

    def test_za_uporabo(self):
        self.assertEqual(P.za_uporabo({}, [Zapis(TB, 5, "a", False, "k5"), Zapis(TB, 7, "b", False, "k7"),
                                           Zapis(TB, 6, "c", False, "k6")], URA, PONUDNIKI, VSE, VSI),
                         [Zapis(TB, 7, "b", False, "k7")])
        veliko = [Zapis(P.kljuc_dodatka("%016x" % i), 5, "a", False, "v") for i in range(1, 101)]
        self.assertEqual(len(P.za_uporabo({}, veliko, URA, PONUDNIKI, VSE, VSI)), 64)
        self.assertEqual(P.za_uporabo({}, [Zapis(TB, 5, "tv", False, "k")], URA, PONUDNIKI, VSE,
                                      lambda i: i == "tablica"), [])
        self.assertTrue(P.izvor_posiljatelja("n-aaaaaaaaaaaaaaaa", "n-aaaaaaaaaaaaaaaa"))
        self.assertFalse(P.izvor_posiljatelja("n-aaaaaaaaaaaaaaaa", "n-bbbbbbbbbbbbbbbb") or P.izvor_posiljatelja("", ""))

    def test_povabilo_in_potrditev(self):
        pov = P.za_povabilo([Zapis(TB, 5, "tel", False, "SKRIVNO"),
                             Zapis(DOD, 6, "tel", False, "https://webtor.io/token/z/x", "webtor.io")])
        self.assertTrue(all(z.vrednost == "" for z in pov))
        self.assertEqual(pov[1].gostitelj, "webtor.io")
        self.assertEqual(P.za_uporabo({}, pov, URA, PONUDNIKI, VSE, VSI), [])
        self.assertTrue(P.vrednosti_za(P.POTRJENA))
        self.assertFalse(P.vrednosti_za(None) or P.vrednosti_za(P.POVABLJENA) or P.vrednosti_za(P.CAKA))
        self.assertTrue(P.caka_velja(0, P.CAKA_VELJA_MS - 1))
        self.assertFalse(P.caka_velja(0, P.CAKA_VELJA_MS) or P.caka_velja(10, 5))

    def test_zamenjave(self):
        obst = {TB: Meta(5, "tel", False, "h"), "usenet": Meta(5, "tel", True, "")}
        self.assertEqual([z.kljuc for z in P.zamenjave(obst, [Zapis(TB, 9, "tv", False, "nov"),
                                                               Zapis(DOD, 9, "tv", False, "x"),
                                                               Zapis("usenet", 9, "tv", True, "")])], [TB])


class TriNaprave(unittest.TestCase):
    def test_scenarij(self):
        tel, tv, tab = Naprava("telefon"), Naprava("tv"), Naprava("tablica")
        tel.spremeni(TB, "KLJUC1", 100)
        tel.spremeni(DOD, "https://webtor.io/token/z1/stremio/manifest.json", 101)
        self.assertEqual(tv.prejmi(tel.stanje(), URA, "telefon"), 2)
        self.assertEqual(tv.prejmi(tel.stanje(), URA, "telefon"), 0, "ponovljeno sporocilo")
        self.assertEqual(len(tv.stanje()), 0, "tuji zapisi se ne posljejo naprej (U2)")
        self.assertEqual(tab.prejmi(tv.stanje(), URA, "tv"), 0)
        self.assertEqual(tab.prejmi([Zapis(TB, 999, "telefon", False, "PODTAKNJEN")], URA, "tv"), 0, "ponarejen izvor")
        self.assertEqual(tab.prejmi(tel.stanje(), URA, "telefon"), 2)
        self.assertEqual(tv.vrednosti[TB], "KLJUC1")
        tel.spremeni(DOD, None, 200)
        tv.prejmi(tel.stanje(), URA, "telefon")
        tab.prejmi(tel.stanje(), URA, "telefon")
        self.assertNotIn(DOD, tab.vrednosti, "izbris dodatka se prenese")
        self.assertTrue(tab.meta[DOD].izbrisan)
        self.assertEqual(tab.prejmi([Zapis(DOD, 101, "telefon", False,
                                           "https://webtor.io/token/z1/stremio/manifest.json")], URA, "telefon"), 0)
        tab.spremeni(DOD, "https://webtor.io/token/z2/stremio/manifest.json", 300)
        tel.prejmi(tab.stanje(), URA, "tablica")
        self.assertEqual(tel.vrednosti[DOD], "https://webtor.io/token/z2/stremio/manifest.json")
        # hkratni spremembi: zmaga kasnejsa
        tel.spremeni(TB, "KLJUC_TEL", 400)
        tv.spremeni(TB, "KLJUC_TV", 401)
        z_tel, z_tv = tel.stanje(), tv.stanje()
        tel.prejmi(z_tv, URA, "tv")
        tv.prejmi(z_tel, URA, "telefon")
        self.assertEqual(tel.vrednosti[TB], tv.vrednosti[TB])
        self.assertEqual(tel.vrednosti[TB], "KLJUC_TV")
        # enak cas: odloci izvor (»tv« > »telefon«)
        tel.spremeni(TB, "A", 500)
        tv.spremeni(TB, "B", 500)
        a1, b1 = tel.stanje(), tv.stanje()
        tel.prejmi(b1, URA, "tv")
        tv.prejmi(a1, URA, "telefon")
        self.assertEqual(tel.vrednosti[TB], tv.vrednosti[TB])
        self.assertEqual(tv.vrednosti[TB], "B")
        # uvoz: obstojeci kljuc ne preglasi kasnejse spremembe druge naprave
        star = Naprava("stara")
        star.vrednosti[TB] = "STAR"
        star.meta.update(P.lokalne_spremembe(star.meta, {TB: "oSTAR"}, set(), "stara", 9_000, uvoz=True))
        star.prejmi(tv.stanje(), URA, "tv")
        self.assertEqual(star.vrednosti[TB], tv.vrednosti[TB])


class KrogInNaprave(unittest.TestCase):
    def test_sprejem(self):
        self.assertEqual(P.sprejem(True, True, P.POTRJENA), P.SPREJMI)
        self.assertEqual(P.sprejem(True, True, P.POVABLJENA), P.VPRASAJ)
        self.assertEqual(P.sprejem(True, True, None), P.VPRASAJ)
        self.assertEqual(P.sprejem(True, True, P.CAKA), P.VPRASAJ)
        self.assertEqual(P.sprejem(True, True, P.ZAVRNJENA), P.ZAVRNI)
        self.assertEqual(P.sprejem(True, False, P.POTRJENA), P.ZAVRNI, "zunaj ozjega kroga nikoli")
        self.assertEqual(P.sprejem(False, True, P.POTRJENA), P.ZAVRNI)

    def test_poslji(self):
        self.assertTrue(P.sme_poslati(True, True, True, True, True, P.POTRJENA))
        self.assertTrue(P.sme_poslati(True, True, True, True, True, None))
        self.assertFalse(P.sme_poslati(True, False, True, True, True, P.POTRJENA), "odstranjena iz kroga")
        self.assertFalse(P.sme_poslati(True, True, False, True, True, P.POTRJENA), "brez zascite")
        self.assertFalse(P.sme_poslati(True, True, True, True, False, P.POTRJENA), "stara razlicica")
        self.assertFalse(P.sme_poslati(True, True, True, True, True, P.ZAVRNJENA))
        self.assertFalse(P.sme_poslati(True, True, True, True, True, P.CAKA))
        self.assertFalse(P.sme_poslati(False, True, True, True, True, P.POTRJENA))
        self.assertFalse(P.sme_poslati(True, True, True, False, True, P.POTRJENA))

    def test_za_poslati(self):
        self.assertEqual(P.za_poslati({TB: Meta(2, "a", False, "h"), "debrid:alldebrid": Meta(3, "a", True, "")}, {}, "a"),
                         [Zapis("debrid:alldebrid", 3, "a", True, "")])
        self.assertEqual(P.za_poslati({TB: Meta(2, "a", False, "h"), "usenet": Meta(3, "b", False, "h")},
                                      {TB: "v", "usenet": "u"}, "a"), [Zapis(TB, 2, "a", False, "v")])
        self.assertEqual(P.za_poslati({TB: Meta(2, "a", False, "h")}, {TB: "v"}, ""), [])


class PreglediGrok(unittest.TestCase):
    def test_n3_n4_n9_n10(self):
        self.assertEqual(P.brez_neberljivih([Zapis(TB, 2, "b", False, "v"), Zapis("usenet", 2, "b", False, "u")], {TB}),
                         [Zapis("usenet", 2, "b", False, "u")])
        self.assertEqual(P.zdruzi_spremembi([TB], {TB: "moj"}, [TB], {TB: "zlo1"}), ([TB], {TB: "moj"}))
        self.assertEqual(P.zdruzi_spremembi([TB], {TB: "moj"}, ["usenet", TB], {"usenet": "u0", TB: "zlo1"}),
                         ([TB, "usenet"], {TB: "moj", "usenet": "u0"}))
        self.assertFalse(P.prehod_koncan({TB, "usenet"}, {TB}))
        self.assertTrue(P.prehod_koncan({TB, "usenet"}, set()))
        self.assertEqual(P.prikaz_gostitelja("https://pravi.test/x/manifest.json", "torrentio.strem.fun", "pravi.test"),
                         "pravi.test")
        self.assertEqual(P.prikaz_gostitelja("", "Torrentio.Strem.Fun‮", ""), "torrentio.strem.fun")
        self.assertEqual(P.samo_ime_gostitelja("evil​moc.test"), "evilmoc.test")

    def test_oddaja(self):
        self.assertEqual(P.oddaja(True, True, True), P.VREDNOST)
        self.assertEqual(P.oddaja(True, True, False), P.NEZNAN)
        self.assertEqual(P.oddaja(False, True, False), P.NEZNAN)
        self.assertEqual(P.oddaja(False, False, False), P.BREZ)
        self.assertEqual(P.lokalne_spremembe({"usenet": Meta(5, "a", False, "h")}, {}, {"usenet"}, "a", 10, False), {})

    def test_f1_odstrani(self):
        tel, tv = Naprava("telefon"), Naprava("tv")
        tel.spremeni(TB, "K1", 100)
        self.assertEqual(tv.prejmi(tel.stanje(), 200, "telefon"), 1)
        tv.odstrani(TB, v_krog=False, ura=300)
        self.assertEqual(tv.stanje(), [], "neveljaven odstranjen - brez groba")
        self.assertEqual(tel.prejmi(tv.stanje(), 400, "tv"), 0)
        self.assertEqual(tel.vrednosti[TB], "K1")
        self.assertEqual(tv.prejmi(tel.stanje(), 500, "telefon"), 1)
        self.assertEqual(tv.vrednosti[TB], "K1")
        tv.odstrani(TB, v_krog=True, ura=600)
        self.assertEqual(tel.prejmi(tv.stanje(), 700, "tv"), 1)
        self.assertNotIn(TB, tel.vrednosti)
        self.assertEqual([P.izbris_v_krog(True), P.izbris_v_krog(False)], [True, False])
        self.assertEqual(P.po_odstranitvi({TB: Meta(3, "a", True, "")}, TB, False), {TB: Meta(3, "a", True, "")})

    def test_f2_vmesna_sprememba(self):
        prejet = Zapis(TB, 100, "telefon", False, "K1")
        self.assertEqual(P.se_vedno_novejsi({TB: Meta(150, "tv", False, "oK2")}, [prejet]), [])
        self.assertEqual(P.se_vedno_novejsi({TB: Meta(50, "tv", False, "o")}, [prejet]), [prejet])

    def test_v1_prebrana_oblika(self):
        def od(v):
            return "h|" + v
        prejeto = '{"url": "https://idx.example", "key": "0123456789abcdef0123456789abcdef"}'
        prebrano = '{"url":"https://idx.example","key":"0123456789abcdef0123456789abcdef"}'
        trenutni = {P.KLJUC_USENET: od(prebrano)}
        stara = {P.KLJUC_USENET: Meta(1000, "naprava-A", False, od(prejeto))}
        self.assertTrue(P.lokalne_spremembe(stara, trenutni, set(), "naprava-B", 2000, False))
        meta = {P.KLJUC_USENET: Meta(1000, "naprava-A", False, od(P.vrednost_za_odtis(prejeto, prebrano)))}
        spr = P.lokalne_spremembe(meta, trenutni, set(), "naprava-B", 2000, False)
        self.assertEqual(spr, {})
        self.assertEqual(P.za_poslati({**meta, **spr}, {P.KLJUC_USENET: prebrano}, "naprava-B"), [])
        self.assertEqual(P.vrednost_za_odtis(prejeto, None), prejeto)


class Sporocilo(unittest.TestCase):
    def test_json_kot_android(self):
        zapisi = [Zapis(TB, 5, "n-a", False, "K"), Zapis("debrid:alldebrid", 6, "n-a", True, ""),
                  Zapis(DOD, 7, "n-a", False, "", "webtor.io")]
        j = P.v_json(zapisi)
        self.assertEqual(j[0], {"k": TB, "c": 5, "i": "n-a", "d": False, "v": "K"})
        self.assertEqual(j[1], {"k": "debrid:alldebrid", "c": 6, "i": "n-a", "d": True})
        self.assertEqual(j[2], {"k": DOD, "c": 7, "i": "n-a", "d": False, "g": "webtor.io"})
        self.assertEqual(P.iz_json(j), zapisi)

    def test_iz_json_odporno(self):
        self.assertEqual(P.iz_json(None), [])
        self.assertEqual(P.iz_json([1, "x", None]), [])
        z = P.iz_json([{"k": TB, "c": "12", "i": "a", "d": True, "v": "SKRIVNO", "g": "Zlo‮.test"}])[0]
        self.assertEqual((z.cas, z.izbrisan, z.vrednost, z.gostitelj), (12, True, "", "zlo.test"))
        self.assertEqual(len(P.iz_json([{"k": TB}] * 100)), P.NAJVEC_ZAPISOV)


if __name__ == "__main__":
    unittest.main()
