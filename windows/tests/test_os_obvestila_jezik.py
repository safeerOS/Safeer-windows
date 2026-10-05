"""Obvestila Safeer OS za Windows so v jeziku vmesnika.

Do 1.0.39 je assets/os/os.js devet obvestil sestavljal iz slovenskih nizov (prejeta in poslana datoteka, zaslon z
druge naprave, predvajanje na drugi napravi, zascitena vsebina v zunanjem brskalniku ...): uporabnik z angleskim ali
nemskim vmesnikom jih je dobil v slovenscini. Zdaj so v assets/os/besedila.js v vseh sestih jezikih.
"""
import json
import re
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
OS_JS = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8").replace("\r\n", "\n")
BESEDILA_JS = (KOREN / "assets" / "os" / "besedila.js").read_text(encoding="utf-8").replace("\r\n", "\n")

JEZIKI = ("sl", "en", "de", "es", "fr", "it")
KLJUCI = ("odpiraSeZunaj", "posiljamNa", "niPoslanoNa", "niNapraveZaDatoteke", "programaNiVec", "zaslonKoncalaNaprava",
          "zaslonSeOdpira", "prejetoZNaprave", "prevzemNiUspel", "datotekaPoslana", "posiljanjeNiUspelo", "predvajaSeNa")
#: Imena izdelkov so v vseh jezikih enaka in smejo stati v kodi.
IMENA_IZDELKOV = {"Safeer Control", "Safeer OS", "Safeer Link", "Safeer Browser"}
NIZ = re.compile(r'"((?:[^"\\]|\\.)*)"')
STAVEK = re.compile(r"[A-Za-zČŠŽčšž]{2,} [A-Za-zČŠŽčšž]{2,}")


def _bloki():
    """Besedila iz vrstic `Object.assign(BESEDILA_OS.<jezik>, {json});`, ki nosijo nove kljuce."""
    najdeno = {}
    for jezik, telo in re.findall(r"^Object\.assign\(BESEDILA_OS\.([a-z]{2}), (\{.*\})\);$", BESEDILA_JS, re.M):
        if '"zaslonSeOdpira"' in telo:
            najdeno[jezik] = json.loads(telo)
    return najdeno


class Obvestila(unittest.TestCase):
    def test_obvestila_niso_sestavljena_iz_nizov_v_enem_jeziku(self):
        sumljivi = []
        for stevilka, vrstica in enumerate(OS_JS.split("\n"), 1):
            if "obvesti(" not in vrstica or "function obvesti" in vrstica:
                continue
            for niz in NIZ.findall(vrstica):
                if STAVEK.search(niz) and niz not in IMENA_IZDELKOV:
                    sumljivi.append((stevilka, niz))
        self.assertEqual(sumljivi, [], "besedilo obvestila sodi v besedila.js (t(kljuc)), ne v os.js")
        self.assertNotIn('obvesti("', OS_JS, "obvestilo z golim nizom")

    def test_nova_besedila_so_v_vseh_sestih_jezikih(self):
        bloki = _bloki()
        self.assertEqual(sorted(bloki), sorted(JEZIKI))
        for jezik in JEZIKI:
            self.assertEqual(sorted(bloki[jezik]), sorted(KLJUCI), jezik)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in bloki[jezik].values()), jezik)

    def test_prevodi_imajo_ista_mesta_za_vrednosti(self):
        bloki = _bloki()
        for kljuc in KLJUCI:
            mesta = sorted(re.findall(r"\{[a-z]+\}", bloki["sl"][kljuc]))
            for jezik in JEZIKI:
                self.assertEqual(sorted(re.findall(r"\{[a-z]+\}", bloki[jezik][kljuc])), mesta, (kljuc, jezik))

    def test_prevodi_niso_prepisana_slovenscina(self):
        bloki = _bloki()
        for kljuc in KLJUCI:
            for jezik in JEZIKI[1:]:
                self.assertNotEqual(bloki[jezik][kljuc], bloki["sl"][kljuc], (kljuc, jezik))

    def test_stran_uporablja_vse_kljuce_z_vrednostmi_ki_jih_besedilo_pricakuje(self):
        bloki = _bloki()
        for kljuc in KLJUCI:
            self.assertIn('"%s"' % kljuc, OS_JS, kljuc)
        # Mesta v besedilu morajo dobiti vrednost: klic t("kljuc", { ime: ..., naprava: ... }).
        for kljuc, mesta in (("posiljamNa", ("ime", "naprava")), ("prejetoZNaprave", ("od", "ime")),
                             ("prevzemNiUspel", ("ime", "napaka")), ("predvajaSeNa", ("naslov", "naprava")),
                             ("odpiraSeZunaj", ("ime", "brskalnik")), ("niPoslanoNa", ("naprava",)),
                             ("datotekaPoslana", ("ime",))):
            klic = re.search(r't\("%s", \{([^}]*)\}' % kljuc, OS_JS)
            self.assertIsNotNone(klic, kljuc)
            for mesto in mesta:
                self.assertIn(mesto + ":", klic.group(1), (kljuc, mesto))
                self.assertIn("{%s}" % mesto, bloki["sl"][kljuc], (kljuc, mesto))


if __name__ == "__main__":
    unittest.main()
