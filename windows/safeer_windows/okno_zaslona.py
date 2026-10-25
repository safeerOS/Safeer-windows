"""Zaslon druge naprave (telefon, tablica) v svojem oknu Safeer OS - z misko, tipkovnico, kolescem in odloziscem.

Lastnik, 25. 10. 2026 (fotografija 07:08): »Odpri tukaj« aplikacije s telefona se je odprl kot zavihek Spleta
(https://<telefon>:8990/cast/screen/<id>/view?k=...) in miska ter tipkovnica aplikacije nista upravljali. Na Linuxu ima
gledalec svoje okno z vbrizganim vnosom (safeer_control.py _odpri_gledalca, GLEDALEC_VNOS_JS); logika vnosa je zdaj v
core/gledalec_vnos.py, ta modul je okno za Windows:

- svoje okno brez okvirja v barvah teme sistema: naslov = aplikacija · naprava, svoj gumb v opravilni vrstici,
  Nazaj / Domov / Odprte aplikacije / Obvestila, celozaslonsko (F11), zapri; okno se prilagodi obliki slike naprave;
- vnos: skripta je v LOCENEM svetu skript (QWebEngineScript.ApplicationWorld) - stran s sredisca je ne vidi in ne more
  poslati lazni dotik (zeton v zaprtju skripte, samo e.isTrusted). Klik/poteg/kolesce/tipke/Ctrl+V gredo po Safeer
  Linku samo napravi, katere zaslon okno kaze (control_backend.poslji_vnos);
- ce naprava vnosa ne sprejme (Safeer Vnos ni vklopljen), okno to pove z natancnim imenom in ponudi gumb, ki napravo
  prosi, naj odpre nastavitve dostopnosti (obstojece dejanje `input.enable`);
- zaprtje okna napravi pove, naj neha deliti zaslon (`apps.close` s `stream: true`, kot Linux);
- potrdilo strani sprejmemo samo z odtisom, ki ga je dal Safeer Link; kljuc ogleda (?k=) nikoli ne gre v dnevnik.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import threading
from typing import Optional

from core import gledalec_vnos as gv

PREDPONA = "__safeer_vnos__:"

try:  # Qt je na Windows vedno; preizkusi brez QtWebEngine uvozijo samo ciste dele.
    from PySide6.QtCore import QPoint, QRect, Qt, QUrl
    from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[assignment,misc]
    QWebEnginePage = object  # type: ignore[assignment,misc]


def poslji_js(zeton: str) -> str:
    """Telo funkcije poslji(d, p) za Qt WebEngine: izpis v konzolo z zetonom (most okna, glej _StranZaslona)."""
    return ('try { console.log(%s + JSON.stringify({z: %s, d: d, p: p})); } catch (e) {}'
            % (json.dumps(PREDPONA), json.dumps(zeton)))


def razberi(sporocilo: str, zeton: str):
    """Izpis v konzolo -> (dejanje, parametri) ali None (ni nas izpis, napacen zeton ali neveljavno dejanje)."""
    if not isinstance(sporocilo, str) or not sporocilo.startswith(PREDPONA):
        return None
    try:
        podatki = json.loads(sporocilo[len(PREDPONA):])
    except ValueError:
        return None
    if not isinstance(podatki, dict):
        return None
    z = podatki.get("z")
    if not isinstance(z, str) or not hmac.compare_digest(z.encode(), str(zeton).encode()):
        return None
    return gv.preveri(podatki)


def naslov_okna(ime_programa: str, ime_naprave: str, jezik: str = "sl") -> str:
    ime_programa, ime_naprave = str(ime_programa or "").strip(), str(ime_naprave or "").strip()
    if ime_programa and ime_naprave:
        return "%s · %s" % (ime_programa, ime_naprave)
    return "%s · %s" % (ime_naprave or "Safeer Link", gv.t("zaslon", jezik))


def odtis_potrdila(der: bytes) -> str:
    return hashlib.sha256(bytes(der)).hexdigest()


class _StranZaslona(QWebEnginePage):  # type: ignore[misc]
    """Stran gledalca: potrdilo samo s pripetim odtisom, brez novih oken, brez navigacije drugam; most vnosa."""

    def __init__(self, profile, okno: "OknoZaslona") -> None:
        super().__init__(profile, okno)
        self._okno = okno
        self.setBackgroundColor(QColor("#000000"))
        try:
            self.certificateError.connect(self._potrdilo)
        except Exception:  # noqa: BLE001
            pass

    def _potrdilo(self, napaka) -> None:
        try:
            veriga = napaka.certificateChain()
            if veriga and self._okno.odtis and hmac.compare_digest(odtis_potrdila(veriga[0].toDer()), self._okno.odtis):
                napaka.acceptCertificate()
                return
            napaka.rejectCertificate()
        except Exception:  # noqa: BLE001
            pass

    def createWindow(self, _vrsta):  # noqa: N802 - Qt
        return None

    def acceptNavigationRequest(self, url, _vrsta, glavni) -> bool:  # noqa: N802 - Qt
        if not glavni:
            return True
        u = url.toString()
        return u == "about:blank" or self._okno.isti_izvor(u)

    def javaScriptConsoleMessage(self, _raven, sporocilo: str, _vrstica: int, _vir: str) -> None:  # noqa: N802
        izid = razberi(sporocilo, self._okno.zeton)
        if izid is not None:
            self._okno.vnos(*izid)
        # Drugih izpisov strani ne pisemo v dnevnik (naslov s kljucem ogleda bi lahko bil v njih).


class _Glava(QWidget):  # type: ignore[misc]
    """Naslovna vrstica okna brez okvirja: vlecenje premakne okno, dvoklik poveca."""

    def __init__(self, okno: "OknoZaslona") -> None:
        super().__init__(okno)
        self._okno = okno

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._okno.windowHandle() is not None:
            self._okno.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, _e) -> None:  # noqa: N802
        self._okno.preklopi_povecavo()


class OknoZaslona(QWidget):  # type: ignore[misc]
    ROB = 5          # sirina roba za spreminjanje velikosti (okno brez okvirja)
    VISINA_GLAVE = 40

    def __init__(self, os_okno, cb, jezik: str = "sl") -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.os_okno, self.cb, self.jezik = os_okno, cb, jezik
        self.zeton = secrets.token_urlsafe(24)
        self.odtis = ""
        self.naprava = ""
        self._izvor = ""
        self._zapiram = False
        self._velikost_slike = ""
        self._vrsta: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._posiljaj, name="safeer-vnos-zaslona", daemon=True).start()
        self.setMouseTracking(True)
        self.setMinimumSize(380, 320)
        try:
            self.setWindowIcon(os_okno.windowIcon())
        except Exception:  # noqa: BLE001
            pass
        self._zgradi()
        self.cb.ob_odzivu_vnosa = lambda o: self.os_okno.dispatcher.dispatch(lambda: self.pokazi_odziv(o))

    # ------------------------------------------------------------------ videz
    def _paleta(self) -> dict:
        try:
            from . import tema
            return dict(tema.paleta())
        except Exception:  # noqa: BLE001
            return {}

    def _zgradi(self) -> None:
        p = self._paleta()
        ozadje, besedilo = p.get("vnos", "#121d2d"), p.get("besedilo", "#eaf2ff")
        poudarek = p.get("poudarek", "#8ac7ff")
        self.setStyleSheet(
            "#OknoZaslona { background: %s; border: 1px solid rgba(255,255,255,0.14); }"
            "QLabel#naslov { color: %s; font-size: 13px; font-weight: 600; }"
            "QLabel#namig { color: #fde68a; font-size: 12px; }"
            "QPushButton { color: %s; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14);"
            " border-radius: 13px; padding: 3px 10px; font-size: 13px; min-height: 20px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.16); }"
            "QPushButton#zapri:hover { background: #c42b1c; }"
            "QPushButton#nastavitve { color: #0b1424; background: %s; border: none; }"
            % (ozadje, besedilo, besedilo, poudarek))
        self.setObjectName("OknoZaslona")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        postavitev = QVBoxLayout(self)
        postavitev.setContentsMargins(self.ROB, self.ROB, self.ROB, self.ROB)
        postavitev.setSpacing(0)
        self.glava = _Glava(self)
        self.glava.setFixedHeight(self.VISINA_GLAVE)
        g = QHBoxLayout(self.glava)
        g.setContentsMargins(10, 4, 4, 4)
        g.setSpacing(6)
        self.naslov = QLabel(self.glava)
        self.naslov.setObjectName("naslov")
        self.naslov.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        g.addWidget(self.naslov, 1)
        for znak, kljuc, tipka in (("◁", "nazaj", "back"), ("○", "domov", "home"), ("▢", "opravila", "recents"),
                                   ("🔔", "obvestila", "notifications")):
            b = QPushButton(znak, self.glava)
            b.setToolTip(gv.t(kljuc, self.jezik))
            b.setAccessibleName(gv.t(kljuc, self.jezik))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=tipka: self.vnos("input.key", {"key": k}))
            g.addWidget(b)
        self.gumb_celo = QPushButton("⛶", self.glava)
        self.gumb_celo.setToolTip(gv.t("celozaslonsko", self.jezik))
        self.gumb_celo.setAccessibleName(gv.t("celozaslonsko", self.jezik))
        self.gumb_celo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gumb_celo.clicked.connect(self.preklopi_celozaslonsko)
        g.addWidget(self.gumb_celo)
        zapri = QPushButton("✕", self.glava)
        zapri.setObjectName("zapri")
        zapri.setToolTip(gv.t("zapri", self.jezik))
        zapri.setAccessibleName(gv.t("zapri", self.jezik))
        zapri.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zapri.clicked.connect(self.close)
        g.addWidget(zapri)
        postavitev.addWidget(self.glava)
        # Opozorilo pod glavo (npr. Safeer Vnos ni vklopljen) z gumbom, ki napravo prosi, naj odpre nastavitve.
        self.vrstica_namiga = QWidget(self)
        n = QHBoxLayout(self.vrstica_namiga)
        n.setContentsMargins(10, 6, 8, 8)
        n.setSpacing(8)
        self.namig = QLabel(self.vrstica_namiga)
        self.namig.setObjectName("namig")
        self.namig.setWordWrap(True)
        n.addWidget(self.namig, 1)
        self.gumb_nastavitve = QPushButton(gv.t("odpriNastavitve", self.jezik), self.vrstica_namiga)
        self.gumb_nastavitve.setObjectName("nastavitve")
        self.gumb_nastavitve.clicked.connect(self.odpri_nastavitve_naprave)
        self.gumb_nastavitve.hide()
        n.addWidget(self.gumb_nastavitve, 0, Qt.AlignmentFlag.AlignVCenter)
        self.vrstica_namiga.hide()
        postavitev.addWidget(self.vrstica_namiga)
        self.pogled = QWebEngineView(self)
        self.pogled.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.stran = _StranZaslona(self.os_okno.profile, self)
        skripta = QWebEngineScript()
        skripta.setName("SafeerVnosZaslona")
        skripta.setSourceCode(gv.skripta(poslji_js(self.zeton)))
        skripta.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        skripta.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)    # locen svet: stran ga ne vidi
        skripta.setRunsOnSubFrames(False)
        self.stran.scripts().insert(skripta)
        self.pogled.setPage(self.stran)
        postavitev.addWidget(self.pogled, 1)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self.preklopi_celozaslonsko,
                  context=Qt.ShortcutContext.WindowShortcut)

    # ------------------------------------------------------------------ deljenje
    def isti_izvor(self, url: str) -> bool:
        u = QUrl(url)
        return bool(self._izvor) and "%s://%s:%d" % (u.scheme(), u.host(), u.port(443)) == self._izvor

    def pokazi_deljenje(self, url: str, odtis: str, naprava: str, ime_naprave: str, ime_programa: str = "") -> None:
        """Zacetek deljenja (share.screen start): stran gledalca v tem oknu. Kljuca iz naslova ne zapisemo nikamor."""
        u = QUrl(url)
        self._izvor = "%s://%s:%d" % (u.scheme(), u.host(), u.port(443))
        self.odtis = str(odtis or "").replace(":", "").lower()
        self.naprava = str(naprava or "")
        self._velikost_slike = ""
        self.pokazi_odziv({"ok": True})
        self.setWindowTitle(naslov_okna(ime_programa, ime_naprave, self.jezik))
        self.naslov.setText(self.windowTitle())
        if not self.isVisible():
            g = QGuiApplication.primaryScreen().availableGeometry()
            s, v = min(520, g.width()), min(int(g.height() * 0.9), 980)
            self.setGeometry(g.x() + (g.width() - s) // 2, g.y() + (g.height() - v) // 2, s, v)
        self.stran.load(u)
        self.show()
        self.raise_()
        self.activateWindow()
        self.pogled.setFocus()

    def koncano_na_napravi(self) -> None:
        """Naprava je deljenje koncala: zadnje slike ne pustimo na zaslonu; napravi ne posiljamo nicesar."""
        self._zapiram = True
        try:
            self.stran.load(QUrl("about:blank"))
            if self.isFullScreen():
                self.showNormal()
            self.hide()
        finally:
            self._zapiram = False
        self.naprava = ""

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._zapiram and self.naprava:
            try:
                self.cb.koncaj_gledanje(self.naprava)       # uporabnik je zaprl okno: naprava naj neha deliti
            except Exception as napaka:  # noqa: BLE001
                print(f"[SafeerOS zaslon] konec gledanja: {napaka}", flush=True)
        self.naprava = ""
        self.stran.load(QUrl("about:blank"))
        if self.isFullScreen():
            self.showNormal()
        e.accept()

    # ------------------------------------------------------------------ vnos
    def vnos(self, dejanje: str, parametri: dict) -> None:
        if dejanje == "okno.velikost":
            self._prilagodi(parametri.get("w"), parametri.get("h"))
            return
        if dejanje == "odlozisce.prilepi":
            p = gv.besedilo_iz_odlozisca(QGuiApplication.clipboard().text())
            if p is None:
                return
            dejanje, parametri = "input.text", p
        if not self.naprava or not dejanje.startswith("input."):
            return
        self._vrsta.put((self.naprava, dejanje, dict(parametri)))

    def _posiljaj(self) -> None:
        """Vnos po vrsti v svoji niti (omrezje ne zadrzi okna; tap pred besedilom ostane tap pred besedilom)."""
        while True:
            naprava, dejanje, parametri = self._vrsta.get()
            if naprava != self.cb.gledani_zaslon:
                continue                                 # dotik je bil za napravo, ki je okno ne kaze vec
            try:
                if not self.cb.poslji_vnos(dejanje, parametri):
                    print(f"[SafeerOS zaslon] vnos {dejanje} ni bil poslan (ni povezave)", flush=True)
            except Exception as napaka:  # noqa: BLE001
                print(f"[SafeerOS zaslon] vnos {dejanje}: {napaka}", flush=True)

    def pokazi_odziv(self, odgovor: dict) -> None:
        besedilo, gumb = gv.odziv(odgovor, self.jezik)
        if odgovor.get("ok") and not besedilo:
            if self.namig.text() == gv.t("nastavitveOdprte", self.jezik):
                return                                   # ostane, dokler uporabnik ne vklopi Safeer Vnos
        self.namig.setText(besedilo)
        self.vrstica_namiga.setVisible(bool(besedilo))
        self.gumb_nastavitve.setVisible(gumb)
        if besedilo:
            print(f"[SafeerOS zaslon] naprava vnosa ne sprejme: {odgovor.get('koda') or '?'}", flush=True)

    def odpri_nastavitve_naprave(self) -> None:
        """Gumb ob opozorilu: naprava sama odpre nastavitve dostopnosti (dejanje input.enable, Safeer Vnos)."""
        self.vnos("input.enable", {})
        self.namig.setText(gv.t("nastavitveOdprte", self.jezik))
        self.gumb_nastavitve.hide()

    # ------------------------------------------------------------------ okno
    def _prilagodi(self, w, h) -> None:
        kljuc = "%sx%s" % (w, h)
        if kljuc == self._velikost_slike or self.isFullScreen() or self.isMaximized():
            return
        self._velikost_slike = kljuc
        g = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        nova = gv.velikost_okna(w, h, (g.x(), g.y(), g.width(), g.height()), rob_zgoraj=self.VISINA_GLAVE + 2 * self.ROB,
                                najmanj_sirina=self.minimumWidth())
        if nova is not None:
            self.setGeometry(QRect(*nova))

    def preklopi_celozaslonsko(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.glava.show()
        else:
            self.glava.hide()
            self.showFullScreen()

    def preklopi_povecavo(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.preklopi_celozaslonsko()
            return
        super().keyPressEvent(e)

    def _robovi(self, tocka: "QPoint"):
        r, w, h = self.ROB, self.width(), self.height()
        robovi = Qt.Edge(0)
        if tocka.x() <= r:
            robovi |= Qt.Edge.LeftEdge
        if tocka.x() >= w - r:
            robovi |= Qt.Edge.RightEdge
        if tocka.y() <= r:
            robovi |= Qt.Edge.TopEdge
        if tocka.y() >= h - r:
            robovi |= Qt.Edge.BottomEdge
        return robovi

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        robovi = self._robovi(e.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if robovi in (L | T, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif robovi in (R | T, L | B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif robovi & (L | R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif robovi & (T | B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        robovi = self._robovi(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and robovi != Qt.Edge(0) and self.windowHandle() is not None:
            self.windowHandle().startSystemResize(robovi)


def odpri(os_okno, podatki: dict, ime_programa: str = "", jezik: str = "sl") -> Optional["OknoZaslona"]:
    """share.screen start -> okno zaslona (eno samo; novo deljenje ga zamenja). None brez Qt WebEngine."""
    if not _QT:
        return None
    url = str(podatki.get("url") or "")
    if not url.startswith("https://"):
        return None
    cb = os_okno.control_backend
    naprava = str(podatki.get("naprava") or cb.gledani_zaslon or "")
    ime = str(podatki.get("od") or "")
    for n in (cb.naprave or []):
        if str(n.get("id") or "") == naprava:
            ime = str(n.get("ime") or n.get("name") or ime)
            break
    okno = getattr(os_okno, "okno_zaslona", None)
    if okno is None:
        okno = os_okno.okno_zaslona = OknoZaslona(os_okno, cb, jezik)
    okno.pokazi_deljenje(url, str(podatki.get("odtis") or ""), naprava, ime, ime_programa)
    return okno
