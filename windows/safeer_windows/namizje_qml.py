"""Namizje Safeer OS za Windows v Qt Quick (QML).

Lastnik, 13. 10. 2026: namizje za Windows v PySide6 + Qt Quick - lasten videz, animacije, prosojni paneli in pozneje
skupna osnova za vec platform. Logika ostane v Pythonu (namizje_win.metode, namizje_datoteke, glavno okno Safeer OS);
QML jo klice po istih imenih kot spletna stran na Linuxu (»most«: klic(metoda, argumenti) -> odgovor).

Okno je isto kot pri spletni razlicici: brez okvirja, brez gumba v opravilni vrstici, lastnik Progman (Win+D ga ne
skrije), vedno na dnu (WM_WINDOWPOSCHANGING).
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import itertools
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from core import os_iskalnik

from . import namizje_win

_WIN = sys.platform == "win32"
QML = Path(__file__).resolve().parent / "qml" / "Namizje.qml"


def _mapa_ikon() -> Path:
    mapa = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "SafeerOS" / "ikone-namizja"
    mapa.mkdir(parents=True, exist_ok=True)
    return mapa


def ikona_v_datoteko(ikona: str) -> str:
    """data:image/...;base64 -> file:/// URL v predpomnilniku (QML Image bere datoteke hitreje in zanesljivo)."""
    if not ikona or not ikona.startswith("data:image/") or ";base64," not in ikona:
        return ikona or ""
    glava, podatki = ikona.split(";base64,", 1)
    koncnica = "png" if "png" in glava else "jpg"
    ime = hashlib.sha1(podatki.encode("ascii", "ignore")).hexdigest()[:20] + "." + koncnica
    pot = _mapa_ikon() / ime
    if not pot.exists():
        try:
            pot.write_bytes(base64.b64decode(podatki))
        except (OSError, ValueError):
            return ""
    return QUrl.fromLocalFile(str(pot)).toString()


class Most(QObject):
    """Klici iz QML: klic(metoda, argumenti_json) vrne id; odgovor pride kot signal (v niti, da vmesnik ne obstane)."""

    odgovor = Signal(int, bool, str)
    dogodek = Signal(str, str)

    def __init__(self, okno: "NamizjeQml") -> None:
        super().__init__()
        self._okno = okno
        self._stevec = itertools.count(1)

    @Slot(str, str, result=int)
    def klic(self, metoda: str, argumenti: str) -> int:
        klic_id = next(self._stevec)
        try:
            a = json.loads(argumenti or "[]")
        except ValueError:
            a = []

        def delo() -> None:
            try:
                izid = self._okno.izvedi(metoda, a if isinstance(a, list) else [])
                self.odgovor.emit(klic_id, True, json.dumps(izid, ensure_ascii=False, default=str))
            except Exception as e:  # noqa: BLE001
                print(f"[SafeerOS namizje QML] {metoda}: {e}", flush=True)
                self.odgovor.emit(klic_id, False, json.dumps(str(e)))
        threading.Thread(target=delo, daemon=True).start()
        return klic_id

    @Slot(str, result=str)
    def datotekaUrl(self, pot: str) -> str:
        return QUrl.fromLocalFile(pot).toString() if pot else ""


class NamizjeQml(QQuickView):
    WM_WINDOWPOSCHANGING = 0x0046
    HWND_BOTTOM = 1

    def __init__(self, os_okno) -> None:
        super().__init__()
        self.os_okno = os_okno
        self.setTitle("Safeer OS namizje")
        self.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.setColor(Qt.GlobalColor.black)
        self.most = Most(self)
        self._metode: Dict[str, Callable[[list], Any]] = namizje_win.metode(self)
        self._nadzor = QFileSystemWatcher()
        self._nadzor.directoryChanged.connect(lambda pot: QTimer.singleShot(400, lambda: self.dogodek("datoteke", {"pot": pot})))
        self._spremljana = ""
        self.rootContext().setContextProperty("Most", self.most)
        threading.Thread(target=os_iskalnik.indeks().zgradi_v_ozadju, daemon=True).start()
        self.setSource(QUrl.fromLocalFile(str(QML)))
        for napaka in self.errors():
            print("[SafeerOS namizje QML]", napaka.toString(), flush=True)
        zaslon = QGuiApplication.primaryScreen()
        zaslon.availableGeometryChanged.connect(lambda *_: self._postavi())
        self._postavi()

    # ------------------------------------------------------------------ klici (isti kot pri spletni razlicici)
    def izvedi(self, metoda: str, a: list) -> Any:
        if metoda == "programiNamizja":
            seznam = self.os_okno._izvedi_metodo("programi", []) or []
            return [dict(p, ikona=ikona_v_datoteko(str(p.get("ikona") or ""))) for p in seznam]
        if metoda == "programiNapraveNamizja":
            r = self.os_okno._izvedi_metodo("programiNaprave", a) or {}
            if isinstance(r, dict):
                r = dict(r, programi=[dict(p, ikona=ikona_v_datoteko(str(p.get("ikona") or ""))) for p in r.get("programi") or []])
            return r
        if metoda == "napraveNamizja":
            return naprave_za_izbiro(self.os_okno.control_backend)
        if metoda in self._metode:
            return self._metode[metoda](a)
        return self.os_okno._izvedi_metodo(metoda, a)

    def dogodek(self, vrsta: str, podatki: Any = None) -> None:
        self.most.dogodek.emit(vrsta, json.dumps(podatki, ensure_ascii=False, default=str))

    # namizje_win.metode pricakuje te metode okna
    def zacetek(self) -> dict:
        z = dict(self.os_okno._izvedi_metodo("zacetek", []) or {})
        z.update({"mape": namizje_win.uporabniske_mape(), "ozadje": ozadje_datoteka()})
        return z

    def odpri_razdelek(self, razdelek: str) -> bool:
        self.os_okno.dispatcher.dispatch(lambda: self.os_okno.prebudi(razdelek))
        return True

    def spremljaj_mapo(self, pot: str) -> bool:
        def nastavi() -> None:
            if self._spremljana:
                self._nadzor.removePath(self._spremljana)
            self._spremljana = pot if os.path.isdir(pot) else ""
            if self._spremljana:
                self._nadzor.addPath(self._spremljana)
        self.os_okno.dispatcher.dispatch(nastavi)
        return True

    # ------------------------------------------------------------------ polozaj: pod vsemi okni
    def _postavi(self) -> None:
        self.setGeometry(QGuiApplication.primaryScreen().availableGeometry())

    def pokazi(self) -> None:
        self.show()
        if _WIN:
            hwnd = int(self.winId())
            u = ctypes.windll.user32
            progman = u.FindWindowW("Progman", None)
            if progman:
                u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                u.SetWindowLongPtrW(hwnd, -8, progman)      # GWLP_HWNDPARENT: Win+D ga ne skrije
            u.SetWindowPos(hwnd, self.HWND_BOTTOM, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)

    def nativeEvent(self, vrsta, sporocilo):  # noqa: N802
        if _WIN:
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(sporocilo))
                if msg.message == self.WM_WINDOWPOSCHANGING:
                    class WINDOWPOS(ctypes.Structure):
                        _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND), ("x", ctypes.c_int),
                                    ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]
                    poz = WINDOWPOS.from_address(msg.lParam)
                    poz.hwndInsertAfter = self.HWND_BOTTOM
                    poz.flags &= ~0x0004
            except Exception:  # noqa: BLE001
                pass
        return False, 0


def ozadje_datoteka() -> str:
    """Pot do ozadja Windows kot file:/// URL (QML bere datoteko neposredno)."""
    if not _WIN:
        return ""
    kandidati = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            kandidati.append(os.path.expandvars(str(winreg.QueryValueEx(k, "WallPaper")[0])))
    except OSError:
        pass
    kandidati.append(os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Themes", "TranscodedWallpaper"))
    for pot in kandidati:
        if pot and os.path.isfile(pot):
            return QUrl.fromLocalFile(pot).toString()
    return ""


def naprave_za_izbiro(cb) -> list:
    """Druge naprave v Safeer Linku za izbiro na namizju. Ena vrstica na napravo: racunalnik je v Linku lahko dvakrat
    (Safeer OS in njegov Control, id »…-control«); za programe in datoteke si zapomnimo id, ki to zna."""
    programi = {n["id"] for n in cb.naprave_s_programi()}
    datoteke = {n["id"] for n in cb.naprave_s_datotekami()}
    po_kljucu: dict = {}
    for n in cb.vse_naprave():
        id_n = str(n.get("id") or "")
        if n.get("ta") or not id_n or (id_n not in programi and id_n not in datoteke):
            continue
        kljuc = id_n[:-len("-control")] if id_n.endswith("-control") else id_n
        v = po_kljucu.setdefault(kljuc, {"kljuc": kljuc, "ime": "", "platforma": "", "programi": "", "datoteke": ""})
        if not v["ime"] or not id_n.endswith("-control"):
            v["ime"] = str(n.get("ime") or id_n)
            v["platforma"] = str(n.get("platforma") or "")
        if id_n in programi and (not v["programi"] or not id_n.endswith("-control")):
            v["programi"] = id_n
        if id_n in datoteke and (not v["datoteke"] or id_n.endswith("-control")):
            v["datoteke"] = id_n
    return sorted(po_kljucu.values(), key=lambda v: v["ime"].lower())
