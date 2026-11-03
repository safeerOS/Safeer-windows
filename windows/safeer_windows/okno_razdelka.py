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
import sys
import threading
import urllib.parse
from typing import Any, Optional, Tuple

#: Razdelki, ki se z namizja odprejo v svojem oknu (isti nabor kot os.js RAZDELEK).
RAZDELKI_V_OKNU = ("nastavitve", "naprave", "zapiski", "sporocila")
#: Skrito okno razdelka se po tem casu zavrze (spomin procesa strani); ob naslednjem odprtju se nalozi znova (S7).
ZAVRZI_PO_S = 120
#: Okna, ki se ne zavrzejo (nezapisan zapisek mora ostati) - samo zamrznejo.
NE_ZAVRZI = ("zapiski",)
#: Safeer Player (naloga 39, 27. 10. 2026): ce Safeer OS ze tece, Player odpre to okno - samo Medijski center
#: (os.js ?predvajalnik=1), domace okno ostane, kakor je. Kot na Linuxu (safeer_os.py _odpri_predvajalnik).
PREDVAJALNIK = "predvajalnik"
#: Okno Safeer Player v procesu Safeer OS ima svoj AppUserModelID - isti kot bliznjica Safeer Player (installer.iss),
#: sicer ga Windows prikaze z ikono in v skupini Safeer OS (lastnik, 3. 11. 2026: »dve ikoni v opravilni vrstici«).
AUMID_PREDVAJALNIKA = "Safeer.Player"
#: Podstrani Nastavitev (ploscici Omrezje in Zvok, vodnik ob prvem zagonu): pokazejo se v oknu Nastavitve.
PODSTRANI = {"omrezje": "nastavitve", "zvok": "nastavitve", "vodnik": "nastavitve"}
NASLOVI = {
    "sl": {"nastavitve": "Nastavitve Safeer OS", "naprave": "Safeer Link", "zapiski": "Zapiski", "sporocila": "Sporočila", "predvajalnik": "Safeer Player"},
    "en": {"nastavitve": "Safeer OS settings", "naprave": "Safeer Link", "zapiski": "Notes", "sporocila": "Messages", "predvajalnik": "Safeer Player"},
    "de": {"nastavitve": "Safeer OS Einstellungen", "naprave": "Safeer Link", "zapiski": "Notizen", "sporocila": "Nachrichten", "predvajalnik": "Safeer Player"},
    "es": {"nastavitve": "Ajustes de Safeer OS", "naprave": "Safeer Link", "zapiski": "Notas", "sporocila": "Mensajes", "predvajalnik": "Safeer Player"},
    "fr": {"nastavitve": "Réglages de Safeer OS", "naprave": "Safeer Link", "zapiski": "Notes", "sporocila": "Messages", "predvajalnik": "Safeer Player"},
    "it": {"nastavitve": "Impostazioni di Safeer OS", "naprave": "Safeer Link", "zapiski": "Note", "sporocila": "Messaggi", "predvajalnik": "Safeer Player"},
}


def je_medijski_center(razdelek: str) -> bool:
    """»media« in »mediji:<iskanje>« z namizja ali iz drugega okna: Medijski center se odpre v oknu Safeer Player, ne v
    glavnem oknu Safeer OS (kot Linux safeer_os.razdelek_predvajalnika). Izmerjeno 3. 11. 2026 na testnem PC: prej je
    prebudi("media") pokazal glavno okno, njegova stran pa je nato odprla se Player - dve okni, dve ikoni."""
    razdelek = str(razdelek or "")
    return razdelek in (PREDVAJALNIK, "media") or razdelek.startswith("mediji:")


def nastavi_aumid_okna(hwnd: int, aumid: str) -> bool:
    """AppUserModelID enega okna (IPropertyStore okna, PKEY_AppUserModel_ID): okno dobi svojo skupino in ikono v
    opravilni vrstici, ceprav tece v procesu Safeer OS (en proces, core/en_proces.py). Nastavi se pred prvim prikazom.
    False zunaj Windows ali ob napaki - okno se odpre tudi brez tega."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        lastnost, ps = _shramba_lastnosti_okna(hwnd)
        if not ps:
            return False
        try:
            vrednost = _PropVariant()
            vrednost.vt = 31                              # VT_LPWSTR; SetValue niz prekopira
            besedilo = ctypes.c_wchar_p(str(aumid))
            vrednost.niz = besedilo
            hr = _metoda(ps, 6, ctypes.c_void_p, ctypes.POINTER(_KljucLastnosti),
                         ctypes.POINTER(_PropVariant))(ps, ctypes.byref(lastnost), ctypes.byref(vrednost))
            if hr == 0:
                hr = _metoda(ps, 7, ctypes.c_void_p)(ps)                   # Commit
            return hr == 0
        finally:
            _metoda(ps, 2, ctypes.c_void_p, vrnjeno=ctypes.c_ulong)(ps)    # Release
    except Exception as e:  # noqa: BLE001
        print(f"[SafeerOS] AppUserModelID okna: {e}", flush=True)
        return False


def aumid_okna(hwnd: int) -> str:
    """AppUserModelID okna, kot ga vidi opravilna vrstica ('' brez lastnega ali zunaj Windows) - za preizkus."""
    if sys.platform != "win32" or not hwnd:
        return ""
    import ctypes
    lastnost, ps = _shramba_lastnosti_okna(hwnd)
    if not ps:
        return ""
    try:
        vrednost = _PropVariant()
        hr = _metoda(ps, 5, ctypes.c_void_p, ctypes.POINTER(_KljucLastnosti),
                     ctypes.POINTER(_PropVariant))(ps, ctypes.byref(lastnost), ctypes.byref(vrednost))
        izid = (vrednost.niz or "") if hr == 0 and vrednost.vt == 31 else ""
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(vrednost))
        return izid
    finally:
        _metoda(ps, 2, ctypes.c_void_p, vrnjeno=ctypes.c_ulong)(ps)


if sys.platform == "win32":
    import ctypes as _c
    import uuid as _uuid

    class _Guid(_c.Structure):
        _fields_ = [("d1", _c.c_uint32), ("d2", _c.c_uint16), ("d3", _c.c_uint16), ("d4", _c.c_ubyte * 8)]

    class _KljucLastnosti(_c.Structure):
        _fields_ = [("fmtid", _Guid), ("pid", _c.c_uint32)]

    class _PropVariant(_c.Structure):
        # vt + trije rezervirani WORD, nato unija (na x64 16 B): skupaj 24 B kot PROPVARIANT
        _fields_ = [("vt", _c.c_ushort), ("r1", _c.c_ushort), ("r2", _c.c_ushort), ("r3", _c.c_ushort),
                    ("niz", _c.c_wchar_p), ("rezerva", _c.c_void_p)]

    def _guid(niz: str) -> "_Guid":
        u = _uuid.UUID(niz)
        g = _Guid(u.fields[0], u.fields[1], u.fields[2])
        g.d4[:] = list(u.bytes[8:])
        return g

    def _metoda(ps, indeks: int, *vrste, vrnjeno=_c.c_long):
        """Metoda COM iz tabele vmesnika IPropertyStore (0-2 IUnknown, 5 GetValue, 6 SetValue, 7 Commit)."""
        tabela = _c.cast(ps, _c.POINTER(_c.POINTER(_c.c_void_p))).contents
        return _c.WINFUNCTYPE(vrnjeno, *vrste)(tabela[indeks])

    def _shramba_lastnosti_okna(hwnd: int):
        iid = _guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")              # IID_IPropertyStore
        kljuc = _KljucLastnosti(_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)   # PKEY_AppUserModel_ID
        ps = _c.c_void_p()
        f = _c.windll.shell32.SHGetPropertyStoreForWindow
        f.argtypes = [_c.c_void_p, _c.POINTER(_Guid), _c.POINTER(_c.c_void_p)]
        f.restype = _c.c_long
        if f(_c.c_void_p(int(hwnd)), _c.byref(iid), _c.byref(ps)) != 0:
            return kljuc, None
        return kljuc, ps


def okno_za(razdelek: str) -> Tuple[str, str]:
    """(okno, cilj): v katerem oknu razdelka se pokaze `razdelek` in kam v njem (npr. »nastavitve#blokScit«).
    Okno '' pomeni, da razdelek ostane v glavnem oknu Safeer OS (Medijski center, Splet, Datoteke ...)."""
    razdelek = str(razdelek or "")
    if je_medijski_center(razdelek):
        return PREDVAJALNIK, "media"
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
    jezik = jezik if jezik in NASLOVI else "en"
    if ime == PREDVAJALNIK:
        return "os/index.html?" + urllib.parse.urlencode([("predvajalnik", "1"), ("jezik", jezik)])
    return "os/index.html?" + urllib.parse.urlencode([("razdelek", ime), ("jezik", jezik)])


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
            ikona = os_okno.windowIcon()
            if ime == PREDVAJALNIK and hasattr(os_okno, "ikona_predvajalnika"):
                ikona = os_okno.ikona_predvajalnika()      # znak Safeer z oznako predvajanja, ne ikona Safeer OS
            self.setWindowIcon(ikona)
        except Exception:  # noqa: BLE001
            pass
        if ime == PREDVAJALNIK:
            # Pred prvim prikazom (winId ustvari okno Windows): opravilna vrstica ga uvrsti pod Safeer Player.
            nastavi_aumid_okna(int(self.winId()), AUMID_PREDVAJALNIKA)
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
        if not getattr(self, "_zavrnjen_zabelezen", False):
            self._zavrnjen_zabelezen = True
            print(f"[SafeerOS {self.ime}] klic mostu z napacnim zetonom zavrnjen", flush=True)

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
