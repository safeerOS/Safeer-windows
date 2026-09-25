"""Vgrajeni razdelek Naprave v Safeer OS (Safeer Link in Safeer Control)."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QFileDialog, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from . import control_backend, policy

BRIDGE_PREFIX = "__safeer_link_bridge__:"

class GuiDispatcher(QObject):
    signal_run = Signal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.signal_run.connect(self._execute, Qt.QueuedConnection)

    @Slot(object)
    def _execute(self, fn):
        try:
            fn()
        except Exception as e:
            print(f"[SafeerControl GuiDispatcher] Napaka: {e}")

    def dispatch(self, fn):
        self.signal_run.emit(fn)

MOST_JS = """
(function () {
  if (window.SafeerLink) return;
  window.__safeerLink = window.__safeerLink || {
    stanje: {"znan": false, "seznanjen": false, "control": true},
    naprave: [],
    stran: {"url": "", "naslov": "", "posljiva": false},
    sinhronizacija: {"zaznamki": {"vklopljena": false, "stevilo": 0}},
    konzola: "",
    jezik: "sl",
    deljenje: {"tece": false, "cilj": "", "ime": "", "napaka": ""},
    vzdevki: {}
  };
  function poslji(metoda, argumenti) {
    try {
      console.log("__safeer_link_bridge__:" + JSON.stringify({ m: metoda, a: argumenti || [] }));
    } catch (e) {}
  }
  window.SafeerLink = {
    jeTelevizor: function () { return false; },
    stanje: function () { return JSON.stringify(window.__safeerLink.stanje); },
    naprave: function () { return JSON.stringify(window.__safeerLink.naprave); },
    trenutnaStranJson: function () { return JSON.stringify(window.__safeerLink.stran); },
    sinhronizacijaStanje: function () { return JSON.stringify(window.__safeerLink.sinhronizacija); },
    naslovKonzole: function () { return window.__safeerLink.konzola || ""; },
    jezik: function () { return window.__safeerLink.jezik || "sl"; },
    vzdevki: function () { return JSON.stringify(window.__safeerLink.vzdevki || {}); },
    shraniVzdevek: function (id, ime) { poslji("shraniVzdevek", [id, ime]); },
    potrdiNovNaslov: function () { poslji("potrdiNovNaslov"); },
    pozabiNapravo: function () { poslji("pozabiNapravo"); },
    poisciHub: function () { poslji("poisciHub"); },
    seznani: function () { poslji("seznani"); },
    potrdiKodo: function (koda) { poslji("potrdiKodo", [String(koda || "")]); },
    prekiniSeznanitev: function () { poslji("prekiniSeznanitev"); },
    zacniQr: function () { poslji("zacniQr"); },
    prekiniQr: function () { poslji("prekiniQr"); },
    poveziSe: function () { poslji("poveziSe"); },
    posljiTrenutno: function (cilj) { poslji("posljiTrenutno", [cilj]); },
    poslji: function (cilj, url, naslov) { poslji("poslji", [cilj, url, naslov]); },
    posljiBesedilo: function (cilj, vsebina) { poslji("posljiBesedilo", [cilj, vsebina]); },
    izberiDatoteko: function (cilj) { poslji("izberiDatoteko", [cilj]); },
    zacniDeljenjeZaslona: function (cilj, ime) { poslji("zacniDeljenjeZaslona", [cilj, ime]); },
    koncajDeljenjeZaslona: function () { poslji("koncajDeljenjeZaslona"); },
    deljenjeZaslonaStanje: function () { return JSON.stringify(window.__safeerLink.deljenje); },
    preimenujNapravo: function (id, ime) { poslji("preimenujNapravo", [id, ime]); },
    nastaviZaupanje: function (v) { poslji("nastaviZaupanje", [!!v]); },
    zacniVabilo: function () { poslji("zacniVabilo"); },
    prekiniVabilo: function () { poslji("prekiniVabilo"); },
    nadaljujBrezPovezave: function () { poslji("nadaljujBrezPovezave"); },
    ukaz: function (cilj, u, podatki, ref) { poslji("ukaz", [cilj, u, podatki, ref]); },
    nadzor: function (cilj, u, v) { poslji("nadzor", [cilj, u, v]); },
    odpri: function (url) { poslji("odpri", [url]); },
    deliStandardneMape: function () { poslji("deliStandardneMape"); },
    poveziNaprave: function () { poslji("poveziNaprave"); },
    novaLokalnaKoda: function () { poslji("novaLokalnaKoda"); },
    hubVklopi: function () { poslji("hubVklopi"); },
    hubIzklopi: function () { poslji("hubIzklopi"); },
    hubOsvezi: function () { poslji("hubOsvezi"); },
    hubStanje: function () { return JSON.stringify(window.__safeerLink.hubStanje || {}); },
    hubPrijave: function () { return JSON.stringify(window.__safeerLink.hubPrijave || []); },
    hubSeznanjene: function () { return JSON.stringify(window.__safeerLink.hubSeznanjene || []); },
    hubPotrdi: function (id) { poslji("hubPotrdi", [id]); },
    hubZavrni: function (id) { poslji("hubZavrni", [id]); },
    hubPreklici: function (id) { poslji("hubPreklici", [id]); },
    deljeneMape: function () { return JSON.stringify(window.__safeerLink.deljeneMape || []); },
    dodajDeljenoMapo: function () { poslji("dodajDeljenoMapo"); },
    odstraniDeljenoMapo: function (i) { poslji("odstraniDeljenoMapo", [i]); },
    deljenVesDisk: function () { return !!window.__safeerLink.deljenVesDisk; },
    nastaviVesDisk: function (v) { poslji("nastaviVesDisk", [!!v]); },
    zapri: function () { poslji("zapri"); }
  };
})();
"""


class SafeerControlPage(QWebEnginePage):
    def __init__(self, profile: QWebEngineProfile, window: "SafeerControlWindow"):
        super().__init__(profile, window)
        self.window_ref = window

    def javaScriptConsoleMessage(self, level, message: str, line: int, source: str) -> None:
        if message.startswith(BRIDGE_PREFIX):
            try:
                payload = json.loads(message[len(BRIDGE_PREFIX):])
                self.window_ref.obdelaj_klic(payload)
            except Exception as e:
                print(f"[SafeerControl] Napaka pri razclenjevanju mostu: {e}")
        else:
            super().javaScriptConsoleMessage(level, message, line, source)


class SafeerControlWindow(QWidget):
    def __init__(self, backend: Optional[control_backend.SafeerControlBackend] = None, parent: Optional[QWidget] = None,
                 na_skritje: Optional[Any] = None):
        super().__init__(parent)
        self.backend = backend or control_backend.get_backend()
        #: Ko je vgrajen v Safeer OS (namesto lastnega vrha-okna): klice se ob "zapri", uspesni
        #: seznanitvi ob prvem zagonu ali "nadaljuj brez povezave", da starsevsko okno preklopi nazaj.
        self.na_skritje = na_skritje
        self.v_prijavi = False
        self.setWindowTitle("Safeer OS · Naprave")
        if parent is None:
            self.resize(960, 640)
            self.setMinimumSize(800, 520)

        # Dispečer za varno izvajanje klicev na glavni GUI niti
        self.dispatcher = GuiDispatcher(self)

        # Ikona
        try:
            icon_p = policy.shared_path("assets/icon.png")
            if os.path.exists(icon_p):
                self.setWindowIcon(QIcon(icon_p))
        except Exception:
            pass

        # Profil in nastavitve
        self.profile = QWebEngineProfile("SafeerControlProfile", self)
        settings = self.profile.settings()
        attr = QWebEngineSettings.WebAttribute
        settings.setAttribute(attr.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(attr.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(attr.ScrollAnimatorEnabled, True)

        # Registriraj skripto mostu
        script = QWebEngineScript()
        script.setName("SafeerLinkBridge")
        script.setSourceCode(MOST_JS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.profile.scripts().insert(script)

        self.view = QWebEngineView(self)
        self.page_obj = SafeerControlPage(self.profile, self)
        self.page_obj.setBackgroundColor(QColor("#090d15"))
        self.view.setPage(self.page_obj)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        # Poslusaj dogodke iz zaledja
        self.backend.dodaj_poslusalca(self._na_dogodek_zaledja)

        # Nalaganje vmesnika
        self.nalozi_vmesnik()

        # Po nalozitvi posodobi stanje v strani
        self.view.loadFinished.connect(self._ob_nalozenem_vmesniku)

    def nalozi_vmesnik(self) -> None:
        try:
            link_html = policy.shared_path("assets/link/index.html")
        except Exception:
            link_html = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "link", "index.html"))

        if os.path.exists(link_html):
            self.view.load(QUrl.fromLocalFile(link_html))
        else:
            print(f"[SafeerControl] Datoteka {link_html} ne obstaja!")

    def _ob_nalozenem_vmesniku(self, ok: bool) -> None:
        if ok:
            self.osvezi_stran()

    def osvezi_stran(self, vrsta: str = "", podatki: Any = None) -> None:
        stanje = {
            "stanje": self.backend.stanje_linka(),
            "naprave": self.backend.naprave,
            "stran": {"url": "", "naslov": "", "posljiva": False},
            "sinhronizacija": {"zaznamki": {"vklopljena": False, "stevilo": 0}},
            "konzola": "",
            "jezik": "sl",
            "deljenje": {"tece": False, "cilj": "", "ime": "", "napaka": ""},
            "vzdevki": self.backend.nastavitve.get("link_vzdevki", {}),
            "deljeneMape": self.backend.deljene_mape(),
        }
        stanje_json = json.dumps(stanje, ensure_ascii=False)
        cmd = f"window.__safeerLink = {stanje_json};"
        if vrsta:
            podatki_json = json.dumps(podatki, ensure_ascii=False)
            cmd += f" if (window.safeerLinkOdziv) window.safeerLinkOdziv({json.dumps(vrsta)}, {podatki_json});"
        else:
            cmd += ' if (window.safeerLinkOdziv) window.safeerLinkOdziv("stanje", window.__safeerLink.stanje);'
        self.dispatcher.dispatch(lambda: self.view.page().runJavaScript(cmd))

    def _na_dogodek_zaledja(self, vrsta: str, podatki: Any) -> None:
        self.dispatcher.dispatch(lambda: self.osvezi_stran(vrsta, podatki))
        if self.na_skritje is not None and getattr(self, "v_prijavi", False) and vrsta == "seznanitev" and (
            podatki and (isinstance(podatki, dict) and podatki.get("uspeh") or podatki is True)
        ):
            self.v_prijavi = False
            self.dispatcher.dispatch(self.na_skritje)

    def pojdi_na_razdelek(self, razdelek: str, id_naprave: str = "") -> None:
        def akcija():
            cmd = f"if (window.safeerLinkOdpri) window.safeerLinkOdpri({json.dumps(razdelek)}, {json.dumps(id_naprave)});"
            self.view.page().runJavaScript(cmd)
        self.dispatcher.dispatch(lambda: QTimer.singleShot(300, akcija))

    def obdelaj_klic(self, sporocilo: dict) -> None:
        metoda = sporocilo.get("m", "")
        a = sporocilo.get("a", [])

        if metoda == "poisciHub":
            import threading
            threading.Thread(target=self.backend.poisci_hub, daemon=True).start()
        elif metoda == "seznani":
            import threading
            threading.Thread(target=self.backend.zacni_seznanitev, daemon=True).start()
        elif metoda == "potrdiKodo":
            koda = str(a[0]) if a else ""
            import threading
            threading.Thread(target=lambda: self.backend.potrdi_kodo(koda), daemon=True).start()
        elif metoda == "prekiniSeznanitev":
            self.backend.prekini_seznanitev()
        elif metoda == "zacniQr":
            self.backend.zacni_qr()
        elif metoda == "prekiniQr":
            self.backend.prekini_qr()
        elif metoda == "poveziSe":
            import threading
            threading.Thread(target=self.backend.povezi_se, daemon=True).start()
        elif metoda == "pozabiNapravo":
            self.backend.pozabi_napravo()
        elif metoda == "nastaviZaupanje":
            self.backend.nastavi_zaupanje(bool(a[0]) if a else False)
        elif metoda == "nadaljujBrezPovezave":
            self.backend.nadaljuj_brez_povezave()
            if self.na_skritje is not None:
                self.dispatcher.dispatch(self.na_skritje)
        elif metoda == "poveziNaprave":
            self.backend.povezi_naprave()
            self.osvezi_stran()
        elif metoda == "novaLokalnaKoda":
            self.backend.nova_lokalna_koda()
        elif metoda == "zacniVabilo":
            self.backend.zacni_qr()
        elif metoda == "prekiniVabilo":
            self.backend.prekini_qr()
        elif metoda == "odpri":
            url = str(a[0]) if a else ""
            if url:
                import webbrowser
                webbrowser.open(url)
        elif metoda == "nadzor":
            cilj = str(a[0]) if len(a) > 0 else ""
            u = str(a[1]) if len(a) > 1 else ""
            v = a[2] if len(a) > 2 else 0
            self.backend.nadzor(cilj, u, v)
        elif metoda == "ukaz":
            cilj = str(a[0]) if len(a) > 0 else ""
            u = str(a[1]) if len(a) > 1 else ""
            podatki = a[2] if len(a) > 2 else None
            ref = str(a[3]) if len(a) > 3 else ""
            self.backend.ukaz(cilj, u, podatki, ref)
        elif metoda == "posljiBesedilo":
            cilj = str(a[0]) if len(a) > 0 else ""
            txt = str(a[1]) if len(a) > 1 else ""
            self.backend.poslji_besedilo(cilj, txt)
        elif metoda == "preimenujNapravo":
            id_n = str(a[0]) if len(a) > 0 else ""
            novo = str(a[1]) if len(a) > 1 else ""
            import threading
            threading.Thread(target=lambda: self.backend.preimenuj_napravo(id_n, novo), daemon=True).start()
        elif metoda == "dodajDeljenoMapo":
            self.dispatcher.dispatch(self._izberi_mapo)
        elif metoda == "odstraniDeljenoMapo":
            idx = int(a[0]) if a else -1
            self.backend.odstrani_deljeno_mapo(idx)
        elif metoda == "zapri":
            if self.na_skritje is not None:
                self.dispatcher.dispatch(self.na_skritje)
            else:
                self.dispatcher.dispatch(self.close)

    def _izberi_mapo(self) -> None:
        mapa = QFileDialog.getExistingDirectory(self, "Izberi mapo za deljenje")
        if mapa:
            self.backend.dodaj_deljeno_mapo(mapa)

    def closeEvent(self, event) -> None:
        # Ce je vgrajen v Safeer OS, klik na X v vgrajenem pogledu ne pride sem (ni okvirja);
        # ta pot ostane za primer, ko je (redko) se vedno pravo okno.
        if self.parent():
            self.hide()
            event.ignore()
        else:
            self.backend.odstrani_poslusalca(self._na_dogodek_zaledja)
            event.accept()
