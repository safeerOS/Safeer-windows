"""21. 11. 2026: Safeer OS se zazene ob prijavi, se preden je zbirka skrivnosti odklenjena. Neuspelo branje kljuca se je
shranilo kot »kljuca ni« do konca seje - Medijski center je kazal »Dodaj debrid«, ceprav je kljuc shranjen."""
import unittest
from unittest import mock

from core import debrid, debrid_pravila as P

KLJUC_TB = "7c1e9a4b-2f6d-4e8a-b3c5-9d0f1a2e6b74"


class ZbirkaZaklenjena(unittest.TestCase):
    def test_kljuc_se_prebere_ko_se_zbirka_odklene(self):
        zaklenjena = [True]
        klici = []

        def desifriraj(s):
            klici.append(s)
            if zaklenjena[0]:
                raise RuntimeError("zbirka je zaklenjena")
            return s[4:][::-1]

        shramba = {"d": {"kljuci": {P.TORBOX: "enc:" + KLJUC_TB[::-1]}}}
        d = debrid.Debrid(lambda: shramba["d"], lambda x: shramba.__setitem__("d", x), lambda s: "enc:" + s[::-1], desifriraj)
        ura = [1000.0]
        with mock.patch.object(debrid.time, "monotonic", side_effect=lambda: ura[0]):
            self.assertIsNone(d.kljuc(P.TORBOX))               # zaklenjeno: kot da kljuca ni
            self.assertEqual(d.z_kljucem(), [])
            self.assertEqual(len(klici), 1)                     # slepi pregled 22. 11.: en poziv za odklep, ne ob vsakem klicu
            zaklenjena[0] = False
            ura[0] += d.PONOVNO_PO_S + 1
            self.assertEqual(d.kljuc(P.TORBOX), KLJUC_TB)       # brez ponovnega zagona
            self.assertEqual(d.z_kljucem(), [P.TORBOX])
            n = len(klici)
            self.assertEqual(d.kljuc(P.TORBOX), KLJUC_TB)
            self.assertEqual(len(klici), n)                     # uspeh ostane v predpomnilniku


if __name__ == "__main__":
    unittest.main()
