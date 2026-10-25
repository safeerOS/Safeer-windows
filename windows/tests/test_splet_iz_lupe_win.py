"""Lupa namizja QML -> Splet (lastnik, 25. 10. 2026 11:44, video na testnem PC).

Lastnik je vtipkal »claude«: zadetkov programov ni bilo, samo »Isci na spletu: claude«; Enter je polje izpraznil in nic
se ni odprlo. Vzrok (koda): namizje_win »spletNaNamizju« je klical odpri_spletno_iskanje, ki odpre Splet v glavnem oknu
Safeer OS - to je ob namizju QML skrito. Zdaj (kot Linux _splet_na_namizju) se Splet odpre v svojem oknu nad namizjem,
v istem procesu. Poleg tega: Enter pred osvezitvijo seznama (casovnik 180 ms) isce TRENUTNO besedilo.
"""
import json
import os
import sys
import types
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_namizje_klice_splet_nad_namizjem():
    vir = (KOREN / "windows" / "safeer_windows" / "namizje_win.py").read_text(encoding="utf-8")
    assert '"spletNaNamizju": lambda a: os_okno.splet_na_namizju(_s(a))' in vir


class _Okno:
    """Nadomestek SafeerOsWindow za splet_na_namizju (glavno okno skrito, namizje QML spredaj)."""

    def __init__(self, vidno):
        self._vidno = vidno
        self.klici = []
        self.dispatcher = types.SimpleNamespace(dispatch=lambda f: f())
        self.browser_app = types.SimpleNamespace(windows=[])
        self._okno_spleta_namizja = None

    def isVisible(self):  # noqa: N802
        return self._vidno

    def isMinimized(self):  # noqa: N802
        return False

    def odpri_spletno_iskanje(self, q):
        self.klici.append(("skrito okno", q))
        return True

    def odpri_splet(self, url, vedno_notri=False):
        self.klici.append(("skrito okno", url))
        return True

    def _sistemsko_okno_brskalnika(self):
        okno = types.SimpleNamespace(odprto=[], prikazano=[])
        okno.open_input = lambda t, new_tab=False: okno.odprto.append((t, new_tab))
        okno.showMaximized = lambda: okno.prikazano.append("max")
        okno.raise_ = lambda: okno.prikazano.append("raise")
        okno.activateWindow = lambda: okno.prikazano.append("aktivno")
        self.browser_app.windows.append(okno)
        return okno


def test_splet_odpre_vidno_okno_nad_namizjem():
    from safeer_windows import os_app
    okno = _Okno(vidno=False)
    for metoda in ("_splet_nad_namizjem",):
        setattr(okno, metoda, types.MethodType(getattr(os_app.SafeerOsWindow, metoda), okno))
    assert os_app.SafeerOsWindow.splet_na_namizju(okno, "claude") is True
    assert okno.klici == []                                   # ne v skritem glavnem oknu
    splet = okno._okno_spleta_namizja
    assert splet.odprto == [("claude", True)]                 # nastavljeni iskalnik (open_input -> resolve_input)
    assert splet.prikazano == ["max", "raise", "aktivno"]
    # Drugo iskanje: isto okno (en Splet, en proces), nov zavihek.
    os_app.SafeerOsWindow.splet_na_namizju(okno, "https://www.example.org/")
    assert len(okno.browser_app.windows) == 1 and splet.odprto[-1] == ("https://www.example.org/", True)
    assert os_app.SafeerOsWindow.splet_na_namizju(okno, "  ") is False


def test_vidno_glavno_okno_obdrzi_splet_v_sebi():
    from safeer_windows import os_app
    okno = _Okno(vidno=True)
    assert os_app.SafeerOsWindow.splet_na_namizju(okno, "claude") is True
    assert okno.klici == [("skrito okno", "claude")]


def _qml():
    from PySide6.QtCore import QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView

    class Most(QObject):
        odgovor = Signal(int, bool, str)
        dogodek = Signal(str, str)

        def __init__(self):
            super().__init__()
            self.klici = []

        @Slot(str, str, result=int)
        def klic(self, m, a):
            self.klici.append((m, json.loads(a or "[]")))
            return len(self.klici)

        @Slot(str, result=str)
        def datotekaUrl(self, p):
            return p

    app = QGuiApplication.instance() or QGuiApplication([])
    most = Most()
    pogled = QQuickView()
    pogled.rootContext().setContextProperty("Most", most)
    pogled.setSource(QUrl.fromLocalFile(str(KOREN / "windows" / "safeer_windows" / "qml" / "Namizje.qml")))
    assert [e.toString() for e in pogled.errors()] == []
    return app, most, pogled


def test_enter_pred_osvezitvijo_seznama_isce_trenutno_besedilo():
    from PySide6.QtCore import QMetaObject, QObject
    app, most, pogled = _qml()
    try:
        koren = pogled.rootObject()
        polje = koren.findChild(QObject, "polje")
        zadetki = koren.findChild(QObject, "zadetki")
        assert polje is not None and zadetki is not None
        # Seznam je ze za »clau« (casovnik je pretekel), uporabnik dotipka »de« in takoj pritisne Enter.
        import time
        polje.setProperty("text", "clau")
        konec = time.monotonic() + 3
        while zadetki.property("poizvedba") != "clau" and time.monotonic() < konec:
            app.processEvents()
            time.sleep(0.02)
        assert zadetki.property("poizvedba") == "clau"
        polje.setProperty("text", "claude")
        assert QMetaObject.invokeMethod(zadetki, "potrdi") is not False
        app.processEvents()
        splet = [a for m, a in most.klici if m == "spletNaNamizju"]
        assert splet == [["claude"]], most.klici
        assert polje.property("text") == ""
    finally:
        pogled.deleteLater()
