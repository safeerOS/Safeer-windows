"""Pripeti odtis potrdila Huba: primerjava s hmac.compare_digest po elementih (revizija 4. 11. 2026, prej `in set`)."""
import hashlib
import unittest
from unittest import mock

from safeer_windows import browser

ODTIS = hashlib.sha256(b"potrdilo-huba").hexdigest()


class _Potrdilo:
    def toDer(self):
        return b"potrdilo-huba"


class _Napaka:
    def __init__(self, der=b"potrdilo-huba"):
        self.der = der
        self.sprejeto = self.zavrnjeno = False

    def certificateChain(self):
        p = _Potrdilo()
        p.toDer = lambda: self.der
        return [p]

    def acceptCertificate(self):
        self.sprejeto = True

    def rejectCertificate(self):
        self.zavrnjeno = True


class OdtisHuba(unittest.TestCase):
    def setUp(self):
        self._prej = set(browser.ZAUPANA_POTRDILA)
        browser.ZAUPANA_POTRDILA.clear()
        browser.ZAUPANA_POTRDILA.update({"0" * 64, ODTIS})

    def tearDown(self):
        browser.ZAUPANA_POTRDILA.clear()
        browser.ZAUPANA_POTRDILA.update(self._prej)

    def test_primerjava_s_compare_digest(self):
        with mock.patch.object(browser.hmac, "compare_digest", wraps=browser.hmac.compare_digest) as primerjava:
            napaka = _Napaka()
            browser.SafeerPage._potrdilo_huba(napaka)
        self.assertTrue(napaka.sprejeto)
        self.assertGreaterEqual(primerjava.call_count, 2, "vsak pripeti odtis s compare_digest")

    def test_tuj_odtis_zavrnjen(self):
        napaka = _Napaka(b"drugo-potrdilo")
        browser.SafeerPage._potrdilo_huba(napaka)
        self.assertTrue(napaka.zavrnjeno)
        self.assertFalse(napaka.sprejeto)

    def test_odtis_zaupan(self):
        self.assertTrue(browser.odtis_zaupan(ODTIS))
        self.assertTrue(browser.odtis_zaupan(ODTIS.upper()))
        for slab in ("", None, ODTIS[:-1], ODTIS + "0", "x" * 64):
            with self.subTest(slab=slab):
                self.assertFalse(browser.odtis_zaupan(slab))


if __name__ == "__main__":
    unittest.main()
