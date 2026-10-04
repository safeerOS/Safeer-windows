"""Most lupine Safeer OS (window.SafeerOS): skripta na strani, zeton, preverba po nalaganju, odlozisce, meni polja.

Povod (4. 10. 2026): straza pomnilnika je koncala proces strani, stran se je nalozila znova brez mostu (QtWebEngine
skript PROFILA v nov proces ne prenese) - »Isci« in vsi drugi gumbi so obnemeli do ponovnega zagona.
"""
import inspect
import io
import json
import shutil
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("PySide6")

from safeer_windows import control_window, os_app  # noqa: E402

KOREN = Path(__file__).resolve().parents[2]
ZETON = "Zeton-za-preizkus_0123456789abcd"


class LaznoOkno:
    zeton_mostu_velja = os_app.SafeerOsWindow.zeton_mostu_velja
    zavrnjen_klic_mostu = os_app.SafeerOsWindow.zavrnjen_klic_mostu
    _preveri_most = os_app.SafeerOsWindow._preveri_most
    _kopiraj = os_app.SafeerOsWindow._kopiraj
    _odlozisce_beri = os_app.SafeerOsWindow._odlozisce_beri

    def __init__(self):
        self._zeton_mostu = ZETON
        self._most_js = os_app.most_js(ZETON)
        self._zavrnjeni_klici_mostu = 0
        self.klici = []
        self.js = []
        self.page_obj = types.SimpleNamespace(runJavaScript=lambda *a: self.js.append(a))

    def obdelaj_klic(self, sporocilo):
        self.klici.append(sporocilo)

    def _na_glavni_niti(self, fn, cakaj=3.0):
        return fn()


def konzola(okno, sporocilo):
    stran = types.SimpleNamespace(window_ref=okno)
    with redirect_stdout(io.StringIO()):
        os_app.SafeerOsPage.javaScriptConsoleMessage(stran, 0, os_app.BRIDGE_PREFIX + sporocilo, 1, "")


class SkriptaMostu(unittest.TestCase):
    def test_skripta_nosi_zeton_in_se_ne_vstavi_dvakrat(self):
        js = os_app.most_js(ZETON)
        self.assertIn('zeton = "%s"' % ZETON, js)
        self.assertIn("z: zeton", js)
        self.assertIn("if (window.SafeerOS && window.SafeerOS.klic) return;", js)
        self.assertNotIn("__ZETON__", js)
        povezava = control_window.most_js(ZETON)
        self.assertIn('zeton = "%s"' % ZETON, povezava)
        self.assertIn("z: zeton", povezava)
        self.assertNotIn("__ZETON__", povezava)

    def test_zeton_mora_biti_varen_niz(self):
        for slab in ("", "kratek", 'a"; alert(1); "' + "x" * 20, "x" * 200, None):
            for modul in (os_app, control_window):
                with self.assertRaises(ValueError):
                    modul.most_js(slab)

    def test_skripta_je_na_strani_ne_na_profilu(self):
        """Skripte profila QtWebEngine po koncu procesa strani v nov proces ne prenese; skripte strani prenese."""
        for razred in (os_app.SafeerOsWindow, control_window.SafeerControlWindow):
            vir = inspect.getsource(razred.__init__)
            self.assertIn("self.page_obj.scripts().insert(script)", vir, razred.__name__)
            self.assertNotIn("self.profile.scripts()", vir, razred.__name__)
            self.assertIn("script.setRunsOnSubFrames(False)", vir, razred.__name__)

    def test_lupina_nima_privzetega_menija_qt_in_preveri_most_po_nalaganju(self):
        vir = inspect.getsource(os_app.SafeerOsWindow.__init__)
        self.assertIn("setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)", vir)
        self.assertIn("self.page_obj.loadFinished.connect(self._preveri_most)", vir)


class KlicSkoziKonzolo(unittest.TestCase):
    def test_klic_z_zetonom_se_izvede_brez_zetona_v_sporocilu(self):
        okno = LaznoOkno()
        konzola(okno, json.dumps({"id": 7, "m": "stanje", "a": [], "z": ZETON}))
        self.assertEqual(okno.klici, [{"id": 7, "m": "stanje", "a": []}])
        self.assertEqual(okno._zavrnjeni_klici_mostu, 0)

    def test_klic_brez_zetona_ali_z_napacnim_se_ne_izvede(self):
        """Izpis v konzolo lahko naredi tudi tuja stran v okvirju (vgradni predvajalnik) - zetona pa ne pozna."""
        okno = LaznoOkno()
        for slabo in ({"id": 1, "m": "napajanje", "a": ["izklop"]},
                      {"id": 2, "m": "napajanje", "a": ["izklop"], "z": "napacen-zeton-napacen-zeton"},
                      {"id": 3, "m": "napajanje", "a": ["izklop"], "z": ZETON + "x"},
                      {"id": 4, "m": "napajanje", "a": ["izklop"], "z": 5},
                      [1, 2, 3], "niz"):
            konzola(okno, json.dumps(slabo))
        self.assertEqual(okno.klici, [])
        self.assertEqual(okno._zavrnjeni_klici_mostu, 6)

    def test_control_zavrne_klic_brez_zetona(self):
        klici = []
        okno = types.SimpleNamespace(zeton_mostu=ZETON, obdelaj_klic=klici.append)
        stran = types.SimpleNamespace(window_ref=okno)
        for sporocilo in ({"m": "nastaviDovoljenje", "a": ["x", "polno"]},
                          {"m": "nastaviDovoljenje", "a": ["x", "polno"], "z": "napacen-zeton-napacen-zeton"}, [1]):
            control_window.SafeerControlPage.javaScriptConsoleMessage(
                stran, 0, control_window.BRIDGE_PREFIX + json.dumps(sporocilo), 1, "")
        self.assertEqual(klici, [])
        control_window.SafeerControlPage.javaScriptConsoleMessage(
            stran, 0, control_window.BRIDGE_PREFIX + json.dumps({"m": "poveziSe", "a": [], "z": ZETON}), 1, "")
        self.assertEqual(klici, [{"m": "poveziSe", "a": []}])


class PreverbaPoNalaganju(unittest.TestCase):
    def test_manjkajoc_most_vstavi_rocno(self):
        okno = LaznoOkno()
        with redirect_stdout(io.StringIO()) as izpis:
            okno._preveri_most(True)
            self.assertEqual(len(okno.js), 1)
            self.assertIn("window.SafeerOS", okno.js[0][0])
            okno.js[0][1](False)                       # stran javi: mostu ni
        self.assertEqual(okno.js[-1], (okno._most_js,))
        self.assertIn("vstavljam jo rocno", izpis.getvalue())

    def test_obstojecega_mostu_se_ne_dotakne(self):
        okno = LaznoOkno()
        okno._preveri_most(True)
        okno.js[0][1](True)
        self.assertEqual(len(okno.js), 1)

    def test_neuspelo_nalaganje_ne_preverja(self):
        okno = LaznoOkno()
        okno._preveri_most(False)
        self.assertEqual(okno.js, [])


class LaznoOdlozisce:
    def __init__(self, sprejme=True, besedilo=""):
        self.sprejme = sprejme
        self.besedilo = besedilo

    def setText(self, besedilo):  # noqa: N802 - ime doloca Qt
        if self.sprejme:
            self.besedilo = besedilo

    def text(self):
        return self.besedilo


class Odlozisce(unittest.TestCase):
    def _okno(self, odlozisce):
        aplikacija = types.SimpleNamespace(clipboard=lambda: odlozisce)
        return LaznoOkno(), mock.patch.object(os_app, "QApplication", aplikacija)

    def test_kopiraj_preveri_da_je_besedilo_res_v_odloziscu(self):
        odlozisce = LaznoOdlozisce()
        okno, qt = self._okno(odlozisce)
        with qt, mock.patch.object(os_app, "_odlozisce_win32_pisi") as win32:
            self.assertTrue(okno._kopiraj("defrag windows"))
        self.assertEqual(odlozisce.besedilo, "defrag windows")
        win32.assert_not_called()

    def test_ce_qt_ne_zapise_poskusi_win32_in_to_zabelezi(self):
        okno, qt = self._okno(LaznoOdlozisce(sprejme=False))
        with qt, mock.patch.object(os_app, "_odlozisce_win32_pisi", return_value=True) as win32, \
                redirect_stdout(io.StringIO()) as izpis:
            self.assertTrue(okno._kopiraj("defrag windows"))
        win32.assert_called_once_with("defrag windows")
        self.assertIn("Win32", izpis.getvalue())
        self.assertNotIn("defrag", izpis.getvalue())          # vsebine odlozisca ni v dnevniku

    def test_neuspeh_se_vrne_kot_false(self):
        okno, qt = self._okno(LaznoOdlozisce(sprejme=False))
        with qt, mock.patch.object(os_app, "_odlozisce_win32_pisi", return_value=False), redirect_stdout(io.StringIO()):
            self.assertFalse(okno._kopiraj("defrag windows"))

    def test_beri_vrne_besedilo_qt_in_ga_omeji(self):
        okno, qt = self._okno(LaznoOdlozisce(besedilo="x" * (os_app.NAJVEC_ODLOZISCE + 50)))
        with qt, mock.patch.object(os_app, "_odlozisce_win32_beri") as win32:
            izid = okno._odlozisce_beri()
        self.assertEqual(len(izid["besedilo"]), os_app.NAJVEC_ODLOZISCE)
        win32.assert_not_called()

    def test_beri_ob_praznem_qt_poskusi_win32(self):
        okno, qt = self._okno(LaznoOdlozisce())
        with qt, mock.patch.object(os_app, "_odlozisce_win32_beri", return_value="iz win32"), \
                redirect_stdout(io.StringIO()) as izpis:
            self.assertEqual(okno._odlozisce_beri(), {"besedilo": "iz win32"})
        self.assertNotIn("iz win32", izpis.getvalue())

    def test_most_pozna_branje_odlozisca(self):
        vir = inspect.getsource(os_app.SafeerOsWindow._izvedi_metodo)
        self.assertIn('metoda == "odlozisceBeri"', vir)


class SporocilaQt(unittest.TestCase):
    def test_opozorila_gredo_v_dnevnik_vsako_najvec_trikrat(self):
        from PySide6 import QtCore
        ujeto = []
        with mock.patch.object(QtCore, "qInstallMessageHandler", ujeto.append):
            os_app._QT_SPOROCILA.clear()
            os_app.qt_sporocila_v_dnevnik()
        obdelaj = ujeto[0]
        with redirect_stdout(io.StringIO()) as izpis:
            for _ in range(6):
                obdelaj(QtCore.QtMsgType.QtWarningMsg, None, "OleSetClipboard: Failed to set mime data")
            obdelaj(QtCore.QtMsgType.QtDebugMsg, None, "razhroscevanje")
            obdelaj(QtCore.QtMsgType.QtWarningMsg, types.SimpleNamespace(category="js"), "izpis strani")
        vrstice = izpis.getvalue().splitlines()
        self.assertEqual(vrstice, ["[Qt] OleSetClipboard: Failed to set mime data"] * 3)


class Vmesnik(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")

    def test_most_se_isce_sproti_in_podatki_pocakajo_nanj(self):
        self.assertIn("function imaMost()", self.js)
        self.assertIn("function koMost(delo)", self.js)
        self.assertNotIn("if (!most)", self.js.replace("if (!most) most = window.SafeerOS || null;", ""))
        self.assertNotIn("if (most)", self.js)
        self.assertNotIn("&& most)", self.js)
        self.assertIn('koMost(function () {\n    klic("zacetek")', self.js)

    def test_meni_polja_gre_skozi_most(self):
        self.assertIn('document.addEventListener("contextmenu"', self.js)
        self.assertIn('klic("odlozisceBeri")', self.js)
        self.assertIn('klic("kopiraj", [izbor.besedilo])', self.js)
        self.assertIn('document.execCommand("insertText", false, besedilo)', self.js)
        css = (KOREN / "assets" / "os" / "os.css").read_text(encoding="utf-8")
        self.assertIn(".meni-polja", css)

    @unittest.skipUnless(shutil.which("node"), "node ni namescen")
    def test_meni_in_obvestilo_sta_prevedena_v_vseh_jezikih(self):
        koda = ("const vm=require('vm'),fs=require('fs');const o={};vm.createContext(o);"
                "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),o);"
                "const b=vm.runInContext('BESEDILA_OS',o);"
                "const k=['meniIzrezi','meniKopiraj','meniPrilepi','meniIzberiVse','meniOdlozisceNapaka','meniOdloziscePrazno','brezMostu'];"
                "const manjka=[];for(const j of ['sl','en','de','es','fr','it'])for(const x of k)"
                "if(typeof b[j][x]!=='string'||!b[j][x].trim())manjka.push(j+'.'+x);"
                "console.log(JSON.stringify({manjka:manjka,sl:b.sl.meniPrilepi,en:b.en.meniPrilepi}));")
        izid = subprocess.run([shutil.which("node"), "-e", koda, str(KOREN / "assets" / "os" / "besedila.js")],
                              capture_output=True, text=True, timeout=60, check=True)
        podatki = json.loads(izid.stdout)
        self.assertEqual(podatki["manjka"], [])
        self.assertEqual((podatki["sl"], podatki["en"]), ("Prilepi", "Paste"))


class StrazaPomnilnika(unittest.TestCase):
    """Straza vmesnik nalozi znova, ko proces strani zraste cez mejo - a ne sredi uporabnikovega dela."""

    def _okno(self, mb):
        okno = types.SimpleNamespace(MEJA_IZRISA_MB=1500, MEJA_IZRISA_TRDA_MB=2600, _zadnja_obnova=-1e9, _razdelek_po_obnovi="",
                                     js=[], nalozeno=[])
        okno.page_obj = types.SimpleNamespace(renderProcessPid=lambda: 4242, runJavaScript=lambda *a: okno.js.append(a))
        okno._nalozi_znova_v_razdelku = okno.nalozeno.append
        return okno, mock.patch.object(os_app, "zasebni_pomnilnik_mb", return_value=mb)

    def _pozeni(self, mb, odgovor):
        okno, pomnilnik = self._okno(mb)
        koncani = []
        with pomnilnik, mock.patch.object(os_app, "koncaj_proces", lambda pid: koncani.append(pid) or True), \
                mock.patch.object(os_app.QTimer, "singleShot", lambda *a: None), redirect_stdout(io.StringIO()) as izpis:
            os_app.SafeerOsWindow._preveri_pomnilnik_izrisa(okno)
            if okno.js:
                okno.js[0][1](odgovor)
        return okno, koncani, izpis.getvalue()

    def test_pod_mejo_se_ne_zgodi_nic(self):
        okno, koncani, _ = self._pozeni(900, "|domov")
        self.assertEqual((okno.js, koncani), ([], []))

    def test_nad_mejo_konca_proces_in_si_zapomni_razdelek(self):
        okno, koncani, izpis = self._pozeni(1502, "|splet")
        self.assertEqual(koncani, [4242])
        self.assertEqual(okno._razdelek_po_obnovi, "splet")
        self.assertIn("nov proces strani", izpis)

    def test_sredi_dela_pocaka(self):
        for razlog in ("predvajanje", "vnos", "vprasanje"):
            okno, koncani, izpis = self._pozeni(1700, razlog + "|mediji")
            self.assertEqual(koncani, [], razlog)
            self.assertIn("odlozeno (%s)" % razlog, izpis)
            self.assertEqual(okno._zadnja_obnova, -1e9)          # naslednja preverba cez minuto poskusi znova

    def test_nad_trdo_mejo_ne_caka_vec(self):
        _, koncani, _ = self._pozeni(2700, "predvajanje|mediji")
        self.assertEqual(koncani, [4242])

    def test_stran_pove_ali_je_uporabnik_sredi_dela(self):
        js = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        self.assertIn("window.safeerOsZaseden = function ()", js)
        for razlog in ('"predvajanje"', '"vprasanje"', '"vnos"'):
            self.assertIn("return " + razlog, js)


class VrataVmesnika(unittest.TestCase):
    """Nova razlicica mora dobiti ista vrata vmesnika kot stara: izvor strani doloca shranjene nastavitve."""

    def test_poslusalca_prepozna_ne_glede_na_jezik_windows(self):
        izpis = (
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1048\n"
            "  TCP    127.0.0.1:47815        0.0.0.0:0              POSLUSANJE      11016\n"
            "  TCP    127.0.0.1:47815        127.0.0.1:50211        ESTABLISHED     11016\n"
            "  TCP    127.0.0.1:47816        0.0.0.0:0              ABHOEREN        11172\n")
        self.assertEqual(os_app._pid_poslusalca(izpis, 47815), 11016)
        self.assertEqual(os_app._pid_poslusalca(izpis, 47816), 11172)
        self.assertEqual(os_app._pid_poslusalca(izpis, 47817), 0)
        self.assertEqual(os_app._pid_poslusalca("", 47815), 0)

    def _isci(self, prosta, cakaj, stara=False):
        klici = {"koncani": [], "spanje": 0}
        ura = [0.0]

        def spi(s):
            klici["spanje"] += 1
            ura[0] += s
        os_app.PREVZEM["cakaj_s"] = cakaj
        with mock.patch.object(os_app, "_prosta_vrata", prosta), mock.patch.object(os_app, "_poslusalec_vrat", return_value=4242), \
                mock.patch.object(os_app, "_je_stara_kopija", return_value=stara), \
                mock.patch.object(os_app, "koncaj_proces", lambda pid: klici["koncani"].append(pid) or True), \
                mock.patch.object(os_app.time, "sleep", spi), mock.patch.object(os_app.time, "monotonic", lambda: ura[0]), \
                redirect_stdout(io.StringIO()):
            vrata = os_app._find_free_port()
        return vrata, klici

    def test_obicajen_zagon_ne_caka(self):
        vrata, klici = self._isci(lambda v: 0 if v == 47815 else (v or 50000), 0.0)
        self.assertEqual((vrata, klici["spanje"], klici["koncani"]), (47816, 0, []))

    def test_prevzem_pocaka_da_stara_kopija_sprosti_vrata(self):
        stanje = {"n": 0}

        def prosta(v):
            if v != 47815:
                return v or 50000
            stanje["n"] += 1
            return 47815 if stanje["n"] > 4 else 0
        vrata, klici = self._isci(prosta, 12.0)
        self.assertEqual((vrata, klici["koncani"]), (47815, []))
        self.assertGreater(klici["spanje"], 0)
        self.assertEqual(os_app.PREVZEM["cakaj_s"], 0.0)          # caka samo prvi zagon po prevzemu

    def test_prevzem_po_roku_konca_staro_kopijo(self):
        stanje = {"koncana": False}

        def prosta(v):
            if v != 47815:
                return v or 50000
            return 47815 if stanje["koncana"] else 0
        klici = {}
        ura = [0.0]
        os_app.PREVZEM["cakaj_s"] = 12.0

        def koncaj(pid):
            stanje["koncana"] = True
            klici["pid"] = pid
            return True
        with mock.patch.object(os_app, "_prosta_vrata", prosta), mock.patch.object(os_app, "_poslusalec_vrat", return_value=4242), \
                mock.patch.object(os_app, "_je_stara_kopija", return_value=True), mock.patch.object(os_app, "koncaj_proces", koncaj), \
                mock.patch.object(os_app.time, "sleep", lambda s: ura.__setitem__(0, ura[0] + s)), \
                mock.patch.object(os_app.time, "monotonic", lambda: ura[0]), redirect_stdout(io.StringIO()) as izpis:
            self.assertEqual(os_app._find_free_port(), 47815)
        self.assertEqual(klici, {"pid": 4242})
        self.assertGreaterEqual(ura[0], 12.0)
        self.assertIn("koncana", izpis.getvalue())

    def test_tujega_procesa_na_vratih_ne_konca(self):
        vrata, klici = self._isci(lambda v: 0 if v == 47815 else (v or 50000), 12.0, stara=False)
        self.assertEqual((vrata, klici["koncani"]), (47816, []))

    def test_po_zanki_qt_se_proces_zagotovo_konca(self):
        ustvarjeni = []

        class Casovnik:
            def __init__(self, cez, fn):
                self.cez, self.fn, self.daemon, self.zagnan = cez, fn, False, False
                ustvarjeni.append(self)

            def start(self):
                self.zagnan = True
        with mock.patch.object(os_app.threading, "Timer", Casovnik):
            os_app.zagotovi_izhod(3, 8.0)
        c = ustvarjeni[0]
        self.assertTrue(c.daemon and c.zagnan)
        self.assertEqual(c.cez, 8.0)
        with mock.patch.object(os_app.os, "_exit") as izhod:
            c.fn()
        izhod.assert_called_once_with(3)
        vir = inspect.getsource(os_app.main)
        self.assertIn("zagotovi_izhod(koda)", vir)
        self.assertIn('PREVZEM["cakaj_s"] = 12.0', vir)

    def test_umik_pred_novo_razlicico_najprej_sprosti_vrata(self):
        vir = inspect.getsource(os_app.SafeerOsWindow.koncaj_za_posodobitev)
        self.assertLess(vir.index("_stop_local_asset_server()"), vir.index("_zaklep_primerka.unlock()"))
        self.assertIn("zagotovi_izhod(0)", vir)


class SesutjeMedBrskanjem(unittest.TestCase):
    def _koncaj(self, spletni_nacin, razdelek_straze=""):
        okno = types.SimpleNamespace(_razdelek_po_obnovi=razdelek_straze, _spletni_nacin=spletni_nacin, nalozeno=[])
        okno._nalozi_znova_v_razdelku = okno.nalozeno.append
        status = os_app.QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus
        with mock.patch.object(os_app.QTimer, "singleShot", lambda ms, fn: fn()), redirect_stdout(io.StringIO()):
            os_app.SafeerOsWindow._izris_koncan(okno, status, 1)
        return okno.nalozeno

    def test_v_spletu_ostane_v_spletu(self):
        self.assertEqual(self._koncaj(True), ["splet"])

    def test_drugje_se_nalozi_privzeti_razdelek(self):
        self.assertEqual(self._koncaj(False), [""])

    def test_straza_pomnilnika_ohrani_svoj_razdelek(self):
        self.assertEqual(self._koncaj(True, "zapiski"), ["zapiski"])


class ZivoVQtWebEngine(unittest.TestCase):
    """Prava stran v QtWebEngine: most ob nalaganju, zeton, meni polja, konec procesa strani, pozno vstavljen most."""

    def test_most_prezivi_konec_procesa_strani(self):
        okolje = dict(__import__("os").environ)
        okolje.setdefault("QT_QPA_PLATFORM", "offscreen")
        okolje["QTWEBENGINE_CHROMIUM_FLAGS"] = (okolje.get("QTWEBENGINE_CHROMIUM_FLAGS", "") + " --disable-gpu").strip()
        okolje["PYTHONPATH"] = __import__("os").pathsep.join([str(KOREN / "windows"), str(KOREN)])
        try:
            izid = subprocess.run([sys.executable, str(Path(__file__).with_name("_most_zivo.py")), str(KOREN)],
                                  capture_output=True, text=True, timeout=150, env=okolje)
        except subprocess.TimeoutExpired:
            self.skipTest("QtWebEngine se v tem okolju ni odzval")
        if izid.returncode == 77:
            self.skipTest("QtWebEngine v tem okolju ne nalozi strani: " + izid.stdout[-300:])
        self.assertEqual(izid.returncode, 0, izid.stdout[-2500:] + izid.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
