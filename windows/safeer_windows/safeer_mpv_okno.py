"""Safeer mpv okno — Qt gostitelj za SafeerMpvPogon (skupna koda za Medijski center v Safeer OS
in samostojni predvajalnik).

Vgradnja: mpv izrisuje v lastno (podrejeno) nativno okno prek rocaja `wid`. Zato:
- SafeerMpvVideo je nativni QWidget (WA_NativeWindow), brez lastnega risanja ozadja;
- prekrivni gumbi NAD videom niso zanesljivi (podrejeno nativno okno je nad Qt-jevimi otroki),
  zato je upravljalna vrstica POD videom in se v celozaslonu skrije/prikaze ob premiku miske;
- vsi klici v pogon so v GUI niti; sporocila iz mpv niti (sprememba/konec/napaka) se v GUI nit
  posredujejo prek Qt signalov (QueuedConnection), nikoli neposredno.
Tipke: presledek = premor, <- -> = 5 s, Shift = 30 s, F / dvoklik = celozaslon, Esc = izhod
iz celozaslona, M = utisaj, +/- = glasnost, N/P = naslednja/prejsnja.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

_log = logging.getLogger("safeer.mpv.okno")


class _Most(QObject):
    """Prenese klice iz mpv niti v GUI nit (Qt signali so nitno varni)."""
    sprememba = Signal(dict)
    konec = Signal()
    napaka = Signal(str)


class SafeerMpvVideo(QWidget):
    """Nativna povrsina za mpv (wid). Ne rise nicesar sama."""
    dvoklik = Signal()
    klik = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background:#000;")
        self.setMinimumSize(160, 90)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def wid(self) -> int:
        return int(self.winId())

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.dvoklik.emit()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self.klik.emit()
        self.setFocus()


class SafeerMpvPredvajalnik(QWidget):
    """Video + upravljalna vrstica; lastnik pogona. `pogon` je SafeerMpvPogon (ali None ob napaki)."""
    stanje_spremenjeno = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None, ustvari_pogon=None):
        super().__init__(parent)
        self._most = _Most()
        self._most.sprememba.connect(self._ob_spremembi, Qt.QueuedConnection)
        self._most.konec.connect(self._ob_koncu, Qt.QueuedConnection)
        self._most.napaka.connect(self._ob_napaki, Qt.QueuedConnection)
        self._celozaslon_prej: Optional[QWidget] = None
        self._drsnik_vlecen = False
        self.pogon = None
        self.zadnji_podatki: dict = {}

        self.video = SafeerMpvVideo(self)
        self.video.dvoklik.connect(self.preklopi_celozaslon)
        self.video.klik.connect(self._prikazi_vrstico)

        self.vrstica = QWidget(self)
        v = QHBoxLayout(self.vrstica); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(8)
        self.gumb_predvajaj = QPushButton("⏵"); self.gumb_predvajaj.setFixedWidth(36)
        self.gumb_predvajaj.clicked.connect(self.premor)
        self.oznaka_cas = QLabel("0:00 / 0:00"); self.oznaka_cas.setMinimumWidth(100)
        self.drsnik = QSlider(Qt.Horizontal); self.drsnik.setRange(0, 1000)
        self.drsnik.sliderPressed.connect(lambda: setattr(self, "_drsnik_vlecen", True))
        self.drsnik.sliderReleased.connect(self._drsnik_spuscen)
        self.gumb_celozaslon = QPushButton("⛶"); self.gumb_celozaslon.setFixedWidth(36)
        self.gumb_celozaslon.clicked.connect(self.preklopi_celozaslon)
        self.oznaka_naslov = QLabel(""); self.oznaka_naslov.setStyleSheet("color:#bbb;")
        for w in (self.gumb_predvajaj, self.oznaka_cas, self.drsnik, self.oznaka_naslov, self.gumb_celozaslon):
            v.addWidget(w)
        v.setStretch(2, 1)

        self._postavitev = QVBoxLayout(self); self._postavitev.setContentsMargins(0, 0, 0, 0); self._postavitev.setSpacing(0)
        self._postavitev.addWidget(self.video, 1)
        self._postavitev.addWidget(self.vrstica, 0)
        self.setStyleSheet("SafeerMpvPredvajalnik{background:#000;}")
        self.vrstica.setStyleSheet("QWidget{background:#111;} QLabel{color:#ddd;} QPushButton{color:#eee;background:#333;border:1px solid #555;border-radius:4px;padding:2px;} QPushButton:hover{background:#444;}")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self._skrij_casovnik = QTimer(self); self._skrij_casovnik.setSingleShot(True); self._skrij_casovnik.setInterval(2500)
        self._skrij_casovnik.timeout.connect(self._skrij_vrstico_ce_celozaslon)

        self._ustvari_pogon = ustvari_pogon
        # Pogon ustvarimo, ko ima video nativno okno (po show). Do takrat je None.
        QTimer.singleShot(0, self._pripravi_pogon)

    # ---- pogon ----
    def _pripravi_pogon(self) -> None:
        if self.pogon is not None:
            return
        try:
            if self._ustvari_pogon is not None:
                self.pogon = self._ustvari_pogon(lambda p=None: self._most.sprememba.emit(p or {}), self._most.konec.emit,
                                                 lambda s="": self._most.napaka.emit(str(s)))
            else:
                from .safeer_mpv_pogon import SafeerMpvPogon
                self.pogon = SafeerMpvPogon(lambda p=None: self._most.sprememba.emit(p or {}), self._most.konec.emit,
                                            lambda s="": self._most.napaka.emit(str(s)))
            self.pogon.povezi_video(self.video.wid())
            _log.info("mpv pogon povezan z wid=%s", self.video.wid())
        except Exception as e:
            self.pogon = None
            _log.error("mpv pogona ni mogoce ustvariti: %s", e)
            self._most.napaka.emit(f"pogon: {e}")

    def pogon_pripravljen(self) -> bool:
        return self.pogon is not None

    # ---- javni ukazi (GUI nit) ----
    def odpri(self, uri: str, naslov: str = "") -> bool:
        if not self.pogon:
            return False
        self.pogon.dodaj(uri, predvajaj=True, naslov=naslov)
        return True

    @Slot()
    def premor(self) -> None:
        if self.pogon:
            self.pogon.premor()

    def skok(self, sekunde: float) -> None:
        if self.pogon:
            self.pogon.skok(sekunde)

    @Slot()
    def preklopi_celozaslon(self) -> None:
        if self.je_celozaslon():
            self._iz_celozaslona()
        else:
            self._v_celozaslon()

    def _v_celozaslon(self) -> None:
        # Video widget se NIKOLI ne prestarsi (na X11 bi Qt ustvaril novo nativno okno, wid bi se
        # spremenil in mpv bi risal v osirotelo staro okno). Namesto tega gre v celozaslon VRHNJE okno,
        # vsi sorodniki na poti do njega pa se skrijejo.
        okno = self.window()
        if self._celozaslon_prej is not None:
            return
        self._celozaslon_stanje = okno.windowState()
        self._celozaslon_geo = okno.geometry() if not (okno.windowState() & Qt.WindowMaximized) else None
        skriti: list[QWidget] = []
        w: QWidget = self
        while w is not okno and w.parentWidget() is not None:
            stars = w.parentWidget()
            for otrok in stars.children():
                if isinstance(otrok, QWidget) and otrok is not w and not otrok.isWindow() and otrok.isVisible():
                    otrok.hide(); skriti.append(otrok)
            w = stars
        self._celozaslon_skriti = skriti
        self._celozaslon_prej = okno
        okno.showFullScreen()
        self.setFocus()
        self._prikazi_vrstico()

    def _iz_celozaslona(self) -> None:
        okno = self._celozaslon_prej
        if okno is None:
            return
        self._celozaslon_prej = None
        for w in getattr(self, "_celozaslon_skriti", []):
            try:
                w.show()
            except Exception:
                pass
        self._celozaslon_skriti = []
        stanje = getattr(self, "_celozaslon_stanje", None)
        if stanje is not None and (stanje & Qt.WindowMaximized):
            okno.showMaximized()
        else:
            okno.showNormal()
            geo = getattr(self, "_celozaslon_geo", None)
            if geo is not None:
                # Nekateri upravljalniki oken (Cinnamon) po showNormal vrnejo drugacno velikost.
                QTimer.singleShot(0, lambda: okno.setGeometry(geo))
        self.vrstica.show()
        self.setFocus()

    def je_celozaslon(self) -> bool:
        return self._celozaslon_prej is not None

    def zapri(self) -> None:
        if self.pogon:
            try:
                self.pogon.zapri()
            except Exception:
                pass
            self.pogon = None

    # ---- dogodki ----
    def keyPressEvent(self, e: QKeyEvent) -> None:
        k, m = e.key(), e.modifiers()
        korak = 30 if (m & Qt.ShiftModifier) else 5
        if k == Qt.Key_Space: self.premor(); self._osd("⏸ Premor" if self.zadnji_podatki.get("stanje") == "predvaja" else "⏵ Predvajanje")
        elif k == Qt.Key_Right: self.skok(korak); self._osd(f"▶ +{korak} s")
        elif k == Qt.Key_Left: self.skok(-korak); self._osd(f"◀ −{korak} s")
        elif k == Qt.Key_F: self.preklopi_celozaslon()
        elif k == Qt.Key_Escape and self.je_celozaslon(): self._iz_celozaslona()
        elif k == Qt.Key_M and self.pogon: self.pogon.utisaj(); self._osd("🔇 Utišano" if not self.zadnji_podatki.get("utisan") else "🔊 Zvok")
        elif k in (Qt.Key_Plus, Qt.Key_Equal) and self.pogon:
            g = min(100, int(self.zadnji_podatki.get("glasnost", 80)) + 5); self.pogon.nastavi_glasnost(g); self._osd(f"🔊 {g} %")
        elif k == Qt.Key_Minus and self.pogon:
            g = max(0, int(self.zadnji_podatki.get("glasnost", 80)) - 5); self.pogon.nastavi_glasnost(g); self._osd(f"🔉 {g} %")
        elif k == Qt.Key_N and self.pogon: self.pogon.naslednja()
        elif k == Qt.Key_P and self.pogon: self.pogon.prejsnja()
        else:
            super().keyPressEvent(e); return
        e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self._prikazi_vrstico()
        super().mouseMoveEvent(e)

    def _prikazi_vrstico(self) -> None:
        self.vrstica.show()
        if self.je_celozaslon():
            self._skrij_casovnik.start()

    def _skrij_vrstico_ce_celozaslon(self) -> None:
        if self.je_celozaslon() and not self._drsnik_vlecen:
            self.vrstica.hide()

    def _osd(self, besedilo: str) -> None:
        if self.pogon and hasattr(self.pogon, "osd"):
            self.pogon.osd(besedilo)

    def _drsnik_spuscen(self) -> None:
        self._drsnik_vlecen = False
        if self.pogon:
            self.pogon.pojdi_na(self.drsnik.value() / 1000.0)

    # ---- sporocila iz pogona (GUI nit) ----
    @Slot(dict)
    def _ob_spremembi(self, p: Optional[dict] = None) -> None:
        if not self.pogon:
            return
        try:
            if self.pogon.obdelaj_konec():
                p = None
        except Exception as e:
            _log.debug("obdelaj_konec: %s", e)
        if not p:
            try:
                p = self.pogon.podatki()
            except Exception as e:
                _log.debug("podatki(): %s", e); return
        self.zadnji_podatki = p
        self.gumb_predvajaj.setText("⏸" if p.get("stanje") == "predvaja" else "⏵")
        self.oznaka_cas.setText(f"{_cas(p.get('polozaj', 0))} / {_cas(p.get('trajanje', 0))}")
        self.oznaka_naslov.setText(str(p.get("naslov", ""))[:60])
        if not self._drsnik_vlecen and p.get("trajanje"):
            self.drsnik.setValue(int(1000 * float(p.get("polozaj", 0)) / float(p["trajanje"])))
        self.stanje_spremenjeno.emit(p)

    @Slot()
    def _ob_koncu(self) -> None:
        self._ob_spremembi(None)

    @Slot(str)
    def _ob_napaki(self, s: str) -> None:
        _log.warning("mpv napaka: %s", s)
        self.oznaka_naslov.setText(f"Napaka: {s}"[:80])


def _cas(s) -> str:
    try:
        s = int(float(s or 0))
    except Exception:
        s = 0
    h, m, sek = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sek:02d}" if h else f"{m}:{sek:02d}"
