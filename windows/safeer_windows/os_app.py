"""Safeer OS za Windows: samostojna aplikacija s celozaslonskim domacim vmesnikom."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import platform
import re
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

from . import browser, control_backend, control_window, os_backend_win, policy, vlc_player, webview2_media, zapiski

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
                if str(payload.get("m") or "").startswith("media"):
                    print(f"[SafeerOS] Media zahteva #{payload.get('id')}: {payload.get('m')}", flush=True)
                self.window_ref.obdelaj_klic(payload)
            except Exception as e:
                print(f"[SafeerOS] Napaka pri razclenjevanju mostu: {e}", flush=True)
        else:
            print(f"[CONSOLE {level}] {message} ({source}:{line})", flush=True)
            super().javaScriptConsoleMessage(level, message, line, source)


class SafeerOsWindow(QMainWindow):
    def __init__(self, v_oknu: bool = False, zacetni_razdelek: str = "", media_engine: str = "auto",
                 browser_settings: Optional[policy.SettingsStore] = None):
        super().__init__()
        print("[SafeerOS] DIAG window_init_started", flush=True)
        self.v_oknu = v_oknu
        self.zacetni_razdelek = zacetni_razdelek
        self.media_engine = media_engine if media_engine in ("auto", "qt") else "auto"
        self._fullscreen_restore_maximized = not v_oknu
        self.setWindowTitle("Safeer OS")
        self.setMinimumSize(960, 600)

        # Dispečer za varno izvajanje klicev na glavni GUI niti
        self.dispatcher = GuiDispatcher(self)

        # Safeer Control & Safeer Link zaledje (enotni program)
        self.control_backend = control_backend.get_backend()
        self.control_window: Optional[control_window.SafeerControlWindow] = None
        self.control_backend.dodaj_poslusalca(self._na_dogodek_linka)
        from core import link_hub_streznik
        link_hub_streznik.POSLUSALCI_KODE.append(
            lambda ime, koda: self.poslji_dogodek("kodaPrijave", {"ime": ime, "koda": koda}))
        self.media_center = os_media.MediaCenter(os_backend_win.CONFIG_DIR)
        try:
            self.media_center.izbrana_drzava = str(os_backend_win.nalozi_shrambo().get("media_watch_country") or "auto")
        except Exception:
            pass
        # Glavne poglede medijskega centra pripravimo v ozadju, da je prvi klik takojsen.
        QTimer.singleShot(8000, self.media_center.prednalozi)

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
        self.media_player.ozadje.connect(self._media_v_ozadju)
        self.zaslon.addWidget(self.media_player)

        # Safeer Browser ni ločen program: ista zaščitena brskalna seja je tretji
        # pogled enotnega Safeer OS. Spletne aplikacije se zato nalagajo kot
        # vrhnja stran (brez nezanesljivega iframe/X-Frame-Options obvoda).
        self.browser_app = browser.SafeerBrowserApp(
            QApplication.instance(), browser_settings or policy.SettingsStore(), "embedded"
        )
        self.browser_window = browser.BrowserWindow(
            self.browser_app, private=True, embedded=True, on_safeer_home=self._zapri_browser
        )
        self.browser_window.setWindowFlags(Qt.Widget)
        self.zapiski = zapiski.Zapiski(os.path.join(os_backend_win.CONFIG_DIR, "zapiski.json"))
        self.browser_window.na_zapisek = self._izrezek_iz_spleta
        self.browser_window.na_zapisek_ob_strani = self._preklopi_zapisek_ob_strani
        self._zapisek_dock = None
        self.browser_app.windows.append(self.browser_window)
        self.browser_window.new_tab(policy.HOME_URL)
        self.zaslon.addWidget(self.browser_window)
        self.webview2_media = webview2_media.WebView2MediaWidget(self._zapri_webview2_media, self)
        self.zaslon.addWidget(self.webview2_media)
        print("[SafeerOS] DIAG media_views_ready", flush=True)
        self._browser_media_active = False
        self.setCentralWidget(self.zaslon)

        # Tipke za celozaslonski nacin
        self.shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        self.shortcut_f11.activated.connect(self.preklopi_celozaslonsko)

        self.shortcut_esc = QShortcut(QKeySequence("Escape"), self)
        self.shortcut_esc.activated.connect(self.na_escape)
        self.shortcut_media = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.shortcut_media.activated.connect(self._pokazi_media_predvajalnik)

        # Uporabnik vir doda enkrat; Safeer OS nato zastarele kataloge tiho
        # osvežuje ob zagonu in na šest ur, ne da bi blokiral glavno okno.
        self.media_refresh_timer = QTimer(self)
        self.media_refresh_timer.setInterval(6 * 60 * 60 * 1000)
        self.media_refresh_timer.timeout.connect(self._osvezi_media_v_ozadju)
        self.media_refresh_timer.start()

        # Nalozi domaco stran
        self.nalozi_vmesnik()
        print("[SafeerOS] DIAG home_page_requested", flush=True)
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
                        "if (window.safeerOsPojdi && !window.__safeerMediaTestStarted) {"
                        "window.__safeerMediaTestStarted = true; window.safeerOsPojdi('media');"
                        "var b = document.querySelector('[data-media-filter=\"serija\"]');"
                        "if (b) { b.click(); }"
                    )
                    self.view.page().runJavaScript(js)
                QTimer.singleShot(700, _odpri_media_serije)
            elif self.zacetni_razdelek == "media-film-predvajaj":
                def _odpri_media_film():
                    js = (
                        "if (window.safeerOsPojdi) window.safeerOsPojdi('media');"
                        "function klikniFilm(poskusi) {"
                        "  var kartice = document.querySelectorAll('.media-kartica');"
                        "  for (var i = 0; i < kartice.length; i++) {"
                        "    if (kartice[i].innerText.indexOf('Gladiator') >= 0 || kartice[i].innerText.indexOf('Inception') >= 0) {"
                        "      kartice[i].click();"
                        "      function klikniPredvajaj(n) {"
                        "        var p = document.querySelector('#mediaEpizode button');"
                        "        if (p) { p.click(); return; }"
                        "        if ((n || 0) < 40) setTimeout(function () { klikniPredvajaj((n || 0) + 1); }, 250);"
                        "      }"
                        "      setTimeout(function () { klikniPredvajaj(0); }, 500); return;"
                        "    }"
                        "  }"
                        "  if ((poskusi || 0) < 20) {"
                        "    setTimeout(function () { klikniFilm((poskusi || 0) + 1); }, 200);"
                        "  }"
                        "}"
                        "setTimeout(function () { klikniFilm(0); }, 500);"
                    )
                    self.view.page().runJavaScript(js)
                QTimer.singleShot(1500, _odpri_media_film)
            elif self.zacetni_razdelek == "media-predvajaj":
                def _odpri_media_predvajaj():
                    js = (
                        "if (window.safeerOsPojdi && !window.__safeerMediaTestStarted) {"
                        "window.__safeerMediaTestStarted = true; window.safeerOsPojdi('media');"
                        "var b = document.querySelector('[data-media-filter=\"serija\"]');"
                        "if (b) { b.click(); }"
                        "function klikniKoJePripravljeno(poskusi) {"
                        "  var kartice = document.querySelectorAll('.media-kartica');"
                        "  for (var i = 0; i < kartice.length; i++) {"
                        "    if (kartice[i].innerText.indexOf('Igra prestolov') >= 0 || kartice[i].innerText.indexOf('Inception') >= 0) {"
                        "      kartice[i].click();"
                        "      function predvajajPrvoEpizodo(n) {"
                        "        var p = document.querySelector('#mediaEpizode .media-epizoda button');"
                        "        if (p) { p.click(); return; }"
                        "        if ((n || 0) < 40) setTimeout(function () { predvajajPrvoEpizodo((n || 0) + 1); }, 250);"
                        "      }"
                        "      setTimeout(function () { predvajajPrvoEpizodo(0); }, 500); return;"
                        "    }"
                        "  }"
                        "  if ((poskusi || 0) < 20) {"
                        "    setTimeout(function () { klikniKoJePripravljeno((poskusi || 0) + 1); }, 200);"
                        "  }"
                        "}"
                        "setTimeout(function () { klikniKoJePripravljeno(0); }, 300);"
                        "}"
                    )
                    self.view.page().runJavaScript(js)
                QTimer.singleShot(1500, _odpri_media_predvajaj)
                QTimer.singleShot(5000, _odpri_media_predvajaj)
                QTimer.singleShot(12000, _odpri_media_predvajaj)
            else:
                QTimer.singleShot(600, lambda: self.view.page().runJavaScript(f"window.safeerOsPojdi && window.safeerOsPojdi('{self.zacetni_razdelek}');"))
        else:
            # Safeer OS se vedno odpre neposredno v domačem vmesniku
            pass

        if self.v_oknu:
            self.resize(1280, 800)
            self.show()
        else:
            self.showMaximized()
        print(f"[SafeerOS] DIAG window_show_called section={self.zacetni_razdelek or 'home'}", flush=True)

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
            self._zapusti_celozaslonsko()
        else:
            self._fullscreen_restore_maximized = self.isMaximized()
            self._nastavi_predvajalnik_celozaslonsko(True)
            self.showFullScreen()

    def _nastavi_predvajalnik_celozaslonsko(self, enabled: bool) -> None:
        if self.zaslon.currentWidget() is self.webview2_media:
            self.webview2_media.set_fullscreen_ui(enabled)
        elif self.zaslon.currentWidget() is self.media_player:
            self.media_player.set_fullscreen_ui(enabled)

    def _zapusti_celozaslonsko(self) -> None:
        self._nastavi_predvajalnik_celozaslonsko(False)
        self.showNormal()
        if self._fullscreen_restore_maximized:
            self.showMaximized()

    def na_escape(self) -> None:
        if self.isFullScreen():
            self._zapusti_celozaslonsko()
            return
        if self.zaslon.currentWidget() is self.media_player:
            self._zapri_media()
            return
        if self.zaslon.currentWidget() is self.browser_window:
            self._zapri_browser()
            return
        if self.zaslon.currentWidget() is self.webview2_media:
            self._zapri_webview2_media()
            return

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

    def _media_v_ozadju(self) -> None:
        """Skrije predvajalnik, vendar pusti zvok teči; Ctrl+Shift+M vrne kontrole."""
        self.zaslon.setCurrentWidget(self.view)
        self.setWindowTitle("Safeer OS · Media · predvajanje v ozadju")

    def _pokazi_media_predvajalnik(self) -> None:
        if self.media_player.player and self.media_player.player.is_playing():
            self.zaslon.setCurrentWidget(self.media_player)
            self.setWindowTitle(f"Safeer OS · Media · {self.media_player.current_item.get('naslov', '')}")

    def _odpri_notranji_splet(self, url: str, *, media: bool = False, item: Optional[dict] = None) -> None:
        self._browser_media_active = media
        webview_item = None
        if media and item:
            selected_url = str(item.get("url") or url)
            selected = next((dict(row) for row in item.get("razlicice", [])
                             if isinstance(row, dict) and str(row.get("url") or "") == selected_url),
                            {"url": selected_url, "vir": item.get("vir", "")})
            webview_item = dict(item, url=selected_url, razlicice=[selected])
        webview_started = False
        if self.media_engine != "qt":
            webview_started = self.webview2_media.open_item(webview_item) if webview_item else False
            if media and not webview_started:
                webview_started = self.webview2_media.open_url(url)
        if media and webview_started:
            self.zaslon.setCurrentWidget(self.webview2_media)
            self.setWindowTitle("Safeer OS · Media")
            return
        if media:
            # Uporabi preverjeno pot iz c1155b1: embed je vrhnja stran v
            # zasebnem, vgrajenem Safeer Browserju. HTML iframe v os.js ga
            # je zamenjal v 9f79709 in ponudniki lahko zavrnejo tak embed.
            self.browser_window.load_media(url)
        else:
            self.browser_window.set_media_mode(False)
            self.browser_window.set_safeer_os_web_mode(True)
            self.browser_window.load_in_current(url)
        self.zaslon.setCurrentWidget(self.browser_window)
        if not media:
            # QMainWindow lahko ob prvem prikazu znova pokaže svoje toolbar
            # akcije; način odseka Splet zato uveljavi tudi po preklopu widgeta.
            self.browser_window.set_safeer_os_web_mode(True)
        self.setWindowTitle("Safeer OS · Media" if media else "Safeer OS · Splet")

    def _zapri_browser(self) -> None:
        if self._browser_media_active:
            view = self.browser_window.current_view()
            if view is not None:
                view.setUrl(QUrl("about:blank"))
        self._browser_media_active = False
        self.browser_window.set_media_mode(False)
        self.browser_window.set_safeer_os_web_mode(False)
        self.zaslon.setCurrentWidget(self.view)
        self.setWindowTitle("Safeer OS")
        self.poslji_dogodek("fokus", None)

    def _zapri_webview2_media(self) -> None:
        self.webview2_media.stop()
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

    # ------------------------------------------------------------------ zapisek ob strani (Splet)
    def _preklopi_zapisek_ob_strani(self) -> None:
        """Zapisek ob strani se odpre samo na uporabnikovo zahtevo; brez njega je Splet cel zaslon."""
        if self._zapisek_dock is None:
            self._zapisek_dock = self._ustvari_zapisek_ob_strani()
        vidno = not self._zapisek_dock.isVisible()
        if vidno:
            self._napolni_zapisek_ob_strani()
        self._zapisek_dock.setVisible(vidno)

    def _ustvari_zapisek_ob_strani(self):
        from PySide6.QtWidgets import (QComboBox, QDockWidget, QLabel, QLineEdit, QPlainTextEdit,
                                       QVBoxLayout, QWidget)
        dock = QDockWidget("Zapisek", self.browser_window)
        dock.setObjectName("zapisekObStrani")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        vsebina = QWidget(dock)
        plast = QVBoxLayout(vsebina)
        self._zs_izbira = QComboBox(vsebina)
        self._zs_naslov = QLineEdit(vsebina)
        self._zs_naslov.setPlaceholderText("Naslov")
        self._zs_besedilo = QPlainTextEdit(vsebina)
        self._zs_besedilo.setPlaceholderText("Piši … »V zapisek« doda izbrano besedilo s strani z virom.")
        self._zs_stanje = QLabel("", vsebina)
        for w in (self._zs_izbira, self._zs_naslov, self._zs_besedilo, self._zs_stanje):
            plast.addWidget(w)
        vsebina.setMinimumWidth(320)
        vsebina.setStyleSheet("QWidget{background:#111924;color:#f0f4f3;font-size:14px}"
                              "QLineEdit,QPlainTextEdit,QComboBox{background:#1b2a33;border:1px solid #2c3a46;"
                              "border-radius:8px;padding:6px}QLabel{color:#b0bdc4;font-size:12px}")
        dock.setWidget(vsebina)
        self.browser_window.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.hide()
        self._zs_id = ""
        self._zs_polnim = False
        self._zs_casovnik = QTimer(self)
        self._zs_casovnik.setSingleShot(True)
        self._zs_casovnik.setInterval(600)
        self._zs_casovnik.timeout.connect(self._shrani_zapisek_ob_strani)
        self._zs_naslov.textEdited.connect(lambda _t: self._zs_casovnik.start())
        self._zs_besedilo.textChanged.connect(lambda: None if self._zs_polnim else self._zs_casovnik.start())
        self._zs_izbira.activated.connect(self._izbran_zapisek_ob_strani)
        return dock

    def _napolni_zapisek_ob_strani(self, ident: str = "") -> None:
        seznam = self.zapiski.seznam()
        if not ident:
            ident = self.zapiski.zadnji() or (seznam[0]["id"] if seznam else "")
        self._zs_polnim = True
        self._zs_izbira.clear()
        self._zs_izbira.addItem("+ Nov zapisek", "")
        for z in seznam:
            self._zs_izbira.addItem(z["naslov"], z["id"])
        z = self.zapiski.dobi(ident) if ident else None
        self._zs_id = z["id"] if z else ""
        self._zs_izbira.setCurrentIndex(max(0, self._zs_izbira.findData(self._zs_id)))
        self._zs_naslov.setText(z.get("naslov", "") if z else "")
        self._zs_besedilo.setPlainText(z.get("besedilo", "") if z else "")
        self._zs_polnim = False

    def _izbran_zapisek_ob_strani(self, indeks: int) -> None:
        self._shrani_zapisek_ob_strani()
        ident = self._zs_izbira.itemData(indeks) or ""
        if not ident:
            ident = self.zapiski.shrani("", "Nov zapisek", "")["id"]
        self._napolni_zapisek_ob_strani(ident)

    def _shrani_zapisek_ob_strani(self) -> None:
        if self._zapisek_dock is None or self._zs_polnim:
            return
        naslov, besedilo = self._zs_naslov.text(), self._zs_besedilo.toPlainText()
        if not self._zs_id and not (naslov.strip() or besedilo.strip()):
            return
        z = self.zapiski.shrani(self._zs_id, naslov or "Zapisek", besedilo)
        self._zs_id = z["id"]
        self._zs_stanje.setText("Shranjeno")
        self.poslji_dogodek("zapiskiSpremenjeni", None)

    def _izrezek_iz_spleta(self) -> None:
        """Gumb 'V zapisek' v Spletu: izbrano besedilo (ali samo stran) gre z virom v zadnji zapisek."""
        view = self.browser_window.current_view()
        if view is None:
            return
        url = view.url().toString()
        naslov = view.page().title()
        gumb = self.browser_window.zapisek_button

        def _potrdi(izbor) -> None:
            try:
                if self._zapisek_dock is not None and self._zapisek_dock.isVisible():
                    self._shrani_zapisek_ob_strani()  # najprej to, kar uporabnik pravkar pise
                z = self.zapiski.dodaj_izrezek(url, naslov, str(izbor or ""))
                sporocilo = "✓ V zapisku »%s«" % z["naslov"]
                if self._zapisek_dock is not None and self._zapisek_dock.isVisible():
                    self._napolni_zapisek_ob_strani(z["id"])
            except Exception as e:
                sporocilo = "Ni dodano: %s" % e
            if gumb is not None:
                gumb.setText(sporocilo)
                QTimer.singleShot(2500, lambda: gumb.setText("V zapisek"))
            self.poslji_dogodek("zapiskiSpremenjeni", None)

        view.page().runJavaScript("window.getSelection ? String(window.getSelection()) : ''", 0, _potrdi)

    def poslji_dogodek(self, vrsta: str, podatki: Any) -> None:
        payload_js = json.dumps(podatki, ensure_ascii=False)
        cmd = f"window.safeerOsDogodek && window.safeerOsDogodek({json.dumps(vrsta)}, {payload_js});"
        self.dispatcher.dispatch(lambda: self.view.page().runJavaScript(cmd))

    def _na_dogodek_linka(self, vrsta: str, podatki: Any) -> None:
        if vrsta in ("povezava", "stanje", "naprave"):
            self.poslji_dogodek("fokus", None)
        if vrsta == "zaslon" and isinstance(podatki, dict):
            url = str(podatki.get("url") or "")
            if podatki.get("dejanje") == "start" and url.startswith("https://"):
                odtis = str(podatki.get("odtis") or "").replace(":", "").lower()
                if odtis:
                    browser.ZAUPANA_POTRDILA.add(odtis)
                self.poslji_dogodek("zaslonZNaprave", {"od": podatki.get("od"), "dejanje": "start"})
                self.dispatcher.dispatch(lambda: self._odpri_notranji_splet(url))
            elif podatki.get("dejanje") == "stop":
                # Naprava je deljenje koncala: zadnje slike ne pustimo na zaslonu, vrnemo se v Safeer OS.
                def _zapri_gledalca() -> None:
                    view = self.browser_window.current_view()
                    naslov = view.url().toString() if view is not None else ""
                    if "/cast/screen/" in naslov:
                        view.setUrl(QUrl("about:blank"))
                        self._zapri_browser()
                self.dispatcher.dispatch(_zapri_gledalca)
                self.poslji_dogodek("zaslonZNaprave", {"od": podatki.get("od"), "dejanje": "stop"})
        if vrsta == "dovoljenjeZahtevano" and isinstance(podatki, dict):
            self.poslji_dogodek("dovoljenjeZahtevano", {"id": podatki.get("id"), "ime": podatki.get("ime")})
        if vrsta == "prejetaDatoteka" and isinstance(podatki, dict):
            self.poslji_dogodek("prejetaDatoteka", podatki)
        if vrsta == "deljenje" and isinstance(podatki, dict) and not podatki.get("tece"):
            # Konec posiljanja datoteke (ali napaka): uporabniku povemo izid.
            self.poslji_dogodek("posiljanjeKoncano", {k: podatki.get(k) for k in ("ime", "cilj", "uspeh", "napaka")})

    def odpri_control(self, razdelek: str = "", id_naprave: str = "", prijava_ob_zagonu: bool = False) -> bool:
        def _odpri():
            if self.control_window is None:
                self.control_window = control_window.SafeerControlWindow(
                    backend=self.control_backend, parent=self, na_skritje=self._na_skritje_controla,
                    na_odpiranje=self._odpri_notranji_splet)
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
                if metoda.startswith("media"):
                    count = len(res.get("vnosi", [])) if isinstance(res, dict) else ""
                    print(f"[SafeerOS] Media odgovor #{klic_id}: {metoda}; vnosi={count}", flush=True)
                self.vrni_odgovor(klic_id, True, res)
            except Exception as e:
                print(f"[SafeerOS] Napaka pri klicu {metoda}: {e}", flush=True)
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
                "nedavne_app": shramba.get("nedavne_app", []),
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

        if metoda == "zapiskiSeznam":
            return self.zapiski.seznam(str(a[0]) if a else "")

        if metoda == "zapisekDobi":
            return self.zapiski.dobi(str(a[0]) if a else "")

        if metoda == "zapisekShrani":
            return self.zapiski.shrani(str(a[0]) if a else "", str(a[1]) if len(a) > 1 else "",
                                       str(a[2]) if len(a) > 2 else "", (bool(a[3]) if len(a) > 3 and a[3] is not None else None))

        if metoda == "zapisekIzbrisi":
            return self.zapiski.izbrisi(str(a[0]) if a else "")

        if metoda == "nastaviDovoljenje":
            return self.control_backend.nastavi_dovoljenje(str(a[0]) if a else "", str(a[1]) if len(a) > 1 else "")

        if metoda == "posljiDatoteko":
            if len(a) < 2:
                return False
            cilj, pot = str(a[0]), str(a[1])
            if not os.path.isfile(pot):
                return False
            return self.control_backend.poslji_datoteko(cilj, pot)

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
            return self.odpri_spletno_iskanje(poizvedba)

        if metoda == "browserSettingsGet":
            settings = self.browser_app.settings
            values = {key: settings.get(key) for key in (
                "search_engine", "startup", "adblock_enabled", "adguard_protection_enabled",
                "tracking_protection_enabled", "gpc_dnt_enabled", "block_third_party_cookies",
                "doh_provider", "custom_doh_url", "force_dark_mode", "hardware_acceleration",
                "ask_download_location", "total_ads_blocked", "total_threats_blocked",
            )}
            values["engines"] = [
                {"id": key, "name": engine.get("name", key)}
                for key, engine in policy.search_engines().items()
            ]
            return values

        if metoda == "browserSettingsSet":
            if len(a) < 2:
                raise ValueError("Manjka nastavitev ali vrednost.")
            key, value = str(a[0]), a[1]
            settings = self.browser_app.settings
            boolean_keys = {
                "adblock_enabled", "adguard_protection_enabled", "tracking_protection_enabled",
                "gpc_dnt_enabled", "block_third_party_cookies", "force_dark_mode",
                "hardware_acceleration", "ask_download_location",
            }
            if key == "search_engine":
                if value not in policy.search_engines():
                    raise ValueError("Neznan iskalnik.")
            elif key == "startup":
                if value not in ("home", "restore"):
                    raise ValueError("Neznana možnost zagona.")
            elif key == "doh_provider":
                if value not in (*policy.DOH_TEMPLATES.keys(), "custom"):
                    raise ValueError("Neznan ponudnik varnega DNS.")
            elif key == "custom_doh_url":
                value = str(value or "").strip()
                if value and not policy.valid_doh_url(value):
                    raise ValueError("Naslov ponudnika DNS mora biti veljaven HTTPS URL.")
            elif key in boolean_keys:
                if not isinstance(value, bool):
                    raise ValueError("Nastavitev mora biti vklopljena ali izklopljena.")
            else:
                raise ValueError("Te nastavitve ni mogoče spreminjati.")
            settings.set(key, value, save=False)
            if not settings.save():
                raise OSError("Nastavitev ni bilo mogoče zapisati.")
            # Interceptor prebere isti SettingsStore sproti; skripte in videz
            # aktivnega zasebnega profila osvežimo na Qt GUI niti brez restarta.
            self.dispatcher.dispatch(self.browser_app.refresh_preferences)
            return self._izvedi_metodo("browserSettingsGet", [])

        if metoda == "browserClearData":
            def clear_embedded_profile():
                profile = self.browser_app.private_profile
                if profile is None:
                    return
                profile.clearHttpCache()
                profile.cookieStore().deleteAllCookies()
                profile.clearAllVisitedLinks()
                self.browser_app.closed_tabs.clear()
                for index in range(self.browser_window.tabs.count()):
                    view = self.browser_window.tabs.widget(index)
                    if isinstance(view, QWebEngineView):
                        view.page().history().clear()
            self.dispatcher.dispatch(clear_embedded_profile)
            return True

        if metoda == "celozaslonsko":
            novo = bool(a[0]) if a else not self.isFullScreen()
            self.dispatcher.dispatch(lambda: self.showFullScreen() if novo else self.showNormal())
            return novo

        if metoda == "samozagon":
            return os_backend_win.nastavi_samozagon(bool(a[0]) if a else False)

        if metoda in ("nazajVMint", "nazajVWindows", "namizje"):
            self.dispatcher.dispatch(self.showMinimized)
            return True

        if metoda == "shraniNedavneApp":
            # Nedavno odprti programi, spletne aplikacije in strani (najvec 20, najnovejsi prvi).
            seznam = a[0] if a and isinstance(a[0], list) else []
            cisti = []
            for vnos in seznam[:20]:
                if isinstance(vnos, dict) and vnos.get("kljuc") and vnos.get("ime"):
                    cisti.append({k: vnos.get(k) for k in ("kljuc", "vrsta", "ime", "id", "url", "naprava",
                                                           "ime_naprave", "ikona", "cas") if vnos.get(k) is not None})
            shramba = os_backend_win.nalozi_shrambo()
            shramba["nedavne_app"] = cisti
            os_backend_win.shrani_shrambo(shramba)
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
            return os_backend_win.pridobi_stanje_omrezja()

        if metoda == "zvok":
            return {"izhodi": [], "vhodi": [], "programi": [],
                    "link": {"naprave": [], "zvok": {}, "povezan": False}, "napredno": True}

        if metoda == "jbl":
            return {"vklop": False, "najdena": False}

        if metoda == "mediaImaKodi":
            return self.media_center.ima_kodi()

        if metoda == "mediaNaKodi":
            return self.media_center.predvajaj_na_kodi(str(a[0]) if a else "")

        if metoda == "mediaOdkrijDlna":
            from core import media_servers
            return media_servers.odkrij_dlna()

        if metoda in ("mediaZvrsti", "mediaKatalog"):
            self.media_center.izbrana_drzava = str(os_backend_win.nalozi_shrambo().get("media_watch_country") or "auto")

        if metoda == "mediaZvrsti":
            from core import zakoniti_viri
            vrsta = str(a[0]) if a else "glasba"
            if vrsta == "tv-v-zivo":
                return self.media_center.tv_drzave()
            return zakoniti_viri.zvrsti_za(vrsta)

        if metoda == "mediaKatalog":
            query = str(a[0]) if a else ""
            kind = str(a[1]) if len(a) > 1 else "vse"
            genre = str(a[2]) if len(a) > 2 else ""
            page = int(a[3]) if len(a) > 3 else 1
            # Najprej shranjeni pogled (takoj), sveze podatke posljemo kot dogodek, ko prispejo.
            razvrsti = str(a[4]) if len(a) > 4 and a[4] else ""
            izklopljeni = [str(x) for x in a[5]][:200] if len(a) > 5 and isinstance(a[5], list) else []
            samo_lokalno = bool(a[6]) if len(a) > 6 else False
            izklopljeni_jeziki = [str(x) for x in a[7]][:100] if len(a) > 7 and isinstance(a[7], list) else []
            return self.media_center.catalog_hitro(
                query, kind, genre, page,
                ob_osvezitvi=lambda kljuc, rezultat: self.poslji_dogodek("mediaKatalogOsvezen", rezultat),
                razvrsti=razvrsti, izklopljeni=izklopljeni, samo_lokalno=samo_lokalno,
                izklopljeni_jeziki=izklopljeni_jeziki)

        if metoda == "mediaPodrobnosti":
            shramba = os_backend_win.nalozi_shrambo()
            language = str(a[1] if len(a) > 1 else shramba.get("jezik") or "sl")
            return self.media_center.details(str(a[0]) if a else "",
                                             str(shramba.get("media_watch_country") or "auto"), language)

        if metoda == "mediaWatchSettings":
            shramba = os_backend_win.nalozi_shrambo()
            language = str(a[0] if a else shramba.get("jezik") or "sl")
            return self.media_center.watch_country_settings(
                str(shramba.get("media_watch_country") or "auto"), language)

        if metoda == "mediaWatchCountry":
            country = str(a[0] if a else "auto").strip().upper()
            if country != "AUTO" and not re.fullmatch(r"[A-Z]{2}", country):
                raise ValueError("Neveljavna koda države.")
            shramba = os_backend_win.nalozi_shrambo()
            shramba["media_watch_country"] = "auto" if country == "AUTO" else country
            os_backend_win.shrani_shrambo(shramba)
            return True

        if metoda == "mediaSezona":
            tmdb_id = int(a[0]) if a else 0
            season = int(a[1]) if len(a) > 1 else 1
            return self.media_center.season(tmdb_id, season)

        if metoda == "mediaEpizoda":
            tmdb_id = int(a[0]) if a else 0
            season = int(a[1]) if len(a) > 1 else 1
            episode = int(a[2]) if len(a) > 2 else 1
            title = str(a[3]) if len(a) > 3 else ""
            return self.media_center.episode_item(tmdb_id, season, episode, title)

        if metoda == "mediaFilm":
            tmdb_id = int(a[0]) if a else 0
            title = str(a[1]) if len(a) > 1 else ""
            return self.media_center.movie_item(tmdb_id, title)

        if metoda == "mediaDodajVir":
            url = str(a[0]) if a else ""
            name = str(a[1]) if len(a) > 1 else ""
            return self.media_center.add_source(url, name)

        if metoda == "mediaDodajMapo":
            return self.media_center.add_local_root(str(a[0]) if a else "")

        if metoda == "mediaDodajStreznik":
            values = [str(value or "") for value in (a[:5] if isinstance(a, list) else [])]
            values += [""] * (5 - len(values))
            return self.media_center.add_server(*values)

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
                print("[SafeerMedia] MEDIA_ROUTE missing_item", flush=True)
                return None
            url = str(item.get("url") or "")
            is_embed = (
                item.get("vrsta") == "embed" or
                "/embed/" in url.lower() or
                any(x in url.lower() for x in ("vidsrc", "vidlink", "videasy", "vidrock", "superembed", "embed.su", "multiembed", "youtube", "vimeo", "dailymotion", "streamtape", "vidbox"))
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
            host = urllib.parse.urlsplit(url).hostname or ""
            print(f"[SafeerMedia] MEDIA_ROUTE engine={self.media_engine} host={host} "
                  f"embed={is_embed} direct={is_direct_stream} native={native}", flush=True)
            if native:
                self.dispatcher.dispatch(lambda: self._odpri_media(item))
            elif is_embed and url.startswith(("http://", "https://")) and (
                    self.media_engine == "qt" or self.webview2_media.available):
                # WebView2 prejme le trenutno izbrani ponudnikov URL. Ne
                # poskušaj zaporedoma vseh ponudnikov ob enem uporabniškem kliku.
                self.dispatcher.dispatch(lambda: self._odpri_notranji_splet(url, media=True, item=item))
                native = True
            return dict(item, native=bool(native))
        if metoda == "mediaStanje":
            return {"na_voljo": True, "native": self.media_player.available,
                    "predvajalnik": "LibVLC + vgrajeni Safeer Media predvajalnik"}

        if metoda in ("odprtaOkna", "mediaNaprave"):
            return []

        return None

    def odpri_splet(self, url: str):
        url = str(url or "").strip()
        if not url:
            return False
        if not urllib.parse.urlsplit(url).scheme:
            url = "https://" + url
        if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
            return False
        if os_backend_win.je_drm_storitev(url):
            izid = os_backend_win.odpri_drm_storitev(url)
            if izid.get("zunanje"):
                return izid
        self.dispatcher.dispatch(lambda: self._odpri_notranji_splet(url))
        return True

    def odpri_spletno_iskanje(self, poizvedba: str) -> bool:
        poizvedba = str(poizvedba or "").strip()
        if not poizvedba:
            return False
        self.dispatcher.dispatch(lambda: self._odpri_spletno_iskanje(poizvedba))
        return True

    def _odpri_spletno_iskanje(self, poizvedba: str) -> None:
        # Uporabi isti resolver/nastavljeni iskalnik kot Safeer Browser, ne ločenega
        # iskalnega URL-ja. S tem ostanejo aktivni tudi njegova pravila za naslove.
        self.browser_window.set_media_mode(False)
        self.browser_window.set_safeer_os_web_mode(True)
        self.browser_window.open_input(poizvedba)
        self.zaslon.setCurrentWidget(self.browser_window)
        self.browser_window.set_safeer_os_web_mode(True)
        self.setWindowTitle("Safeer OS · Splet")

    def closeEvent(self, event) -> None:
        try:
            self.control_backend.koncaj()
        except Exception:
            pass
        try:
            if hasattr(self, "scit") and self.scit is not None:
                self.scit.koncaj()
        except Exception:
            pass
        try:
            self.webview2_media.stop()
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
    parser.add_argument("--media-engine", choices=("auto", "qt"), default="auto",
                        help=argparse.SUPPRESS)
    parser.add_argument("--ozadje", action="store_true", help="Zazeni le v ozadju")
    args = parser.parse_args(argv)

    # Browser settings are the single shared store for Safeer OS and the
    # embedded Safeer Browser. Apply restart-only Chromium/DNS options before
    # creating the WebEngine profile, then pass this exact store to the host.
    browser_settings = policy.SettingsStore()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = policy.chromium_flags(
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""), browser_settings
    )

    browser.register_schemes()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SafeerOS")
    app.setOrganizationName("Safeer")
    browser.apply_dns_mode(browser_settings)
    print(f"[SafeerOS] DIAG main_start section={args.razdelek or 'home'} media_engine={args.media_engine}", flush=True)

    zacetni = ""
    if args.control:
        zacetni = args.razdelek or "naprave"
    elif args.razdelek:
        zacetni = args.razdelek

    # Ce je izbran control razdelek ali --okno, odpri v oknu
    v_oknu = True if (args.control or args.razdelek or args.okno) else False

    window = SafeerOsWindow(v_oknu=v_oknu, zacetni_razdelek=zacetni, media_engine=args.media_engine,
                            browser_settings=browser_settings)
    print("[SafeerOS] DIAG event_loop_start", flush=True)

    if args.ozadje:
        window.control_backend.povezi_se()
        window.hide()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
