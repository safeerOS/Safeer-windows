"""Safeer Predvajalnik — samostojna aplikacija (isti pogon in isti widget kot Medijski center v Safeer OS).

Zagon: python -m safeer_windows --predvajalnik [datoteka|URL ...]
Podpira: odpiranje datotek/URL-jev (meni, argumenti, povleci-in-spusti), seznam predvajanja (N/P),
podnapise (sub-add prek pogona), celozaslon (F/dvoklik/Esc), tipke kot v Medijskem centru,
nadaljuj tam, kjer si koncal, skok na cas (Ctrl+T), zamik podnapisov/zvoka, poglavja, hitrost,
slicico po slicico in posnetek zaslona (S).
Ne vsebuje katalogov ali obvodov DRM; predvaja, kar mu uporabnik da.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox, QStatusBar)

from .safeer_mpv_okno import SafeerMpvPredvajalnik

_log = logging.getLogger("safeer.predvajalnik")
_PRIPONE_MEDIJEV = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".mp3", ".flac", ".ogg",
                    ".opus", ".wav", ".m4a", ".aac", ".mpd", ".m3u8")
_PRIPONE_PODNAPISOV = (".srt", ".vtt", ".ass", ".ssa", ".sub")


def _uri_iz(vnos: str) -> str:
    v = vnos.strip()
    if "://" in v:
        return v
    return os.path.abspath(v)


class SafeerPredvajalnikOkno(QMainWindow):
    def __init__(self, ustvari_pogon=None):
        super().__init__()
        self.setWindowTitle("Safeer Predvajalnik")
        self.resize(960, 600)
        self.setAcceptDrops(True)
        self.pred = SafeerMpvPredvajalnik(self, ustvari_pogon=ustvari_pogon)
        self.setCentralWidget(self.pred)
        self.pred.stanje_spremenjeno.connect(self._ob_stanju)
        self.setStatusBar(QStatusBar(self))
        self._meni()

    def _meni(self) -> None:
        m = self.menuBar().addMenu("&Datoteka")
        a = QAction("&Odpri datoteko…", self); a.setShortcut(QKeySequence.Open); a.triggered.connect(self.odpri_datoteko); m.addAction(a)
        a = QAction("Odpri &URL…", self); a.setShortcut("Ctrl+U"); a.triggered.connect(self.odpri_url); m.addAction(a)
        a = QAction("Naloži &podnapise…", self); a.setShortcut("Ctrl+P"); a.triggered.connect(self.nalozi_podnapise); m.addAction(a)
        m.addSeparator()
        a = QAction("&Zapri", self); a.setShortcut(QKeySequence.Quit); a.triggered.connect(self.close); m.addAction(a)
        p = self.menuBar().addMenu("&Predvajanje")
        for ime, blz, f in (("Predvajaj/premor", "Space", self.pred.premor), ("Naslednja", "N", lambda: self.pred.pogon and self.pred.pogon.naslednja()),
                            ("Prejšnja", "P", lambda: self.pred.pogon and self.pred.pogon.prejsnja()),
                            ("Od začetka", "Home", self.pred.od_zacetka),
                            ("Skok na čas…", "Ctrl+T", self.skok_na_cas),
                            ("Celozaslon", "F", self.pred.preklopi_celozaslon)):
            a = QAction(ime, self); a.setShortcut(blz); a.triggered.connect(f); p.addAction(a)
        p.addSeparator()
        h = p.addMenu("&Hitrost")
        for ime, blz, f in (("Počasneje (−0,1)", "[", lambda: self.pred.hitrost(delta=-0.1)), ("Hitreje (+0,1)", "]", lambda: self.pred.hitrost(delta=0.1)),
                            ("Običajna (1×)", "Backspace", lambda: self.pred.hitrost(1.0))):
            a = QAction(ime, self); a.setShortcut(blz); a.triggered.connect(f); h.addAction(a)
        for v in (0.5, 0.75, 1.25, 1.5, 2.0):
            a = QAction(f"{v:g}×", self); a.triggered.connect(lambda _c=False, v=v: self.pred.hitrost(v)); h.addAction(a)
        for ime, blz, f in (("Sličica naprej (premor)", ".", lambda: self.pred.slicica(1)), ("Sličica nazaj (premor)", ",", lambda: self.pred.slicica(-1)),
                            ("Posnetek zaslona (PNG)", "S", self.posnetek)):
            a = QAction(ime, self); a.setShortcut(blz); a.triggered.connect(f); p.addAction(a)
        self.meni_poglavja = self.menuBar().addMenu("Po&glavja")
        self._poglavja_kljuc = None
        nast = self.menuBar().addMenu("&Nastavitve")
        a = QAction("&Dodatki (Stremio, Kodi)…", self); a.setShortcut("Ctrl+D"); a.triggered.connect(self.odpri_dodatke); nast.addAction(a)
        self.meni_zvok = self.menuBar().addMenu("&Zvok")
        self.meni_podnapisi = self.menuBar().addMenu("Pod&napisi")
        self._steze_kljuc = None

    def _zamiki(self, meni, kaj: str, f) -> None:
        """Podmeni zamika (podnapisi ali zvok): -/+ 0,1 s, -/+ 1 s, vnos, ponastavi."""
        z = meni.addMenu("Zamik")
        for ime, blz, d in ((f"{kaj} prej (−0,1 s)", "Z" if kaj == "Podnapisi" else "K", -0.1), (f"{kaj} pozneje (+0,1 s)", "X" if kaj == "Podnapisi" else "L", 0.1),
                            ("−1 s", "Shift+Z" if kaj == "Podnapisi" else "Shift+K", -1.0), ("+1 s", "Shift+X" if kaj == "Podnapisi" else "Shift+L", 1.0)):
            a = QAction(ime, self); a.setShortcut(blz); a.triggered.connect(lambda _c=False, d=d: f(delta=d)); z.addAction(a)
        z.addSeparator()
        a = QAction("Vnesi zamik…", self); a.triggered.connect(lambda: self._vnesi_zamik(kaj, f)); z.addAction(a)
        a = QAction("Ponastavi (0 s)", self); a.triggered.connect(lambda: f(0.0)); z.addAction(a)

    def _vnesi_zamik(self, kaj: str, f) -> None:
        kljuc = "zamikPodnapisov" if kaj == "Podnapisi" else "zamikZvoka"
        trenutni = float(self.pred.zadnji_podatki.get(kljuc) or 0.0)
        v, ok = QInputDialog.getDouble(self, f"Zamik — {kaj.lower()}", "Sekunde (pozitivno = pozneje):", trenutni, -60.0, 60.0, 1)
        if ok:
            f(v)

    def skok_na_cas(self) -> None:
        from .predvajalnik_nadaljuj import razclleni_cas
        t = float(self.pred.zadnji_podatki.get("trajanje") or 0)
        if t <= 0:
            self.statusBar().showMessage("Nič se ne predvaja", 3000); return
        from .safeer_mpv_okno import _cas
        b, ok = QInputDialog.getText(self, "Skok na čas", f"Čas (h:mm:ss, mm:ss ali sekunde; trajanje {_cas(t)}):",
                                     text=_cas(float(self.pred.zadnji_podatki.get("polozaj") or 0)))
        if not ok:
            return
        sek = razclleni_cas(b)
        if sek is None:
            QMessageBox.warning(self, "Skok na čas", "Časa ni bilo mogoče razbrati (npr. 1:23:45, 23:45, 90, 1h5m)."); return
        self.pred.pojdi_na_cas(sek)

    def posnetek(self) -> None:
        pot = self.pred.posnetek()
        self.statusBar().showMessage(f"Posnetek shranjen: {pot}" if pot else "Posnetek ni uspel", 5000)

    def _osvezi_poglavja(self, p: dict) -> None:
        kljuc = (p.get("uri"), int(p.get("nPoglavij") or 0), int(p.get("poglavje", -1)))
        if kljuc == self._poglavja_kljuc:
            return
        self._poglavja_kljuc = kljuc
        m = self.meni_poglavja; m.clear()
        for ime, blz, sm in (("Prejšnje poglavje", "PgUp", -1), ("Naslednje poglavje", "PgDown", 1)):
            a = QAction(ime, self); a.setShortcut(blz); a.triggered.connect(lambda _c=False, sm=sm: self.pred.poglavje(sm)); m.addAction(a)
        pog = self.pred.pogon.poglavja() if (self.pred.pogon and kljuc[1]) else []
        if not pog:
            m.addSeparator(); a = QAction("(datoteka nima poglavij)", self); a.setEnabled(False); m.addAction(a); return
        m.addSeparator()
        from .safeer_mpv_okno import _cas
        for c in pog:
            a = QAction(f"{c['indeks'] + 1}. {c['naslov']}  ({_cas(c['cas'])})", self); a.setCheckable(True)
            a.setChecked(c["indeks"] == kljuc[2])
            a.triggered.connect(lambda _c=False, i=c["indeks"]: self.pred.pogon and self.pred.pogon.poglavje(i)); m.addAction(a)

    def _osvezi_steze(self, p: dict) -> None:
        """Meniji sledi se osvezijo le, ko se seznam sledi spremeni (ne ob vsakem tiku)."""
        s = p.get("steze") or {}
        kljuc = (tuple((t.get("indeks"), t.get("ime")) for t in s.get("zvok", [])), s.get("trenutniZvok"),
                 tuple((t.get("indeks"), t.get("ime")) for t in s.get("podnapisi", [])), s.get("trenutniPodnapis"))
        if kljuc == self._steze_kljuc:
            return
        self._steze_kljuc = kljuc
        for meni, sledi, trenutni, f in ((self.meni_zvok, s.get("zvok", []), s.get("trenutniZvok"), lambda i: self.pred.pogon.nastavi_zvok(i)),
                                        (self.meni_podnapisi, s.get("podnapisi", []), s.get("trenutniPodnapis"), lambda i: self.pred.pogon.nastavi_podnapis(i))):
            meni.clear()
            for t in sledi:
                a = QAction(str(t.get("ime", "")), self); a.setCheckable(True); a.setChecked(t.get("indeks") == trenutni)
                a.triggered.connect(lambda _c=False, i=t.get("indeks"), f=f: f(i)); meni.addAction(a)
            meni.addSeparator()
            if meni is self.meni_podnapisi:
                a = QAction("Naloži podnapise…", self); a.triggered.connect(self.nalozi_podnapise); meni.addAction(a)
                self._zamiki(meni, "Podnapisi", self.pred.zamik_podnapisov)
            else:
                self._zamiki(meni, "Zvok", self.pred.zamik_zvoka)

    # ---- odpiranje ----
    def odpri(self, vnosi: list[str]) -> int:
        if not self.pred.pogon_pripravljen():
            QMessageBox.critical(self, "Safeer Predvajalnik", "Predvajalni pogon (libmpv) ni na voljo.")
            return 0
        n = 0
        for i, v in enumerate(vnosi):
            uri = _uri_iz(v)
            if uri.lower().endswith(_PRIPONE_PODNAPISOV):
                self.pred.pogon.nalozi_podnapis(uri); continue
            self.pred.pogon.dodaj(uri, predvajaj=(n == 0), naslov=os.path.basename(uri) if "://" not in uri else uri)
            n += 1
        if n:
            self.statusBar().showMessage(f"Dodano: {n}", 3000)
        return n

    def odpri_datoteko(self) -> None:
        filt = "Mediji (" + " ".join("*" + p for p in _PRIPONE_MEDIJEV) + ");;Vse datoteke (*)"
        poti, _ = QFileDialog.getOpenFileNames(self, "Odpri", "", filt)
        if poti:
            self.odpri(poti)

    def odpri_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Odpri URL", "Naslov (http/https):")
        if ok and url.strip():
            if not url.strip().lower().startswith(("http://", "https://")):
                QMessageBox.warning(self, "Odpri URL", "Dovoljeni so le http/https naslovi."); return
            self.odpri([url.strip()])

    def odpri_dodatke(self) -> None:
        from .predvajalnik_dodatki_okno import DodatkiOkno
        okno = DodatkiOkno(self)
        if okno.exec():
            n = okno.nastavitve
            self.statusBar().showMessage(f"Dodatki shranjeni: Stremio {len(n['stremio_dodatki'])}, Kodi {len(n['kodi_dodatki'])}", 4000)

    def nalozi_podnapise(self) -> None:
        pot, _ = QFileDialog.getOpenFileName(self, "Podnapisi", "", "Podnapisi (*.srt *.vtt *.ass *.ssa *.sub)")
        if pot and self.pred.pogon:
            if not self.pred.pogon.nalozi_podnapis(pot):
                self.statusBar().showMessage("Podnapisov ni bilo mogoče naložiti", 4000)

    # ---- povleci in spusti ----
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        vnosi = []
        for u in e.mimeData().urls():
            if u.isLocalFile():
                vnosi.append(u.toLocalFile())
            elif u.scheme() in ("http", "https"):
                vnosi.append(u.toString())
        if vnosi:
            self.odpri(vnosi)

    # ---- stanje ----
    def _ob_stanju(self, p: dict) -> None:
        self._osvezi_steze(p)
        self._osvezi_poglavja(p)
        naslov = p.get("naslov") or ""
        self.setWindowTitle(f"{naslov} — Safeer Predvajalnik" if naslov else "Safeer Predvajalnik")

    def closeEvent(self, e) -> None:
        self.pred.zapri()
        super().closeEvent(e)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    logging.basicConfig(level=os.environ.get("SAFEER_LOG", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = QApplication.instance() or QApplication(argv)
    okno = SafeerPredvajalnikOkno()
    okno.show()
    vnosi = [a for a in argv[1:] if not a.startswith("-")]
    if vnosi:
        QTimer.singleShot(50, lambda: okno.odpri(vnosi))
    ms = os.environ.get("SAFEER_TEST_ZAPRI_MS")
    if ms:
        QTimer.singleShot(int(ms), okno.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
