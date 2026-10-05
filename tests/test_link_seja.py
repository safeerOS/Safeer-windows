"""Zaupanje racunalniku in seja prijave (core/link_seja.py): nezaupan racunalnik se ob vsaki novi
prijavi znova poveze, zaupan samo enkrat; »brez povezave« velja do konca prijave."""
import os
import tempfile
import unittest
from unittest import mock

from core import link_seja

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Preizkus z oznako bere vmesnik Safeer Controla za Linux; v repozitoriju Safeer OS za Windows (isto jedro) ga ni.
JE_CONTROL_ZA_LINUX = os.path.isfile(os.path.join(KOREN, "core", "safeer_link.py"))
POVEZAN = {"control_token": "saf_x", "hub_fp": "f" * 64, "hub_url": "wss://h:8990/cast/ws",
           "seznanitve": {"f" * 64: {"token": "saf_x"}}}


def _beri(*deli):
    with open(os.path.join(KOREN, *deli), encoding="utf-8") as f:
        return f.read()


class Seja(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "seja prijave se bere iz /proc in logind (Linux)")
    def test_seja(self):
        with tempfile.TemporaryDirectory() as proc:
            os.makedirs(os.path.join(proc, "sys/kernel/random"))
            os.makedirs(os.path.join(proc, "self"))
            with open(os.path.join(proc, "sys/kernel/random/boot_id"), "w") as f:
                f.write("zagon-1\n")
            with open(os.path.join(proc, "self/sessionid"), "w") as f:
                f.write("7")
            logind = mock.Mock(returncode=0, stdout="c3\n")
            with mock.patch("subprocess.run", return_value=logind):
                self.assertEqual(link_seja.trenutna_seja(proc), "zagon-1:c3")
            brez = mock.Mock(returncode=1, stdout="")
            with mock.patch("subprocess.run", return_value=brez), mock.patch.dict(os.environ, {"XDG_SESSION_ID": "c2"}):
                self.assertEqual(link_seja.trenutna_seja(proc), "zagon-1:c2")
            with mock.patch("subprocess.run", return_value=brez), mock.patch.dict(os.environ, {"XDG_SESSION_ID": ""}):
                self.assertEqual(link_seja.trenutna_seja(proc), "zagon-1:7")

    def test_nezaupan_velja_do_konca_prijave(self):
        p = dict(POVEZAN)
        link_seja.po_prijavi(p, zaupaj=False, seja="A")
        self.assertTrue(link_seja.povezava_velja(p, "A"))
        self.assertFalse(link_seja.pocisti(p, "A"), "ista prijava: nic ne odpade")
        self.assertFalse(link_seja.povezava_velja(p, "B"))
        self.assertTrue(link_seja.pocisti(p, "B"))
        for kljuc in ("control_token", "hub_fp", "seznanitve", "seja_prijave"):
            self.assertNotIn(kljuc, p)
        self.assertEqual(p["hub_url"], POVEZAN["hub_url"], "naslov sredisca ostane (ni skrivnost)")
        self.assertFalse(p["zaupana"], "odlocitev ostane za naslednjo prijavo")

    def test_zaupan_samo_enkrat(self):
        p = dict(POVEZAN)
        link_seja.po_prijavi(p, zaupaj=True, seja="A")
        self.assertFalse(link_seja.pocisti(p, "B"))
        self.assertTrue(link_seja.povezava_velja(p, "B"))

    def test_stara_seznanitev_ostane_zaupana(self):
        p = dict(POVEZAN)
        self.assertTrue(link_seja.zaupana(p))
        self.assertFalse(link_seja.pocisti(p, "B"))
        self.assertTrue(link_seja.povezava_velja(p, "B"))

    def test_brez_povezave_do_konca_prijave(self):
        p = {"brez_povezave": "A"}
        self.assertTrue(link_seja.brez_v_seji(p, "A"))
        self.assertFalse(link_seja.brez_v_seji(p, "B"))
        self.assertTrue(link_seja.pocisti(p, "B"))
        self.assertNotIn("brez_povezave", p)
        p = {"brez_povezave": True}          # stari zapis: prijavno okno se pokaze znova
        self.assertTrue(link_seja.pocisti(p, "A"))

    @unittest.skipUnless(JE_CONTROL_ZA_LINUX, "vmesnik Safeer Controla za Linux")
    def test_prijavno_okno_ima_zaupanje(self):
        html = _beri("assets", "link", "index.html")
        js = _beri("assets", "link", "link.js")
        most = _beri("core", "safeer_link.py")
        self.assertIn('id="prijavaZaupaj"', html)
        self.assertIn("most.nastaviZaupanje", js)
        self.assertIn('"nastaviZaupanje"', most)
        self.assertEqual(js.count("prijavaZaupajOpis:"), 6, "vseh 6 jezikov")
        # Nezaupan racunalnik ne gre v krog zaupanja in se ne prijavlja s podpisom.
        hub = _beri("core", "link_hub.py")
        self.assertIn("s_podpisom = self.v_krog and", hub)
        self.assertIn("not s_podpisom and self.v_krog", hub)
        self.assertIn("v_krog=self._zaupana()", most)


if __name__ == "__main__":
    unittest.main()
