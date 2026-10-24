"""Namestitveni skripti obstajata v korenu (namestitev iz izvorne kode) in v mapi windows/ (paket). Kopiji se ne smeta
razlikovati: do 1.0.133 je korenska install.ps1 izpustila zeroconf (Link Mesh), ker je bil popravek vnesen samo v eno kopijo.
Kdor spremeni eno kopijo, mora enako spremeniti drugo - ta test to preveri ob vsakem teku CI."""
from pathlib import Path
import unittest

KOREN = Path(__file__).resolve().parents[2]
PARI = ("install.ps1", "uninstall.ps1", "install.bat", "uninstall.bat")


class EnakeKopije(unittest.TestCase):
    def test_korenske_in_windows_kopije_so_enake(self):
        for ime in PARI:
            koren, windows = KOREN / ime, KOREN / "windows" / ime
            self.assertTrue(koren.is_file() and windows.is_file(), f"manjka {ime} v korenu ali v windows/")
            self.assertEqual(koren.read_bytes(), windows.read_bytes(),
                             f"{ime} in windows/{ime} se razlikujeta - spremembo prenesi v obe kopiji")


if __name__ == "__main__":
    unittest.main()
