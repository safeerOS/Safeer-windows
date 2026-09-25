"""Safeer OS za Windows: samostojna aplikacija s celozaslonskim domacim vmesnikom."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import urllib.parse
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from . import control_backend, control_window, os_backend_win, policy

BRIDGE_PREFIX = "__safeer_os_bridge__:"

MOST_JS = r"""
(function () {
  var cakajo = {}, stevec = 0;
  window.__safeerOsOdgovor = function (id, ok, podatki) {
    var c = cakajo[id]; if (!c) return; delete cakajo[id];
    if (ok) c.res(podatki); else c.rej(podatki);
  };
  window.SafeerOS = {
    klic: function (metoda, argumenti) {
      return new Promise(function (res, rej) {
        var id = ++stevec; cakajo[id] = { res: res, rej: rej };
        try {
          console.log("__safeer_os_bridge__:" + JSON.stringify({ id: id, m: metoda, a: argumenti || [] }));
        } catch (e) { delete cakajo[id]; rej(String(e)); }
      });
    }
  };
})();
"""


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
            print(f"[SafeerOS GuiDispatcher] Napaka: {e}")

    def dispatch(self, fn):
        self.signal_run.emit(fn)


class SafeerOsPage(QWebEnginePage):
    def __init__(self, profile: QWebEngineProfile, window: "SafeerOsWindow"):
        super().__init__(profile, window)
        self.window_ref = window

    def javaScriptConsoleMessage(self, level, message: str, line: int, source: str) -> None:
        if message.startswith(BRIDGE_PREFIX):
            try:
                payload = json.loads(message[len(BRIDGE_PREFIX):])
                self.window_ref.obdelaj_klic(payload)
            except Exception as e:
                print(f"[SafeerOS] Napaka pri razclenjevanju mostu: {e}")
        else:
            super().javaScriptConsoleMessage(level, message, line, source)


class SafeerOsWindow(QMainWindow):
    def __init__(self, v_oknu: bool = False, zacetni_razdelek: str = ""):
        super().__init__()
        self.v_oknu = v_oknu
        self.zacetni_razdelek = zacetni_razdelek
        self.setWindowTitle("Safeer OS")
        self.setMinimumSize(960, 600)

        # Dispečer za varno izvajanje klicev na glavni GUI niti
        self.dispatcher = GuiDispatcher(self)

        # Safeer Control & Safeer Link zaledje (enotni program)
        self.control_backend = control_backend.get_backend()
        self.control_window: Optional[control_window.SafeerControlWindow] = None
        self.control_backend.dodaj_poslusalca(self._na_dogodek_linka)

        # Ikona
        try:
            icon_p = policy.shared_path("assets/icon.png")
            if os.path.exists(icon_p):
                self.setWindowIcon(QIcon(icon_p))
        except Exception:
            pass

        # Profil in nastavitve
        self.profile = QWebEngineProfile("SafeerOSProfile", self)
        settings = self.profile.settings()
        attr = QWebEngineSettings.WebAttribute
        settings.setAttribute(attr.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(attr.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(attr.ScrollAnimatorEnabled, True)
        settings.setAttribute(attr.FullScreenSupportEnabled, True)

        # Registriraj skripto mostu
        script = QWebEngineScript()
        script.setName("SafeerOsBridge")
        script.setSourceCode(MOST_JS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.profile.scripts().insert(script)

        # Pogled
        self.view = QWebEngineView(self)
        self.page_obj = SafeerOsPage(self.profile, self)
        self.view.setPage(self.page_obj)

        self.zaslon = QStackedWidget(self)
        self.zaslon.addWidget(self.view)
        self.setCentralWidget(self.zaslon)

        # Tipke za celozaslonski nacin
        self.shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        self.shortcut_f11.activated.connect(self.preklopi_celozaslonsko)

        self.shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        self.shortcut_esc.activated.connect(self.na_escape)

        # Nalozi domaco stran
        self.nalozi_vmesnik()

        # Ce je dolocen zacetni razdelek (npr. 'control', 'daljinec', 'novaNaprava'),
        # odpri neposredno ta razdelek v vgrajenem Safeer Controlu!
        if self.zacetni_razdelek:
            self.odpri_control(razdelek=self.zacetni_razdelek)
        else:
            # Ce racunalnik se ni povezan in uporabnik se ni izbral »brez povezave«,
            # takoj prikazemo vgrajen prijavni zaslon (QR / 6-mestna koda / nadaljuj brez)
            st = self.control_backend.stanje_povezave().get("stanje")
            if st == "nov":
                self.odpri_control(prijava_ob_zagonu=True)

        if self.v_oknu:
            self.resize(1280, 800)
            self.show()
        else:
            self.showFullScreen()

    def nalozi_vmesnik(self) -> None:
        try:
            os_html = policy.shared_path("assets/os/index.html")
        except Exception:
            os_html = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "os", "index.html"))

        if os.path.exists(os_html):
            self.view.load(QUrl.fromLocalFile(os_html))
        else:
            print(f"[SafeerOS] Datoteka {os_html} ne obstaja!")

    def preklopi_celozaslonsko(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def na_escape(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def poslji_dogodek(self, vrsta: str, podatki: Any) -> None:
        payload_js = json.dumps(podatki, ensure_ascii=False)
        cmd = f"window.safeerOsDogodek && window.safeerOsDogodek({json.dumps(vrsta)}, {payload_js});"
        self.dispatcher.dispatch(lambda: self.view.page().runJavaScript(cmd))

    def _na_dogodek_linka(self, vrsta: str, podatki: Any) -> None:
        if vrsta in ("povezava", "stanje", "naprave"):
            self.poslji_dogodek("fokus", None)

    def odpri_control(self, razdelek: str = "", id_naprave: str = "", prijava_ob_zagonu: bool = False) -> bool:
        def _odpri():
            if self.control_window is None:
                self.control_window = control_window.SafeerControlWindow(
                    backend=self.control_backend, parent=self, na_skritje=self._na_skritje_controla)
                self.control_window.setWindowFlags(Qt.Widget)
                self.zaslon.addWidget(self.control_window)
            else:
                self.control_window.osvezi_stran()
            self.control_window.v_prijavi = bool(prijava_ob_zagonu)
            if razdelek:
                self.control_window.pojdi_na_razdelek(razdelek, id_naprave)
            self.control_window.show()
            self.zaslon.setCurrentWidget(self.control_window)
            self.setWindowTitle("Safeer OS — Safeer Control")
        self.dispatcher.dispatch(_odpri)
        return True

    def _na_skritje_controla(self) -> None:
        """Prijava/Control je koncan (zapri, uspesna povezava ali "nadaljuj brez") - nazaj na Safeer OS."""
        def _preklopi():
            self.zaslon.setCurrentWidget(self.view)
            self.setWindowTitle("Safeer OS")
            self.poslji_dogodek("fokus", None)
        self.dispatcher.dispatch(_preklopi)

    def vrni_odgovor(self, klic_id: int, ok: bool, podatki: Any) -> None:
        payload_js = json.dumps(podatki, ensure_ascii=False)
        ok_js = "true" if ok else "false"
        cmd = f"window.__safeerOsOdgovor && window.__safeerOsOdgovor({klic_id}, {ok_js}, {payload_js});"
        self.dispatcher.dispatch(lambda: self.view.page().runJavaScript(cmd))

    def obdelaj_klic(self, sporocilo: dict) -> None:
        klic_id = sporocilo.get("id", 0)
        metoda = sporocilo.get("m", "")
        a = sporocilo.get("a", [])

        def delo():
            try:
                res = self._izvedi_metodo(metoda, a)
                self.vrni_odgovor(klic_id, True, res)
            except Exception as e:
                print(f"[SafeerOS] Napaka pri klicu {metoda}: {e}")
                self.vrni_odgovor(klic_id, False, str(e))

        threading.Thread(target=delo, daemon=True).start()

    def _izvedi_metodo(self, metoda: str, a: list) -> Any:
        if metoda == "zacetek":
            shramba = os_backend_win.nalozi_shrambo()
            return {
                "jezik": "sl",
                "ime": os.environ.get("USERNAME", "Uporabnik"),
                "racunalnik": platform.node(),
                "ozadje": "",
                "razpolozljivo": {
                    "programi": True,
                    "datoteke": True,
                    "naprave": True,
                    "nastavitve": True,
                    "zvok": False,
                    "jbl": False,
                    "omrezje": True,
                },
                "mape": os_backend_win.uporabniske_mape(),
                "celozaslonsko": self.isFullScreen(),
                "namizje": "windows",
                "spletne": shramba.get("spletne", [
                    {"ime": "Gmail", "url": "https://mail.google.com"},
                    {"ime": "YouTube", "url": "https://www.youtube.com"},
                    {"ime": "Google", "url": "https://www.google.com"},
                    {"ime": "Safeer", "url": "https://safeer.si"}
                ]),
                "razlicica": "0.5.0",
                "sistem": f"Windows {platform.release()}",
                "samozagon": False,
                "povezava": self.control_backend.stanje_povezave(),
            }

        if metoda == "programi":
            return os_backend_win.poisci_start_menu_programe()

        if metoda == "zazeni":
            pot = str(a[0]) if a else ""
            return os_backend_win.zazeni_program(pot)

        if metoda == "mapa":
            pot = str(a[0]) if a else "~"
            return os_backend_win.preglej_mapo(pot)

        if metoda == "odpriDatoteko":
            pot = str(a[0]) if a else ""
            return os_backend_win.odpri_datoteko(pot)

        if metoda == "pokaziVMapi":
            pot = str(a[0]) if a else ""
            return os_backend_win.pokazi_v_mapi(pot)

        if metoda == "isciDatoteke":
            iskano = str(a[0]) if a else ""
            return os_backend_win.isci_datoteke(iskano)

        if metoda == "stanje":
            return os_backend_win.stanje_sistema()

        if metoda == "nastavitve":
            razdelek = str(a[0]) if a else ""
            return os_backend_win.odpri_nastavitve(razdelek)

        if metoda == "napajanje":
            ukaz = str(a[0]) if a else ""
            return os_backend_win.napajanje(ukaz)

        if metoda in ("splet", "odpri_url"):
            url = str(a[0]) if a else ""
            return self.odpri_splet(url)

        if metoda == "iskanjeSplet":
            poizvedba = str(a[0]) if a else ""
            url = "https://duckduckgo.com/?q=" + urllib.parse.quote(poizvedba)
            return self.odpri_splet(url)

        if metoda == "celozaslonsko":
            novo = bool(a[0]) if a else not self.isFullScreen()
            self.dispatcher.dispatch(lambda: self.showFullScreen() if novo else self.showNormal())
            return novo

        if metoda in ("nazajVMint", "nazajVWindows", "namizje"):
            self.dispatcher.dispatch(self.showMinimized)
            return True

        if metoda == "shraniSpletne":
            nove = a[0] if a else []
            shramba = os_backend_win.nalozi_shrambo()
            shramba["spletne"] = nove
            os_backend_win.shrani_shrambo(shramba)
            return True

        if metoda == "pripni":
            id_app = str(a[0]) if a else ""
            pripeto = bool(a[1]) if len(a) > 1 else True
            shramba = os_backend_win.nalozi_shrambo()
            pripeti = set(shramba.get("pripeti", []))
            if pripeto:
                pripeti.add(id_app)
            else:
                pripeti.discard(id_app)
            shramba["pripeti"] = list(pripeti)
            os_backend_win.shrani_shrambo(shramba)
            return True

        if metoda == "skrijDomov":
            id_app = str(a[0]) if a else ""
            skrij = bool(a[1]) if len(a) > 1 else True
            shramba = os_backend_win.nalozi_shrambo()
            skriti = set(shramba.get("skriti", []))
            if skrij:
                skriti.add(id_app)
            else:
                skriti.discard(id_app)
            shramba["skriti"] = list(skriti)
            os_backend_win.shrani_shrambo(shramba)
            return True

        if metoda == "scit":
            return {"stanje": "aktiven", "oglasi": 0, "groznje": 0}

        # Safeer Link & Safeer Control metode
        if metoda == "povezava":
            return self.control_backend.stanje_povezave()

        if metoda in ("control", "prijava"):
            razdelek = str(a[0]) if a else ""
            id_nap = str(a[1]) if len(a) > 1 else ""
            self.odpri_control(razdelek, id_nap)
            return True

        if metoda == "daljinec":
            id_nap = str(a[0]) if a else ""
            self.odpri_control("daljinec", id_nap)
            return True

        if metoda == "novaNaprava":
            self.odpri_control("novaNaprava")
            return True

        if metoda == "odjava":
            return self.control_backend.pozabi_napravo()

        if metoda == "zaupanje":
            return self.control_backend.nastavi_zaupanje(bool(a[0]) if a else False)

        if metoda == "vseNaprave":
            return self.control_backend.vse_naprave()

        if metoda == "napraveSProgrami":
            return self.control_backend.naprave_s_programi()

        if metoda == "programiNaprave":
            id_n = str(a[0]) if a else ""
            return self.control_backend.programi_naprave(id_n)

        if metoda == "napraveSDatoteki":
            return self.control_backend.naprave_s_datotekami()

        if metoda == "datotekeNaprave":
            id_n = str(a[0]) if a else ""
            mapa = str(a[1]) if len(a) > 1 else ""
            return self.control_backend.datoteke_naprave(id_n, mapa)

        if metoda == "odpriDatotekoNaprave":
            id_n = str(a[0]) if a else ""
            id_dat = str(a[1]) if len(a) > 1 else ""
            return self.control_backend.odpri_datoteko_naprave(id_n, id_dat)

        if metoda == "prenesiDatotekoNaprave":
            id_n = str(a[0]) if a else ""
            id_dat = str(a[1]) if len(a) > 1 else ""
            ime_dat = str(a[2]) if len(a) > 2 else ""
            streznik = a[3] if len(a) > 3 and isinstance(a[3], dict) else None
            return self.control_backend.prenesi_datoteko_naprave(id_n, id_dat, ime_dat, streznik)

        if metoda == "zazeniNaNapravi":
            id_n = str(a[0]) if a else ""
            app = str(a[1]) if len(a) > 1 else ""
            return self.control_backend.zazeni_na_napravi(id_n, app)

        if metoda == "odpriTukaj":
            id_n = str(a[0]) if a else ""
            app = str(a[1]) if len(a) > 1 else ""
            return self.control_backend.odpri_tukaj(id_n, app)

        if metoda == "preimenujNapravo":
            id_n = str(a[0]) if a else ""
            novo = str(a[1]) if len(a) > 1 else ""
            return self.control_backend.preimenuj_napravo(id_n, novo)

        if metoda == "nedavne":
            return []

        if metoda in ("omrezje", "zvok", "jbl", "mediaKatalog", "mediaStanje"):
            return {}

        return None

    def odpri_splet(self, url: str) -> bool:
        if not url:
            return False
        try:
            subprocess.Popen([sys.executable, "-m", "safeer_windows", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass

        try:
            if sys.platform == "win32":
                os.startfile(url)  # noqa: S606
                return True
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            print(f"[SafeerOS] Napaka pri odpiranju URL {url}: {e}")
            return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Safeer OS za Windows (z vgrajenim Safeer Controlom)")
    parser.add_argument("--okno", action="store_true", help="Odpri v oknu namesto celozaslonsko")
    parser.add_argument("--control", "-c", action="store_true", help="Odpri neposredno v razdelku Safeer Control")
    parser.add_argument("--razdelek", type=str, default="", help="Zacetni razdelek (npr. control, daljinec, naprave, novaNaprava)")
    parser.add_argument("--ozadje", action="store_true", help="Zazeni le v ozadju")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SafeerOS")
    app.setOrganizationName("Safeer")

    zacetni = ""
    if args.control:
        zacetni = args.razdelek or "naprave"
    elif args.razdelek:
        zacetni = args.razdelek

    # Ce je izbran control razdelek ali --okno, odpri v oknu
    v_oknu = True if (args.control or args.razdelek or args.okno) else False

    window = SafeerOsWindow(v_oknu=v_oknu, zacetni_razdelek=zacetni)

    if args.ozadje:
        window.control_backend.povezi_se()
        window.hide()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
