"""Hladni zagon: prvi zunanji naslov pocaka na podpisani seznam grozenj.

Revizija 4. 11. 2026: okno je naslov iz argv/drugega zagona odprlo takoj, podpisani seznam (core/threat_intel) pa se
nalaga v svoji niti ~1-2 s (Safeer OS ga zamakne se za 3 s) - request_decision je prvo stran preveril s praznim virom.
Zdaj naslov pocaka na vir.loaded, najvec policy.ROK_VIRA_GROZENJ, brez cakanja v glavni niti (QTimer).
"""
import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QObject

from safeer_windows import browser, policy


class _Vir:
    def __init__(self, nalozen=False):
        self.enabled = True
        self._thread = object()
        self.loaded = threading.Event()
        if nalozen:
            self.loaded.set()


class _App(QObject):
    po_viru_grozenj = getattr(browser.SafeerBrowserApp, "po_viru_grozenj", None)

    def __init__(self, vir):
        super().__init__()
        self.threat_intel = vir


def _vrti(pogoj, rok):
    konec = time.monotonic() + rok
    while not pogoj() and time.monotonic() < konec:
        QCoreApplication.processEvents()
        time.sleep(0.01)


class VirGrozenjObZagonu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QCoreApplication.instance() or QCoreApplication([])

    def test_pripravljenost(self):
        self.assertTrue(policy.vir_grozenj_pripravljen(None))
        self.assertTrue(policy.vir_grozenj_pripravljen(_Vir(nalozen=True)))
        self.assertFalse(policy.vir_grozenj_pripravljen(_Vir()))
        nezagnan = _Vir()
        nezagnan._thread = None   # smoke ali izklopljen vir: ni na kaj cakati
        self.assertTrue(policy.vir_grozenj_pripravljen(nezagnan))

    def test_naslov_pocaka_na_vir(self):
        vir = _Vir()
        app = _App(vir)
        klici = []
        zacetek = time.monotonic()
        app.po_viru_grozenj(lambda: klici.append(time.monotonic() - zacetek))
        self.assertEqual(klici, [], "naslov se ne sme odpreti pred nalozenim virom")
        threading.Timer(0.3, vir.loaded.set).start()
        _vrti(lambda: klici, 3)
        self.assertEqual(len(klici), 1)
        self.assertGreaterEqual(klici[0], 0.25)
        self.assertLess(klici[0], 1.5)

    def test_po_roku_se_odpre_brez_vira(self):
        app = _App(_Vir())
        klici = []
        with mock.patch.object(policy, "ROK_VIRA_GROZENJ", 0.3):
            app.po_viru_grozenj(lambda: klici.append(1))
            self.assertEqual(klici, [])
            _vrti(lambda: klici, 3)
        self.assertEqual(klici, [1])

    def test_nalozen_vir_takoj(self):
        app = _App(_Vir(nalozen=True))
        klici = []
        app.po_viru_grozenj(lambda: klici.append(1))
        self.assertEqual(klici, [1])

    def _okno(self):
        okno = mock.Mock()
        zavihki = ["cakalni"]
        okno.tabs.count.side_effect = lambda: len(zavihki)
        okno.tabs.indexOf.side_effect = lambda v: zavihki.index(v) if v in zavihki else -1
        okno.close_tab.side_effect = lambda i: zavihki.pop(i)
        okno.open_input.side_effect = lambda url, **k: zavihki.append(url) if url.startswith("https://") else None
        okno.new_tab.side_effect = lambda url=None: zavihki.append(url)
        return okno, zavihki

    def test_cakalni_zavihek_se_zapre_ko_se_odpre_naslov(self):
        okno, zavihki = self._okno()
        cakalni = mock.Mock()
        zavihki[0] = cakalni
        app = mock.Mock(windows=[okno])
        browser.SafeerBrowserApp._odpri_zunanje(app, okno, ["https://example.com/"], cakalni)
        okno.open_input.assert_called_once_with("https://example.com/", new_tab=True, zunanji=True)
        self.assertEqual(zavihki, ["https://example.com/"])

    def test_cakalni_zavihek_dobi_zacetno_stran_ce_ni_nic_odprto(self):
        okno, zavihki = self._okno()
        cakalni = mock.Mock()
        zavihki[0] = cakalni
        app = mock.Mock(windows=[okno])
        browser.SafeerBrowserApp._odpri_zunanje(app, okno, [r"\\\\streznik\\x"], cakalni)
        self.assertEqual(zavihki, [cakalni])
        self.assertEqual(cakalni.load.call_args[0][0].toString(), policy.HOME_URL)

    def test_argv_in_drugi_zagon_gresta_skozi_vir(self):
        import inspect
        self.assertIn("po_viru_grozenj", inspect.getsource(browser.SafeerBrowserApp.new_window))
        self.assertIn("po_viru_grozenj", inspect.getsource(browser.SafeerBrowserApp.on_instance_data))
        self.assertIn("zunanji=True", inspect.getsource(browser.SafeerBrowserApp._odpri_zunanje))


if __name__ == "__main__":
    unittest.main()
