"""Skok na zadetek iskanja v pogovoru: mehurcek dobi razred zadetek-iskanja, ne zadetek (SAFEER-ZNANJE Z6240).

.zadetek je vrstica iskalnika v os.css (flex, velikosti slik, ozadje ob lebdenju) - na mehurcku sporocila je ta razred
pogovor razlezel. Linux ima popravek od 12. 10. 2026; Windows od 25. 10. 2026.
"""
import re
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
OS_JS = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
OS_CSS = (KOREN / "assets" / "os" / "os.css").read_text(encoding="utf-8")


class ZadetekVPogovoru(unittest.TestCase):
    def test_mehurcek_dobi_zadetek_iskanja(self):
        self.assertIn('m.classList.add("zadetek-iskanja")', OS_JS)
        self.assertNotIn('m.classList.add("zadetek")', OS_JS)

    def test_css_ne_trci_z_iskalnikom(self):
        self.assertRegex(OS_CSS, r"\.mehurcek\.zadetek-iskanja\s*\{[^}]*outline")
        self.assertIsNone(re.search(r"\.mehurcek\.zadetek\s*[{,]", OS_CSS))


if __name__ == "__main__":
    unittest.main()
