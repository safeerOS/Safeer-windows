"""Prostori (Safeer Link Spaces, MVP) - cista pravila core/link_prostori.py: kdo je prostor, sorodniki, stalen vrstni red,
naprave brez povezave, odvzet ozji krog, varno odpiranje (samo prostor s seznama).

Ista datoteka preizkusov kot na Linuxu (Safeer-linux tests/test_link_prostori.py, 6241c32); modul je skupen."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import link_prostori as lp  # noqa: E402


def naprava(id_, ime="", zm=(), platforma="", vrsta="", ta=False, ozji=True):
    return {"id": id_, "ime": ime or id_, "zmoznosti": list(zm), "platforma": platforma, "vrsta": vrsta,
            "ta": ta, "ozji": ozji}


PC = naprava("pc-1-control", "Pisarna", ["desktop", "apps", "remote"], "windows", "control")
TABLICA = naprava("t-1-os", "Tablica", ["zaslon.deli", "remote", "apps"], "tablet")
TV = naprava("tv-1", "Dnevna soba", ["screen", "media"], "tv")
TV_OS = naprava("tv-1-os", "Dnevna soba", ["zaslon.deli", "remote", "apps"], "tv")
TA = naprava("jaz-control", "Ta", ["desktop"], "linux", ta=True)


class KdoJeProstor(unittest.TestCase):
    def test_racunalnik_in_android(self):
        z = lp.zive_s_prostorom([PC, TABLICA, TA])
        self.assertEqual(set(z), {"pc-1", "t-1"})
        self.assertEqual(z["pc-1"]["nacin"], lp.NACIN_RACUNALNIK)
        self.assertEqual(z["pc-1"]["vrsta"], "racunalnik")
        self.assertEqual(z["t-1"]["nacin"], lp.NACIN_ZASLON)
        self.assertEqual(z["t-1"]["vrsta"], "tablica")

    def test_brez_zaslona_ni_prostor(self):
        self.assertEqual(lp.zive_s_prostorom([TV]), {})

    def test_izven_ozjega_kroga_ni_prostor(self):
        self.assertEqual(lp.zive_s_prostorom([dict(PC, ozji=False)]), {})

    def test_ta_racunalnik_in_sorodniki_niso_prostor(self):
        self.assertEqual(lp.zive_s_prostorom([TA, naprava("jaz", "Ta", ["url"], "linux")]), {})

    def test_sorodniki_en_prostor_ukaz_vnosu_z_zaslonom(self):
        z = lp.zive_s_prostorom([TV, TV_OS])
        self.assertEqual(list(z), ["tv-1"])
        self.assertEqual(z["tv-1"]["id"], "tv-1-os", "ukaz gre vnosu, ki zaslon deli")
        self.assertEqual(z["tv-1"]["vrsta"], "tv")
        self.assertTrue(z["tv-1"]["aplikacije"])

    def test_namizje_pred_deljenjem(self):
        a = naprava("x", "X", ["zaslon.deli", "a", "b", "c"], "tablet")
        b = naprava("x-control", "X", ["desktop"], "linux")
        self.assertEqual(lp.zive_s_prostorom([a, b])["x"]["id"], "x-control")

    def test_lazen_sorodnik_izven_kroga_ne_dobi_ukaza(self):
        # Pregled 25. 10. 2026: ozji krog se preveri za vsakega clana, ne za skupino - "pc-a-control" izven ozjega kroga
        # z namizjem ne sme dobiti miske in tipkovnice, ceprav je pravi "pc-a" v krogu.
        pravi = naprava("pc-a", "Moj PC", ["zaslon.deli"], "tablet")
        lazen = naprava("pc-a-control", "Moj PC", ["desktop", "apps"], "linux", ozji=False)
        p = lp.za_odpiranje([pravi, lazen], "pc-a")
        self.assertEqual(p["id"], "pc-a")
        self.assertEqual(p["nacin"], lp.NACIN_ZASLON)
        self.assertFalse(p["aplikacije"], "zmoznosti laznega sorodnika ne stejejo")
        self.assertEqual(lp.za_odpiranje([pravi, lazen], "pc-a-control")["id"], "pc-a")
        # Samo lazni sorodnik zaslon zna: skupina ni prostor.
        self.assertIsNone(lp.za_odpiranje([naprava("pc-a", "Moj PC", ["url"], "linux"), lazen], "pc-a"))
        self.assertEqual(lp.zive_s_prostorom([naprava("pc-a", "Moj PC", ["url"], "linux"), lazen]), {})

    def test_pokvarjeni_vnosi(self):
        self.assertEqual(lp.zive_s_prostorom([None, "x", {"id": ""}, {"id": "y", "zmoznosti": "desktop"}]), {})

    def test_vrsta(self):
        self.assertEqual(lp.vrsta(naprava("a", platforma="phone")), "telefon")
        self.assertEqual(lp.vrsta(naprava("a", platforma="tv")), "tv")
        self.assertEqual(lp.vrsta(naprava("a", platforma="linux")), "racunalnik")
        self.assertEqual(lp.vrsta(naprava("a")), "naprava")


class Zapis(unittest.TestCase):
    def test_stalen_vrstni_red(self):
        z1 = lp.zapomni([], [TABLICA], 100)
        z2 = lp.zapomni(z1, [PC, TABLICA], 200)
        self.assertEqual([z["kljuc"] for z in z2], ["t-1", "pc-1"], "nova naprava gre na konec")
        # Tablica odide in pride nazaj: mesto ostane.
        z3 = lp.zapomni(z2, [PC], 300)
        z4 = lp.zapomni(z3, [PC, TABLICA], 400)
        self.assertEqual([z["kljuc"] for z in z4], ["t-1", "pc-1"])
        self.assertEqual(z4[0]["dodana"], 100)
        self.assertEqual(z4[0]["videna"], 400)

    def test_brez_povezave_ostane(self):
        z = lp.zapomni(lp.zapomni([], [PC, TABLICA], 100), [PC], 200)
        p = lp.prostori(z, [PC])
        self.assertEqual([(x["id"], x["povezana"]) for x in p], [("pc-1-control", True), ("t-1-os", False)])
        self.assertEqual(p[1]["videna"], 100)
        self.assertFalse(p[1]["aplikacije"], "naprava brez povezave nima programov")

    def test_odvzet_ozji_krog_izpade(self):
        z = lp.zapomni([], [PC, TABLICA], 100)
        z = lp.zapomni(z, [PC, dict(TABLICA, ozji=False)], 200)
        self.assertEqual([x["kljuc"] for x in z], ["pc-1"])

    def test_brez_zaslona_v_linku_ostane_na_mestu(self):
        # Izklopljeno deljenje zaslona (ali prazne zmoznosti ob ponovni povezavi): zapis ostane, »ni povezana«.
        z = lp.zapomni([], [TABLICA], 100)
        z2 = lp.zapomni(z, [dict(TABLICA, zmoznosti=["remote"])], 200)
        self.assertEqual(z2, z)
        self.assertFalse(lp.prostori(z2, [dict(TABLICA, zmoznosti=["remote"])])[0]["povezana"])

    def test_tv_samo_brskalnik_ostane_na_svojem_mestu(self):
        # TV "tv-1" (brskalnik, brez zaslona) in "tv-1-os" (Safeer OS): ko tece samo brskalnik, TV ne izgine in se ob
        # vrnitvi Safeer OS ne premakne na konec (pregled 25. 10. 2026).
        z = lp.zapomni([], [TV, TV_OS], 100)
        z = lp.zapomni(z, [TV, TV_OS, PC], 200)
        self.assertEqual([x["kljuc"] for x in z], ["tv-1", "pc-1"])
        z = lp.zapomni(z, [TV, PC], 300)
        self.assertEqual([x["kljuc"] for x in z], ["tv-1", "pc-1"])
        self.assertEqual([x["povezana"] for x in lp.prostori(z, [TV, PC])], [False, True])
        z = lp.zapomni(z, [TV, TV_OS, PC], 400)
        self.assertEqual([x["kljuc"] for x in z], ["tv-1", "pc-1"])
        self.assertEqual(z[0]["dodana"], 100)

    def test_odvzet_ozji_krog_brez_zaslona_izpade(self):
        z = lp.zapomni([], [TV, TV_OS], 100)
        self.assertEqual(lp.zapomni(z, [dict(TV, ozji=False)], 200), [])

    def test_osvezitev_brez_spremembe_ne_spremeni_zapisa(self):
        # Pregled 25. 10. 2026: osvezitev vsakih 5 s je vsakic zapisala os.json, ker se je `videna` vedno spremenil.
        z = lp.zapomni([], [PC, TABLICA], 1000)
        self.assertEqual(lp.zapomni(z, [PC, TABLICA], 1005), z)
        self.assertEqual(lp.zapomni(z, [PC, TABLICA], 1000 + lp.VIDENA_NAJVEC_NA_S - 1), z)
        # Po minuti (ali ob bistveni spremembi) se `videna` posodobi.
        po_minuti = lp.zapomni(z, [PC, TABLICA], 1000 + lp.VIDENA_NAJVEC_NA_S)
        self.assertEqual([x["videna"] for x in po_minuti], [1000 + lp.VIDENA_NAJVEC_NA_S] * 2)
        novo_ime = lp.zapomni(z, [dict(PC, ime="Delo"), TABLICA], 1010)
        self.assertNotEqual(novo_ime, z)
        self.assertEqual(novo_ime[0]["videna"], 1010)
        self.assertEqual(novo_ime[1]["videna"], 1000, "nespremenjena naprava ostane enaka")
        self.assertNotEqual(lp.zapomni(z, [PC, TABLICA, TV_OS], 1005), z, "nova naprava je sprememba")

    def test_ime_se_posodobi(self):
        z = lp.zapomni([], [PC], 100)
        z = lp.zapomni(z, [dict(PC, ime="Delo")], 200)
        self.assertEqual(lp.prostori(z, [])[0]["ime"], "Delo")

    def test_najvec_znanih_najprej_izpadejo_nevidene(self):
        zive = [naprava("n%d" % i, "N%d" % i, ["zaslon.deli"], "phone") for i in range(lp.NAJVEC_ZNANIH)]
        z = lp.zapomni([], zive[:1], 1)                       # n0 viden najdlje nazaj
        z = lp.zapomni(z, zive[1:], 2)
        self.assertEqual(len(z), lp.NAJVEC_ZNANIH)
        z = lp.zapomni(z, [naprava("nova", "Nova", ["desktop"], "linux")] + zive[1:], 3)
        kljuci = [x["kljuc"] for x in z]
        self.assertEqual(len(z), lp.NAJVEC_ZNANIH)
        self.assertNotIn("n0", kljuci)
        self.assertEqual(kljuci[-1], "nova")

    def test_meja_enaka_za_zapis_in_vmesnik(self):
        # Pregled 25. 10. 2026: zapis je imel 19 prostorov, vmesnik 16 (ocisti_znane je rezal znova) - ob vsaki osvezitvi
        # so se zadnji trije znova dodali (in zapisali). Zdaj: ena meja, druga osvezitev je brez spremembe.
        zive = [naprava("n%02d" % i, "N%02d" % i, ["zaslon.deli"], "phone") for i in range(lp.NAJVEC_ZNANIH + 3)]
        z1 = lp.zapomni([], zive[:lp.NAJVEC_ZNANIH], 5)
        z2 = lp.zapomni(z1, zive, 6)
        self.assertEqual(len(z2), lp.NAJVEC_ZNANIH)
        self.assertEqual(z2, z1, "stara mesta ostanejo, nazadnje dodane ne izrinejo prejsnjih")
        self.assertEqual(lp.ocisti_znane(z2), z2)
        self.assertEqual(len(lp.prostori(z2, zive)), len(z2))
        self.assertEqual(lp.zapomni(z2, zive, 7), z2, "druga osvezitev brez zapisa")

    def test_pokvarjen_zapis(self):
        surovo = [None, 5, {"kljuc": ""}, {"kljuc": "a", "vrsta": "<script>", "nacin": "x", "dodana": "zz",
                                            "ime": "A" * 500}, {"kljuc": "a"}]
        c = lp.ocisti_znane(surovo)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["vrsta"], "naprava")
        self.assertEqual(c[0]["nacin"], lp.NACIN_ZASLON)
        self.assertEqual(c[0]["dodana"], 0)
        self.assertLessEqual(len(c[0]["ime"]), 80)
        self.assertEqual(lp.ocisti_znane("ni seznam"), [])


class Odpiranje(unittest.TestCase):
    def test_samo_prostor_s_seznama(self):
        zive = [PC, TABLICA, TV, TV_OS, TA]
        self.assertEqual(lp.za_odpiranje(zive, "pc-1-control")["nacin"], lp.NACIN_RACUNALNIK)
        self.assertEqual(lp.za_odpiranje(zive, "tv-1")["id"], "tv-1-os", "tudi id sorodnika najde prostor")
        self.assertIsNone(lp.za_odpiranje(zive, "jaz-control"), "ta racunalnik ni prostor")
        self.assertIsNone(lp.za_odpiranje(zive, "neznana"))
        self.assertIsNone(lp.za_odpiranje(zive, ""))
        self.assertIsNone(lp.za_odpiranje([dict(PC, ozji=False)], "pc-1-control"))
        self.assertIsNone(lp.za_odpiranje([dict(PC, ozji=False), naprava("pc-1", "Pisarna", ["url"], "windows")],
                                          "pc-1"), "sorodnik v krogu brez zaslona ne odpre sorodnika izven kroga")

    def test_cel_zaslon_kot_android(self):
        self.assertEqual(lp.CEL_ZASLON, "safeer.cel.zaslon")      # Android link/Daljinec.CEL_ZASLON
        self.assertEqual(lp.ZMOZNOST_DELI_ZASLON, "zaslon.deli")  # Android link/Daljinec.ZMOZNOST_DELI_ZASLON


if __name__ == "__main__":
    unittest.main()
