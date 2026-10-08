"""Varovalo za pravilo iz CONTRIBUTING.md: v Safeerju ni kode, napisane za eno imenovano stran.

Neodvisni pregled 8. 10. 2026: pravilo je veljalo samo na papirju - core/adblock.py je vseboval skript za pet imenovanih
strani (Hookshot Media) in nobeno varovalo ga ni ustavilo. Zdaj test pregleda vse skripte, ki jih Safeer vstavi v strani
(konstante *_SCRIPT / *_JS / *_CSS v core/adblock.py): vsebovati ne smejo domenskih imen.

Izjema, izrecno naštetá: YouTube (lasten predvajalnik in oglasni cevovod; funkcija izdelka, ne popravek ene strani).
Nova izjema zahteva spremembo tega seznama in utemeljitev v pregledu kode."""
import os
import re
import sys
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

IZJEME = {"YOUTUBE_ADBLOCK_SCRIPT", "YOUTUBE_KEEP_WATCHING_SCRIPT"}
DOMENA = re.compile(r"""['"/(][a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|tv|io|si|ai|gg|co|be|de|eu|uk|us|info)['"/)]""")
KONSTANTA = re.compile(r'^([A-Z][A-Z_0-9]*)\s*=\s*r?"""(.*?)"""', re.S | re.M)


def _vstavljeni_skripti():
    with open(os.path.join(KOREN, "core", "adblock.py"), encoding="utf-8") as f:
        koda = f.read()
    return [(ime, telo) for ime, telo in KONSTANTA.findall(koda)]


class BrezReceptovZaStrani(unittest.TestCase):

    def test_najde_vsaj_znane_skripte(self):
        # Varovalka varovalke: ce bi se zapis konstant spremenil in regex ne bi nic vec nasel, test ne bi preveril nicesar.
        imena = {ime for ime, _ in _vstavljeni_skripti()}
        self.assertTrue({"YOUTUBE_ADBLOCK_SCRIPT", "GPC_AND_DNT_SCRIPT", "TAB_THROTTLER_SCRIPT"} <= imena, imena)

    def test_skripti_nimajo_domen(self):
        kriv = {}
        for ime, telo in _vstavljeni_skripti():
            if ime in IZJEME:
                continue
            najdeno = sorted({m.group(0) for m in DOMENA.finditer(telo)})
            if najdeno:
                kriv[ime] = najdeno
        self.assertEqual(kriv, {}, "skript za imenovane strani je v nasprotju s CONTRIBUTING.md (pravilo »brez receptov«)")

    def test_registracije_ne_nosijo_seznama_strani(self):
        # Skripti, ki bi bil vezan na seznam imenovanih strani prek vzorcev URL, ni dovoljeno registrirati (razen YouTube/prijava).
        with open(os.path.join(KOREN, "safeer_mint.py"), encoding="utf-8") as f:
            koda = f.read()
        self.assertNotIn("HOOKSHOT", koda)
        with open(os.path.join(KOREN, "windows", "safeer_windows", "policy.py"), encoding="utf-8") as f:
            self.assertNotIn("HOOKSHOT", f.read())
        self.assertNotRegex(koda, r'for site in \(\s*"pushsquare')

    def test_izjeme_so_samo_youtube(self):
        self.assertTrue(all(i.startswith("YOUTUBE_") for i in IZJEME))


if __name__ == "__main__":
    unittest.main()
