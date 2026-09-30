"""Safeer mpv okno — Qt gostitelj za SafeerMpvPogon (skupna koda za Medijski center v Safeer OS
in samostojni predvajalnik).

Vgradnja: mpv izrisuje v lastno (podrejeno) nativno okno prek rocaja `wid`. Zato:
- SafeerMpvVideo je nativni QWidget (WA_NativeWindow), brez lastnega risanja ozadja;
- prekrivni gumbi NAD videom niso zanesljivi (podrejeno nativno okno je nad Qt-jevimi otroki),
  zato je upravljalna vrstica POD videom in se v celozaslonu skrije/prikaze ob premiku miske;
- vsi klici v pogon so v GUI niti; sporocila iz mpv niti (sprememba/konec/napaka) se v GUI nit
  posredujejo prek Qt signalov (QueuedConnection), nikoli neposredno.
Tipke: presledek = premor, <- -> = 5 s, Shift = 30 s, F / dvoklik = celozaslon, Esc = izhod
iz celozaslona, M = utisaj, +/- = glasnost, N/P = naslednja/prejsnja, Home = od zacetka,
Z/X = podnapisi -/+ 0,1 s (Shift: 1 s), K/L = zvok -/+ 0,1 s, PgUp/PgDn = poglavje, [ ] = hitrost,
Backspace = hitrost 1x, , . = slicica nazaj/naprej (premor), S = posnetek zaslona (PNG v Slike).

Nadaljuj tam, kjer si koncal: polozaj se belezi vsakih ~5 s (predvajalnik_nadaljuj), ob zaprtju in ob
premoru; ob ponovnem odprtju istega naslova se predvajanje zacne tam (OSD to pove). Izklop:
SAFEER_NADALJUJ=0.
"""
from __future__ import annotations

import logging
import os
import time
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
        from .predvajalnik_nadaljuj import Sledilec
        self._nadaljuj = Sledilec()
        self._zadnji_uri = ""
        self.mpris = None            # predvajalnik_mpris.SafeerMpris (Linux), po _pripravi_pogon
        self.ime_za_sistem = "Safeer Predvajalnik"   # Identity za MPRIS/SMTC; Medijski center nastavi svoje

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
            self._pripravi_nadaljevanje()
            self._pripravi_mpris()
            _log.info("mpv pogon povezan z wid=%s", self.video.wid())
        except Exception as e:
            self.pogon = None
            _log.error("mpv pogona ni mogoce ustvariti: %s", e)
            self._most.napaka.emit(f"pogon: {e}")

    def pogon_pripravljen(self) -> bool:
        return self.pogon is not None

    # ---- nadaljuj tam, kjer si koncal (logika v predvajalnik_nadaljuj.Sledilec) ----
    def _pripravi_nadaljevanje(self) -> None:
        try:
            self._nadaljuj.povezi(self.pogon)
        except Exception as e:
            _log.warning("nadaljevanje ni na voljo: %s", e)

    def _pripravi_mpris(self) -> None:
        if os.environ.get("SAFEER_MPRIS", "1") == "0":
            return
        try:
            from .predvajalnik_mpris import SafeerMpris
            m = SafeerMpris(self.pogon, ime=self.ime_za_sistem, okno=self.window())
            self.mpris = m if m.aktiven else None
        except Exception as e:
            _log.debug("mpris: %s", e)

    def _seeked(self) -> None:
        if self.mpris:
            self.mpris.oddaj_seeked()

    def od_zacetka(self) -> None:
        if self.pogon:
            self.pogon.pojdi_na(0.0); self._osd("⏮ Od začetka")

    # ---- javni ukazi (GUI nit) ----
    def odpri(self, uri: str, naslov: str = "") -> bool:
        if not self.pogon:
            return False
        self.pogon.dodaj(uri, predvajaj=True, naslov=naslov)
        return True

    @Slot()
    def premor(self) -> None:
        if not self.pogon:
            return
        p = self.zadnji_podatki
        if p.get("stanje") == "ustavljeno" and int(p.get("indeks", -1)) >= 0 and int(p.get("nSeznam") or 0):
            self.pogon.predvajaj(int(p["indeks"]))   # po koncu datoteke (keep-open) gumb ⏵ predvaja znova
            return
        self.pogon.premor()

    def skok(self, sekunde: float) -> None:
        if self.pogon:
            self.pogon.skok(sekunde); self._seeked()

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
        if self.mpris:
            try:
                self.mpris.zapri()
            except Exception:
                pass
            self.mpris = None
        if self.pogon:
            try:
                self._nadaljuj.zabelezi(self.zadnji_podatki, takoj=True)
            except Exception:
                pass
            try:
                self.pogon.zapri()
            except Exception:
                pass
            self.pogon = None

    # ---- dogodki ----
    def keyPressEvent(self, e: QKeyEvent) -> None:
        k, m = e.key(), e.modifiers()
        korak = 30 if (m & Qt.ShiftModifier) else 5
        if k in (Qt.Key_MediaPlay, Qt.Key_MediaPause, Qt.Key_MediaTogglePlayPause): self.premor()
        elif k == Qt.Key_MediaStop and self.pogon: self.pogon.ustavi()
        elif k == Qt.Key_MediaNext and self.pogon: self.pogon.naslednja()
        elif k == Qt.Key_MediaPrevious and self.pogon: self.pogon.prejsnja()
        elif k == Qt.Key_Space: self.premor(); self._osd("⏸ Premor" if self.zadnji_podatki.get("stanje") == "predvaja" else "⏵ Predvajanje")
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
        elif k == Qt.Key_Home: self.od_zacetka()
        elif k in (Qt.Key_Z, Qt.Key_X) and self.pogon:
            d = (1.0 if (m & Qt.ShiftModifier) else 0.1) * (1 if k == Qt.Key_X else -1); self.zamik_podnapisov(delta=d)
        elif k in (Qt.Key_K, Qt.Key_L) and self.pogon:
            d = (1.0 if (m & Qt.ShiftModifier) else 0.1) * (1 if k == Qt.Key_L else -1); self.zamik_zvoka(delta=d)
        elif k == Qt.Key_PageDown and self.pogon: self.poglavje(1)
        elif k == Qt.Key_PageUp and self.pogon: self.poglavje(-1)
        elif k == Qt.Key_BracketRight and self.pogon: self.hitrost(delta=0.1)
        elif k == Qt.Key_BracketLeft and self.pogon: self.hitrost(delta=-0.1)
        elif k == Qt.Key_Backspace and self.pogon: self.hitrost(1.0)
        elif k == Qt.Key_Period and self.pogon: self.slicica(1)
        elif k == Qt.Key_Comma and self.pogon: self.slicica(-1)
        elif k == Qt.Key_S and not (m & Qt.ControlModifier): self.posnetek()
        else:
            super().keyPressEvent(e); return
        e.accept()

    # ---- napredni ukazi (skupni za tipke in menije) ----
    def zamik_podnapisov(self, sekunde: Optional[float] = None, delta: float = 0.0) -> float:
        if not self.pogon:
            return 0.0
        z = self.pogon.zamik_podnapisov(sekunde, delta); self._osd(f"Podnapisi: {z:+.1f} s"); return z

    def zamik_zvoka(self, sekunde: Optional[float] = None, delta: float = 0.0) -> float:
        if not self.pogon:
            return 0.0
        z = self.pogon.zamik_zvoka(sekunde, delta); self._osd(f"Zvok: {z:+.1f} s"); return z

    def poglavje(self, smer: int) -> None:
        if not self.pogon:
            return
        if not int(self.zadnji_podatki.get("nPoglavij") or 0):
            self._osd("Ni poglavij"); return
        self.pogon.naslednje_poglavje(smer)
        QTimer.singleShot(150, self._osd_poglavje)

    def _osd_poglavje(self) -> None:
        p = self.zadnji_podatki; i = int(p.get("poglavje", -1)); n = int(p.get("nPoglavij") or 0)
        if n and i >= 0:
            pog = self.pogon.poglavja() if self.pogon else []
            ime = pog[i]["naslov"] if 0 <= i < len(pog) else ""
            self._osd(f"Poglavje {i + 1}/{n} {ime}".strip())

    def pojdi_na_cas(self, sekunde: float) -> bool:
        if not self.pogon:
            return False
        t = float(self.zadnji_podatki.get("trajanje") or 0)
        if t <= 0:
            return False
        sekunde = max(0.0, min(float(sekunde), t))
        self.pogon.pojdi_na(sekunde / t); self._osd(f"⏩ {_cas(sekunde)}"); self._seeked(); return True

    def hitrost(self, vrednost: Optional[float] = None, delta: float = 0.0) -> float:
        if not self.pogon:
            return 1.0
        h = float(vrednost) if vrednost is not None else float(self.zadnji_podatki.get("hitrost") or 1.0) + delta
        h = max(0.25, min(4.0, round(h, 2)))
        self.pogon.nastavi_hitrost(h); self._osd(f"Hitrost {h:g}×"); return h

    def slicica(self, smer: int) -> None:
        if self.pogon:
            self.pogon.slicica(smer); self._osd("⏭ sličica" if smer > 0 else "⏮ sličica")

    def posnetek(self, pot: Optional[str] = None) -> Optional[str]:
        """PNG trenutne slike (brez OSD) v uporabnikovo mapo Slike (ali podano pot)."""
        if not self.pogon:
            return None
        if not pot:
            try:
                from PySide6.QtCore import QStandardPaths
                mapa = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or os.path.expanduser("~")
            except Exception:
                mapa = os.path.expanduser("~")
            mapa = os.path.join(mapa, "Safeer")
            os.makedirs(mapa, exist_ok=True)
            pot = os.path.join(mapa, time.strftime("safeer-%Y%m%d-%H%M%S") + ".png")
        if self.pogon.posnetek(pot):
            self._osd("📷 " + os.path.basename(pot)); return pot
        self._osd("Posnetek ni uspel"); return None

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

    def _osd(self, besedilo: str, ms: int = 1200) -> None:
        if self.pogon and hasattr(self.pogon, "osd"):
            self.pogon.osd(besedilo, ms)

    def _drsnik_spuscen(self) -> None:
        self._drsnik_vlecen = False
        if self.pogon:
            self.pogon.pojdi_na(self.drsnik.value() / 1000.0); self._seeked()

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
        uri = str(p.get("uri") or "")
        if uri != self._zadnji_uri:
            self._zadnji_uri = uri
            zp = float(getattr(self.pogon, "zacel_pri", 0.0) or 0.0)
            if uri and zp > 0:
                self._osd(f"⏵ Nadaljujem od {_cas(zp)}", 2500)
        try:
            self._nadaljuj.ob_podatkih(p)
        except Exception as e:
            _log.debug("nadaljuj: %s", e)
        if self.mpris:
            self.mpris.ob_podatkih(p)
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
