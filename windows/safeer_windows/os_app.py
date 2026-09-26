"""Safeer OS za Windows: samostojna aplikacija s celozaslonskim domacim vmesnikom."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import platform
import socket
import socketserver
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                     QWebEngineSettings)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from core import os_media, os_scit

from . import browser, control_backend, control_window, os_backend_win, policy, vlc_player

class ShrambaWrapper:
    def get(self, key: str, default: Any = None) -> Any:
        return os_backend_win.nalozi_shrambo().get(key, default)

    def set(self, key: str, value: Any) -> None:
        s = os_backend_win.nalozi_shrambo()
        s[key] = value
        os_backend_win.shrani_shrambo(s)

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


def _find_free_port() -> int:
    """Poišče prosto TCP vrata na lokalnem vmesniku."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _SafeerAssetHandler(BaseHTTPRequestHandler):
    """Minimalni HTTP handler ki streže datoteke iz assets_root mape.
    Brez log izpisa v konzolo in brez zunanjih dostopov.
    """
    assets_root: str = ""

    def do_GET(self) -> None:
        url_path = urllib.parse.urlsplit(self.path).path
        # Varnostna omejitev: samo relativne poti znotraj assets_root
        rel = url_path.lstrip("/")
        # Prepreči path traversal
        target = Path(self.assets_root) / rel
        try:
            resolved = target.resolve()
            base_resolved = Path(self.assets_root).resolve()
            if not str(resolved).startswith(str(base_resolved)):
                self.send_error(403)
                return
        except Exception:
            self.send_error(403)
            return

        # Privzeto: index.html
        if resolved.is_dir():
            resolved = resolved / "index.html"

        if not resolved.is_file():
            self.send_error(404)
            return

        mime_type, _ = mimetypes.guess_type(str(resolved))
        if not mime_type:
            suffix = resolved.suffix.lower()
            mime_type = {
                ".js": "application/javascript",
                ".css": "text/css",
                ".html": "text/html",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".ico": "image/x-icon",
                ".json": "application/json",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
            }.get(suffix, "application/octet-stream")

        try:
            data = resolved.read_bytes()
        except OSError:
            self.send_error(500)
            return

        self.send_response(200)
        self.send_header("Content-Type", mime_type + ("; charset=utf-8" if "text" in mime_type or "javascript" in mime_type else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Permissions-Policy", "autoplay=(self), fullscreen=(self), picture-in-picture=(self)")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # type: ignore[override]
        # Tiho — ne izpisujemo HTTP requestov v konzolo
        pass


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_local_server: Optional[_ThreadedHTTPServer] = None
_local_server_port: int = 0


def _start_local_asset_server(assets_root: str) -> int:
    """Zažene lokalni HTTP server za assets v ozadjem threadu. Vrne port."""
    global _local_server, _local_server_port
    if _local_server is not None:
        return _local_server_port

    port = _find_free_port()

    class _Handler(_SafeerAssetHandler):
        pass
    _Handler.assets_root = assets_root

    server = _ThreadedHTTPServer(("127.0.0.1", port), _Handler)
    _local_server = server
    _local_server_port = port

    t = threading.Thread(target=server.serve_forever, name="SafeerAssetHTTP", daemon=True)
    t.start()
    print(f"[SafeerOS] Lokalni asset server zagnan na http://127.0.0.1:{port}/", flush=True)
    return port


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

    def createWindow(self, _type):
        # Blokiraj vsa nova / pojavna okna iz vdelanih spletnih strani ali oglasov
        return None

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # Glavno okno Safeer OS sme nalagati le lokalni UI; zunanji preusmeritveni poskusi
        # (npr. top-navigation iz oglasnih skript) so blokirani.
        if is_main_frame:
            url_str = url.toString() if hasattr(url, "toString") else str(url)
            if (url_str.startswith("file:") or url_str.startswith("qrc:")
                    or "assets/os" in url_str
                    or url_str.startswith("http://127.0.0.1:")):
                return True
            print(f"[SafeerOS] Blokirana zunanja navigacija glavnega okna na: {url_str}")
            return False
        return True

    def javaScriptConsoleMessage(self, level, message: str, line: int, source: str) -> None:
        if message.startswith(BRIDGE_PREFIX):
            try:
                payload = json.loads(message[len(BRIDGE_PREFIX):])
                self.window_ref.obdelaj_klic(payload)
            except Exception as e:
                print(f"[SafeerOS] Napaka pri razclenjevanju mostu: {e}", flush=True)
        else:
            print(f"[CONSOLE {level}] {message} ({source}:{line})", flush=True)
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
        self.media_center = os_media.MediaCenter(os_backend_win.CONFIG_DIR)

        # Safeer Ščit za zaščito celotne naprave (DNS filtriranje na napravi)
        self.scit = os_scit.Scit(ShrambaWrapper())
        self.scit.zacni_ce_vklopljen()

        # Ikona
        try:
            icon_p = policy.shared_path("assets/icon.png")
            if os.path.exists(icon_p):
                self.setWindowIcon(QIcon(icon_p))
        except Exception:
            pass

        # Profil in nastavitve
        self.profile = QWebEngineProfile("SafeerOSProfile", self)
        self.profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        settings = self.profile.settings()
        attr = QWebEngineSettings.WebAttribute
        settings.setAttribute(attr.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(attr.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(attr.ScrollAnimatorEnabled, True)
        settings.setAttribute(attr.FullScreenSupportEnabled, True)
        settings.setAttribute(attr.PlaybackRequiresUserGesture, False)
        settings.setAttribute(attr.AllowRunningInsecureContent, False)
        settings.setAttribute(attr.JavascriptCanOpenWindows, False)
        settings.setAttribute(attr.PluginsEnabled, False)

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
        self.page_obj.renderProcessTerminated.connect(
            lambda status, code: print(f"[SafeerOS] RenderProcessTerminated: status={status}, code={code}", flush=True)
        )
        self.view.setPage(self.page_obj)

        self.zaslon = QStackedWidget(self)
        self.zaslon.addWidget(self.view)
        self.media_player = vlc_player.VlcPlayerWidget(self)
        self.media_player.nazaj.connect(self._zapri_media)
        self.zaslon.addWidget(self.media_player)

        # Safeer Browser ni ločen program: ista zaščitena brskalna seja je tretji
        # pogled enotnega Safeer OS. Spletne aplikacije se zato nalagajo kot
        # vrhnja stran (brez nezanesljivega iframe/X-Frame-Options obvoda).
        self.browser_app = browser.SafeerBrowserApp(
            QApplication.instance(), policy.SettingsStore(), "embedded"
        )
        self.browser_window = browser.BrowserWindow(
            self.browser_app, embedded=True, on_safeer_home=self._zapri_browser
        )
        self.browser_window.setWindowFlags(Qt.Widget)
        self.browser_app.windows.append(self.browser_window)
        self.browser_window.new_tab(policy.HOME_URL)
        self.zaslon.addWidget(self.browser_window)
        self._browser_media_active = False
        self.setCentralWidget(self.zaslon)

        # Tipke za celozaslonski nacin
        self.shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        self.shortcut_f11.activated.connect(self.preklopi_celozaslonsko)

        self.shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        self.shortcut_esc.activated.connect(self.na_escape)

        # Uporabnik vir doda enkrat; Safeer OS nato zastarele kataloge tiho
        # osvežuje ob zagonu in na šest ur, ne da bi blokiral glavno okno.
        self.media_refresh_timer = QTimer(self)
        self.media_refresh_timer.setInterval(6 * 60 * 60 * 1000)
        self.media_refresh_timer.timeout.connect(self._osvezi_media_v_ozadju)
        self.media_refresh_timer.start()

        # Nalozi domaco stran
        self.nalozi_vmesnik()
        QTimer.singleShot(0, self._osvezi_media_v_ozadju)

        # Ce je dolocen zacetni razdelek (npr. 'control', 'daljinec', 'novaNaprava', 'media', 'nastavitve'),
        # odpri ustrezen vgrajen razdelek!
        if self.zacetni_razdelek:
            if self.zacetni_razdelek in ("control", "daljinec", "naprave", "novaNaprava", "prijava"):
                self.odpri_control(razdelek=self.zacetni_razdelek)
            elif self.zacetni_razdelek == "media-nastavitve":
                def _odpri_media_nastavitve():
                    js = (
                        "if (window.safeerOsPojdi) window.safeerOsPojdi('nastavitve');"
                        "var pl = document.getElementById('mediaNastavitvePlosca');"
                        "if (pl) { pl.hidden = false; pl.scrollIntoView(); }"
                        "var bg = document.getElementById('mediaPrimerKodeGumb');"
                        "if (bg) { bg.click(); }"
                    )
                    self.view.page().runJavaScript(js)
            elif self.zacetni_razdelek == "media-serije":
                def _odpri_media_serije():
                    js = (
                        "if (window.safeerOsPojdi) window.safeerOsPojdi('media');"
                        "var b = document.querySelector('[data-media-filter=\"serija\"]');"
                        "if (b) { b.click(); }"
                    )
                    self.view.page().runJavaScript(js)
                QTimer.singleShot(700, _odpri_media_serije)
            elif self.zacetni_razdelek == "media-predvajaj":
                def _odpri_media_predvajaj():
                    js = (
                        "if (window.safeerOsPojdi) window.safeerOsPojdi('media');"
                        "var b = document.querySelector('[data-media-filter=\"serija\"]');"
                        "if (b) { b.click(); }"
                        "function klikniKoJePripravljeno(poskusi) {"
                        "  var kartice = document.querySelectorAll('.media-kartica');"
                        "  for (var i = 0; i < kartice.length; i++) {"
                        "    if (kartice[i].innerText.indexOf('Igra prestolov') >= 0 || kartice[i].innerText.indexOf('Inception') >= 0) {"
                        "      kartice[i].click(); return;"
                        "    }"
                        "  }"
                        "  if ((poskusi || 0) < 20) {"
                        "    setTimeout(function () { klikniKoJePripravljeno((poskusi || 0) + 1); }, 200);"
                        "  }"
                        "}"
                        "setTimeout(function () { klikniKoJePripravljeno(0); }, 300);"
                    )
                    self.view.page().runJavaScript(js)
                QTimer.singleShot(700, _odpri_media_predvajaj)
            else:
                QTimer.singleShot(600, lambda: self.view.page().runJavaScript(f"window.safeerOsPojdi && window.safeerOsPojdi('{self.zacetni_razdelek}');"))
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
            # Strežemo celotno assets/ mapo (nadrejena assets/os/)
            assets_root = os.path.abspath(os.path.join(os.path.dirname(os_html), ".."))
        except Exception:
            assets_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets"))
            os_html = os.path.join(assets_root, "os", "index.html")

        if not os.path.exists(os_html):
            print(f"[SafeerOS] Datoteka {os_html} ne obstaja!")
            return

        # Lokalni HTTP izvor zagotovi predvidljivo nalaganje modulov in sredstev;
        # zunanje strani se odpirajo v ločenem zaščitenem profilu Safeer Browserja.
        port = _start_local_asset_server(assets_root)
        url = f"http://127.0.0.1:{port}/os/index.html"

        # Shrani port za morebitne kasnejše klice
        self._asset_server_port = port
        self.view.load(QUrl(url))

    def preklopi_celozaslonsko(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def na_escape(self) -> None:
        if self.zaslon.currentWidget() is self.media_player:
            self._zapri_media()
            return
        if self.zaslon.currentWidget() is self.browser_window:
            self._zapri_browser()
            return
        if self.isFullScreen():
            self.showNormal()

    def _odpri_media(self, item: dict) -> None:
        if self.media_player.play_item(item):
            self.zaslon.setCurrentWidget(self.media_player)
            self.setWindowTitle(f"Safeer OS · Media · {item.get('naslov', '')}")
        else:
            self.poslji_dogodek("mediaFallback", item)

    def _zapri_media(self) -> None:
        self.media_player.stop()
        self.zaslon.setCurrentWidget(self.view)
        self.setWindowTitle("Safeer OS")

    def _odpri_notranji_splet(self, url: str, *, media: bool = False) -> None:
        self._browser_media_active = media
        self.browser_window.load_in_current(url)
        self.zaslon.setCurrentWidget(self.browser_window)
        self.setWindowTitle("Safeer OS · Media" if media else "Safeer OS · Splet")

    def _zapri_browser(self) -> None:
        if self._browser_media_active:
            view = self.browser_window.current_view()
            if view is not None:
                view.setUrl(QUrl("about:blank"))
        self._browser_media_active = False
        self.zaslon.setCurrentWidget(self.view)
        self.setWindowTitle("Safeer OS")
        self.poslji_dogodek("fokus", None)

    def _osvezi_media_v_ozadju(self) -> None:
        def _delo() -> None:
            rezultat = self.media_center.refresh_stale()
            if rezultat.get("osvezenih"):
                self.poslji_dogodek("mediaOsvezen", rezultat)

        threading.Thread(target=_delo, name="SafeerMediaRefresh", daemon=True).start()

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
            self.setWindowTitle("Safeer OS · Naprave")
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
                "razpolozljivo": os_backend_win.razpolozljive_nastavitve(),
                "mape": os_backend_win.uporabniske_mape(),
                "celozaslonsko": self.isFullScreen(),
                "namizje": "windows",
                "spletne": shramba.get("spletne", [
                    {"ime": "Gmail", "url": "https://mail.google.com"},
                    {"ime": "YouTube", "url": "https://www.youtube.com"},
                    {"ime": "Google", "url": "https://www.google.com"},
                    {"ime": "Safeer", "url": "https://safeer.si"}
                ]),
                "razlicica": policy.APP_VERSION,
                "sistem": f"Windows {platform.release()}",
                "samozagon": os_backend_win.samozagon_vklopljen(),
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

        if metoda == "samozagon":
            return os_backend_win.nastavi_samozagon(bool(a[0]) if a else False)

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
            return self.scit.stanje()

        if metoda == "scitVklop":
            vklop = bool(a[0]) if a else False
            return self.scit.nastavi(vklop)

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

        if metoda == "omrezje":
            return {"naprave": [], "omrezja": [], "shranjene": [],
                    "wifi_vklopljen": False, "napredno": True}

        if metoda == "zvok":
            return {"izhodi": [], "vhodi": [], "programi": [],
                    "link": {"naprave": [], "zvok": {}, "povezan": False}, "napredno": True}

        if metoda == "jbl":
            return {"vklop": False, "najdena": False}

        if metoda == "mediaKatalog":
            query = str(a[0]) if a else ""
            kind = str(a[1]) if len(a) > 1 else "vse"
            return self.media_center.catalog(query, kind)

        if metoda == "mediaDodajVir":
            url = str(a[0]) if a else ""
            name = str(a[1]) if len(a) > 1 else ""
            return self.media_center.add_source(url, name)

        if metoda == "mediaUvoziJson":
            raw_json = a[0] if a else ""
            default_name = str(a[1]) if len(a) > 1 else ""
            return self.media_center.import_json(raw_json, default_name)

        if metoda == "mediaIzvoziJson":
            return self.media_center.export_json()

        if metoda == "mediaOdstraniVir":
            return self.media_center.remove_source(str(a[0]) if a else "")

        if metoda == "mediaOsveziVir":
            source_id = str(a[0]) if a else ""
            return self.media_center.refresh_source(source_id) if source_id else self.media_center.refresh_all()

        if metoda == "mediaPredvajaj":
            item = self.media_center.resolve(str(a[0]) if a else "")
            if not item:
                return None
            url = str(item.get("url") or "")
            is_embed = (
                item.get("vrsta") == "embed" or
                "/embed/" in url.lower() or
                any(x in url.lower() for x in ("vidsrc", "vidlink", "superembed", "embed.su", "multiembed", "youtube", "vimeo", "dailymotion", "streamtape", "vidbox"))
            )
            parsed_path = urllib.parse.urlsplit(url).path.lower()
            _, ext = os.path.splitext(parsed_path)
            is_direct_stream = (
                url.startswith("file:") or
                ext in os_media.MEDIA_EXT or
                parsed_path.endswith((".m3u8", ".mpd", ".ts")) or
                bool(item.get("glave"))
            )
            native = self.media_player.available and is_direct_stream and not is_embed
            internal = False
            if native:
                self.dispatcher.dispatch(lambda: self._odpri_media(item))
            elif url.startswith(("http://", "https://", "file:")):
                self.dispatcher.dispatch(lambda: self._odpri_notranji_splet(url, media=True))
                internal = True
            return dict(item, native=native, internal=internal)

        if metoda == "mediaStanje":
            return {"na_voljo": True, "native": self.media_player.available,
                    "predvajalnik": "LibVLC + zaščiteni Safeer Browser"}

        if metoda in ("odprtaOkna", "mediaNaprave"):
            return []

        return None

    def odpri_splet(self, url: str) -> bool:
        url = str(url or "").strip()
        if not url:
            return False
        if not urllib.parse.urlsplit(url).scheme:
            url = "https://" + url
        if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
            return False
        self.dispatcher.dispatch(lambda: self._odpri_notranji_splet(url))
        return True

    def closeEvent(self, event) -> None:
        try:
            if hasattr(self, "scit") and self.scit is not None:
                self.scit.koncaj()
        except Exception:
            pass
        try:
            self.browser_app.shutdown()
        except Exception:
            pass
        event.accept()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Safeer OS za Windows (z vgrajenim Safeer Controlom)")
    parser.add_argument("--okno", action="store_true", help="Odpri v oknu namesto celozaslonsko")
    parser.add_argument("--control", "-c", action="store_true", help="Odpri neposredno v razdelku Naprave")
    parser.add_argument("--razdelek", type=str, default="", help="Zacetni razdelek (npr. control, daljinec, naprave, novaNaprava)")
    parser.add_argument("--ozadje", action="store_true", help="Zazeni le v ozadju")
    args = parser.parse_args(argv)

    browser.register_schemes()
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
