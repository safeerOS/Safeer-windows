"""Naslovna vrstica Spleta (Windows, WebView2): po kliku v spletno stran ni vec v urejanju.

Izmerjeno 5. 10. 2026 na testnem Windows (1.0.40 pred popravkom): nov zavihek (»+«) -> klik bliznjice na zacetni strani
-> stran se nalozi, naslovna vrstica ostane prazna. Fokus Windows je imelo okno Chrome_WidgetWin_1 tujega procesa
(WebView2), Qt pa je naslovno vrstico se naprej stel za fokusirano; gostiteljev »gotfocus« ob kliku z misko ni prisel.
"""
import os
import sys
import types
import unittest
from unittest import mock

from PySide6.QtCore import QUrl

from safeer_windows import browser, policy

STRAN = "https://example.org/clanek"


def _app(gostitelji=True):
    return types.SimpleNamespace(_wv_gostitelji={False: object()} if gostitelji else {})


def _windows():
    return mock.patch.object(browser, "sys", types.SimpleNamespace(platform="win32"))


class FokusVStrani(unittest.TestCase):
    def test_okno_tujega_procesa_ima_fokus(self):
        with _windows(), mock.patch.object(browser, "_okno_s_fokusom", return_value=(0x1234, os.getpid() + 1)):
            self.assertTrue(browser.SafeerBrowserApp.fokus_v_strani(_app()))

    def test_fokus_je_v_lupini(self):
        with _windows(), mock.patch.object(browser, "_okno_s_fokusom", return_value=(0x1234, os.getpid())):
            self.assertFalse(browser.SafeerBrowserApp.fokus_v_strani(_app()))

    def test_program_ni_v_ospredju(self):
        with _windows(), mock.patch.object(browser, "_okno_s_fokusom", return_value=(0, 0)):
            self.assertFalse(browser.SafeerBrowserApp.fokus_v_strani(_app()))

    def test_brez_webview2_ne_sprasujemo(self):
        with _windows(), mock.patch.object(browser, "_okno_s_fokusom") as klic:
            self.assertFalse(browser.SafeerBrowserApp.fokus_v_strani(_app(gostitelji=False)))
        klic.assert_not_called()

    def test_na_drugem_sistemu_ne_sprasujemo(self):
        with mock.patch.object(browser, "sys", types.SimpleNamespace(platform="linux")), \
                mock.patch.object(browser, "_okno_s_fokusom") as klic:
            self.assertFalse(browser.SafeerBrowserApp.fokus_v_strani(_app()))
        klic.assert_not_called()

    def test_napaka_klica_ni_usodna(self):
        with _windows(), mock.patch.object(browser, "_okno_s_fokusom", side_effect=OSError("user32")):
            self.assertFalse(browser.SafeerBrowserApp.fokus_v_strani(_app()))

    @unittest.skipUnless(sys.platform == "win32", "klic user32 obstaja samo v Windows")
    def test_klic_windows_vrne_okno_in_proces(self):
        okno, proces = browser._okno_s_fokusom()
        self.assertIsInstance(okno, int)
        self.assertIsInstance(proces, int)
        self.assertEqual(bool(okno), bool(proces))


class Okno:
    """Nadomestek okna Spleta: naslovna vrstica s fokusom Qt in stran, ki ima (ali nima) fokus Windows."""

    def __init__(self, fokus_qt, fokus_strani, naslov=STRAN):
        self.o = mock.Mock()
        self.fokus = {"qt": fokus_qt}
        self.o.address.hasFocus.side_effect = lambda: self.fokus["qt"]
        self.o.address.clearFocus.side_effect = lambda: self.fokus.update(qt=False)
        self.o.app.fokus_v_strani.return_value = fokus_strani
        self.view = mock.Mock()
        self.view.url.return_value = QUrl(naslov)
        self.o.current_view.return_value = self.view
        self.o._naslov_v_urejanju = lambda: browser.BrowserWindow._naslov_v_urejanju(self.o)
        self.o.wv_fokus_v_strani = lambda: browser.BrowserWindow.wv_fokus_v_strani(self.o)

    def sprememba_naslova(self, naslov=STRAN, view=None):
        browser.BrowserWindow.on_url_changed(self.o, view or self.view, QUrl(naslov))

    def vpisano(self):
        return [klic.args[0] for klic in self.o.address.setText.call_args_list]


class NaslovnaVrstica(unittest.TestCase):
    def test_klik_bliznjice_v_novem_zavihku_vpise_naslov(self):
        o = Okno(fokus_qt=True, fokus_strani=True)        # »+« je dal fokus vrstici, uporabnik je kliknil v stran
        o.sprememba_naslova()
        self.assertEqual(o.vpisano()[-1], policy.display_url(STRAN))
        o.o.address.clearFocus.assert_called_once_with()
        self.assertFalse(o.fokus["qt"], "vrstica ni vec v urejanju")

    def test_med_pisanjem_naslova_ne_prepisemo(self):
        o = Okno(fokus_qt=True, fokus_strani=False)       # uporabnik pise, stran se sama preusmeri
        o.sprememba_naslova("https://example.org/preusmeritev")
        self.assertEqual(o.vpisano(), [])
        o.o.address.clearFocus.assert_not_called()

    def test_brez_fokusa_se_naslov_vpise_brez_vprasanja_windows(self):
        o = Okno(fokus_qt=False, fokus_strani=False)
        o.sprememba_naslova()
        self.assertEqual(o.vpisano(), [policy.display_url(STRAN)])
        o.o.app.fokus_v_strani.assert_not_called()

    def test_zavihek_v_ozadju_vrstice_ne_spreminja(self):
        o = Okno(fokus_qt=True, fokus_strani=True)
        o.sprememba_naslova(view=mock.Mock())             # naslov je spremenil drug zavihek
        self.assertEqual(o.vpisano(), [])
        o.o.app.fokus_v_strani.assert_not_called()

    def test_urejanje(self):
        self.assertFalse(browser.BrowserWindow._naslov_v_urejanju(Okno(False, False).o))
        self.assertTrue(browser.BrowserWindow._naslov_v_urejanju(Okno(True, False).o))
        self.assertFalse(browser.BrowserWindow._naslov_v_urejanju(Okno(True, True).o))


if __name__ == "__main__":
    unittest.main()
