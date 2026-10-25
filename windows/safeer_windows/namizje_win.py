"""Namizje Safeer OS za Windows (po vzoru Safeer OS Linux).

Ista stran kot na Linuxu (assets/os/delovna.html: iskanje, mini predvajalnik, datoteke, programi naprav) lezi pod
vsemi okni namesto obicajnega namizja z ikonami. Opravilna vrstica Windows (Start, ura, odprti programi) ostane -
uporabnik jo pozna in Windows brez nje izgubi del funkcij. En klik v nastavitvah vrne obicajno namizje.

Okno: brez okvirja, brez gumba v opravilni vrstici in v Alt+Tab, vedno na dnu (WM_WINDOWPOSCHANGING), lastnik je
Progman - tako ga »Pokazi namizje« (Win+D) ne skrije. Klici strani gredo najprej sem (metode namizja z obliko podatkov,
kot jo pricakuje delovna.js), vse ostalo po isti poti kot glavno okno Safeer OS.
"""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, Optional

from core import os_datoteke, os_iskalnik, os_lupa

from . import namizje_datoteke as nd

_WIN = sys.platform == "win32"

#: Razdelki sistemskih nastavitev (ms-settings), ki jih namizje odpira.
NASTAVITVE = {
    "": "ms-settings:", "zaslon": "ms-settings:display", "zvok": "ms-settings:sound", "omrezje": "ms-settings:network",
    "bluetooth": "ms-settings:bluetooth", "tiskalniki": "ms-settings:printers", "ozadje": "ms-settings:personalization-background",
    "tema": "ms-settings:themes", "barve": "ms-settings:colors", "opravilna": "ms-settings:taskbar",
    "programi": "ms-settings:appsfeatures", "privzeti": "ms-settings:defaultapps", "posodobitve": "ms-settings:windowsupdate",
    "napajanje": "ms-settings:powersleep", "shramba": "ms-settings:storagesense", "jezik": "ms-settings:regionlanguage",
}


def _odpri_uri(uri: str) -> bool:
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def privzeti_brskalnik() -> str:
    """Ime privzetega brskalnika (UserChoice za https) - za napis »Splet odpri v …«."""
    if not _WIN:
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = str(winreg.QueryValueEx(k, "ProgId")[0])
    except OSError:
        return ""
    znani = {"ChromeHTML": "Google Chrome", "MSEdgeHTM": "Microsoft Edge", "FirefoxURL": "Firefox", "BraveHTML": "Brave",
             "OperaStable": "Opera", "VivaldiHTM": "Vivaldi"}
    for predpona, ime in znani.items():
        if progid.startswith(predpona):
            return ime
    return progid.split("-")[0].split(".")[0]


#: Znane mape Windows (User Shell Folders) - lahko so prestavljene, npr. v OneDrive.
_ZNANE_MAPE = (("DESKTOP", "Desktop"), ("DOCUMENTS", "Personal"), ("DOWNLOAD", "{374DE290-123F-4565-9164-39C4925E467B}"),
               ("PICTURES", "My Pictures"), ("MUSIC", "My Music"), ("VIDEOS", "My Video"))


def uporabniske_mape() -> list:
    """Domača mapa in znane mape, kot jih ima uporabnik (iz registra; brez njega privzete poti)."""
    dom = os.path.expanduser("~")
    izhod = [{"vrsta": "HOME", "pot": dom, "ime": os.path.basename(dom)}]
    registrske = {}
    if _WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                for vrsta, ime in _ZNANE_MAPE:
                    try:
                        registrske[vrsta] = os.path.expandvars(str(winreg.QueryValueEx(k, ime)[0]))
                    except OSError:
                        pass
        except OSError:
            pass
    privzeto = {"DESKTOP": "Desktop", "DOCUMENTS": "Documents", "DOWNLOAD": "Downloads", "PICTURES": "Pictures",
                "MUSIC": "Music", "VIDEOS": "Videos"}
    for vrsta, _ in _ZNANE_MAPE:
        pot = registrske.get(vrsta) or os.path.join(dom, privzeto[vrsta])
        if os.path.isdir(pot):
            izhod.append({"vrsta": vrsta, "pot": pot, "ime": os.path.basename(pot.rstrip("\\/"))})
    return izhod


def ozadje_windows(sirina: int = 1920) -> str:
    """Ozadje namizja Windows kot data: URL (stran je na http://127.0.0.1 in ne bere file://); brez slike prazno."""
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
            try:
                import base64
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
                from PySide6.QtGui import QImage
                slika = QImage(pot)
                if slika.isNull():
                    continue
                if slika.width() > sirina:
                    slika = slika.scaledToWidth(sirina, Qt.TransformationMode.SmoothTransformation)
                podatki = QByteArray()
                b = QBuffer(podatki)
                b.open(QIODevice.OpenModeFlag.WriteOnly)
                slika.save(b, "JPEG", 85)
                return "data:image/jpeg;base64," + base64.b64encode(bytes(podatki)).decode("ascii")
            except Exception:  # noqa: BLE001
                continue
    return ""


_lupa: Optional[os_lupa.Ucenje] = None


def lupa() -> os_lupa.Ucenje:
    global _lupa
    if _lupa is None:
        mapa = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SafeerOS")
        os.makedirs(mapa, exist_ok=True)
        _lupa = os_lupa.Ucenje(os.path.join(mapa, "lupa.json"))
    return _lupa


def _s(a: list, i: int = 0, privzeto: str = "") -> str:
    return str(a[i]) if len(a) > i and a[i] is not None else privzeto


def metode(okno: "NamizjeOkno") -> Dict[str, Callable[[list], Any]]:
    """Metode, ki jih namizje razresi samo (oblika podatkov kot na Linuxu); ostale gredo glavnemu oknu."""
    os_okno = okno.os_okno
    return {
        "mapa": lambda a: nd.preglej(_s(a, 0, "~")),
        "nedavne": lambda a: nd.nedavne(),
        "isciDatoteke": lambda a: os_iskalnik.isci(_s(a), min(300, max(1, int(a[1]))) if len(a) > 1 and isinstance(a[1], (int, float))
                                                 and not isinstance(a[1], bool) else os_datoteke.NAJVEC_ZADETKOV),
        "odpriDatoteko": lambda a: nd.odpri(_s(a)),
        "pokaziVMapi": lambda a: nd.pokazi_v_mapi(_s(a)),
        "novaMapa": lambda a: os_datoteke.ustvari_mapo(_s(a), _s(a, 1)),
        "novaDatoteka": lambda a: os_datoteke.ustvari_datoteko(_s(a), _s(a, 1), _s(a, 2, "prazna"), _s(a, 3)),
        "predlogeDatotek": lambda a: [],
        "preimenujDatoteko": lambda a: os_datoteke.preimenuj(_s(a), _s(a, 1)),
        "vSmeti": lambda a: nd.v_smeti(_s(a)),
        "smeti": lambda a: nd.smeti(),
        "obnoviIzSmeti": lambda a: nd.obnovi_iz_smeti(_s(a)),
        "izprazniSmeti": lambda a: nd.izprazni_smeti(),
        "nosilci": lambda a: nd.nosilci(),
        "izvrziNosilec": lambda a: nd.izvrzi(_s(a)),
        "prostorDiska": lambda a: nd.prostor(),
        "najvecjeDatoteke": lambda a: os_datoteke.najvecje(os.path.expanduser("~")),
        "lastnostiDatoteke": lambda a: os_datoteke.lastnosti(_s(a)),
        "prilepiDatoteke": lambda a: os_datoteke.prilepi(a[0] if a and isinstance(a[0], list) else [], _s(a, 1),
                                                         bool(a[2]) if len(a) > 2 else False),
        "razveljaviDatoteke": lambda a: os_datoteke.razveljavi(a[0] if a and isinstance(a[0], dict) else {}),
        "sliciceDatotek": lambda a: nd.slicice(a[0] if a and isinstance(a[0], list) else []),
        "spremljajMapo": lambda a: okno.spremljaj_mapo(_s(a)),
        "zacniVlecenje": lambda a: False,
        "spusceneDatoteke": lambda a: [],
        "programiZaDatoteko": lambda a: {"ok": True, "programi": [], "privzeti": None},
        "programiZaOdpiranje": lambda a: [],
        "odpriZ": lambda a: nd.odpri_z(str((a[0] or [""])[0]) if a and isinstance(a[0], list) and a[0] else ""),
        "odpriRazdelek": lambda a: okno.odpri_razdelek(_s(a)),
        # Lupa: Splet v svojem oknu nad namizjem (kot Linux _splet_na_namizju), ne v skritem glavnem oknu.
        "spletNaNamizju": lambda a: os_okno.splet_na_namizju(_s(a)),
        "odpriVBrskalniku": lambda a: _s(a).startswith(("http://", "https://")) and _odpri_uri(_s(a)),
        "privzetiBrskalnik": lambda a: privzeti_brskalnik(),
        "sistemskeNastavitve": lambda a: _odpri_uri(NASTAVITVE.get(_s(a), "ms-settings:")),
        "nastavitveOzadja": lambda a: _odpri_uri(NASTAVITVE["ozadje"]),
        "nastavitveDocka": lambda a: _odpri_uri(NASTAVITVE["opravilna"]),
        "dock": lambda a: {"plank": False, "programi": []},
        "dockRazvrsti": lambda a: False,
        "videzCinnamonNastavi": lambda a: False,
        "kavcCelZaslon": lambda a: False,
        "lupaUcenje": lambda a: lupa().podatki(),
        "lupaZapomni": lambda a: lupa().zapomni(*(list(a or [])[:3])),
        "govorStanje": lambda a: {"podprto": False},
        "igreOblak": lambda a: [],
        "ponudnikiProgramov": lambda a: [],
        "viriProgramov": lambda a: {},
        "zacetek": lambda a: okno.zacetek(),
        # Safeer Link: naprave z datotekami in posiljanje datotek (Safeer Control je vgrajen v Safeer OS).
        "napraveZDatotekami": lambda a: os_okno.control_backend.naprave_s_datotekami(),
        "napraveZaPosiljanje": lambda a: os_okno.control_backend.naprave_s_datotekami(),
        "posljiNapravi": lambda a: poslji_napravi(os_okno.control_backend, _s(a), a[1] if len(a) > 1 and isinstance(a[1], list) else []),
    }


def poslji_napravi(cb, cilj: str, poti: list) -> dict:
    """Datoteke na napravo v Linku (iz delovne niti; caka do konca). Mape preskoci (kot Linux za zdaj)."""
    poti = [str(p) for p in poti[:200] if os.path.isfile(str(p))]
    if not cilj or not poti:
        return {"ok": False, "razlog": "ni_datotek"}
    ime = next((n.get("ime", "") for n in cb.naprave_s_datotekami() if n.get("id") == cilj), "")
    poslanih, napaka = 0, {}
    for pot in poti:
        uspeh, napaka = cb.poslji_datoteko_napravi(cilj, pot)
        if not uspeh:
            break
        poslanih += 1
    if poslanih < len(poti):
        return {"ok": False, "razlog": (napaka or {}).get("sporocilo", ""), "naprava": ime}
    return {"ok": True, "stanje": "poslano", "datotek": len(poti), "ime": os.path.basename(poti[0]), "naprava": ime}


try:  # Qt je na Windows vedno; v preizkusih na Linuxu (brez zaslona) modul uvozimo tudi brez nje.
    from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEngineScript
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QWidget
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[assignment,misc]


class NamizjeOkno(QWidget):  # type: ignore[misc]
    """Stran delovna.html kot namizje pod vsemi okni."""

    WM_WINDOWPOSCHANGING = 0x0046
    HWND_BOTTOM = 1

    def __init__(self, os_okno, page_cls, most_js: Callable[[str], str]) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.os_okno = os_okno
        self.setWindowTitle("Safeer OS namizje")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background:#0b1220;")
        self._zeton = secrets.token_urlsafe(24)
        self._metode = metode(self)
        self._nadzor = QFileSystemWatcher(self)
        self._nadzor.directoryChanged.connect(self._mapa_spremenjena)
        self._spremljana = ""
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page_obj = page_cls(os_okno.profile, self)
        skripta = QWebEngineScript()
        skripta.setName("SafeerNamizjeMost")
        skripta.setSourceCode(most_js(self._zeton))
        skripta.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        skripta.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        skripta.setRunsOnSubFrames(False)
        self.page_obj.scripts().insert(skripta)
        self.view.setPage(self.page_obj)
        self._postavi()
        try:
            zaslon = QApplication.primaryScreen()
            zaslon.availableGeometryChanged.connect(lambda *_: self._postavi())
        except Exception:  # noqa: BLE001
            pass
        threading.Thread(target=os_iskalnik.indeks().zgradi_v_ozadju, daemon=True).start()

    # ------------------------------------------------------------------ most (iste metode kot SafeerOsPage pricakuje)
    def zeton_mostu_velja(self, zeton: Any) -> bool:
        import hmac
        return isinstance(zeton, str) and hmac.compare_digest(zeton.encode(), self._zeton.encode())

    def zavrnjen_klic_mostu(self) -> None:
        pass

    def obdelaj_klic(self, sporocilo: dict) -> None:
        klic_id, metoda, a = sporocilo.get("id", 0), str(sporocilo.get("m", "")), list(sporocilo.get("a") or [])

        def delo() -> None:
            try:
                if metoda in self._metode:
                    izid = self._metode[metoda](a)
                else:
                    izid = self.os_okno._izvedi_metodo(metoda, a)
                self._odgovor(klic_id, True, izid)
            except Exception as e:  # noqa: BLE001
                print(f"[SafeerOS namizje] {metoda}: {e}", flush=True)
                self._odgovor(klic_id, False, str(e))
        threading.Thread(target=delo, daemon=True).start()

    def _odgovor(self, klic_id: int, ok: bool, podatki: Any) -> None:
        koda = "window.__safeerOsOdgovor && window.__safeerOsOdgovor(%d, %s, %s);" % (
            int(klic_id), "true" if ok else "false", json.dumps(podatki, ensure_ascii=False, default=str))
        self.os_okno.dispatcher.dispatch(lambda: self.page_obj.runJavaScript(koda))

    def dogodek(self, vrsta: str, podatki: Any = None) -> None:
        koda = "window.safeerOsDogodek && window.safeerOsDogodek(%s, %s);" % (json.dumps(vrsta), json.dumps(podatki))
        self.os_okno.dispatcher.dispatch(lambda: self.page_obj.runJavaScript(koda))

    # ------------------------------------------------------------------ metode namizja
    def zacetek(self) -> dict:
        z = dict(self.os_okno._izvedi_metodo("zacetek", []) or {})
        z.update({"mape": uporabniske_mape(), "zaznamki": [], "vlecenjeDatotek": False, "videz": z.get("videz") or {},
                  "ozadje": ozadje_windows()})
        return z

    def odpri_razdelek(self, razdelek: str) -> bool:
        # Nastavitve, Safeer Link ... v svojem oknu Safeer OS (okno_razdelka.py), drugo v glavnem oknu.
        self.os_okno.dispatcher.dispatch(lambda: self.os_okno.odpri_razdelek_namizja(razdelek))
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

    def _mapa_spremenjena(self, pot: str) -> None:
        QTimer.singleShot(400, lambda: self.dogodek("datoteke", {"pot": pot}))

    # ------------------------------------------------------------------ polozaj: pod vsemi okni
    def _postavi(self) -> None:
        g = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(g)
        self.view.setGeometry(0, 0, g.width(), g.height())

    def resizeEvent(self, dogodek) -> None:  # noqa: N802
        self.view.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(dogodek)

    def pokazi(self, url: str) -> None:
        self.page_obj.load(QUrl(url))
        self.show()
        if _WIN:
            hwnd = int(self.winId())
            u = ctypes.windll.user32
            progman = u.FindWindowW("Progman", None)
            if progman:
                # Lastnik Progman: »Pokazi namizje« okna ne pomanjsa (okna namizja ostanejo).
                u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                u.SetWindowLongPtrW(hwnd, -8, progman)   # GWLP_HWNDPARENT
            u.SetWindowPos(hwnd, self.HWND_BOTTOM, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)  # NOMOVE|NOSIZE|NOACTIVATE

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
                    poz.hwndInsertAfter = self.HWND_BOTTOM      # vedno na dnu, tudi ob kliku vanj
                    poz.flags &= ~0x0004                       # SWP_NOZORDER izklopljen, da velja HWND_BOTTOM
            except Exception:  # noqa: BLE001
                pass
        return False, 0
