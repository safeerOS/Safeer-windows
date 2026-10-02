"""Splet na WebView2 (Windows): pravila navigacije, vmesnik pogledov in gostitelj (brez WebView2 - samo logika)."""
import os
import sys
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.dirname(KOREN))

try:
    from safeer_windows import policy, splet_webview2
    IMA_QT = True
except Exception:  # PySide6 ni namescen (preizkus na racunalniku brez Qt)
    IMA_QT = False


def _vir(ime: str) -> str:
    with open(os.path.join(KOREN, ime), encoding="utf-8") as f:
        return f.read()


class GostiteljVir(unittest.TestCase):
    """Preverbe izvorne kode gostitelja in povezave z oknom (delujejo tudi brez Qt)."""

    def test_gostitelj_ima_kljucne_dele(self):
        cs = _vir("webview2_host/SpletHost.cs")
        # zacetna stran safeer:// kot registrirana shema, scit prek vprasanja Pythonu, novo okno kot zavihek
        self.assertIn('CoreWebView2CustomSchemeRegistration("safeer")', cs)
        self.assertIn('ev = "request"', cs)
        self.assertIn('ev = "newwindow"', cs)
        self.assertIn("p.Args.NewWindow = core", cs)
        self.assertIn("IsInPrivateModeEnabled", cs)
        # brez odgovora v roku zahteva stece naprej (stran ne obvisi)
        self.assertIn("AskAsync(ask, new { ev = \"request\"", cs)
        self.assertIn("Task.Delay(timeoutMs)", cs)
        # ob koncu stdin (Python se je zaprl) se gostitelj ugasne - brez osirotelih procesov
        self.assertIn("Application.Exit", cs)

    def test_isti_dpi_nacin_kot_qt(self):
        # Brez tega drugi zavihek odpove (0x8007139F): okno gostitelja je otrok okna Qt (PerMonitorV2).
        self.assertIn("<ApplicationHighDpiMode>PerMonitorV2</ApplicationHighDpiMode>", _vir("webview2_host/SafeerMediaWebView.csproj"))

    def test_program_ima_nacin_splet(self):
        self.assertIn('args.Contains("--splet")', _vir("webview2_host/Program.cs"))

    def test_okno_uporablja_oba_pogona(self):
        b = _vir("safeer_windows/browser.py")
        self.assertIn("POGLEDI = (QWebEngineView, splet_webview2.WvView)", b)
        self.assertIn("def wv_gostitelj(self, zasebno: bool)", b)
        self.assertIn("def fokus_v_lupino", b)        # tipkovnica nazaj v lupino ob kliku v naslovno vrstico
        self.assertNotIn("isinstance(view, QWebEngineView)", b)


@unittest.skipUnless(IMA_QT, "PySide6 ni na voljo")
class Navigacija(unittest.TestCase):
    def test_navadna_stran_gre_naprej(self):
        self.assertEqual(splet_webview2.odlocitev_navigacije("https://365.rtvslo.si/arhiv/tuji-filmi/1", True, False, True, True), (True, None))

    def test_oglasna_stran_se_ne_odpre(self):
        dovoli, dejanje = splet_webview2.odlocitev_navigacije("https://doubleclick.net/", True, False, True, True)
        self.assertFalse(dovoli)
        self.assertEqual(dejanje[0], "ad")
        # z izklopljenim scitom se odpre
        self.assertTrue(splet_webview2.odlocitev_navigacije("https://doubleclick.net/", True, False, False, True)[0])

    def test_sledilni_parametri_se_odstranijo_samo_ob_kliku(self):
        url = "https://primer.si/clanek?utm_source=x&id=5"
        ociscen = policy.adblock.strip_tracking_parameters(url)
        if ociscen == url:
            self.skipTest("pravila ne odstranijo utm_source")
        dovoli, dejanje = splet_webview2.odlocitev_navigacije(url, True, False, True, True)
        self.assertFalse(dovoli)
        self.assertEqual(dejanje[:2], ("load", ociscen))
        # preusmeritev ali navigacija iz skripte: brez posega; izklopljena zascita: brez posega
        self.assertTrue(splet_webview2.odlocitev_navigacije(url, True, True, True, True)[0])
        self.assertTrue(splet_webview2.odlocitev_navigacije(url, False, False, True, True)[0])
        self.assertTrue(splet_webview2.odlocitev_navigacije(url, True, False, True, False)[0])

    def test_vmesnik_pogleda_kot_qt(self):
        for ime in ("page", "url", "title", "load", "setUrl", "reload", "stop", "back", "forward", "history",
                    "zoomFactor", "setZoomFactor", "titleChanged", "urlChanged", "loadStarted", "loadFinished", "iconChanged"):
            self.assertTrue(hasattr(splet_webview2.WvView, ime), ime)
        for ime in ("url", "load", "runJavaScript", "findText", "triggerAction", "lifecycleState", "recommendedState",
                    "setLifecycleState", "settings", "devToolsPage", "setDevToolsPage", "fullScreenRequested",
                    "windowCloseRequested", "renderProcessTerminated", "linkHovered"):
            self.assertTrue(hasattr(splet_webview2.WvPage, ime), ime)

    def test_brez_windows_ni_na_voljo(self):
        if sys.platform != "win32":
            self.assertFalse(splet_webview2.na_voljo())
            self.assertEqual(splet_webview2.runtime_razlicica(), "")


if __name__ == "__main__":
    unittest.main()
