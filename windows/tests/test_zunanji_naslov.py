"""Naslov od zunaj (argv, drugi zagon prek QLocalServer) ne sme odpreti SMB.

Revizija 4. 11. 2026: resolve_input je sprejel \\\\streznik\\deljeno in file://streznik/... - povezava iz druge
aplikacije (Safeer kot privzeti brskalnik) bi Windows poslala na SMB in razkrila NTLM uporabnika. Od zunaj zdaj velja
samo http(s), naslov/iskanje in krajevna pot na pogonu s crko; vpis v naslovno vrstico ostane kot prej.
"""
import types
import unittest
from unittest import mock

from safeer_windows import browser, policy

ZAVRNJENI = (
    r"\\streznik\deljeno\a.html",
    "//streznik/deljeno",
    r"/\streznik\deljeno",
    r"\\?\UNC\streznik\deljeno",
    "file://streznik/deljeno/a.html",
    "FILE://streznik/a",
    "file:////streznik/deljeno",
    "file:///%5C%5Cstreznik%5Cdeljeno",
    "file:///etc/passwd",
    "  \\\\streznik\\x  ",
)


class ZunanjiNaslov(unittest.TestCase):
    def test_unc_in_file_gostitelj_zavrnjena(self):
        for besedilo in ZAVRNJENI:
            with self.subTest(besedilo=besedilo):
                self.assertEqual(policy.resolve_external_input(besedilo), ("denied", ""))

    def test_dovoljeno_od_zunaj(self):
        primeri = {
            "https://example.com/": ("url", "https://example.com/"),
            "example.com": ("url", "https://example.com"),
            r"C:\Users\x y\a.html": ("url", "file:///C:/Users/x%20y/a.html"),
            "C:/a.html": ("url", "file:///C:/a.html"),
            "file:///C:/a.html": ("url", "file:///C:/a.html"),
            "file://localhost/C:/a%20b.html": ("url", "file:///C:/a%20b.html"),
            "about:blank": ("url", "about:blank"),
            "": ("empty", ""),
        }
        for besedilo, pricakovano in primeri.items():
            with self.subTest(besedilo=besedilo):
                self.assertEqual(policy.resolve_external_input(besedilo), pricakovano)

    def test_javascript_in_data_ostaneta_iskanje(self):
        for besedilo in ("javascript:alert(1)", "data:text/html,<b>x</b>"):
            with self.subTest(besedilo=besedilo):
                self.assertEqual(policy.resolve_external_input(besedilo)[0], "search")

    def test_naslovna_vrstica_nespremenjena(self):
        # uporabnik, ki sam vpise UNC, ga dobi kot prej
        self.assertEqual(policy.resolve_input(r"\\streznik\d\a.html")[0], "url")

    def _okno(self):
        nastavitve = types.SimpleNamespace(get=lambda k, d=None: {"search_engine": "duckduckgo",
                                                                  "tracking_protection_enabled": True}.get(k, d))
        return types.SimpleNamespace(app=types.SimpleNamespace(settings=nastavitve), odpri_drm=mock.Mock(return_value=False),
                                     new_tab=mock.Mock(), load_in_current=mock.Mock())

    def test_open_input_zunanji_ne_dotakne_poti_in_ne_odpre(self):
        okno = self._okno()
        with mock.patch.object(browser.os.path, "exists", side_effect=AssertionError("exists na UNC odpre SMB")), \
                mock.patch.object(browser.os.path, "isabs", return_value=True):
            for besedilo in ZAVRNJENI:
                browser.BrowserWindow.open_input(okno, besedilo, new_tab=True, zunanji=True)
        okno.new_tab.assert_not_called()
        okno.load_in_current.assert_not_called()

    def test_open_input_zunanji_https_odpre(self):
        okno = self._okno()
        browser.BrowserWindow.open_input(okno, "https://example.com/", new_tab=True, zunanji=True)
        okno.new_tab.assert_called_once_with("https://example.com/")

    def test_argv_in_drugi_zagon_sta_zunanja(self):
        import inspect
        src_okno = inspect.getsource(browser.SafeerBrowserApp.new_window)
        src_drugi = inspect.getsource(browser.SafeerBrowserApp.on_instance_data)
        for src in (src_okno, src_drugi):
            for vrstica in src.splitlines():
                if "open_input(" in vrstica:
                    self.assertIn("zunanji=True", vrstica)


if __name__ == "__main__":
    unittest.main()
