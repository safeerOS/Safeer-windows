"""Okno »Dodatki« Safeer predvajalnika (Qt) — skupno za samostojno aplikacijo in Medijski center.

Eno jasno oznaceno polje: Stremio dodatek (naslov manifesta). Ponujamo samo dodatke, ki jih Safeer sam poganja.
Brez prilozenih katalogov: seznam je prazen, dokler uporabnik ne vnese svojih naslovov.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import predvajalnik_nastavitve as N


class _Odsek(QGroupBox):
    def __init__(self, vrsta: str, naslov: str, namig: str, nastavitve: dict, parent: Optional[QWidget] = None):
        # Naslov odseka je navadna oznaka (ne naslov okvirja): v temnem oknu predvajalnika je bil naslov okvirja
        # temen na temnem in se ga ni dalo prebrati.
        super().__init__(parent)
        self._vrsta = vrsta
        self._naslov = naslov
        self._n = nastavitve
        v = QVBoxLayout(self)
        glava = QLabel(naslov); glava.setWordWrap(True); glava.setStyleSheet("font-weight:600;")
        v.addWidget(glava)
        n = QLabel(namig); n.setWordWrap(True); n.setStyleSheet("color:#888;")
        v.addWidget(n)
        vrstica = QHBoxLayout()
        self.vnos = QLineEdit(); self.vnos.setPlaceholderText("https://…/manifest.json")
        self.ime = QLineEdit(); self.ime.setPlaceholderText("Ime (neobvezno)"); self.ime.setMaximumWidth(160)
        dodaj = QPushButton("Dodaj"); dodaj.clicked.connect(self._dodaj)
        self.vnos.returnPressed.connect(self._dodaj)
        vrstica.addWidget(self.vnos, 1); vrstica.addWidget(self.ime); vrstica.addWidget(dodaj)
        v.addLayout(vrstica)
        self.seznam = QListWidget(); v.addWidget(self.seznam)
        odstrani = QPushButton("Odstrani izbranega"); odstrani.clicked.connect(self._odstrani)
        v.addWidget(odstrani, 0, Qt.AlignRight)
        self._osvezi()

    def _kljuc(self) -> str:
        return "stremio_dodatki"

    def _osvezi(self) -> None:
        self.seznam.clear()
        for x in self._n[self._kljuc()]:
            it = QListWidgetItem((x.get("ime") + " — " if x.get("ime") else "") + x["naslov"])
            it.setData(Qt.UserRole, x["naslov"]); self.seznam.addItem(it)

    def _dodaj(self) -> None:
        ok, sporocilo = N.dodaj(self._n, self._vrsta, self.vnos.text(), self.ime.text())
        if not ok:
            QMessageBox.warning(self, self._naslov, sporocilo); return
        self.vnos.clear(); self.ime.clear(); self._osvezi()

    def _odstrani(self) -> None:
        it = self.seznam.currentItem()
        if it is None:
            return
        N.odstrani(self._n, self._vrsta, it.data(Qt.UserRole)); self._osvezi()


class DodatkiOkno(QDialog):
    """Vrne shranjene nastavitve v .nastavitve; shrani ob »Shrani«."""

    def __init__(self, parent: Optional[QWidget] = None, pot: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Safeer predvajalnik — Dodatki")
        self.resize(720, 420)
        self._pot = pot
        self.nastavitve = N.nalozi(pot)
        v = QVBoxLayout(self)
        opomba = QLabel(N.BESEDILA["opomba"]); opomba.setWordWrap(True); v.addWidget(opomba)
        self.stremio = _Odsek("stremio", N.BESEDILA["stremio_naslov"], N.BESEDILA["stremio_namig"], self.nastavitve, self)
        v.addWidget(self.stremio)
        gumbi = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        gumbi.button(QDialogButtonBox.Save).setText("Shrani"); gumbi.button(QDialogButtonBox.Cancel).setText("Prekliči")
        gumbi.accepted.connect(self._shrani); gumbi.rejected.connect(self.reject)
        v.addWidget(gumbi)

    def _shrani(self) -> None:
        if not N.shrani(self.nastavitve, self._pot):
            QMessageBox.critical(self, self.windowTitle(), "Nastavitev ni bilo mogoče shraniti."); return
        self.accept()
