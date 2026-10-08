import unittest

from core import adblock


class ProtiZaznavanjuBlokatorjaTests(unittest.TestCase):
    def test_skripta_je_del_zascite_in_splosna(self):
        s = adblock.ADGUARD_PROTECTION_SCRIPT
        self.assertIn("__safeerProtiAdblock", s)
        for ime in ("canRunAds", "getBoundingClientRect", "getComputedStyle", "XMLHttpRequest", "fetch"):
            self.assertIn(ime, s)

    def test_praznega_vabnega_elementa_ne_brise(self):
        self.assertIn("textContent || '').trim()) continue", adblock.GENERIC_COSMETIC_SCRIPT)


if __name__ == "__main__":
    unittest.main()
