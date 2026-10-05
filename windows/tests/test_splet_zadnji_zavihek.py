"""Odsek Splet v Safeer OS za Windows: zapiranje zadnjega zavihka.

Izmerjeno 5. 10. 2026 na testnem Windows (1.0.39): po zaprtju zadnjega zavihka je Splet ostal prazen - brez zavihka,
z naslovom zaprte strani v naslovni vrstici; pomagal je sele gumb »+«. Zadnji zavihek zdaj zamenja zacetna stran.
Samostojno okno brskalnika se ob zadnjem zavihku zapre kot prej.
"""
import types
import unittest
from unittest import mock

from safeer_windows import browser


class _Pogled:
    def __init__(self, naslov):
        self._naslov = naslov
        self.izbrisan = False

    def url(self):
        return types.SimpleNamespace(toString=lambda: self._naslov)

    def page(self):
        return mock.Mock()

    def deleteLater(self):
        self.izbrisan = True


class _Zavihki:
    def __init__(self, pogledi):
        self.pogledi = list(pogledi)

    def widget(self, i):
        return self.pogledi[i] if 0 <= i < len(self.pogledi) else None

    def removeTab(self, i):
        del self.pogledi[i]

    def count(self):
        return len(self.pogledi)


class ZadnjiZavihekSpleta(unittest.TestCase):
    def _okno(self, pogledi, embedded=True, splet=True):
        return types.SimpleNamespace(tabs=_Zavihki(pogledi), private=False, devtools=None, embedded=embedded,
                                     safeer_os_web_mode=splet, app=types.SimpleNamespace(closed_tabs=[]),
                                     new_tab=mock.Mock(), close=mock.Mock())

    def _zapri(self, okno, indeks=0):
        with mock.patch.object(browser, "POGLEDI", (_Pogled,)):
            browser.BrowserWindow.close_tab(okno, indeks)

    def test_v_odseku_splet_zadnji_zavihek_zamenja_zacetna_stran(self):
        pogled = _Pogled("https://example.org/")
        okno = self._okno([pogled])
        self._zapri(okno)
        okno.new_tab.assert_called_once_with()
        okno.close.assert_not_called()
        self.assertTrue(pogled.izbrisan)
        self.assertEqual(okno.app.closed_tabs, ["https://example.org/"])

    def test_ni_zadnji_zavihek(self):
        okno = self._okno([_Pogled("https://a.example/"), _Pogled("https://b.example/")])
        self._zapri(okno, 1)
        okno.new_tab.assert_not_called()
        okno.close.assert_not_called()
        self.assertEqual(okno.tabs.count(), 1)

    def test_samostojno_okno_in_predvajalnik_se_zapreta_kot_prej(self):
        for embedded, splet in ((False, False), (True, False)):
            okno = self._okno([_Pogled("https://example.org/")], embedded=embedded, splet=splet)
            self._zapri(okno)
            okno.close.assert_called_once_with()
            okno.new_tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
