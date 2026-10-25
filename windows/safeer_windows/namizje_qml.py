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

from . import namizje_win, slicice_win

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
        # Slicice slik in videov (ta racunalnik in naprave v Linku): v nitih v ozadju, vsaka pride sproti kot dogodek.
        self.slicice = slicice_win.Slicice(lambda d: self.dogodek("slicica", slicica_za_qml(d)))
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
        if metoda == "videzNamizja":
            return videz_za_qml(self._jezik())
        if metoda == "nastaviVidezNamizja":
            # Prilagodi namizje (ozadje, zameglitev, prosojnost): shrani in povej Spletu (njegovo ozadje = to ozadje).
            v = nastavi_videz(a[0] if a and isinstance(a[0], dict) else {})
            self.os_okno.dispatcher.dispatch(self.os_okno.uporabi_temo)
            return dict(v, **{k: x for k, x in videz_za_qml(self._jezik()).items() if k == "ozadja"})
        if metoda == "diskiNamizja":
            # Diski s prostim prostorom in opozorilom (core/sistem_podatki - isti modul kot Nastavitve in Linux).
            from core import sistem_podatki
            return sistem_podatki.diski()
        if metoda == "sliciceNamizja":
            return self._slicice(a)
        if metoda == "besedilaProstorov":
            return besedila_prostorov(_beri_besedila_os(), self._jezik())
        if metoda in self._metode:
            return self._metode[metoda](a)
        return self.os_okno._izvedi_metodo(metoda, a)

    def _slicice(self, a: list) -> dict:
        """[izvor, elementi, streznik]: izvor »ta« (ta racunalnik) ali id naprave v Linku. Slicice naprave samo za
        napravo v ozjem krogu z datotekami - drugih vmesnik ne kaze in jih tudi tu ne zahtevamo."""
        izvor = str(a[0]) if a else "ta"
        elementi = a[1] if len(a) > 1 and isinstance(a[1], list) else []
        streznik = a[2] if len(a) > 2 and isinstance(a[2], dict) else None
        if izvor != "ta":
            cb = self.os_okno.control_backend
            if not any(n.get("id") == izvor and n.get("ozji") for n in cb.naprave_s_datotekami()):
                return {"slicice": {}, "v_delu": 0}
        else:
            # Ta racunalnik: samo absolutne poti do datotek (vmesnik jih dobi iz seznama mape).
            elementi = [e for e in elementi if isinstance(e, dict) and os.path.isabs(str(e.get("pot") or ""))]
        r = self.slicice.zahtevaj(izvor, elementi, streznik)
        return dict(r, slicice={k: QUrl.fromLocalFile(p).toString() for k, p in r["slicice"].items()})

    def _jezik(self) -> str:
        try:
            return str((self.os_okno._izvedi_metodo("zacetek", []) or {}).get("jezik") or "sl")
        except Exception:  # noqa: BLE001
            return "sl"

    def ustavi(self) -> None:
        self.slicice.ustavi()

    def nalozeno(self) -> bool:
        """Ali se je namizje nalozilo (koren QML brez napak) - sicer ga ne pokazemo (varnostna vrata)."""
        return self.rootObject() is not None and not self.errors()

    def osvezi_videz(self) -> None:
        """Tema ali ozadje sta se spremenila (Nastavitve Safeer OS ali Prilagodi namizje): namizje se prebarva."""
        self.dogodek("videz", videz_za_qml(self._jezik()))

    def dogodek(self, vrsta: str, podatki: Any = None) -> None:
        self.most.dogodek.emit(vrsta, json.dumps(podatki, ensure_ascii=False, default=str))

    # namizje_win.metode pricakuje te metode okna
    def zacetek(self) -> dict:
        z = dict(self.os_okno._izvedi_metodo("zacetek", []) or {})
        v = videz_za_qml(str(z.get("jezik") or "sl"))
        z.update({"mape": namizje_win.uporabniske_mape(), "ozadje": v["ozadje"], "videz": v})
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

    def prostori(self, smer: int = 1) -> None:
        """Bliznjica Prostorov (Ctrl+Win+Tab): pokazi namizje (pomanjsaj okna) in odpri preklopnik Prostori."""
        if _WIN:
            u = ctypes.windll.user32
            pladenj = u.FindWindowW("Shell_TrayWnd", None)
            if pladenj:
                u.PostMessageW(pladenj, 0x0111, 419, 0)     # WM_COMMAND MIN_ALL: pomanjsaj vsa okna
        self.requestActivate()
        self.dogodek("prostori", {"smer": -1 if smer < 0 else 1})

    def isci_od_drugod(self, niz: str) -> None:
        """Glas s telefona (search.query): pokazi namizje (pomanjsaj okna) in niz vpisi v iskanje."""
        if _WIN:
            u = ctypes.windll.user32
            pladenj = u.FindWindowW("Shell_TrayWnd", None)
            if pladenj:
                u.PostMessageW(pladenj, 0x0111, 419, 0)     # WM_COMMAND MIN_ALL: pomanjsaj vsa okna
        self.requestActivate()
        self.dogodek("iskanjeOdDrugod", {"q": niz})

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


# ---------------------------------------------------------------------------------------- videz namizja
#: Ozadja Safeer (ista kot na Linuxu - paket safeer-cinnamon, TV in tablica). Privzeto: gore in jezero.
OZADJA = (("jezero", "Gore in jezero", "Mountains and lake", "safeer-jezero.jpg"),
          ("gore", "Gore", "Mountains", "safeer-gore-3840x2160.png"),
          ("aurora", "Aurora", "Aurora", "safeer-aurora.jpg"),
          ("zora", "Zora", "Dawn", "safeer-zora.jpg"),
          ("globina", "Globina", "Depth", "safeer-globina.jpg"))
PRIVZETI_VIDEZ = {"ozadje": "safeer:jezero", "zameglitev": 1.0, "prosojnost": 0.55}
SLIKE = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def _pot_ozadja_safeer(kljuc: str) -> str:
    ime = next((o[3] for o in OZADJA if o[0] == kljuc), "")
    if not ime:
        return ""
    try:
        from . import policy
        return policy.shared_path("assets/ozadja/" + ime)
    except Exception:  # noqa: BLE001
        pot = Path(__file__).resolve().parents[2] / "assets" / "ozadja" / ime
        return str(pot) if pot.is_file() else ""


def videz() -> dict:
    """Shranjen videz namizja (shramba Safeer OS, kljuc namizje_videz), preverjen in dopolnjen s privzetim."""
    from . import os_backend_win
    v = dict(PRIVZETI_VIDEZ)
    shranjeno = os_backend_win.nalozi_shrambo().get("namizje_videz")
    if isinstance(shranjeno, dict):
        v.update(_preveri_videz(shranjeno))
    return v


def _preveri_videz(sprememba: dict) -> dict:
    """Samo veljavne vrednosti: ozadje Safeer, ozadje Windows ali obstojeca slika; drsniki v mejah."""
    izid: dict = {}
    oz = sprememba.get("ozadje")
    if isinstance(oz, str):
        if oz.startswith("safeer:") and any(o[0] == oz[7:] for o in OZADJA):
            izid["ozadje"] = oz
        elif oz == "windows":
            izid["ozadje"] = oz
        elif os.path.isabs(oz) and oz.lower().endswith(SLIKE) and os.path.isfile(oz):
            izid["ozadje"] = oz
    for k, lo, hi in (("zameglitev", 0.0, 1.0), ("prosojnost", 0.2, 0.9)):
        x = sprememba.get(k)
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            izid[k] = round(max(lo, min(hi, float(x))), 3)
    return izid


def nastavi_videz(sprememba: dict) -> dict:
    from . import os_backend_win
    if not isinstance(sprememba, dict):
        return videz_za_qml()
    s = os_backend_win.nalozi_shrambo()
    if sprememba.get("privzeto"):
        s.pop("namizje_videz", None)
    else:
        trenutni = videz()
        trenutni.update(_preveri_videz(sprememba))
        s["namizje_videz"] = trenutni
    os_backend_win.shrani_shrambo(s)
    return videz_za_qml()


def pot_ozadja() -> str:
    """Datoteka trenutnega ozadja namizja ('' ce je ni). Izbrane slike ni vec: privzeto ozadje Safeer."""
    oz = videz()["ozadje"]
    if oz.startswith("safeer:"):
        pot = _pot_ozadja_safeer(oz[7:])
    elif oz == "windows":
        pot = QUrl(ozadje_datoteka()).toLocalFile() if ozadje_datoteka() else ""
    else:
        pot = oz if os.path.isfile(oz) else ""
    return pot or _pot_ozadja_safeer("jezero")


def videz_za_qml(jezik: str = "sl") -> dict:
    v = videz()
    oz = v["ozadje"]
    pot = pot_ozadja()
    url = QUrl.fromLocalFile(pot).toString() if pot else ""
    ozadja = []
    for kljuc, sl, en, _ime in OZADJA:
        pot = _pot_ozadja_safeer(kljuc)
        if pot:
            ozadja.append({"kljuc": "safeer:" + kljuc, "ime": sl if jezik == "sl" else en,
                           "url": QUrl.fromLocalFile(pot).toString()})
    windows = ozadje_datoteka()
    from . import tema
    return {"izbira": oz, "ozadje": url, "zameglitev": v["zameglitev"], "prosojnost": v["prosojnost"],
            "ozadja": ozadja, "windows": windows, "paleta": tema.paleta(),
            "lastna": oz if not oz.startswith("safeer:") and oz != "windows" else ""}


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


def besedila_prostorov(besedilo_js: str, jezik: str = "sl") -> dict:
    """Besedila Prostorov iz assets/os/besedila.js (vrstice »Object.assign(BESEDILA_OS.<jezik>, {"prostori": ...})«) -
    ista kot v oknu Safeer OS, en vir za oba vmesnika. Manjkajoce v izbranem jeziku dopolni anglescina."""
    import re
    po_jezikih: dict = {}
    for m in re.finditer(r'^Object\.assign\(BESEDILA_OS\.([a-z]{2}), (\{"prostori".*\})\);\s*$', besedilo_js or "", re.M):
        try:
            po_jezikih.setdefault(m.group(1), {}).update(json.loads(m.group(2)))
        except ValueError:
            continue
    izid = dict(po_jezikih.get("en", {}))
    izid.update(po_jezikih.get(jezik, {}))
    return izid


def preveri_nalaganje(porocilo: str = "") -> int:
    """Nalozi Namizje.qml z laznim mostom (brez Linka, oken in zapisov) in vrne 0, ce QML nima napak - za CI v
    zamrznjenem SafeerOS.exe (pregled 25. 10. 2026, V1: manjkajoca mapa qml ali obrezan modul QtQuick v paketu)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    class Most(QObject):
        odgovor = Signal(int, bool, str)
        dogodek = Signal(str, str)

        @Slot(str, str, result=int)
        def klic(self, _metoda, _argumenti):
            return 1

        @Slot(str, result=str)
        def datotekaUrl(self, pot):
            return pot

    app = QGuiApplication.instance() or QGuiApplication([])
    most = Most()
    pogled = QQuickView()
    pogled.rootContext().setContextProperty("Most", most)
    pogled.setSource(QUrl.fromLocalFile(str(QML)))
    napake = [e.toString() for e in pogled.errors()]
    if not napake and pogled.rootObject() is None:
        napake = ["Namizje.qml: korenski objekt ni nastal"]
    izid = {"qml": str(QML), "obstaja": QML.exists(), "napake": napake, "ok": not napake}
    pogled.deleteLater()
    app.processEvents()
    if porocilo:
        try:
            Path(porocilo).parent.mkdir(parents=True, exist_ok=True)
            Path(porocilo).write_text(json.dumps(izid, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"[SafeerOS] Porocila QML ni mogoce zapisati: {e}", flush=True)
    print(f"[SafeerOS] Preverjanje QML: {'v redu' if not napake else '; '.join(napake)}", flush=True)
    return 0 if not napake else 1


def _beri_besedila_os() -> str:
    try:
        from . import policy
        pot = policy.shared_path("assets/os/besedila.js")
    except Exception:  # noqa: BLE001
        pot = str(Path(__file__).resolve().parents[2] / "assets" / "os" / "besedila.js")
    try:
        with open(pot, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def slicica_za_qml(d: dict) -> dict:
    """Dogodek »slicica« za QML: pot v predpomnilniku -> file:/// naslov (QML Image ga bere neposredno)."""
    return {"izvor": d.get("izvor", ""), "id": d.get("id", ""), "url": QUrl.fromLocalFile(str(d.get("pot") or "")).toString()}


def naprave_za_izbiro(cb) -> list:
    """Druge naprave v Safeer Linku za izbiro na namizju. Ena vrstica na napravo: racunalnik je v Linku lahko dvakrat
    (Safeer OS in njegov Control, id »…-control«); za programe in datoteke si zapomnimo id, ki to zna."""
    programi = {n["id"] for n in cb.naprave_s_programi()}
    # Datoteke samo naprav v ozjem krogu zaupanja (core/link_dostop; kot Linux): drugih za brskanje ne pokazemo.
    datoteke = {n["id"] for n in cb.naprave_s_datotekami() if n.get("ozji", True)}
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
