"""Okno enega razdelka Safeer OS na namizju (Windows): Nastavitve, Safeer Link, Zapiski, Sporocila.

Lastnik, 25. 10. 2026: »ce kliknem desni gumb miske -> Nastavitve sistema, se odpre stara aplikacija Safeer Link
namesto elegantnega novega okna, ki daje obcutek, da je del operacijskega sistema«. Z namizja se je odprlo celo glavno
okno Safeer OS (stranska vrstica Domov, Medijski center, Safeer Link ... in glava z iskanjem) - kot stara aplikacija.

Zdaj se tak razdelek odpre v svojem oknu: ista stran assets/os/index.html?razdelek=<ime> (os.js skrije stransko
vrstico in glavo, body.en-razdelek), z istim mostom do Safeer OS in z barvami teme sistema. Tako je na Linuxu ze od
12. 10. 2026 (safeer_os.py _odpri_okno_razdelka). Zapiranje okno samo skrije: naslednji klic ga takoj vrne.
"""

from __future__ import annotations

import json
import secrets
import threading
import urllib.parse
from typing import Any, Optional, Tuple

#: Razdelki, ki se z namizja odprejo v svojem oknu (isti nabor kot os.js RAZDELEK).
RAZDELKI_V_OKNU = ("nastavitve", "naprave", "zapiski", "sporocila")
#: Skrito okno razdelka se po tem casu zavrze (spomin procesa strani); ob naslednjem odprtju se nalozi znova (S7).
ZAVRZI_PO_S = 120
#: Okna, ki se ne zavrzejo (nezapisan zapisek mora ostati) - samo zamrznejo.
NE_ZAVRZI = ("zapiski",)
#: Podstrani Nastavitev (ploscici Omrezje in Zvok, vodnik ob prvem zagonu): pokazejo se v oknu Nastavitve.
PODSTRANI = {"omrezje": "nastavitve", "zvok": "nastavitve", "vodnik": "nastavitve"}
NASLOVI = {
    "sl": {"nastavitve": "Nastavitve Safeer OS", "naprave": "Safeer Link", "zapiski": "Zapiski", "sporocila": "Sporočila"},
    "en": {"nastavitve": "Safeer OS settings", "naprave": "Safeer Link", "zapiski": "Notes", "sporocila": "Messages"},
    "de": {"nastavitve": "Safeer OS Einstellungen", "naprave": "Safeer Link", "zapiski": "Notizen", "sporocila": "Nachrichten"},
    "es": {"nastavitve": "Ajustes de Safeer OS", "naprave": "Safeer Link", "zapiski": "Notas", "sporocila": "Mensajes"},
    "fr": {"nastavitve": "Réglages de Safeer OS", "naprave": "Safeer Link", "zapiski": "Notes", "sporocila": "Messages"},
    "it": {"nastavitve": "Impostazioni di Safeer OS", "naprave": "Safeer Link", "zapiski": "Note", "sporocila": "Messaggi"},
}


def okno_za(razdelek: str) -> Tuple[str, str]:
    """(okno, cilj): v katerem oknu razdelka se pokaze `razdelek` in kam v njem (npr. »nastavitve#blokScit«).
    Okno '' pomeni, da razdelek ostane v glavnem oknu Safeer OS (Medijski center, Splet, Datoteke ...)."""
    razdelek = str(razdelek or "")
    if razdelek.startswith("zapisek:"):
        return "zapiski", razdelek
    if razdelek.startswith(("pogovor:", "sporocila:", "kanal:")):
        return "sporocila", razdelek
    osnova = razdelek.split("#", 1)[0]
    if osnova in PODSTRANI:
        return PODSTRANI[osnova], "nastavitve" if osnova == "vodnik" else razdelek
    if osnova in RAZDELKI_V_OKNU:
        return osnova, razdelek
    return "", razdelek


def naslov_strani(ime: str, jezik: str) -> str:
    """Pot strani okna (glede na streznik vmesnika): os/index.html?razdelek=<ime>&jezik=<jezik>."""
    return "os/index.html?" + urllib.parse.urlencode([("razdelek", ime), ("jezik", jezik if jezik in NASLOVI else "en")])


def naslov_okna(ime: str, jezik: str) -> str:
    return NASLOVI.get(jezik, NASLOVI["en"]).get(ime, "Safeer OS")


try:  # Qt je na Windows vedno; v preizkusih brez QtWebEngine se modul uvozi tudi brez nje (ciste funkcije zgoraj).
    from PySide6.QtCore import QTimer, QUrl, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QMainWindow = object  # type: ignore[assignment,misc]


class OknoRazdelka(QMainWindow):  # type: ignore[misc]
    """Eno okno razdelka. Most: iste metode kot glavno okno (os_okno._izvedi_metodo), lasten zeton (tuja stran v
    okvirju ga ne vidi - kot SafeerOsPage v glavnem oknu)."""

    def __init__(self, os_okno, ime: str, page_cls, most_js, jezik: str = "sl") -> None:
        super().__init__(None)
        self.os_okno = os_okno
        self.ime = ime
        self._zeton = secrets.token_urlsafe(24)
        self._nalozeno = False
        self._cakajoci_cilj = ""
        self.setWindowTitle(naslov_okna(ime, jezik))
        try:
            self.setWindowIcon(os_okno.windowIcon())
        except Exception:  # noqa: BLE001
            pass
        self.setStyleSheet("background:#0b1220;")
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page_obj = page_cls(os_okno.profile, self)
        self.page_obj.setBackgroundColor(QColor("#0b1220"))      # brez belega bliska pred prvim izrisom
        skripta = QWebEngineScript()
        skripta.setName("SafeerOsRazdelekMost")
        skripta.setSourceCode(most_js(self._zeton))
        skripta.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        skripta.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        skripta.setRunsOnSubFrames(False)
        self.page_obj.scripts().insert(skripta)
        self.page_obj.loadFinished.connect(self._nalozena)
        # Skrito okno (S7): stran zamrzne (brez JS casovnikov in izrisa), po ZAVRZI_PO_S se zavrze.
        self._zavrzi = QTimer(self)
        self._zavrzi.setSingleShot(True)
        self._zavrzi.setInterval(ZAVRZI_PO_S * 1000)
        self._zavrzi.timeout.connect(lambda: self._v_stanje("zavrzena"))
        self.view.setPage(self.page_obj)
        self.setCentralWidget(self.view)
        g = QApplication.primaryScreen().availableGeometry()
        sirina, visina = min(1280, int(g.width() * 0.8)), min(880, int(g.height() * 0.86))
        self.setGeometry(g.x() + (g.width() - sirina) // 2, g.y() + (g.height() - visina) // 2, sirina, visina)
        self.setMinimumSize(720, 520)
        vrata = getattr(os_okno, "_asset_server_port", None)
        self.view.load(QUrl(f"http://127.0.0.1:{int(vrata)}/" + naslov_strani(ime, jezik)))

    # ------------------------------------------------------------------ most (kar SafeerOsPage pricakuje od okna)
    def zeton_mostu_velja(self, zeton: Any) -> bool:
        import hmac
        return isinstance(zeton, str) and hmac.compare_digest(zeton.encode(), self._zeton.encode())

    def zavrnjen_klic_mostu(self) -> None:
        pass

    def obdelaj_klic(self, sporocilo: dict) -> None:
        klic_id, metoda, a = sporocilo.get("id", 0), str(sporocilo.get("m", "")), list(sporocilo.get("a") or [])

        def delo() -> None:
            try:
                if metoda == "odpriRazdelek":
                    # Razdelek, ki ga to okno nima (npr. Medijski center iz Nastavitev): odpre ga Safeer OS.
                    cilj = str(a[0]) if a else ""
                    self.os_okno.dispatcher.dispatch(lambda: self.os_okno.odpri_razdelek_namizja(cilj))
                    izid: Any = True
                else:
                    izid = self.os_okno._izvedi_metodo(metoda, a)
                self._odgovor(klic_id, True, izid)
            except Exception as e:  # noqa: BLE001
                print(f"[SafeerOS {self.ime}] {metoda}: {e}", flush=True)
                self._odgovor(klic_id, False, str(e))
        threading.Thread(target=delo, daemon=True).start()

    def _odgovor(self, klic_id: int, ok: bool, podatki: Any) -> None:
        koda = "window.__safeerOsOdgovor && window.__safeerOsOdgovor(%d, %s, %s);" % (
            int(klic_id), "true" if ok else "false", json.dumps(podatki, ensure_ascii=False, default=str))
        self.os_okno.dispatcher.dispatch(lambda: self.page_obj.runJavaScript(koda))

    def dogodek(self, vrsta: str, podatki: Any = None) -> None:
        koda = "window.safeerOsDogodek && window.safeerOsDogodek(%s, %s);" % (
            json.dumps(vrsta), json.dumps(podatki, ensure_ascii=False, default=str))
        self.os_okno.dispatcher.dispatch(lambda: self.page_obj.runJavaScript(koda))

    # ------------------------------------------------------------------ prikaz
    def _nalozena(self, ok: bool) -> None:
        self._nalozeno = bool(ok)
        if ok and self._cakajoci_cilj:
            cilj, self._cakajoci_cilj = self._cakajoci_cilj, ""
            self.pojdi(cilj)

    def pojdi(self, cilj: str) -> None:
        if not cilj or cilj == self.ime:
            return
        if not self._nalozeno:
            self._cakajoci_cilj = cilj
            return
        self.page_obj.runJavaScript("window.safeerOsPojdi && window.safeerOsPojdi(%s);" % json.dumps(cilj))

    def _v_stanje(self, stanje: str) -> None:
        """»aktivna«, »zamrznjena« (samo skrito okno) ali »zavrzena« (spomin strani sproscen, ob prikazu se nalozi)."""
        try:
            Lc = QWebEnginePage.LifecycleState
            if stanje == "aktivna":
                self._zavrzi.stop()
                if self.page_obj.lifecycleState() != Lc.Active:
                    if self.page_obj.lifecycleState() == Lc.Discarded:
                        self._nalozeno = False      # stran se nalozi znova - cilj pocaka na loadFinished
                    self.page_obj.setLifecycleState(Lc.Active)
                return
            if self.isVisible():
                return
            if stanje == "zamrznjena" and self.page_obj.lifecycleState() == Lc.Active:
                self.page_obj.setLifecycleState(Lc.Frozen)
            elif stanje == "zavrzena" and self.ime not in NE_ZAVRZI:
                self.page_obj.setLifecycleState(Lc.Discarded)
                print(f"[SafeerOS {self.ime}] skrito okno zavrzeno (spomin sproscen)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerOS {self.ime}] stanje strani {stanje}: {e}", flush=True)

    def hideEvent(self, dogodek) -> None:  # noqa: N802 - Qt
        super().hideEvent(dogodek)
        if getattr(self, "_koncaj", False):
            return
        QTimer.singleShot(1000, lambda: self._v_stanje("zamrznjena"))
        self._zavrzi.start()

    def pokazi(self, cilj: str = "") -> None:
        self._v_stanje("aktivna")
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self.pojdi(cilj)

    def closeEvent(self, dogodek) -> None:  # noqa: N802 - Qt
        # Zapiranje okno samo skrije (nezapisan zapisek ostane, naslednji klic ga takoj vrne); ob izhodu Safeer OS
        # ga zapre glavno okno (zapri_vse).
        if getattr(self, "_koncaj", False):
            dogodek.accept()
            return
        dogodek.ignore()
        self.hide()

    def zapri_zares(self) -> None:
        self._koncaj = True
        try:
            self.page_obj.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self.close()


def odpri(os_okno, razdelek: str, page_cls, most_js, jezik: str = "sl") -> Optional[bool]:
    """Pokazi okno za `razdelek` (ustvari ga ob prvem klicu). None, ce razdelek ne sodi v svoje okno ali streznika
    vmesnika se ni - klicatelj takrat odpre glavno okno kot prej."""
    ime, cilj = okno_za(razdelek)
    if not ime or not _QT or not getattr(os_okno, "_asset_server_port", None):
        return None
    okna = getattr(os_okno, "okna_razdelkov", None)
    if okna is None:
        okna = os_okno.okna_razdelkov = {}
    okno = okna.get(ime)
    if okno is None:
        okno = okna[ime] = OknoRazdelka(os_okno, ime, page_cls, most_js, jezik)
    okno.pokazi(cilj if cilj != ime else "")
    return True
