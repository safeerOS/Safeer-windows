"""Okno »Brskaj po dodatkih (Stremio)« za samostojni predvajalnik: dodatek → katalog (+ iskanje) → vnos
(→ epizode pri serijah) → tok → predvajaj. Omrezje tece v niti (QThreadPool); okno ostane odzivno.
Vrne izbrani tok prek `izbrani_tok` = {"url", "naslov", "glave", "podnapisi"}."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import predvajalnik_nastavitve as N
from .stremio_dodatki import StremioDodatek, predvajljiv

_log = logging.getLogger("safeer.stremio.okno")


class _Most(QObject):
    """En objekt v lasti okna: opravila v niti javijo (rod, rezultat, napaka); okno dobi klic v GUI niti."""
    koncano = Signal(int, object, object)


class _Opravilo(QRunnable):
    def __init__(self, most: _Most, rod: int, f, *a):
        super().__init__(); self.most, self.rod, self.f, self.a = most, rod, f, a

    def run(self) -> None:
        try:
            r = self.f(*self.a); self.most.koncano.emit(self.rod, r, None)
        except Exception as e:  # noqa: BLE001
            self.most.koncano.emit(self.rod, None, e)


class StremioOkno(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, nastavitve: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Brskaj po dodatkih (Stremio)")
        self.resize(820, 560)
        self.nastavitve = nastavitve or N.nalozi()
        self.izbrani_tok: Optional[dict] = None
        self._dodatek: Optional[StremioDodatek] = None
        self._vnosi: list = []
        self._videi: list = []
        self._tokovi: list = []
        self._rod = 0
        self._po = None
        self._bazen = QThreadPool.globalInstance()
        self._most = _Most(self); self._most.koncano.connect(self._koncano, Qt.QueuedConnection)

        k = QVBoxLayout(self)
        vrstica = QHBoxLayout()
        self.dodatki = QComboBox()
        for d in self.nastavitve.get("stremio_dodatki") or []:
            self.dodatki.addItem(str(d.get("ime") or d.get("naslov")), d.get("naslov"))
        self.katalogi = QComboBox()
        self.iskanje = QLineEdit(); self.iskanje.setPlaceholderText("Iskanje v katalogu (Enter)")
        self.gumb_isci = QPushButton("Išči")
        for w in (QLabel("Dodatek:"), self.dodatki, QLabel("Katalog:"), self.katalogi, self.iskanje, self.gumb_isci):
            vrstica.addWidget(w)
        vrstica.setStretch(1, 2); vrstica.setStretch(3, 2); vrstica.setStretch(4, 3)
        k.addLayout(vrstica)

        sredina = QHBoxLayout()
        self.seznam = QListWidget(); self.seznam.setMinimumWidth(260)
        self.epizode = QListWidget(); self.epizode.setMinimumWidth(200)
        self.tokovi = QListWidget()
        for naslov, w in (("Vnosi", self.seznam), ("Epizode", self.epizode), ("Tokovi", self.tokovi)):
            stolpec = QVBoxLayout(); stolpec.addWidget(QLabel(naslov)); stolpec.addWidget(w); sredina.addLayout(stolpec)
        k.addLayout(sredina, 1)

        self.opis = QLabel(""); self.opis.setWordWrap(True); self.opis.setStyleSheet("color:#aaa;")
        k.addWidget(self.opis)
        self.stanje = QLabel(N.BESEDILA["opomba"]); self.stanje.setStyleSheet("color:#888;")
        spodaj = QHBoxLayout(); spodaj.addWidget(self.stanje, 1)
        self.gumb_predvajaj = QPushButton("Predvajaj"); self.gumb_predvajaj.setEnabled(False)
        self.gumb_zapri = QPushButton("Zapri")
        spodaj.addWidget(self.gumb_predvajaj); spodaj.addWidget(self.gumb_zapri)
        k.addLayout(spodaj)

        self.dodatki.currentIndexChanged.connect(self._nalozi_dodatek)
        self.katalogi.currentIndexChanged.connect(lambda _i: self._nalozi_katalog())
        self.iskanje.returnPressed.connect(self._nalozi_katalog); self.gumb_isci.clicked.connect(self._nalozi_katalog)
        self.seznam.currentRowChanged.connect(self._izbran_vnos)
        self.epizode.currentRowChanged.connect(self._izbrana_epizoda)
        self.tokovi.currentRowChanged.connect(self._izbran_tok)
        self.tokovi.itemDoubleClicked.connect(lambda _i: self._predvajaj())
        self.gumb_predvajaj.clicked.connect(self._predvajaj); self.gumb_zapri.clicked.connect(self.reject)

        if self.dodatki.count():
            self._nalozi_dodatek(0)
        else:
            self.stanje.setText("Ni dodatkov. Vnesi jih v Nastavitve ▸ Dodatki (Stremio, Kodi)… (Ctrl+D).")

    # ---- pomocniki ----
    def _v_niti(self, f, *a, po=None) -> None:
        self._rod += 1; self._po = po
        self._bazen.start(_Opravilo(self._most, self._rod, f, *a))

    @Slot(int, object, object)
    def _koncano(self, rod: int, r, e) -> None:
        if rod != self._rod:   # zastarel odgovor (uporabnik je medtem izbral kaj drugega)
            return
        if e is not None:
            self.stanje.setText(f"Napaka: {e}"); _log.warning("stremio: %s", e); return
        if self._po is not None:
            self._po(r)

    def _sporoci(self, b: str) -> None:
        self.stanje.setText(b)

    # ---- koraki ----
    def _nalozi_dodatek(self, i: int) -> None:
        naslov = self.dodatki.itemData(i)
        if not naslov:
            return
        self.katalogi.blockSignals(True); self.katalogi.clear(); self.katalogi.blockSignals(False)
        self.seznam.clear(); self.epizode.clear(); self.tokovi.clear(); self.gumb_predvajaj.setEnabled(False)
        d = StremioDodatek(str(naslov)); self._dodatek = d
        self._sporoci("Nalagam manifest …")
        self._v_niti(d.nalozi_manifest, po=self._manifest_nalozen)

    def _manifest_nalozen(self, _m) -> None:
        d = self._dodatek
        self.katalogi.blockSignals(True); self.katalogi.clear()
        for kat in d.katalogi():
            self.katalogi.addItem(f"{kat['ime']} ({kat['tip']})", kat)
        self.katalogi.blockSignals(False)
        self._sporoci(f"{d.ime}: {self.katalogi.count()} katalogov, viri: {', '.join(sorted(d.viri())) or '–'}")
        if self.katalogi.count():
            self._nalozi_katalog()

    def _nalozi_katalog(self) -> None:
        kat = self.katalogi.currentData(); d = self._dodatek
        if not kat or not d:
            return
        iskanje = self.iskanje.text().strip()
        if kat.get("obvezniFiltri") and not (iskanje and "search" in kat["obvezniFiltri"] and len(kat["obvezniFiltri"]) == 1):
            self._sporoci("Ta katalog zahteva filter: " + ", ".join(kat["obvezniFiltri"]) + (" — vnesi iskanje." if "search" in kat["obvezniFiltri"] else ""))
            self.seznam.clear(); return
        self.seznam.clear(); self.epizode.clear(); self.tokovi.clear(); self.gumb_predvajaj.setEnabled(False)
        self._sporoci("Nalagam katalog …")
        self._v_niti(d.katalog, kat["tip"], kat["id"], iskanje, po=self._katalog_nalozen)

    def _katalog_nalozen(self, vnosi: list) -> None:
        self._vnosi = vnosi
        self.seznam.clear()
        for v in vnosi:
            it = QListWidgetItem(v["ime"] + (f"  ({v['leto']})" if v.get("leto") else "")); it.setToolTip(v.get("opis") or ""); self.seznam.addItem(it)
        self._sporoci(f"{len(vnosi)} vnosov")

    def _izbran_vnos(self, vrstica: int) -> None:
        self.epizode.clear(); self.tokovi.clear(); self.gumb_predvajaj.setEnabled(False)
        if not (0 <= vrstica < len(self._vnosi)) or not self._dodatek:
            return
        v = self._vnosi[vrstica]; self.opis.setText(v.get("opis") or "")
        d = self._dodatek
        if "meta" in d.viri():
            self._sporoci("Nalagam podatke …")
            self._v_niti(d.meta, v["tip"], v["id"], po=lambda m: self._meta_nalozena(v, m))
        else:
            self._meta_nalozena(v, {"videi": []})

    def _meta_nalozena(self, v: dict, m: dict) -> None:
        self._videi = m.get("videi") or []
        if m.get("opis"):
            self.opis.setText(m["opis"])
        self.epizode.clear()
        if self._videi:
            for e in self._videi:
                oznaka = f"S{e['sezona']}E{e['epizoda']} " if e.get("sezona") is not None and e.get("epizoda") is not None else ""
                self.epizode.addItem(oznaka + e["ime"])
            self._sporoci(f"{len(self._videi)} epizod — izberi epizodo")
        else:
            self._nalozi_tokove(v["tip"], v["id"], v["ime"])

    def _izbrana_epizoda(self, vrstica: int) -> None:
        if not (0 <= vrstica < len(self._videi)):
            return
        v = self._vnosi[self.seznam.currentRow()] if 0 <= self.seznam.currentRow() < len(self._vnosi) else {"tip": "series", "ime": ""}
        e = self._videi[vrstica]
        self._nalozi_tokove(v["tip"], e["id"], f"{v['ime']} — {e['ime']}")

    def _nalozi_tokove(self, tip: str, id_vnosa: str, naslov: str) -> None:
        d = self._dodatek
        self.tokovi.clear(); self.gumb_predvajaj.setEnabled(False); self._naslov = naslov
        if not d or "stream" not in d.viri():
            self._sporoci("Ta dodatek ne ponuja tokov (le katalog/podatke). Tokove poišči v drugem svojem dodatku."); return
        self._sporoci("Iščem tokove …")
        self._v_niti(d.tokovi, tip, id_vnosa, po=self._tokovi_nalozeni)

    def _tokovi_nalozeni(self, tokovi: list) -> None:
        self._tokovi = tokovi; self.tokovi.clear()
        for t in tokovi:
            oznaka = {"url": "▶", "napovednik": "↗", "torrent": "⇣", "neznano": "?"}.get(t["vrsta"], "?")
            it = QListWidgetItem(f"{oznaka} {t['ime']}  {t['naslov']}".strip()); it.setToolTip(t["url"])
            if not predvajljiv(t):
                it.setForeground(Qt.gray)
            self.tokovi.addItem(it)
        if not any(predvajljiv(t) for t in tokovi):
            self._sporoci("Te vsebine trenutno ni na voljo v tem dodatku.")
            return
        self._sporoci(f"{len(tokovi)} tokov (▶ predvajljivi tukaj; ↗ napovednik; ⇣ torrent — tu ni podprt)")

    def _izbran_tok(self, vrstica: int) -> None:
        self.gumb_predvajaj.setEnabled(0 <= vrstica < len(self._tokovi) and self._tokovi[vrstica]["vrsta"] in ("url", "napovednik"))

    def _predvajaj(self) -> None:
        r = self.tokovi.currentRow()
        if not (0 <= r < len(self._tokovi)):
            return
        t = self._tokovi[r]
        if t["vrsta"] == "napovednik":
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(t["url"])); return
        if t["vrsta"] != "url":
            QMessageBox.information(self, "Tok", "Tega toka samostojni predvajalnik ne predvaja (torrent ali neznana vrsta)."); return
        self.izbrani_tok = {"url": t["url"], "naslov": getattr(self, "_naslov", "") or t["ime"], "glave": t.get("glave") or {}, "podnapisi": t.get("podnapisi") or []}
        self.accept()
