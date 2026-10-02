"""Splet na WebView2 (Windows): pogledi zavihkov, ki jih rise sistemski WebView2 namesto Qt WebEngine.

Zakaj: uradna gradnja Qt WebEngine nima licencnih zapisov H.264/AAC in DRM; WebView2 (del Windows) jih ima, zato
strani predvajajo video na mestu (RTV 365, arhivi televizij, pretocne storitve). Qt ostane lupina: zavihki,
naslovna vrstica, scit, zacetna stran, bliznjice. Vse zavihke drzi en pomozni proces
(`SafeerMediaWebView.exe --splet`, windows/webview2_host/SpletHost.cs); s Pythonom se pogovarja z vrsticami JSON
po stdin/stdout.

`WvView` in `WvPage` imata isti vmesnik, kot ga okno brskalnika uporablja pri QWebEngineView/QWebEnginePage
(url, title, load, back, signali ...), zato je logika okna ena sama za oba pogona. Brez WebView2 Runtime ali brez
pomoznega programa (`na_voljo()` vrne False) Splet tece na Qt WebEngine kot prej.
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QWidget

from . import policy

# Dejanja mostu, ki jih sme sproziti katerakoli stran (stevec oglasov, obvestilo o videu); vse drugo samo safeer://.
_JAVNA_DEJANJA = ("increment_ads", "media_unsupported")


def izvrsljiva() -> Path:
    return Path(__file__).resolve().parents[1] / "SafeerMediaWebView.exe"


def runtime_razlicica() -> str:
    """Razlicica namescenega WebView2 Runtime ('' = ni namescen). Na Windows 11 je del sistema."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    kljuc = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for koren, pot in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + kljuc),
                       (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + kljuc),
                       (winreg.HKEY_CURRENT_USER, "Software\\" + kljuc)):
        try:
            with winreg.OpenKey(koren, pot) as k:
                vrednost, _ = winreg.QueryValueEx(k, "pv")
        except OSError:
            continue
        if vrednost and str(vrednost) != "0.0.0.0":
            return str(vrednost)
    return ""


def na_voljo() -> bool:
    return sys.platform == "win32" and izvrsljiva().is_file() and bool(runtime_razlicica())


def odlocitev_navigacije(url: str, uporabnik: bool, preusmeritev: bool, adblock_vklopljen: bool, sledenje_vklopljeno: bool):
    """Odlocitev za navigacijo glavnega okvirja - ista pravila kot BrowserWindow.accept_navigation (Qt).

    Vrne (dovoli, dejanje); dejanje je None ali (vrsta, cilj, razlog): vrsta "load" = nalozi cilj (stran z opozorilom,
    naslov brez sledilnih parametrov), "ad" = oglasna stran (pojavno okno se zapre). Cista funkcija (testi).
    """
    ad = policy.adblock
    if ad.is_passthrough_host(url):
        return True, None
    if ad.is_threat_domain(url):
        return False, ("load", policy.blocked_page_url(url), "block-threat")
    banka = ad.fake_bank_verdict(url)
    if banka is not None:
        return False, ("load", policy.fake_bank_page_url(url, banka), "block-threat")
    if adblock_vklopljen and ad.is_ad_domain(url):
        return False, ("ad", "", "block-ad")
    if sledenje_vklopljeno and uporabnik and not preusmeritev:
        ociscen = ad.strip_tracking_parameters(url)
        if ociscen != url:
            return False, ("load", ociscen, "")
    return True, None


class Gostitelj(QObject):
    """En pomozni proces z vsemi zavihki enega profila (navaden ali zaseben)."""

    dogodek = Signal(dict)   # iz bralne niti v nit vmesnika

    def __init__(self, app, zasebno: bool):
        super().__init__(app)
        self.app = app
        self.zasebno = zasebno
        self.proces: Optional[subprocess.Popen] = None
        self.pripravljen = False
        self.odpovedal = False
        self.razlicica = ""
        self.pogledi: Dict[str, "WvView"] = {}
        self._stevec = itertools.count(1)
        self._zaklep = threading.Lock()
        self._caka: List[dict] = []                    # ukazi pred "ready"
        self._klici: Dict[str, Callable[[Any], None]] = {}
        self.dogodek.connect(self._v_niti_vmesnika)

    # -- zagon -----------------------------------------------------------------
    def zazeni(self) -> bool:
        if self.proces is not None:
            return not self.odpovedal
        koren = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "SafeerOS"
        profil = koren / ("WebView2SpletZasebno" if self.zasebno else "WebView2Splet")
        args = [str(izvrsljiva()), "--splet", f"--profile={profil}", f"--private={'1' if self.zasebno else '0'}"]
        # Jezik okenc WebView2 (prenosi, dovoljenja, meni desnega klika) sledi jeziku Safeerja.
        jezik = self.app.lang
        vir = getattr(self.app, "jezik_vmesnika", None)
        if vir is not None:
            try:
                jezik = str(vir())[:2] or jezik
            except Exception:
                pass
        args.append(f"--lang={jezik}")
        zastavice = []
        if self.app.settings.get("force_dark_mode"):
            zastavice.append("--enable-features=WebContentsForceDark")
        if zastavice:
            args.append("--flags=" + " ".join(zastavice))
        try:
            self.proces = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self.odpovedal = True
            return False
        threading.Thread(target=self._beri, name="safeer-splet-webview2", daemon=True).start()
        self.nastavi()
        return True

    def nastavi(self) -> None:
        """Skripte Safeerja (scit, YouTube ...), zasebnostni glavi in pripeta potrdila - ob zagonu in ob spremembi nastavitev."""
        skripte = [{"source": spec["source"], "start": bool(spec["at_start"])} for spec in policy.script_specs(self.app.settings)]
        from . import browser
        self._pisi({"cmd": "config", "scripts": skripte, "gpc": bool(self.app.settings.get("gpc_dnt_enabled")),
                    "trusted": sorted(str(x).upper() for x in browser.ZAUPANA_POTRDILA)})

    def nov_id(self) -> str:
        return f"z{next(self._stevec)}"

    # -- pisanje ---------------------------------------------------------------
    def _pisi(self, sporocilo: dict) -> None:
        proces = self.proces
        if proces is None or proces.stdin is None or proces.poll() is not None:
            return
        try:
            with self._zaklep:
                proces.stdin.write((json.dumps(sporocilo, ensure_ascii=False) + "\n").encode("utf-8"))
                proces.stdin.flush()
        except (OSError, ValueError):
            pass

    def poslji(self, **sporocilo) -> None:
        if not self.pripravljen:
            self._caka.append(sporocilo)
            return
        self._pisi(sporocilo)

    def izvedi(self, zavihek: str, js: str, klic: Optional[Callable[[Any], None]] = None) -> None:
        oznaka = ""
        if klic is not None:
            oznaka = f"k{next(self._stevec)}"
            self._klici[oznaka] = klic
        self.poslji(cmd="exec", tab=zavihek, id=oznaka, js=js)

    def ustavi(self) -> None:
        proces, self.proces = self.proces, None
        if proces is None:
            return
        try:
            if proces.stdin is not None:
                proces.stdin.close()     # gostitelj se ob koncu stdin ugasne sam
            proces.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proces.kill()
            except OSError:
                pass

    # -- branje (pomozna nit) --------------------------------------------------
    def _beri(self) -> None:
        proces = self.proces
        if proces is None or proces.stdout is None:
            return
        try:
            for surova in proces.stdout:
                try:
                    m = json.loads(surova.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                ev = m.get("ev")
                # Vprasanja gostitelja odgovorimo kar tu (hitro, brez niti vmesnika): stran medtem caka.
                if ev == "request":
                    self._odgovori_zahtevo(m)
                elif ev == "resource":
                    self._odgovori_vir(m)
                elif ev == "nav":
                    self._odgovori_navigacijo(m)
                else:
                    self.dogodek.emit(m)
        except (OSError, ValueError):
            pass
        self.dogodek.emit({"ev": "exit"})

    def _odgovori_zahtevo(self, m: dict) -> None:
        url = str(m.get("url") or "")
        try:
            odlocitev = policy.request_decision(url, False, str(m.get("first") or ""), bool(self.app.settings.get("adblock_enabled")))
        except Exception:
            odlocitev = "allow"
        self._pisi({"cmd": "reply", "id": m.get("id"), "block": odlocitev != "allow"})
        if odlocitev != "allow":
            self.dogodek.emit({"ev": "blocked", "url": url, "decision": odlocitev})

    def _odgovori_vir(self, m: dict) -> None:
        mime, podatki = "", b""
        try:
            deli = urllib.parse.urlsplit(str(m.get("url") or ""))
            izid = policy.scheme_resource(deli.hostname or "", deli.path, deli.query, self.app.lang)
            if izid is not None:
                mime, podatki = izid
        except Exception:
            pass
        self._pisi({"cmd": "reply", "id": m.get("id"), "mime": mime, "data": base64.b64encode(podatki).decode("ascii")})

    def _odgovori_navigacijo(self, m: dict) -> None:
        url = str(m.get("url") or "")
        try:
            dovoli, dejanje = odlocitev_navigacije(url, bool(m.get("user")), bool(m.get("redirect")),
                                                   bool(self.app.settings.get("adblock_enabled")),
                                                   bool(self.app.settings.get("tracking_protection_enabled")))
        except Exception:
            dovoli, dejanje = True, None
        self._pisi({"cmd": "reply", "id": m.get("id"), "allow": dovoli})
        self.dogodek.emit({"ev": "navblocked", "tab": m.get("tab"), "url": url, "dejanje": list(dejanje)} if dejanje
                          else {"ev": "committed", "tab": m.get("tab")})

    # -- dogodki (nit vmesnika) ------------------------------------------------
    def _v_niti_vmesnika(self, m: dict) -> None:
        ev = m.get("ev")
        if ev in ("ready", "created", "tabfailed", "error", "fatal", "exit", "orphan", "crashed"):
            # Kratek dnevnik zivljenja zavihkov (v safeer_os.log) - brez naslovov strani.
            print(f"[SafeerSplet] {ev} zavihek={m.get('tab', '')} {str(m.get('detail') or m.get('kind') or m.get('version') or '')[:200]}", flush=True)
        if ev == "ready":
            self.pripravljen = True
            self.razlicica = str(m.get("version") or "")
            cakajoci, self._caka = self._caka, []
            for sporocilo in cakajoci:
                self._pisi(sporocilo)
            return
        if ev in ("fatal", "exit"):
            if self.proces is not None or ev == "fatal":
                self.odpovedal = True
                print(f"[SafeerSplet] WebView2 gostitelj se je ustavil: {m.get('detail', ev)}", flush=True)
                for pogled in list(self.pogledi.values()):
                    pogled.gostitelj_ugasnil()
            return
        if ev == "result":
            klic = self._klici.pop(str(m.get("id") or ""), None)
            if klic is not None:
                try:
                    vrednost = json.loads(m.get("value") or "null")
                except ValueError:
                    vrednost = None
                try:
                    klic(vrednost)
                except Exception:
                    pass
            return
        if ev == "blocked":
            try:
                self.app.note_blocked(str(m.get("url") or ""), str(m.get("decision") or ""))
            except Exception:
                pass
            return
        pogled = self.pogledi.get(str(m.get("tab") or ""))
        if pogled is not None:
            pogled.obdelaj(m)


class _Zgodovina:
    def __init__(self, pogled: "WvView"):
        self._pogled = pogled

    def canGoBack(self) -> bool:
        return self._pogled._nazaj

    def canGoForward(self) -> bool:
        return self._pogled._naprej

    def clear(self) -> None:
        pass


class _Nastavitve:
    def setAttribute(self, *_args) -> None:
        pass


class _Celozaslon:
    """Enak vmesnik kot QWebEngineFullScreenRequest (toggleOn, accept)."""

    def __init__(self, vklop: bool):
        self._vklop = vklop

    def toggleOn(self) -> bool:
        return self._vklop

    def accept(self) -> None:
        pass


class WvPage(QObject):
    linkHovered = Signal(str)
    fullScreenRequested = Signal(object)
    renderProcessTerminated = Signal(object, int)
    windowCloseRequested = Signal()

    def __init__(self, pogled: "WvView", okno):
        super().__init__(pogled)
        self._pogled = pogled
        self.window_ref = okno
        self.opened_as_popup = False
        self.committed_navigation = False
        self._nastavitve = _Nastavitve()

    def url(self) -> QUrl:
        return self._pogled.url()

    def title(self) -> str:
        return self._pogled.title()

    def load(self, url: QUrl) -> None:
        self._pogled.load(url)

    def runJavaScript(self, js: str, *args) -> None:
        klic = next((a for a in args if callable(a)), None)
        self._pogled.gostitelj.izvedi(self._pogled.tab, js, klic)

    def findText(self, besedilo: str, *zastavice) -> None:
        nazaj = "true" if zastavice else "false"
        self.runJavaScript(f"window.find({json.dumps(besedilo)}, false, {nazaj}, true, false, true, false)")

    def triggerAction(self, dejanje) -> None:
        akcije = QWebEnginePage.WebAction
        if dejanje == akcije.ExitFullScreen:
            self.runJavaScript("document.fullscreenElement && document.exitFullscreen()")
        elif dejanje in (akcije.ReloadAndBypassCache, akcije.Reload):
            self._pogled.reload()

    def lifecycleState(self):
        return QWebEnginePage.LifecycleState.Active

    def recommendedState(self):
        return QWebEnginePage.LifecycleState.Active

    def setLifecycleState(self, _stanje) -> None:
        pass

    def settings(self) -> _Nastavitve:
        return self._nastavitve

    def devToolsPage(self):
        return None

    def setDevToolsPage(self, _stran) -> None:
        pass

    def setFeaturePermission(self, *_args) -> None:
        pass


class WvView(QWidget):
    titleChanged = Signal(str)
    urlChanged = Signal(QUrl)
    loadStarted = Signal()
    loadFinished = Signal(bool)
    iconChanged = Signal(QIcon)

    def __init__(self, parent: QWidget, gostitelj: Gostitelj, okno, zahteva: str = ""):
        super().__init__(parent)
        # Lastno nativno okno (vanj se vstavi WebView2), brez spreminjanja prednikov v nativna okna.
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setStyleSheet("background:#070b12;")
        self.gostitelj = gostitelj
        self.tab = gostitelj.nov_id()
        self._url = QUrl()
        self._naslov = ""
        self._nazaj = False
        self._naprej = False
        self._povecava = 1.0
        self._zahteva = zahteva
        self._zacetni = ""
        self._ustvarjen = False
        self._zaprt = False
        self._page = WvPage(self, okno)
        self._zgodovina = _Zgodovina(self)
        gostitelj.pogledi[self.tab] = self
        # Zavihek v gostitelju ustvarimo, ko je pogled ze na svojem mestu v oknu (Qt ga ob vstavitvi lahko prestavi).
        QTimer.singleShot(0, self._ustvari)

    def _ustvari(self) -> None:
        if self._ustvarjen or self._zaprt:
            return
        self._ustvarjen = True
        self.gostitelj.poslji(cmd="create", tab=self.tab, parent=int(self.winId()), url=self._zacetni, req=self._zahteva)

    # -- vmesnik QWebEngineView -------------------------------------------------
    def page(self) -> WvPage:
        return self._page

    def setPage(self, _stran) -> None:
        pass

    def url(self) -> QUrl:
        return QUrl(self._url)

    def title(self) -> str:
        return self._naslov

    def history(self) -> _Zgodovina:
        return self._zgodovina

    def load(self, url: QUrl) -> None:
        besedilo = url.toString() if isinstance(url, QUrl) else str(url)
        if not besedilo:
            return
        if not self._ustvarjen:
            self._zacetni = besedilo
            self._url = QUrl(besedilo)
            return
        self.gostitelj.poslji(cmd="navigate", tab=self.tab, url=besedilo)

    setUrl = load

    def reload(self) -> None:
        self.gostitelj.poslji(cmd="reload", tab=self.tab)

    def stop(self) -> None:
        self.gostitelj.poslji(cmd="stop", tab=self.tab)

    def back(self) -> None:
        self.gostitelj.poslji(cmd="back", tab=self.tab)

    def forward(self) -> None:
        self.gostitelj.poslji(cmd="forward", tab=self.tab)

    def zoomFactor(self) -> float:
        return self._povecava

    def setZoomFactor(self, faktor: float) -> None:
        self._povecava = float(faktor)
        self.gostitelj.poslji(cmd="zoom", tab=self.tab, factor=self._povecava)

    def setFocus(self, *args) -> None:
        super().setFocus(*args)
        self.gostitelj.poslji(cmd="focus", tab=self.tab)

    def odpri_orodja(self) -> None:
        self.gostitelj.poslji(cmd="devtools", tab=self.tab)

    def odpri_prenose(self) -> None:
        """Okence prenosov WebView2 (prenose vodi WebView2: mapa Prenosi, napredek, »Odpri datoteko«)."""
        self.gostitelj.poslji(cmd="downloads", tab=self.tab)

    def pocisti_podatke(self) -> None:
        self.gostitelj.poslji(cmd="cleardata", tab=self.tab)

    def ponastavi_dovoljenja(self) -> None:
        """Odlocitve »Dovoli« / »Blokiraj« (kamera, mikrofon, lokacija ...) za odprto stran nazaj na »vprasaj«."""
        self.gostitelj.poslji(cmd="resetperm", tab=self.tab)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._ustvarjen:
            self.gostitelj.poslji(cmd="fit", tab=self.tab)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._ustvarjen:
            self.gostitelj.poslji(cmd="fit", tab=self.tab)

    def zapri(self) -> None:
        if self._zaprt:
            return
        self._zaprt = True
        self.gostitelj.pogledi.pop(self.tab, None)
        if self._ustvarjen:
            self.gostitelj.poslji(cmd="close", tab=self.tab)
        elif self._zahteva:
            self.gostitelj.poslji(cmd="dropwindow", req=self._zahteva)

    def gostitelj_ugasnil(self) -> None:
        self._page.renderProcessTerminated.emit(None, 1)

    # -- dogodki gostitelja ------------------------------------------------------
    def obdelaj(self, m: dict) -> None:
        ev = m.get("ev")
        if ev == "url":
            self._url = QUrl(str(m.get("url") or ""))
            self.urlChanged.emit(QUrl(self._url))
        elif ev == "title":
            self._naslov = str(m.get("title") or "")
            self.titleChanged.emit(self._naslov)
        elif ev == "loading":
            if m.get("on"):
                self.loadStarted.emit()
            else:
                self.loadFinished.emit(bool(m.get("ok")))
        elif ev == "history":
            self._nazaj, self._naprej = bool(m.get("back")), bool(m.get("forward"))
            okno = self._page.window_ref
            if okno is not None:
                okno.update_nav_state()
        elif ev == "icon":
            slika = QPixmap()
            try:
                if slika.loadFromData(base64.b64decode(str(m.get("png") or ""))):
                    self.iconChanged.emit(QIcon(slika))
            except (ValueError, TypeError):
                pass
        elif ev == "fullscreen":
            self._page.fullScreenRequested.emit(_Celozaslon(bool(m.get("on"))))
        elif ev == "closerequested":
            self._page.windowCloseRequested.emit()
        elif ev == "crashed":
            self._page.renderProcessTerminated.emit(None, 1)
        elif ev == "committed":
            self._page.committed_navigation = True
        elif ev == "gotfocus":
            okno = self._page.window_ref
            if okno is not None:
                okno.wv_fokus_v_strani()
        elif ev == "message":
            sporocilo = policy.parse_bridge_message(str(m.get("data") or ""))
            if sporocilo is None:
                return
            # Dejanja lupine (bliznjice, jezik, navigacija z zacetne strani) samo s strani Safeerja.
            if sporocilo.get("action") not in _JAVNA_DEJANJA and not str(m.get("source") or "").startswith("safeer://"):
                return
            okno = self._page.window_ref
            if okno is not None:
                okno.app.on_bridge_message(self._page, sporocilo)
        else:
            okno = self._page.window_ref
            if okno is not None:
                okno.wv_dogodek(self, m)
