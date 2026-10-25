"""Popravki po neodvisnem pregledu teme in namizja Windows (25. 10. 2026)."""
import http.client
import re
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage

from safeer_windows import browser, os_app, policy, tema, webview2_media

KOREN = Path(__file__).resolve().parents[2]
SW = KOREN / "windows" / "safeer_windows"
KLIK = QWebEnginePage.NavigationType.NavigationTypeLinkClicked


class _Naprej(Exception):
    """Navigacija je sla mimo veje DRM (naprej v obicajno preverjanje)."""


class _Okno:
    """Le toliko BrowserWindow, kolikor ga potrebuje veja DRM v accept_navigation."""

    def __init__(self, drm, mozen):
        self._je_drm = lambda url: drm
        self._mozen = mozen
        self.odprto = []
        self._drm_mozen = types.MethodType(lambda s, url: s._mozen, self)
        self._drm_obidi_zdaj = types.MethodType(browser.BrowserWindow._drm_obidi_zdaj, self)
        self.odpri_drm = lambda url: self.odprto.append(url) or False

    def __getattr__(self, ime):
        if ime.startswith("_drm"):
            raise AttributeError(ime)
        raise _Naprej(ime)


class DrmNavigacija(unittest.TestCase):
    def _navigiraj(self, okno, url):
        with mock.patch.object(browser.QTimer, "singleShot") as casovnik:
            try:
                izid = browser.BrowserWindow.accept_navigation(okno, None, QUrl(url), KLIK, True)
            except _Naprej:
                return "naprej", casovnik
        return izid, casovnik

    def test_https_naslov(self):
        self.assertEqual(webview2_media.https_naslov("http://www.netflix.com/si/"), "https://www.netflix.com/si/")
        self.assertEqual(webview2_media.https_naslov("https://a.si"), "https://a.si")
        self.assertEqual(webview2_media.https_naslov("ftp://a.si"), "")

    def test_brez_predvajalnika_se_stran_nalozi(self):
        # Prej: navigacija zavrnjena, predvajalnik se ni odprl -> prazen zavihek.
        izid, casovnik = self._navigiraj(_Okno(drm=True, mozen=False), "http://www.netflix.com/")
        self.assertEqual(izid, "naprej")
        casovnik.assert_not_called()

    def test_s_predvajalnikom_v_drm(self):
        izid, casovnik = self._navigiraj(_Okno(drm=True, mozen=True), "https://www.netflix.com/")
        self.assertIs(izid, False)
        casovnik.assert_called_once()

    def test_po_neuspehu_ena_navigacija_v_zavihek(self):
        okno = _Okno(drm=True, mozen=True)
        okno.__dict__["_drm_obidi"] = ("www.netflix.com", time.monotonic())
        self.assertEqual(self._navigiraj(okno, "https://www.netflix.com/")[0], "naprej")
        self.assertIs(self._navigiraj(okno, "https://www.netflix.com/")[0], False)     # le enkrat

    def test_mozen_preveri_https_in_predvajalnik(self):
        okno = types.SimpleNamespace()
        mozen = types.MethodType(browser.BrowserWindow._drm_mozen, okno)
        with mock.patch.object(webview2_media, "predvajalnik_na_voljo", return_value=True):
            self.assertTrue(mozen("http://www.netflix.com/"))       # http se prepise v https
            self.assertFalse(mozen("ftp://www.netflix.com/"))
        with mock.patch.object(webview2_media, "predvajalnik_na_voljo", return_value=False):
            self.assertFalse(mozen("https://www.netflix.com/"))


class StreznikVmesnika(unittest.TestCase):
    def _get(self, port, pot, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.putrequest("GET", pot, skip_host=True)
            c.putheader("Host", host or "127.0.0.1:%d" % port)
            c.endheaders()
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def test_tuj_host_zavrnjen(self):
        port = os_app._start_local_asset_server(str(KOREN / "assets"))
        self.assertEqual(self._get(port, "/os/index.html")[0], 200)
        self.assertEqual(self._get(port, "/os/index.html", "localhost:%d" % port)[0], 200)
        self.assertEqual(self._get(port, "/os/index.html", "zlobna.si:%d" % port)[0], 403)     # DNS rebinding
        self.assertEqual(self._get(port, "/os/index.html", "127.0.0.1:1")[0], 403)

    def test_ozadje_glave(self):
        port = os_app._start_local_asset_server(str(KOREN / "assets"))
        with mock.patch.object(os_app, "_ozadje_za_splet", return_value=("image/png", b"\x89PNG\r\n\x1a\n" + b"\0" * 16)):
            status, glave, _ = self._get(port, "/ozadje-namizja")
            self.assertEqual(self._get(port, "/ozadje-namizja", "zlobna.si:%d" % port)[0], 403)
        self.assertEqual(status, 200)
        self.assertEqual(glave.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(glave.get("X-Content-Type-Options"), "nosniff")

    def test_sosednja_mapa_ni_dostopna(self):
        src = (SW / "os_app.py").read_text(encoding="utf-8")
        self.assertIn("resolved.is_relative_to(base_resolved)", src)
        self.assertNotIn("str(resolved).startswith(str(base_resolved))", src)


class ShemaSafeer(unittest.TestCase):
    def test_ozadje_in_tema_samo_za_nas_izvor(self):
        self.assertTrue(policy.scheme_izvor_dovoljen("/ozadje", "safeer"))
        self.assertTrue(policy.scheme_izvor_dovoljen("/tema.css", "safeer"))
        self.assertFalse(policy.scheme_izvor_dovoljen("/ozadje", "https"))
        self.assertFalse(policy.scheme_izvor_dovoljen("/tema.css", ""))
        self.assertTrue(policy.scheme_izvor_dovoljen("/", ""))               # domaca stran (naslovna vrstica)
        self.assertTrue(policy.scheme_izvor_dovoljen("/blocked", "https"))

    def test_rocaj_preveri_pobudnika(self):
        src = (SW / "browser.py").read_text(encoding="utf-8")
        self.assertIn("policy.scheme_izvor_dovoljen(url.path(), job.initiator().scheme())", src)


class SafeerDrmMainJs(unittest.TestCase):
    JS = (KOREN / "windows" / "safeer_drm" / "main.js").read_text(encoding="utf-8")

    def test_zaprte_koncnice_se_ne_razresijo(self):
        pravila = re.search(r"host-resolver-rules', '([^']*)'", self.JS).group(1)
        self.assertNotIn("127.0.0.1", pravila)
        self.assertEqual(pravila.count("~NOTFOUND"), 5)

    def test_preusmeritev_ostane_na_domeni(self):
        self.assertIn("wc.on('will-redirect'", self.JS)
        self.assertRegex(self.JS, r"will-redirect[\s\S]{0,600}izvenDomene\(naslov\)")


class Glasnost(unittest.TestCase):
    def test_com_se_sprosti(self):
        src = (SW / "glasnost_win.py").read_text(encoding="utf-8")
        self.assertIn("ole.CoUninitialize()", src)
        self.assertIn("in (0, 1)", src)


class VidezOkna(unittest.TestCase):
    def test_tema_in_ozadje_v_glavno_okno(self):
        src = (SW / "os_app.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"def uporabi_temo[\s\S]{0,1200}poslji_dogodek\(\"videz\"")
        js = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        self.assertIn('vrsta === "videz"', js)

    def test_ok_in_fokus_po_temah(self):
        css = (KOREN / "assets" / "os" / "os.css").read_text(encoding="utf-8")
        with mock.patch.object(tema, "_os_css", return_value=css):
            tema._predpomnilnik.clear()
            try:
                safeer, dracula = tema.paleta("safeer"), tema.paleta("dracula")
            finally:
                tema._predpomnilnik.clear()
        self.assertEqual(safeer["fokus"], "#9dceff")
        self.assertEqual(dracula["fokus"], "#bd93f9")
        self.assertEqual(dracula["ok"], "#50fa7b")
        for ime in ("catppuccin", "tokyonight", "gruvbox", "nord", "dracula"):
            blok = re.search(r':root\[data-tema="%s"\] \{([^}]*)\}' % ime, css).group(1)
            self.assertIn("--fokus:", blok)
            self.assertIn("--ok:", blok)


class ZapiranjeZNamizjem(unittest.TestCase):
    def _okno(self):
        o = types.SimpleNamespace(namizje=object(), skrito=0, koncano=[])
        o.webview2_media = types.SimpleNamespace(stop=lambda: None)
        o.hide = lambda: setattr(o, "skrito", o.skrito + 1)
        o.media_player = types.SimpleNamespace()
        o.control_backend = types.SimpleNamespace(koncaj=lambda: o.koncano.append("link"))
        o._ustavi_torrente = lambda: o.koncano.append("torrenti")
        o.sporocila = types.SimpleNamespace(zapri=lambda: o.koncano.append("sporocila"))
        o.scit = types.SimpleNamespace(koncaj=lambda: o.koncano.append("scit"))
        o.browser_app = types.SimpleNamespace(shutdown=lambda: o.koncano.append("splet"))
        o._pocisti = types.MethodType(os_app.SafeerOsWindow._pocisti, o)
        return o

    def test_obicajno_zapiranje_le_skrije(self):
        o = self._okno()
        os_app.SafeerOsWindow.closeEvent(o, mock.Mock())
        self.assertEqual((o.skrito, o.koncano), (1, []))

    def test_odjava_windows_zapre_vse_enkrat(self):
        o = self._okno()
        os_app.SafeerOsWindow._ob_koncu_seje(o, None)            # commitDataRequest
        dogodek = mock.Mock()
        os_app.SafeerOsWindow.closeEvent(o, dogodek)
        dogodek.accept.assert_called_once()
        self.assertEqual(o.koncano, ["link", "torrenti", "sporocila", "scit", "splet"])
        o._pocisti()                                             # aboutToQuit za tem: nic dvakrat
        self.assertEqual(len(o.koncano), 5)

    def test_signala_povezana(self):
        src = (SW / "os_app.py").read_text(encoding="utf-8")
        self.assertIn("commitDataRequest.connect(self._ob_koncu_seje)", src)
        self.assertIn("aboutToQuit.connect(self._pocisti)", src)


if __name__ == "__main__":
    unittest.main()
